"""Carga los lugares desde YAML/JSON a una base SQLite."""

import json
import sqlite3
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from esquema import Lugar


BASE_DIR = Path(__file__).parent
DATOS_DIR = BASE_DIR / "datos" / "lugares"
DB_PATH = BASE_DIR / "paysandu.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lugares (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    categoria TEXT NOT NULL,
    descripcion_corta TEXT NOT NULL,
    descripcion_larga TEXT,
    historia TEXT,
    singularidad INTEGER NOT NULL CHECK (singularidad BETWEEN 1 AND 5),
    nivel_masificacion TEXT NOT NULL,
    accesible INTEGER NOT NULL,
    gratuito INTEGER NOT NULL,
    lat REAL,
    lon REAL,
    direccion TEXT NOT NULL,
    horarios TEXT,
    precio TEXT,
    duracion_visita_min INTEGER,
    transporte_recomendado TEXT,
    sitio_web TEXT,
    telefono TEXT,
    instagram TEXT,
    fuente TEXT,
    curiosidades TEXT NOT NULL,          -- JSON array
    motivos_singularidad TEXT NOT NULL,  -- JSON array
    fotos TEXT NOT NULL                  -- JSON array
);

CREATE TABLE IF NOT EXISTS etiquetas (
    lugar_id TEXT NOT NULL,
    etiqueta TEXT NOT NULL,
    PRIMARY KEY (lugar_id, etiqueta),
    FOREIGN KEY (lugar_id) REFERENCES lugares(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cerca_de (
    lugar_id TEXT NOT NULL,
    cerca_de_id TEXT NOT NULL,
    PRIMARY KEY (lugar_id, cerca_de_id),
    FOREIGN KEY (lugar_id) REFERENCES lugares(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lugares_categoria ON lugares(categoria);
CREATE INDEX IF NOT EXISTS idx_lugares_singularidad ON lugares(singularidad DESC);
CREATE INDEX IF NOT EXISTS idx_lugares_masificacion ON lugares(nivel_masificacion);
CREATE INDEX IF NOT EXISTS idx_etiquetas_etiqueta ON etiquetas(etiqueta);
"""


def leer_archivo(path: Path) -> dict:
    """Lee un .yaml, .yml o .json y devuelve el dict."""
    texto = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(texto)
    if path.suffix.lower() == ".json":
        return json.loads(texto)
    raise ValueError(f"Extensión no soportada: {path.suffix}")


def cargar_lugares(datos_dir: Path) -> list[Lugar]:
    """Recorre el directorio y valida cada archivo con Pydantic."""
    if not datos_dir.exists():
        raise FileNotFoundError(f"No existe el directorio: {datos_dir}")

    archivos = sorted(
        p for p in datos_dir.iterdir()
        if p.suffix.lower() in (".yaml", ".yml", ".json")
    )
    if not archivos:
        raise ValueError(f"No se encontraron archivos en {datos_dir}")

    lugares: list[Lugar] = []
    errores: list[str] = []

    for path in archivos:
        try:
            data = leer_archivo(path)
            lugares.append(Lugar(**data))
        except ValidationError as e:
            errores.append(f"❌ {path.name}:\n{e}")
        except Exception as e:
            errores.append(f"❌ {path.name}: {type(e).__name__}: {e}")

    if errores:
        print("\n".join(errores))
        raise SystemExit(f"\n{len(errores)} archivo(s) con errores. Abortando.")

    # Detectar ids duplicados
    ids = [l.id for l in lugares]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise SystemExit(f"IDs duplicados: {sorted(duplicados)}")

    return lugares


def crear_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def limpiar_db(conn: sqlite3.Connection) -> None:
    """Borra todo para recargar desde cero."""
    conn.executescript("""
        DELETE FROM cerca_de;
        DELETE FROM etiquetas;
        DELETE FROM lugares;
    """)
    conn.commit()


def insertar_lugar(conn: sqlite3.Connection, lugar: Lugar) -> None:
    conn.execute(
        """
        INSERT INTO lugares (
            id, nombre, categoria, descripcion_corta, descripcion_larga,
            historia, singularidad, nivel_masificacion, accesible, gratuito,
            lat, lon, direccion, horarios, precio, duracion_visita_min,
            transporte_recomendado, sitio_web, telefono, instagram, fuente,
            curiosidades, motivos_singularidad, fotos
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            lugar.id,
            lugar.nombre,
            lugar.categoria.value,
            lugar.descripcion_corta,
            lugar.descripcion_larga,
            lugar.historia,
            lugar.singularidad,
            lugar.nivel_masificacion.value,
            int(lugar.accesible),
            int(lugar.gratuito),
            lugar.lat,
            lugar.lon,
            lugar.direccion,
            lugar.horarios,
            lugar.precio,
            lugar.duracion_visita_min,
            lugar.transporte_recomendado.value if lugar.transporte_recomendado else None,
            lugar.sitio_web,
            lugar.telefono,
            lugar.instagram,
            lugar.fuente,
            json.dumps(lugar.curiosidades, ensure_ascii=False),
            json.dumps(lugar.motivos_singularidad, ensure_ascii=False),
            json.dumps(lugar.fotos, ensure_ascii=False),
        ),
    )

    conn.executemany(
        "INSERT INTO etiquetas (lugar_id, etiqueta) VALUES (?, ?)",
        [(lugar.id, et) for et in lugar.etiquetas],
    )


def insertar_relaciones(conn: sqlite3.Connection, lugares: list[Lugar]) -> None:
    """Se hace después de insertar todos los lugares (por las FKs)."""
    ids_validos = {l.id for l in lugares}
    faltantes: list[str] = []

    for lugar in lugares:
        for rel in lugar.cerca_de:
            if rel not in ids_validos:
                faltantes.append(f"{lugar.id} -> {rel}")
                continue
            conn.execute(
                "INSERT OR IGNORE INTO cerca_de (lugar_id, cerca_de_id) VALUES (?, ?)",
                (lugar.id, rel),
            )

    if faltantes:
        print("⚠️  Relaciones 'cerca_de' apuntan a ids inexistentes:")
        for f in faltantes:
            print(f"   - {f}")


def main() -> None:
    print(f"📂 Leyendo lugares desde: {DATOS_DIR}")
    lugares = cargar_lugares(DATOS_DIR)
    print(f"✅ {len(lugares)} lugar(es) validados con Pydantic")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        crear_db(conn)
        limpiar_db(conn)

        for lugar in lugares:
            insertar_lugar(conn, lugar)
        insertar_relaciones(conn, lugares)

        conn.commit()
        print(f"💾 Base de datos: {DB_PATH}")
        print(f"   - lugares: {conn.execute('SELECT COUNT(*) FROM lugares').fetchone()[0]}")
        print(f"   - etiquetas: {conn.execute('SELECT COUNT(*) FROM etiquetas').fetchone()[0]}")
        print(f"   - relaciones: {conn.execute('SELECT COUNT(*) FROM cerca_de').fetchone()[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
