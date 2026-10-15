"""Esquema de datos para lugares singulares de Paysandú."""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Categoria(str, Enum):
    historico = "historico"
    arquitectura = "arquitectura"
    natural = "natural"
    gastronomico = "gastronomico"
    cultural = "cultural"
    mural = "mural"
    mirador = "mirador"
    religioso = "religioso"
    industrial = "industrial"
    otro = "otro"


class NivelMasificacion(str, Enum):
    bajo = "bajo"
    medio = "medio"
    alto = "alto"


class Transporte(str, Enum):
    a_pie = "a pie"
    bici = "bici"
    auto = "auto"
    bus = "bus"
    mixto = "mixto"


class Lugar(BaseModel):
    # --- Identificación ---
    id: str = Field(..., description="Slug único: minúsculas, números y guiones")
    nombre: str
    categoria: Categoria
    descripcion_corta: str = Field(..., max_length=200)
    descripcion_larga: Optional[str] = None
    historia: Optional[str] = None

    # --- Singularidad ---
    singularidad: int = Field(..., ge=1, le=5)
    motivos_singularidad: list[str] = Field(default_factory=list)
    nivel_masificacion: NivelMasificacion = NivelMasificacion.medio
    accesible: bool = True
    gratuito: bool = True

    # --- Ubicación (opcional) ---
    lat: Optional[float] = None
    lon: Optional[float] = None
    direccion: str

    # --- Contexto ---
    curiosidades: list[str] = Field(default_factory=list)
    etiquetas: list[str] = Field(default_factory=list)

    # --- Info práctica ---
    horarios: Optional[str] = None
    precio: Optional[str] = None
    duracion_visita_min: Optional[int] = None
    transporte_recomendado: Optional[Transporte] = None

    # --- Contacto ---
    sitio_web: Optional[str] = None
    telefono: Optional[str] = None
    instagram: Optional[str] = None

    # --- Medios y relaciones ---
    fotos: list[str] = Field(default_factory=list)
    cerca_de: list[str] = Field(default_factory=list)
    fuente: Optional[str] = None

    # --- Validadores ---
    @field_validator("id")
    @classmethod
    def validar_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", v):
            raise ValueError(
                "El id debe ser un slug: minúsculas, números y guiones "
                "(ej. 'rincon-leandro-gomez')"
            )
        return v

    @field_validator("lat")
    @classmethod
    def validar_lat(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not (-35.5 <= v <= -30.0):
            raise ValueError(f"lat={v} fuera del rango de Uruguay (-35.5 a -30.0)")
        return v

    @field_validator("lon")
    @classmethod
    def validar_lon(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not (-58.5 <= v <= -53.0):
            raise ValueError(f"lon={v} fuera del rango de Uruguay (-58.5 a -53.0)")
        return v
