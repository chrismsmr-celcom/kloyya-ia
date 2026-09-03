-- Kloyya webapp — schéma initial
-- Reprend fidèlement le modèle de kloyya-webapp-backend-spec.md §2.
-- À exécuter sur le projet Supabase Postgres (SQL editor ou `supabase db push`).

create extension if not exists "uuid-ossp";
create extension if not exists vector;
create extension if not exists pgcrypto;

-- ============================================================
-- ENUMS — gardés fermés volontairement (spec: "closed enum")
-- ============================================================
create type outcome_state as enum (
  'draft','clarifying','planned','running','paused_for_approval',
  'delivered','blocked','failed','cancelled'
);

create type plan_step_kind as enum ('read','reason','write','approval');
create type plan_step_state as enum ('pending','running','done','skipped','failed');
create type run_state as enum ('queued','running','paused','done','failed','cancelled');
create type run_event_tag as enum
  ('auth','read','filter','rule','signal','gap','insight','notify','reason');
create type run_event_level as enum ('debug','info','warn','error');
create type finding_response as enum ('pivot','note');
create type artifact_state as enum ('draft','pending_approval','approved','executed','rejected');
create type approval_state as enum ('pending','approved','rejected');
create type connection_state as enum ('pending','connected','error','revoked');
create type tool_id as enum
  ('slack','gmail','gcal','gdrive','notion','linear','jira','github',
   'figma','salesforce','hubspot','asana','whatsapp','instagram');
create type tier_id as enum ('free','starter','business','teams','enterprise');
create type identity_provider as enum ('password','google','microsoft','slack','saml','oidc');

-- ============================================================
-- WORKSPACES / USERS
-- ============================================================
create table workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  persona text,                    -- 'work' | 'business' | 'school' | 'life'
  role text,
  first_outcome text,
  tier tier_id not null default 'free',
  seat_limit int not null default 1,
  trial_ends_at timestamptz,
  free_period_ends_at timestamptz, -- signup_at + 30 days, cf spec landing §6
  stripe_customer_id text,
  llm_provider_prefs jsonb not null default '{}'::jsonb,  -- override par workspace (ex: {"planner":"openai/gpt-4o"})
  data_residency text not null default 'us',
  created_at timestamptz not null default now()
);

create table users (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  supabase_auth_id uuid unique not null,  -- auth.users.id de Supabase
  email text not null,
  name text,
  role text not null default 'member',    -- 'owner' | 'admin' | 'member'
  identity_provider identity_provider not null default 'password',
  external_id text,
  email_verified_at timestamptz,
  created_at timestamptz not null default now(),
  unique (workspace_id, email)
);

create index idx_users_workspace on users(workspace_id);
create index idx_users_auth_id on users(supabase_auth_id);

-- ============================================================
-- OUTCOMES — l'objet central (spec §1)
-- ============================================================
create table outcomes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  created_by uuid not null references users(id),
  title text not null,
  state outcome_state not null default 'draft',
  persona_context jsonb not null default '{}'::jsonb,
  scope_json jsonb not null default '{}'::jsonb,
  sources_revoked boolean not null default false,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  delivered_at timestamptz,
  duration_ms bigint
);

create index idx_outcomes_workspace on outcomes(workspace_id);
create index idx_outcomes_workspace_state on outcomes(workspace_id, state);

create table outcome_questions (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  question text not null,
  options_json jsonb not null default '[]'::jsonb,
  answer text,
  answered_at timestamptz,
  created_at timestamptz not null default now()
);

create table plan_steps (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  ordinal int not null,
  title text not null,
  detail text,
  kind plan_step_kind not null,
  tool_ids tool_id[] not null default '{}',
  requires_approval boolean not null default false,
  state plan_step_state not null default 'pending',
  edited_by_user boolean not null default false,
  created_at timestamptz not null default now(),
  unique (outcome_id, ordinal)
);

create index idx_plan_steps_outcome on plan_steps(outcome_id);

create table runs (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  state run_state not null default 'queued',
  started_at timestamptz,
  finished_at timestamptz,
  error text,
  token_usage int not null default 0,
  idempotency_key text unique
);

create index idx_runs_outcome on runs(outcome_id);

-- run_events = le journal d'activité affiché dans Live run
create table run_events (
  id bigserial primary key,
  run_id uuid not null references runs(id) on delete cascade,
  ts timestamptz not null default now(),
  tag run_event_tag not null,
  message text not null,
  level run_event_level not null default 'info',
  step_id uuid references plan_steps(id)
);

