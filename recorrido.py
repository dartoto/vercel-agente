"""Lógica para armar recorridos caminables entre lugares con coordenadas."""

import math
from typing import Optional

import db


# Velocidades promedio en km/h
VELOCIDADES = {
    "a pie": 5.0,
    "bici": 15.0,
    "auto": 20.0,
    "bus": 20.0,
    "mixto": 15.0,
}

DURACION_VISITA_DEFAULT = 25  # minutos, si el lugar no tiene duracion_visita_min


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _minutos_traslado(distancia_km: float, transporte: str) -> int:
    velocidad = VELOCIDADES.get(transporte, 5.0)
    return max(1, round(distancia_km / velocidad * 60))


def _duracion_visita(lugar: dict) -> int:
    return lugar.get("duracion_visita_min") or DURACION_VISITA_DEFAULT


def _resolver_punto_partida(
    desde: Optional[str],
    desde_lat: Optional[float],
    desde_lon: Optional[float],
) -> Optional[dict]:
    """
    Devuelve un dict con lat/lon/nombre del punto de partida, o None si no
    hay. Acepta un lugar por nombre/id o coordenadas directas.
    """
    if desde_lat is not None and desde_lon is not None:
        return {"nombre": "punto de partida", "lat": desde_lat, "lon": desde_lon}

    if desde:
        candidatos = db.buscar_por_nombre(desde, limite=1)
        if candidatos:
            c = candidatos[0]
            if c.get("lat") and c.get("lon"):
                return {"nombre": c["nombre"], "lat": c["lat"], "lon": c["lon"]}
            # Si el lugar no tiene coordenadas, no podemos usarlo
            return None

    return None


def armar_recorrido(
    horas: float = 2.0,
    categoria: Optional[str] = None,
    etiqueta: Optional[str] = None,
    min_singularidad: int = 3,
    desde: Optional[str] = None,
    desde_lat: Optional[float] = None,
    desde_lon: Optional[float] = None,
    transporte: str = "a pie",
    max_paradas: int = 6,
) -> dict:
    """
    Arma un recorrido caminable por lugares con coordenadas, ajustado al
    tiempo disponible. Devuelve las paradas ordenadas con distancias y
    tiempos estimados.
    """
    minutos_disponibles = int(horas * 60)

    # 1. Traer candidatos con coordenadas
    candidatos = db.buscar_con_coordenadas(
        categoria=categoria,
        etiqueta=etiqueta,
        min_singularidad=min_singularidad,
        limite=50,
    )

    if not candidatos:
        return {
            "ok": False,
            "error": (
                "No hay lugares con coordenadas que cumplan esos filtros. "
                "Probá bajar min_singularidad o quitar filtros."
            ),
        }

    # 2. Resolver punto de partida
    partida = _resolver_punto_partida(desde, desde_lat, desde_lon)

    # 3. Ordenar con greedy del vecino más cercano
    if partida:
        actual_lat, actual_lon = partida["lat"], partida["lon"]
    else:
        # Sin partida: empezar por el más singular
        candidatos.sort(key=lambda x: -x["singularidad"])
        primero = candidatos.pop(0)
        actual_lat, actual_lon = primero["lat"], primero["lon"]
        candidatos.insert(0, primero)

    paradas: list[dict] = []
    restantes = list(candidatos)
    minutos_usados = 0
    distancia_total = 0.0

    while restantes and len(paradas) < max_paradas:
        # Elegir el más cercano al punto actual
        restantes.sort(
            key=lambda x: _haversine_km(actual_lat, actual_lon, x["lat"], x["lon"])
        )
        siguiente = restantes.pop(0)

        dist = _haversine_km(actual_lat, actual_lon, siguiente["lat"], siguiente["lon"])
        minutos_traslado = _minutos_traslado(dist, transporte)
        minutos_visita = _duracion_visita(siguiente)
        minutos_necesarios = minutos_traslado + minutos_visita

        # Si no entra, y ya tenemos al menos una parada, cortamos
        if minutos_usados + minutos_necesarios > minutos_disponibles:
            if paradas:
                break
            # Si es la primera parada y no entra, igual la incluimos con aviso
            # (para no devolver un recorrido vacío)

        paradas.append({
            "orden": len(paradas) + 1,
            "id": siguiente["id"],
            "nombre": siguiente["nombre"],
            "categoria": siguiente["categoria"],
            "lat": siguiente["lat"],
            "lon": siguiente["lon"],
            "motivos_singularidad": siguiente.get("motivos_singularidad", []),
            "duracion_visita_min": minutos_visita,
            "distancia_desde_anterior_km": round(dist, 3) if paradas else 0.0,
            "minutos_traslado": minutos_traslado if paradas else 0,
            "gratuito": siguiente.get("gratuito", True),
        })

        minutos_usados += minutos_necesarios
        distancia_total += dist
        actual_lat, actual_lon = siguiente["lat"], siguiente["lon"]

    if not paradas:
        return {
            "ok": False,
            "error": "No se pudo armar un recorrido con esos parámetros.",
        }

    return {
        "ok": True,
        "transporte": transporte,
        "minutos_disponibles": minutos_disponibles,
        "minutos_estimados": minutos_usados,
        "distancia_total_km": round(distancia_total, 2),
        "total_paradas": len(paradas),
        "punto_partida": partida["nombre"] if partida else paradas[0]["nombre"],
        "paradas": paradas,
    }
