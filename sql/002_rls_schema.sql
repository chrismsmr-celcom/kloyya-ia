-- Multi-tenant enforcement au niveau base de données (spec §8 : "ne pas compter
-- uniquement sur la discipline applicative"). On s'appuie sur une fonction qui lit
-- le workspace_id courant depuis une variable de session Postgres, positionnée par
-- l'API à chaque connexion (voir app/db/session.py -> set_workspace_context()).

create or replace function current_workspace_id() returns uuid as $$
  select coalesce(current_setting('kloyya.workspace_id', true), '')::uuid
$$ language sql stable;

-- Active RLS sur toutes les tables tenant-scopées.
do $$
declare
  t text;
begin
  for t in select unnest(array[
    'workspaces','users','outcomes','outcome_questions','plan_steps','runs',
    'run_events','findings','answers','answer_rows','citations','artifacts',
    'approvals','connections','connection_scopes','memory_facts','usage_counters',
    'audit_log','documents'
  ])
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

-- workspaces : visible seulement si c'est le workspace courant
create policy workspace_isolation on workspaces
  using (id = current_workspace_id());

create policy users_isolation on users
  using (workspace_id = current_workspace_id());

create policy outcomes_isolation on outcomes
  using (workspace_id = current_workspace_id());

-- Tables filles : on rejoint via outcome_id -> outcomes.workspace_id
create policy outcome_questions_isolation on outcome_questions
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy plan_steps_isolation on plan_steps
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy runs_isolation on runs
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy run_events_isolation on run_events
  using (run_id in (
    select r.id from runs r join outcomes o on o.id = r.outcome_id
    where o.workspace_id = current_workspace_id()
  ));

create policy findings_isolation on findings
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy answers_isolation on answers
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy answer_rows_isolation on answer_rows
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy citations_isolation on citations
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy artifacts_isolation on artifacts
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy approvals_isolation on approvals
  using (outcome_id in (select id from outcomes where workspace_id = current_workspace_id()));

create policy connections_isolation on connections
  using (workspace_id = current_workspace_id());

create policy connection_scopes_isolation on connection_scopes
  using (connection_id in (select id from connections where workspace_id = current_workspace_id()));

create policy memory_facts_isolation on memory_facts
  using (workspace_id = current_workspace_id());

create policy usage_counters_isolation on usage_counters
  using (workspace_id = current_workspace_id());

create policy audit_log_isolation on audit_log
  using (workspace_id = current_workspace_id());

create policy documents_isolation on documents
  using (workspace_id = current_workspace_id());

-- Le rôle applicatif (service role côté API) doit être BYPASSRLS=false et passer
-- systématiquement par set_workspace_context(). Le service_role key de Supabase,
-- lui, contourne RLS par nature : ne JAMAIS l'utiliser pour des requêtes lisant des
-- données utilisateur sans filtrer explicitement par workspace_id dans le SQL.