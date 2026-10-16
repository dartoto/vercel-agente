"""Función serverless del agente de Paysandú. Expone /api/chat."""

import os
import sys
from pathlib import Path
from typing import List

# 1. Cargar variables de entorno ANTES de cualquier import del proyecto.
#    Esto es crítico: db.py evalúa USE_TURSO a nivel de módulo, así que
#    las variables tienen que estar en os.environ antes de importarlo.
from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).parent.parent
load_dotenv(dotenv_path=RAIZ_PROYECTO / ".env")

# 2. Asegurar que la raíz del proyecto esté en sys.path
sys.path.insert(0, str(RAIZ_PROYECTO))

# 3. Ahora sí, imports de terceros y del proyecto
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agente import chat, _crear_cliente


# ---------- App FastAPI ----------

app = FastAPI(title="Agente Paysandú")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Modelos de request/response ----------

class Mensaje(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    mensajes: List[Mensaje]


class ChatResponse(BaseModel):
    respuesta: str


# ---------- Endpoints ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "servicio": "agente-paysandu"}


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    try:
        cliente = _crear_cliente()
        mensajes = [m.model_dump() for m in request.mensajes]
        respuesta = chat(mensajes, cliente=cliente)
        return ChatResponse(respuesta=respuesta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


# ---------- Endpoint de diagnóstico (BORRAR cuando todo funcione) ----------

@app.get("/api/debug")
def debug():
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    return {
        "turso_url_presente": bool(url),
        "turso_url_prefijo": url[:35] if url else "FALTA",
        "turso_token_presente": bool(token),
        "turso_token_longitud": len(token) if token else 0,
        "groq_key_presente": bool(os.environ.get("GROQ_API_KEY")),
        "use_turso_efectivo": bool(url and token),
    }
