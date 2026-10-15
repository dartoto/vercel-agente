"""Consultas a la base de lugares. Sin dependencias de LLM."""

import json
import math
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent / "paysandu.db"

CAMPOS_JSON = ("curiosidades", "motivos_singularidad", "fotos")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _sin_acentos(texto: str) -> str:
    """Normaliza texto: sin acentos, minúsculas. Para búsquedas tolerantes."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower().strip()


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for campo in CAMPOS_JSON:
        if campo in d and isinstance(d[campo], str):
            d[campo] = json.loads(d[campo])
    for campo in ("accesible", "gratuito"):
        if campo in d:
            d[campo] = bool(d[campo])
    return d


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------- Consultas públicas ----------

def buscar_lugares(
    categoria: Optional[str] = None,
    etiqueta: Optional[str] = None,
    min_singularidad: int = 1,
    nivel_masificacion: Optional[str] = None,
    solo_gratuitos: bool = False,
    solo_accesibles: bool = False,
    limite: int = 10,
) -> list[dict]:
    """Búsqueda flexible con filtros combinables."""
    sql = ["SELECT DISTINCT l.* FROM lugares l"]
    params: list = []

    if etiqueta:
        sql.append("JOIN etiquetas e ON e.lugar_id = l.id")
        sql.append("WHERE e.etiqueta = ? AND l.singularidad >= ?")
        params.extend([etiqueta, min_singularidad])
    else:
        sql.append("WHERE l.singularidad >= ?")
        params.append(min_singularidad)

    if categoria:
        sql.append("AND l.categoria = ?")
        params.append(categoria)

    if nivel_masificacion:
        sql.append("AND l.nivel_masificacion = ?")
        params.append(nivel_masificacion)

    if solo_gratuitos:
        sql.append("AND l.gratuito = 1")

    if solo_accesibles:
        sql.append("AND l.accesible = 1")

    sql.append("ORDER BY l.singularidad DESC, l.nombre ASC LIMIT ?")
    params.append(limite)

    with _conn() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
    return [_decode(r) for r in rows]


def buscar_por_nombre(texto: str, limite: int = 5) -> list[dict]:
    """
    Búsqueda parcial por nombre, tolerante a acentos y mayúsculas.
    Trae todos los lugares y filtra en Python para poder normalizar.
    """
    objetivo = _sin_acentos(texto)
    if not objetivo:
        return []

    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM lugares ORDER BY singularidad DESC, nombre ASC"
        ).fetchall()

    coincidencias = []
    for r in rows:
        lugar = _decode(r)
        nombre_norm = _sin_acentos(lugar["nombre"])
        id_norm = _sin_acentos(lugar["id"])
        if objetivo in nombre_norm or objetivo in id_norm:
            coincidencias.append(lugar)
        if len(coincidencias) >= limite:
            break

    return coincidencias


def buscar_con_coordenadas(
    categoria: Optional[str] = None,
    etiqueta: Optional[str] = None,
    min_singularidad: int = 1,
    limite: int = 50,
) -> list[dict]:
    """
    Igual que buscar_lugares, pero solo devuelve lugares con lat/lon.
    Usado por armar_recorrido.
    """
    sql = ["SELECT DISTINCT l.* FROM lugares l"]
    params: list = []

    if etiqueta:
        sql.append("JOIN etiquetas e ON e.lugar_id = l.id")
        sql.append(
            "WHERE e.etiqueta = ? AND l.singularidad >= ? "
            "AND l.lat IS NOT NULL AND l.lon IS NOT NULL"
        )
        params.extend([etiqueta, min_singularidad])
    else:
        sql.append(
            "WHERE l.singularidad >= ? "
            "AND l.lat IS NOT NULL AND l.lon IS NOT NULL"
        )
        params.append(min_singularidad)

    if categoria:
        sql.append("AND l.categoria = ?")
        params.append(categoria)

    sql.append("ORDER BY l.singularidad DESC LIMIT ?")
    params.append(limite)

    with _conn() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
    return [_decode(r) for r in rows]


def obtener_ficha(lugar_id: str) -> Optional[dict]:
    """Ficha completa de un lugar, incluidas etiquetas y relacionados."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM lugares WHERE id = ?", (lugar_id,)
        ).fetchone()
        if row is None:
            return None

        lugar = _decode(row)

        lugar["etiquetas"] = [
            r["etiqueta"]
            for r in conn.execute(
                "SELECT etiqueta FROM etiquetas WHERE lugar_id = ? ORDER BY etiqueta",
                (lugar_id,),
            ).fetchall()
        ]

        lugar["cerca_de"] = [
            {"id": r["cerca_de_id"], "nombre": r["nombre"]}
            for r in conn.execute(
                """
                SELECT c.cerca_de_id, l.nombre
                FROM cerca_de c
                JOIN lugares l ON l.id = c.cerca_de_id
                WHERE c.lugar_id = ?
                ORDER BY l.singularidad DESC
                """,
                (lugar_id,),
            ).fetchall()
        ]

    return lugar


def buscar_cerca(
    lat: float,
    lon: float,
    radio_km: float = 1.0,
    limite: int = 10,
) -> list[dict]:
    """Lugares dentro de un radio (km) de una coordenada."""
    dlat = radio_km / 111.0
    dlon = radio_km / (111.0 * math.cos(math.radians(lat)))

    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM lugares
            WHERE lat IS NOT NULL
              AND lon IS NOT NULL
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            """,
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()

    lugares = []
    for r in rows:
        d = _decode(r)
        if d["lat"] is None or d["lon"] is None:
            continue
        d["distancia_km"] = round(_haversine_km(lat, lon, d["lat"], d["lon"]), 3)
        if d["distancia_km"] <= radio_km:
            lugares.append(d)

    lugares.sort(key=lambda x: x["distancia_km"])
    return lugares[:limite]


def lugares_relacionados(lugar_id: str) -> list[dict]:
    """Lugares conectados vía 'cerca_de' (en ambos sentidos)."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT l.*
            FROM lugares l
            WHERE l.id IN (
                SELECT cerca_de_id FROM cerca_de WHERE lugar_id = ?
                UNION
                SELECT lugar_id FROM cerca_de WHERE cerca_de_id = ?
            )
            ORDER BY l.singularidad DESC, l.nombre ASC
            """,
            (lugar_id, lugar_id),
        ).fetchall()
    return [_decode(r) for r in rows]


def listar_etiquetas() -> list[dict]:
    """Etiquetas disponibles con su frecuencia."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT etiqueta, COUNT(*) AS usos
            FROM etiquetas
            GROUP BY etiqueta
            ORDER BY usos DESC, etiqueta ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def listar_categorias() -> list[dict]:
    """Categorías disponibles con su frecuencia."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT categoria, COUNT(*) AS usos
            FROM lugares
            GROUP BY categoria
            ORDER BY usos DESC, categoria ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]
