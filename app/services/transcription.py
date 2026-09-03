"""
Transcription serveur (spec §9) : POST /api/outcomes/:id/transcribe.
Server-side plutôt que `SpeechRecognition` navigateur — qualité constante et
l'audio de l'utilisateur ne part jamais vers un vendor de navigateur tiers.

L'audio n'est JAMAIS persisté après transcription (spec explicite) : on le
reçoit en mémoire, on l'envoie au provider, on jette le buffer.
"""
from __future__ import annotations

import httpx

from app.config import get_settings


async def transcribe_audio(raw_audio: bytes, content_type: str = "audio/webm") -> str:
    settings = get_settings()

    if settings.TRANSCRIPTION_PROVIDER == "openai":
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                files={"file": ("audio.webm", raw_audio, content_type)},
                data={"model": "whisper-1"},
            )
            resp.raise_for_status()
            return resp.json()["text"]

    raise NotImplementedError(f"Unknown transcription provider: {settings.TRANSCRIPTION_PROVIDER}")
    # raw_audio sort de portée ici et n'est jamais écrit sur disque ni en DB.