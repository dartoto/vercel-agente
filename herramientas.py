"""Herramientas expuestas al LLM + capa de dispatch (agente de chat)."""

import json

import db


ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_por_nombre",
            "description": (
                "Busca lugares por nombre (parcial, tolerante a acentos y "
                "mayúsculas). Usar SIEMPRE que el usuario mencione un lugar "
                "específico por su nombre ('Palacio Municipal', 'Centro Cultural "
                "Gobbi', 'Basílica', etc.). Es más directo que buscar por categoría."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {
                        "type": "string",
                        "description": "Texto a buscar en el nombre del lugar.",
                    },
                    "limite": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_lugares",
            "description": (
                "Busca lugares aplicando filtros por categoría, etiqueta, "
                "singularidad o masificación. Usar cuando el usuario expresa "
                "intereses generales ('algo histórico', 'algo poco turístico', "
                "'algo gratis')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": [
                            "historico", "arquitectura", "natural",
                            "gastronomico", "cultural", "mural",
                            "mirador", "religioso", "industrial", "otro",
                        ],
                    },
                    "etiqueta": {
                        "type": "string",
                        "description": (
                            "Etiqueta libre (ej. 'mural', 'siglo XIX'). "
                            "Usar listar_etiquetas si no sabés cuáles existen."
                        ),
                    },
                    "min_singularidad": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "nivel_masificacion": {
                        "type": "string",
                        "enum": ["bajo", "medio", "alto"],
                    },
                    "solo_gratuitos": {"type": "boolean"},
                    "solo_accesibles": {"type": "boolean"},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_ficha",
            "description": (
                "Devuelve la ficha completa de un lugar por su id exacto. "
                "Usar cuando ya conocés el id del lugar (por ejemplo, porque "
                "lo devolvió buscar_por_nombre o buscar_lugares)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lugar_id": {"type": "string"},
                },
                "required": ["lugar_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_cerca",
            "description": (
                "Busca lugares dentro de un radio (km) de una coordenada. "
                "Usar cuando el usuario menciona 'cerca de', 'a pocas cuadras de'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radio_km": {"type": "number", "minimum": 0.1, "maximum": 10},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lugares_relacionados",
            "description": (
                "Devuelve lugares vinculados a uno dado. "
                "Útil para armar recorridos o sugerir 'también te puede interesar'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lugar_id": {"type": "string"},
                },
                "required": ["lugar_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_etiquetas",
            "description": (
                "Lista las etiquetas disponibles con su frecuencia. "
                "Usar para descubrir qué temas existen antes de filtrar."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "armar_recorrido",
            "description": (
                "Arma un recorrido caminable por varios lugares, ordenados "
                "geográficamente para minimizar distancias. Usar cuando el "
                "usuario pide una ruta, un circuito, un plan por horas, o "
                "'qué puedo visitar en X horas'. Solo incluye lugares que "
                "tienen coordenadas cargadas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "horas": {
                        "type": "number",
                        "description": "Tiempo disponible en horas (ej. 2.5).",
                        "minimum": 0.5,
                        "maximum": 12,
                    },
                    "categoria": {
                        "type": "string",
                        "enum": [
                            "historico", "arquitectura", "natural",
                            "gastronomico", "cultural", "mural",
                            "mirador", "religioso", "industrial", "otro",
                        ],
                        "description": "Filtrar por categoría. Opcional.",
                    },
                    "etiqueta": {
                        "type": "string",
                        "description": "Filtrar por etiqueta. Opcional.",
                    },
                    "min_singularidad": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Singularidad mínima. Default 3.",
                    },
                    "desde": {
                        "type": "string",
                        "description": (
                            "Nombre o id del lugar desde donde arranca el "
                            "recorrido. Opcional. Si no se pasa, empieza por "
                            "el lugar más singular."
                        ),
                    },
                    "transporte": {
                        "type": "string",
                        "enum": ["a pie", "bici", "auto", "bus", "mixto"],
                        "description": "Medio de transporte. Default: a pie.",
                    },
                    "max_paradas": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 10,
                        "description": "Máximo de paradas. Default 6.",
                    },
                },
                "required": [],
            },
        },
    },
]


def ejecutar(nombre: str, argumentos: dict) -> dict:
    """Ejecuta una herramienta y devuelve un dict serializable."""
    try:
        if nombre == "buscar_por_nombre":
            resultados = db.buscar_por_nombre(**argumentos)
            return {"ok": True, "total": len(resultados), "lugares": resultados}

        if nombre == "buscar_lugares":
            resultados = db.buscar_lugares(**argumentos)
            return {"ok": True, "total": len(resultados), "lugares": resultados}

        if nombre == "obtener_ficha":
            ficha = db.obtener_ficha(argumentos["lugar_id"])
            if ficha is None:
                return {
                    "ok": False,
                    "error": f"No existe el lugar '{argumentos['lugar_id']}'",
                }
            return {"ok": True, "lugar": ficha}

        if nombre == "buscar_cerca":
            resultados = db.buscar_cerca(**argumentos)
            return {"ok": True, "total": len(resultados), "lugares": resultados}

        if nombre == "lugares_relacionados":
            resultados = db.lugares_relacionados(argumentos["lugar_id"])
            return {"ok": True, "total": len(resultados), "lugares": resultados}

        if nombre == "listar_etiquetas":
            return {"ok": True, "etiquetas": db.listar_etiquetas()}

        if nombre == "armar_recorrido":
            from recorrido import armar_recorrido
            return armar_recorrido(**argumentos)

        return {"ok": False, "error": f"Herramienta desconocida: {nombre}"}

    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
