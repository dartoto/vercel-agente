"""Función serverless del agente de Paysandú. Expone /api/chat y /api/lugar."""

import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).parent.parent
load_dotenv(dotenv_path=RAIZ_PROYECTO / ".env")

sys.path.insert(0, str(RAIZ_PROYECTO))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agente import chat, _crear_cliente


app = FastAPI(title="Agente Paysandú")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Modelos ----------

class Mensaje(BaseModel):
    role: str
    content: str


class Ubicacion(BaseModel):
    lat: float
    lon: float


class ChatRequest(BaseModel):
    mensajes: List[Mensaje]
    ubicacion: Optional[Ubicacion] = None


class ChatResponse(BaseModel):
    respuesta: str
    lugares: List[dict] = []


# ---------- Endpoints ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "servicio": "agente-paysandu"}


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    try:
        cliente = _crear_cliente()
        mensajes = [m.model_dump() for m in request.mensajes]
        ubicacion = request.ubicacion.model_dump() if request.ubicacion else None
        resultado = chat(
            mensajes,
            cliente=cliente,
            devolver_lugares=True,
            ubicacion=ubicacion,
        )
        return ChatResponse(
            respuesta=resultado["respuesta"],
            lugares=resultado["lugares"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/lugar/{lugar_id}")
def obtener_lugar(lugar_id: str):
    from db import obtener_ficha
    ficha = obtener_ficha(lugar_id)
    if not ficha:
        raise HTTPException(status_code=404, detail=f"Lugar '{lugar_id}' no encontrado")
    return ficha
