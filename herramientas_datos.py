"""Herramientas para el asistente de carga de datos."""

import json
import re
import unicodedata
from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError

from esquema import Lugar


BASE_DIR = Path(__file__).parent
DATOS_DIR = BASE_DIR / "datos" / "lugares"

USER_AGENT = "agente-paysandu/0.1 (contacto: local)"

# Última propuesta validada, por id. Permite que guardar_lugar no
# requiera que el modelo reenvíe todos los campos.
_ULTIMA_PROPUESTA: dict[str, dict] = {}


# ---------- Utilidades ----------

def _slug(texto: str) -> str:
    """Convierte texto a slug: minúsculas, sin acentos, con guiones."""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def _dict_a_yaml(lugar_dict: dict) -> str:
    """Serializa un dict de lugar a YAML en formato bloque (no flow)."""
    return yaml.safe_dump(
        lugar_dict,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _coercionar_campos(campos: dict) -> dict:
    """
    Convierte strings a los tipos esperados. Defensa contra modelos chicos
    que mandan 'false', '4' o '[]' como strings.
    """
    c = dict(campos)

    # Vacíos → None
    for k in list(c.keys()):
        if c[k] == "" or c[k] is None:
            c[k] = None

    # Booleanos
    for k in ("accesible", "gratuito"):
        if k in c and c[k] is not None:
            v = c[k]
            if isinstance(v, str):
                c[k] = v.strip().lower() in ("true", "1", "sí", "si", "yes")
            else:
                c[k] = bool(v)

    # Flotantes
    for k in ("lat", "lon"):
        if k in c and c[k] is not None:
            try:
                c[k] = float(c[k])
            except (ValueError, TypeError):
                c[k] = None
            if c[k] == 0.0:
                c[k] = None

    # Enteros
    for k in ("singularidad", "duracion_visita_min"):
        if k in c and c[k] is not None:
            try:
                c[k] = int(c[k])
            except (ValueError, TypeError):
                c[k] = None

    # Listas que pueden venir como string JSON
    for k in ("etiquetas", "curiosidades", "motivos_singularidad", "fotos", "cerca_de"):
        if k in c and isinstance(c[k], str):
            s = c[k].strip()
            if not s:
                c[k] = []
            elif s.startswith("["):
                try:
                    c[k] = json.loads(s)
                except json.JSONDecodeError:
                    c[k] = []
            else:
                c[k] = [s]
        elif k in c and c[k] is None:
            c[k] = []

    # Quitar None para no romper opcionales
    c = {k: v for k, v in c.items() if v is not None}
    return c


# ---------- Búsqueda externa ----------

def buscar_wikipedia(consulta: str) -> dict:
    """Busca un resumen en Wikipedia en español."""
    try:
        search_url = "https://es.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{consulta} Paysandú",
            "format": "json",
            "srlimit": 3,
        }
        r = httpx.get(
            search_url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        r.raise_for_status()
        resultados = r.json().get("query", {}).get("search", [])
        if not resultados:
            return {"ok": False, "error": f"Sin resultados para '{consulta}'"}

        titulo = resultados[0]["title"]

        summary_url = (
            "https://es.wikipedia.org/api/rest_v1/page/summary/"
            + httpx.URL(titulo.replace(" ", "_")).__str__()
        )
        r2 = httpx.get(
            summary_url,
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        r2.raise_for_status()
        data = r2.json()

        return {
            "ok": True,
            "titulo": data.get("title"),
            "extracto": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def geocodificar(consulta: str) -> dict:
    """Obtiene lat/lon desde Nominatim (OpenStreetMap)."""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": consulta,
            "format": "json",
            "limit": 1,
            "countrycodes": "uy",
        }
        r = httpx.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        r.raise_for_status()
        resultados = r.json()
        if not resultados:
            return {"ok": False, "error": f"Sin coordenadas para '{consulta}'"}

        item = resultados[0]
        return {
            "ok": True,
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "direccion_completa": item.get("display_name", ""),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def investigar_lugar(nombre: str) -> dict:
    """
    Hace TODO el trabajo de búsqueda en una sola llamada: Wikipedia +
    geocodificación. Devuelve un draft pre-armado.
    """
    wiki = buscar_wikipedia(nombre)
    geo = geocodificar(f"{nombre}, Paysandú, Uruguay")

    nombre_canonico = wiki["titulo"] if wiki.get("ok") else nombre

    draft: dict = {
        "id": _slug(nombre_canonico),
        "nombre": nombre_canonico,
    }

    if wiki.get("ok"):
        extracto = (wiki.get("extracto") or "").strip()
        draft["descripcion_larga"] = extracto
        if extracto:
            primera_frase = re.split(r"(?<=[.!?])\s", extracto, maxsplit=1)[0]
            draft["descripcion_corta"] = primera_frase[:200].strip()

    if geo.get("ok"):
        draft["lat"] = geo["lat"]
        draft["lon"] = geo["lon"]
        draft["direccion"] = geo.get("direccion_completa", "")

    draft["fuente"] = (
        "Wikipedia + OSM"
        if (wiki.get("ok") and geo.get("ok"))
        else ("Wikipedia" if wiki.get("ok") else ("OSM" if geo.get("ok") else "Investigación propia"))
    )
    draft["accesible"] = True
    draft["gratuito"] = True
    draft["nivel_masificacion"] = "medio"
    draft["etiquetas"] = []
    draft["motivos_singularidad"] = []

    return {
        "ok": True,
        "draft": draft,
        "wikipedia": wiki,
        "geocoding": geo,
        "instrucciones": (
            "Si wikipedia.ok y geocoding.ok: copiá el draft, completá categoria, "
            "singularidad, motivos_singularidad y etiquetas, y llamá a proponer_lugar. "
            "Si falta info esencial (lat/lon o direccion): pedile al usuario los datos "
            "y usá proponer_lugar_manual."
        ),
    }


# ---------- Estado actual de la base ----------

def listar_lugares_existentes() -> dict:
    """Lista id, nombre y categoría de todos los lugares ya cargados."""
    if not DATOS_DIR.exists():
        return {"ok": True, "total": 0, "lugares": []}

    lugares = []
    for path in sorted(DATOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            lugares.append({
                "id": data.get("id", path.stem),
                "nombre": data.get("nombre", ""),
                "categoria": data.get("categoria", ""),
            })
        except Exception:
            continue
    return {"ok": True, "total": len(lugares), "lugares": lugares}


def listar_etiquetas_usadas() -> dict:
    """Etiquetas ya usadas, con su frecuencia."""
    contador: dict[str, int] = {}
    if not DATOS_DIR.exists():
        return {"ok": True, "etiquetas": []}

    for path in DATOS_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for et in data.get("etiquetas", []) or []:
                contador[et] = contador.get(et, 0) + 1
        except Exception:
            continue

    etiquetas = sorted(
        ({"etiqueta": k, "usos": v} for k, v in contador.items()),
        key=lambda x: (-x["usos"], x["etiqueta"]),
    )
    return {"ok": True, "etiquetas": etiquetas}


def leer_lugar(lugar_id: str) -> dict:
    """Lee el YAML de un lugar existente (para editarlo)."""
    path = DATOS_DIR / f"{lugar_id}.yaml"
    if not path.exists():
        return {"ok": False, "error": f"No existe '{lugar_id}'"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return {"ok": True, "lugar": data}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------- Propuesta y guardado ----------

def proponer_lugar(campos: dict) -> dict:
    """
    Valida los campos con Pydantic, devuelve un preview en YAML y
    registra la propuesta en memoria para poder guardarla después
    sin reenviar todos los campos.
    """
    campos = _coercionar_campos(campos)
    try:
        lugar = Lugar(**campos)
    except ValidationError as e:
        errores = [
            {"campo": ".".join(str(x) for x in err["loc"]), "msg": err["msg"]}
            for err in e.errors()
        ]
        return {
            "ok": False,
            "errores": errores,
            "sugerencia": (
                "Corregí los campos indicados en 'errores' y volvé a llamar "
                "a proponer_lugar con los datos completos."
            ),
        }

    datos = lugar.model_dump(mode="json", exclude_none=True)
    yaml_text = _dict_a_yaml(datos)

    # Registramos la propuesta para guardarla después solo con el id
    _ULTIMA_PROPUESTA[lugar.id] = datos

    return {
        "ok": True,
        "yaml_preview": yaml_text,
        "campos_validados": datos,
        "id_para_guardar": lugar.id,
    }


def proponer_lugar_manual(campos: dict) -> dict:
    """
    Propone un lugar sin info externa. Geocodifica la dirección si no
    vienen lat/lon. Genera id y descripcion_corta automáticamente si faltan.
    """
    c = dict(campos)

    # Generar id desde el nombre si no vino
    if not c.get("id"):
        c["id"] = _slug(c.get("nombre", ""))

    # Generar descripcion_corta desde motivos si falta
    if not c.get("descripcion_corta") and c.get("motivos_singularidad"):
        motivos = c["motivos_singularidad"]
        if isinstance(motivos, list) and motivos:
            c["descripcion_corta"] = str(motivos[0])[:200]
        elif isinstance(motivos, str):
            c["descripcion_corta"] = motivos[:200]

    # Geocodificar si no hay coordenadas
    if not c.get("lat") or not c.get("lon"):
        direccion = c.get("direccion", "")
        if direccion:
            consulta = f"{direccion}, Paysandú, Uruguay"
            geo = geocodificar(consulta)
            if geo.get("ok"):
                c["lat"] = geo["lat"]
                c["lon"] = geo["lon"]
            else:
                return {
                    "ok": False,
                    "error": (
                        f"No pude geocodificar '{direccion}'. "
                        "Probá con una dirección más específica "
                        "(calle y número, o esquina) o pasá lat/lon manualmente."
                    ),
                }
        else:
            return {
                "ok": False,
                "error": "Falta 'direccion' para poder geocodificar.",
            }

    # Fuente por defecto
    if not c.get("fuente"):
        c["fuente"] = "Investigación propia (usuario)"

    return proponer_lugar(c)


def guardar_lugar(
    lugar_id: str | None = None,
    campos: dict | None = None,
    sobrescribir: bool = False,
) -> dict:
    """
    Guarda un lugar ya propuesto. Dos formas de llamarla:
      1) guardar_lugar(lugar_id="foo")  — usa la última propuesta en memoria.
      2) guardar_lugar(campos={...})    — fallback con campos explícitos.
    """
    # Caso 1: guardar desde la última propuesta registrada
    if lugar_id and lugar_id in _ULTIMA_PROPUESTA:
        datos = _ULTIMA_PROPUESTA[lugar_id]

    # Caso 2: fallback con campos explícitos
    elif campos:
        campos = _coercionar_campos(campos)
        try:
            lugar = Lugar(**campos)
        except ValidationError as e:
            errores = [
                {"campo": ".".join(str(x) for x in err["loc"]), "msg": err["msg"]}
                for err in e.errors()
            ]
            return {"ok": False, "errores": errores}
        datos = lugar.model_dump(mode="json", exclude_none=True)
        lugar_id = lugar.id

    else:
        return {
            "ok": False,
            "error": (
                "No hay propuesta registrada para ese id. Llamá primero a "
                "proponer_lugar o proponer_lugar_manual."
            ),
        }

    path = DATOS_DIR / f"{lugar_id}.yaml"
    if path.exists() and not sobrescribir:
        return {
            "ok": False,
            "error": f"Ya existe '{lugar_id}'. Pasá sobrescribir=true para reemplazarlo.",
        }

    DATOS_DIR.mkdir(parents=True, exist_ok=True)
    yaml_text = _dict_a_yaml(datos)
    path.write_text(yaml_text, encoding="utf-8", newline="\n")

    # Ya no hace falta la propuesta en memoria
    _ULTIMA_PROPUESTA.pop(lugar_id, None)

    return {"ok": True, "path": str(path), "id": lugar_id}


# ---------- Definición de campos ----------

CAMPOS_LUGAR = {
    "id": {
        "type": "string",
        "description": "Slug en minúsculas con guiones, ej. 'teatro-florencio-sanchez'.",
    },
    "nombre": {
        "type": "string",
        "description": "Nombre visible del lugar.",
    },
    "categoria": {
        "type": "string",
        "enum": [
            "historico", "arquitectura", "natural", "gastronomico",
            "cultural", "mural", "mirador", "religioso", "industrial", "otro",
        ],
        "description": "Categoría principal. 'teatro' NO es válido; usá 'cultural'.",
    },
    "descripcion_corta": {
        "type": "string",
        "description": "Máximo 200 caracteres.",
    },
    "descripcion_larga": {"type": "string"},
    "historia": {"type": "string"},
    "singularidad": {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "1 = común, 5 = muy singular. Teatro del siglo XIX = 4.",
    },
    "motivos_singularidad": {
        "type": "array",
        "items": {"type": "string"},
        "description": "2 o 3 razones concretas.",
    },
    "nivel_masificacion": {
        "type": "string",
        "enum": ["bajo", "medio", "alto"],
    },
    "accesible": {"type": "boolean"},
    "gratuito": {"type": "boolean"},
    "lat": {"type": "number"},
    "lon": {"type": "number"},
    "direccion": {"type": "string"},
    "curiosidades": {"type": "array", "items": {"type": "string"}},
    "etiquetas": {
        "type": "array",
        "items": {"type": "string"},
        "description": "3 a 6 etiquetas. Reutilizá las existentes cuando puedas.",
    },
    "horarios": {"type": "string"},
    "precio": {"type": "string"},
    "duracion_visita_min": {"type": "integer"},
    "transporte_recomendado": {
        "type": "string",
        "enum": ["a pie", "bici", "auto", "bus", "mixto"],
    },
    "sitio_web": {"type": "string"},
    "telefono": {"type": "string"},
    "instagram": {"type": "string"},
    "fotos": {"type": "array", "items": {"type": "string"}},
    "cerca_de": {
        "type": "array",
        "items": {"type": "string"},
        "description": "IDs de otros lugares ya cargados.",
    },
    "fuente": {"type": "string"},
}

CAMPOS_REQUERIDOS = [
    "id", "nombre", "categoria", "descripcion_corta",
    "singularidad", "lat", "lon", "direccion",
]


# ---------- Esquemas expuestos al LLM ----------

ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "investigar_lugar",
            "description": (
                "PRIMER PASO SIEMPRE. Hace Wikipedia + geocodificación en una "
                "sola llamada y devuelve un draft pre-armado. Si no encuentra "
                "nada, el draft estará incompleto: en ese caso hay que usar "
                "proponer_lugar_manual."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "Nombre del lugar tal cual lo mencionó el usuario.",
                    },
                },
                "required": ["nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_wikipedia",
            "description": "Busca info en Wikipedia. Solo si investigar_lugar no alcanzó.",
            "parameters": {
                "type": "object",
                "properties": {"consulta": {"type": "string"}},
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocodificar",
            "description": "Obtiene lat/lon. Solo si investigar_lugar no alcanzó.",
            "parameters": {
                "type": "object",
                "properties": {"consulta": {"type": "string"}},
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_lugares_existentes",
            "description": "Lista los lugares ya cargados. Usar para evitar duplicados.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_etiquetas_usadas",
            "description": "Lista las etiquetas ya usadas con su frecuencia.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_lugar",
            "description": "Devuelve el YAML completo de un lugar existente.",
            "parameters": {
                "type": "object",
                "properties": {"lugar_id": {"type": "string"}},
                "required": ["lugar_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_lugar",
            "description": (
                "SEGUNDO PASO cuando SÍ hubo info externa. Valida los campos "
                "y devuelve un YAML de vista previa. No guarda. Al usarla, "
                "el sistema recuerda la propuesta y devuelve 'id_para_guardar'."
            ),
            "parameters": {
                "type": "object",
                "properties": CAMPOS_LUGAR,
                "required": CAMPOS_REQUERIDOS,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_lugar_manual",
            "description": (
                "SEGUNDO PASO cuando NO hubo info externa. Propone un lugar con "
                "los datos del usuario (nombre, direccion, categoria, "
                "singularidad, motivos_singularidad). Geocodifica la dirección, "
                "genera id y arma la ficha. No guarda. Devuelve 'id_para_guardar'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "direccion": {
                        "type": "string",
                        "description": "Dirección en Paysandú. Ej: '19 de Abril 1234'.",
                    },
                    "categoria": {
                        "type": "string",
                        "enum": [
                            "historico", "arquitectura", "natural", "gastronomico",
                            "cultural", "mural", "mirador", "religioso",
                            "industrial", "otro",
                        ],
                    },
                    "singularidad": {"type": "integer", "minimum": 1, "maximum": 5},
                    "motivos_singularidad": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "descripcion_corta": {"type": "string"},
                    "descripcion_larga": {"type": "string"},
                    "historia": {"type": "string"},
                    "curiosidades": {"type": "array", "items": {"type": "string"}},
                    "etiquetas": {"type": "array", "items": {"type": "string"}},
                    "horarios": {"type": "string"},
                    "precio": {"type": "string"},
                    "accesible": {"type": "boolean"},
                    "gratuito": {"type": "boolean"},
                    "nivel_masificacion": {
                        "type": "string",
                        "enum": ["bajo", "medio", "alto"],
                    },
                    "transporte_recomendado": {
                        "type": "string",
                        "enum": ["a pie", "bici", "auto", "bus", "mixto"],
                    },
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "fuente": {"type": "string"},
                },
                "required": [
                    "nombre", "direccion", "categoria",
                    "singularidad", "motivos_singularidad",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_lugar",
            "description": (
                "TERCER PASO. Guarda definitivamente el lugar que ya propusiste "
                "con proponer_lugar o proponer_lugar_manual. Solo necesita el "
                "'lugar_id' que devolvió la propuesta (campo 'id_para_guardar'). "
                "NO reenvíes los demás campos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lugar_id": {
                        "type": "string",
                        "description": "El id del lugar ya propuesto.",
                    },
                    "sobrescribir": {"type": "boolean"},
                },
                "required": ["lugar_id"],
            },
        },
    },
]


# ---------- Dispatch ----------

def ejecutar(nombre: str, argumentos: dict) -> dict:
    """Ejecuta una herramienta y devuelve un dict serializable."""
    try:
        if nombre == "investigar_lugar":
            return investigar_lugar(argumentos["nombre"])
        if nombre == "buscar_wikipedia":
            return buscar_wikipedia(argumentos["consulta"])
        if nombre == "geocodificar":
            return geocodificar(argumentos["consulta"])
        if nombre == "listar_lugares_existentes":
            return listar_lugares_existentes()
        if nombre == "listar_etiquetas_usadas":
            return listar_etiquetas_usadas()
        if nombre == "leer_lugar":
            return leer_lugar(argumentos["lugar_id"])
        if nombre == "proponer_lugar":
            return proponer_lugar(argumentos)
        if nombre == "proponer_lugar_manual":
            return proponer_lugar_manual(argumentos)
        if nombre == "guardar_lugar":
            return guardar_lugar(
                lugar_id=argumentos.get("lugar_id"),
                sobrescribir=bool(argumentos.get("sobrescribir", False)),
            )
        return {"ok": False, "error": f"Herramienta desconocida: {nombre}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