create index idx_run_events_run on run_events(run_id, id);

create table findings (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  kind text not null,
  body text not null,
  surfaced_at timestamptz not null default now(),
  user_response finding_response
);

create table answers (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null unique references outcomes(id) on delete cascade,
  headline text not null,
  narrative text not null,
  confidence numeric(4,3) not null,  -- 0..1, champ réel, pas décoratif (spec §2)
  stats_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table answer_rows (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  ordinal int not null,
  label text not null,
  value_json jsonb not null,
  risk text,                 -- ex: 'low' | 'medium' | 'high' | null
  rationale text,
  confidence numeric(4,3),
  low_confidence boolean not null default false
);

create index idx_answer_rows_outcome on answer_rows(outcome_id);

-- citations : contrainte dure — toute affirmation doit pouvoir en produire une (spec §7)
create table citations (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  tool_id tool_id,
  source_ref text not null,       -- URL/permalink/doc id ouvrable par l'utilisateur
  what_was_read text not null,
  record_count int not null default 1,
  document_id uuid,               -- si la source est un document RAG plutôt qu'un tool
  created_at timestamptz not null default now()
);

create index idx_citations_outcome on citations(outcome_id);

create table artifacts (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  kind text not null,             -- 'email' | 'doc' | 'slack_message' | 'crm_update' ...
  name text not null,
  state artifact_state not null default 'draft',
  destination text,
  payload_ref text,               -- pointeur vers le contenu final (jsonb inline si petit, storage si gros)
  payload jsonb,
  size_label text
);

create table approvals (
  id uuid primary key default gen_random_uuid(),
  outcome_id uuid not null references outcomes(id) on delete cascade,
  artifact_id uuid not null references artifacts(id) on delete cascade,
  state approval_state not null default 'pending',
  decided_by uuid references users(id),
  decided_at timestamptz
);

-- ============================================================
-- CONNECTIONS (Composio) — spec §5
-- ============================================================
create table connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  tool_id tool_id not null,
  state connection_state not null default 'pending',
  composio_connected_account_id text,   -- id renvoyé par Composio
  scopes_json jsonb not null default '{}'::jsonb,
  granted_by uuid references users(id),
  granted_at timestamptz,
  last_sync_at timestamptz,
  revoked_at timestamptz,
  unique (workspace_id, tool_id)
);

create table connection_scopes (
  id uuid primary key default gen_random_uuid(),
  connection_id uuid not null references connections(id) on delete cascade,
  resource text not null,       -- ex: '#eng-standup', 'inbox:promotions'
  allowed boolean not null default true,
  meta jsonb not null default '{}'::jsonb
);

create index idx_connection_scopes_conn on connection_scopes(connection_id);

-- ============================================================
-- MEMORY (mémoire de workspace, rétractable)
-- ============================================================
create table memory_facts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  fact text not null,
  source_outcome_id uuid references outcomes(id) on delete set null,
  confidence numeric(4,3) not null default 0.8,
  created_at timestamptz not null default now(),
  retracted_at timestamptz
);

create index idx_memory_workspace on memory_facts(workspace_id) where retracted_at is null;

-- ============================================================
-- USAGE / AUDIT
-- ============================================================
create table usage_counters (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  period_start date not null,
  runs_used int not null default 0,
  primary key (workspace_id, period_start)
);

create table audit_log (
  id bigserial primary key,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  actor uuid,
  action text not null,
  target text,
  meta_json jsonb not null default '{}'::jsonb,
  ts timestamptz not null default now()
);

create index idx_audit_workspace on audit_log(workspace_id, ts desc);

-- ============================================================
-- RAG — documents uploadés par le workspace (voir 003_pgvector_rag.sql pour les embeddings)
-- ============================================================
create table documents (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  uploaded_by uuid references users(id),
  filename text not null,
  mime_type text,
  storage_path text not null,     -- chemin dans le bucket Supabase Storage
  size_bytes bigint,
  status text not null default 'processing',  -- processing | ready | failed
  page_count int,
  created_at timestamptz not null default now()
);

create index idx_documents_workspace on documents(workspace_id);

alter table citations
  add constraint citations_document_fk foreign key (document_id) references documents(id) on delete set null;