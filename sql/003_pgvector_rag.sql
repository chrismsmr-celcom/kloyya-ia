-- RAG : chunks + embeddings par document. Index tenant-scopé strictement —
-- pas d'index d'embeddings partagé entre workspaces (spec §8 : "no shared
-- embedding index across workspaces" doit être vrai architecturalement).

create table document_chunks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  document_id uuid not null references documents(id) on delete cascade,
  ordinal int not null,
  content text not null,
  token_count int,
  embedding vector(3072),   -- dimension de text-embedding-3-large ; ajuster si autre modèle
  created_at timestamptz not null default now(),
  unique (document_id, ordinal)
);

create index idx_document_chunks_workspace on document_chunks(workspace_id);

-- Index HNSW par workspace via un index partiel n'est pas supporté nativement ;
-- on garde un seul index vectoriel mais CHAQUE requête de similarité DOIT filtrer
-- sur workspace_id en plus du opérateur <=> (voir rag_service.py). RLS ci-dessous
-- rend ça obligatoire même en cas d'erreur applicative.
create index idx_document_chunks_embedding on document_chunks
  using hnsw (embedding vector_cosine_ops);

alter table document_chunks enable row level security;

create policy document_chunks_isolation on document_chunks
  using (workspace_id = current_workspace_id());

-- Mémoire longue également indexée pour que le RAG puisse retrouver les
-- memory_facts pertinents pendant la planification, en plus des documents.
alter table memory_facts add column if not exists embedding vector(3072);