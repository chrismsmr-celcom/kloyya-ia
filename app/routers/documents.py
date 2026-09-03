"""
Solution RAG côté produit : l'utilisateur uploade un document (contrat,
export CRM, compte rendu...), il est chunké + embeddé, et devient une
source que le planner peut choisir de lire au même titre qu'un outil
connecté (plan_steps avec tool_ids=[] -> lecture RAG, voir run_engine).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app.deps import CurrentUser, get_current_user, get_tenant_conn
from app.services.rag_service import get_rag_service
from supabase import create_client
from app.config import get_settings

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type: {ext}")

    raw = await file.read()
    settings = get_settings()
    storage_path = f"{user.workspace_id}/{uuid4()}-{file.filename}"

    # Stockage du fichier original dans Supabase Storage (bucket privé, par workspace).
    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    supabase.storage.from_(settings.DOCUMENT_STORAGE_BUCKET).upload(
        storage_path, raw, {"content-type": file.content_type or "application/octet-stream"}
    )

    doc = await conn.fetchrow(
        """
        insert into documents (workspace_id, uploaded_by, filename, mime_type, storage_path, size_bytes, status)
        values ($1, $2, $3, $4, $5, $6, 'processing')
        returning id
        """,
        user.workspace_id, user.user_id, file.filename, file.content_type, storage_path, len(raw),
    )

    rag = get_rag_service(user.workspace_id)
    chunk_count = await rag.ingest(conn, document_id=doc["id"], filename=file.filename, raw_bytes=raw)

    return {"id": str(doc["id"]), "filename": file.filename, "chunks": chunk_count, "status": "ready" if chunk_count else "failed"}


@router.get("")
async def list_documents(conn: asyncpg.Connection = Depends(get_tenant_conn)):
    rows = await conn.fetch("select id, filename, mime_type, size_bytes, status, created_at from documents order by created_at desc")
    return [dict(r) for r in rows]


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    settings = get_settings()
    doc = await conn.fetchrow("select storage_path from documents where id = $1", document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")

    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    supabase.storage.from_(settings.DOCUMENT_STORAGE_BUCKET).remove([doc["storage_path"]])

    await conn.execute("delete from document_chunks where document_id = $1", document_id)
    await conn.execute("delete from documents where id = $1", document_id)
    return {"ok": True}