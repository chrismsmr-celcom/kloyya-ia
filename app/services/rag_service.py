"""
Solution RAG : les documents uploadés par un workspace (contrats, comptes
rendus, exports CRM, PDF...) deviennent une source lisible par les
plan_steps de kind='read', au même titre qu'un outil Composio. Le résultat
alimente les `citations` avec `document_id` plutôt que `tool_id`.

Pipeline : upload -> extraction texte -> chunking -> embeddings -> pgvector.
Retrieval : similarité cosinus, filtrée STRICTEMENT par workspace_id (RLS +
filtre applicatif redondant, cf. spec §8 "architecturally true, not
policy-true").
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
from docx import Document as DocxDocument
from pypdf import PdfReader

from app.config import get_settings
from app.services.llm_router import TaskRole, get_llm_router


@dataclass
class RetrievedChunk:
    document_id: UUID
    filename: str
    ordinal: int
    content: str
    similarity: float


def _extract_text(filename: str, raw: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(raw))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if lower.endswith(".docx"):
        doc = DocxDocument(io.BytesIO(raw))
        return "\n\n".join(p.text for p in doc.paragraphs)
    # txt / md / csv / json — traité comme texte brut
    return raw.decode("utf-8", errors="ignore")


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(chunk_size - overlap, 1)
    i = 0
    while i < len(words):
        window = words[i : i + chunk_size]
        chunks.append(" ".join(window))
        i += step
    return chunks


class RagService:
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.settings = get_settings()
        self.router = get_llm_router()

    async def ingest(
        self,
        conn: asyncpg.Connection,
        *,
        document_id: UUID,
        filename: str,
        raw_bytes: bytes,
    ) -> int:
        """Extrait, découpe, embed, et stocke les chunks. Retourne le nombre de chunks."""
        text = _extract_text(filename, raw_bytes)
        chunks = _chunk_text(text, self.settings.RAG_CHUNK_SIZE, self.settings.RAG_CHUNK_OVERLAP)

        if not chunks:
            await conn.execute(
                "update documents set status = 'failed' where id = $1 and workspace_id = $2",
                document_id, self.workspace_id,
            )
            return 0

        embeddings = await self.router.embed(chunks)

        rows = [
            (uuid4(), self.workspace_id, document_id, idx, chunk, len(chunk.split()), embedding)
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        await conn.executemany(
            """
            insert into document_chunks
                (id, workspace_id, document_id, ordinal, content, token_count, embedding)
            values ($1, $2, $3, $4, $5, $6, $7)
            """,
            rows,
        )
        await conn.execute(
            "update documents set status = 'ready' where id = $1 and workspace_id = $2",
            document_id, self.workspace_id,
        )
        return len(chunks)

    async def retrieve(
        self, conn: asyncpg.Connection, *, query: str, top_k: int | None = None
    ) -> list[RetrievedChunk]:
        top_k = top_k or self.settings.RAG_TOP_K
        [query_embedding] = await self.router.embed([query])

        rows = await conn.fetch(
            """
            select c.document_id, d.filename, c.ordinal, c.content,
                   1 - (c.embedding <=> $1::vector) as similarity
            from document_chunks c
            join documents d on d.id = c.document_id
            where c.workspace_id = $2   -- filtre applicatif redondant avec RLS, volontairement
            order by c.embedding <=> $1::vector
            limit $3
            """,
            query_embedding, self.workspace_id, top_k,
        )

        return [
            RetrievedChunk(
                document_id=r["document_id"],
                filename=r["filename"],
                ordinal=r["ordinal"],
                content=r["content"],
                similarity=r["similarity"],
            )
            for r in rows
            if r["similarity"] >= self.settings.RAG_MIN_SIMILARITY
        ]

    async def retrieve_memory_facts(self, conn: asyncpg.Connection, *, query: str, top_k: int = 5) -> list[dict]:
        """Retrouve les memory_facts pertinents (mémoire de workspace) pour enrichir
        le planning, en plus des documents."""
        [query_embedding] = await self.router.embed([query])
        rows = await conn.fetch(
            """
            select id, fact, confidence, created_at,
                   1 - (embedding <=> $1::vector) as similarity
            from memory_facts
            where workspace_id = $2 and retracted_at is null and embedding is not null
            order by embedding <=> $1::vector
            limit $3
            """,
            query_embedding, self.workspace_id, top_k,
        )
        return [dict(r) for r in rows if r["similarity"] >= self.settings.RAG_MIN_SIMILARITY]


def get_rag_service(workspace_id: UUID) -> RagService:
    return RagService(workspace_id)