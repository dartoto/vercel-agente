"""Función serverless del agente de Paysandú. Expone /api/chat."""

import os
import sys
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Agregamos la raíz del proyecto al path para importar los módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agente import chat, _crear_cliente  # noqa: E402


app = FastAPI(title="Agente Paysandú")

# Permitir CORS para que un frontend externo pueda consumir la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Mensaje(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    mensajes: List[Mensaje]


class ChatResponse(BaseModel):
    respuesta: str


@app.get("/api/health")
def health():
    return {"status": "ok", "servicio": "agente-paysandu"}

@app.get("/api/debug")
def debug():
    import os
    from pathlib import Path
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    return {
        "turso_url_presente": bool(url),
        "turso_url_prefijo": url[:35] if url else "FALTA",
        "turso_token_presente": bool(token),
        "turso_token_longitud": len(token) if token else 0,
        "groq_key_presente": bool(os.environ.get("GROQ_API_KEY")),
        "env_file_existe": (Path(__file__).parent.parent / ".env").exists(),
    }
@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    try:
        cliente = _crear_cliente()
        mensajes = [m.model_dump() for m in request.mensajes]
        respuesta = chat(mensajes, cliente=cliente)
        return ChatResponse(respuesta=respuesta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
@app.get("/api/debug")
def debug():
    import os
    from pathlib import Path
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    return {
        "turso_url_presente": bool(url),
        "turso_url_prefijo": url[:35] if url else "FALTA",
        "turso_token_presente": bool(token),
        "turso_token_longitud": len(token) if token else 0,
        "groq_key_presente": bool(os.environ.get("GROQ_API_KEY")),
        "env_file_existe": (Path(__file__).parent.parent / ".env").exists(),
    }
