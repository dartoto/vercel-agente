"""Formulario interactivo para cargar y editar lugares singulares de Paysandú."""

import re
import unicodedata
from pathlib import Path
from typing import Optional

import questionary
import yaml
from pydantic import ValidationError

from esquema import Lugar
from herramientas_datos import geocodificar


DATOS_DIR = Path(__file__).parent / "datos" / "lugares"

CATEGORIAS = [
    "historico", "arquitectura", "natural", "gastronomico",
    "cultural", "mural", "mirador", "religioso", "industrial", "otro",
]
NIVELES = ["bajo", "medio", "alto"]
TRANSPORTES = ["a pie", "bici", "auto", "bus", "mixto"]


# ---------- Utilidades ----------

def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def _sep(titulo: str) -> None:
    print()
    print("═" * 60)
    print(f"  {titulo}")
    print("═" * 60)


def _lista_desde_texto(texto: str) -> list[str]:
    return [x.strip() for x in (texto or "").split(",") if x.strip()]


def _texto_desde_lista(lista) -> str:
    if not lista:
        return ""
    return ", ".join(str(x) for x in lista)


def _leer_yaml(lugar_id: str) -> Optional[dict]:
    path = DATOS_DIR / f"{lugar_id}.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _lugares_existentes(excluir_id: str = "") -> list[dict]:
    if not DATOS_DIR.exists():
        return []
    lugares = []
    for path in sorted(DATOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not data:
                continue
            lugar_id = data.get("id", path.stem)
            if lugar_id == excluir_id:
                continue
            lugares.append({
                "id": lugar_id,
                "nombre": data.get("nombre", ""),
                "categoria": data.get("categoria", ""),
            })
        except Exception:
            continue
    return lugares


def _a_yaml(datos: dict) -> str:
    return yaml.safe_dump(
        datos,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _guardar(datos: dict, sobrescribir: bool = False) -> Path:
    DATOS_DIR.mkdir(parents=True, exist_ok=True)
    path = DATOS_DIR / f"{datos['id']}.yaml"
    if path.exists() and not sobrescribir:
        raise FileExistsError(path)
    path.write_text(_a_yaml(datos), encoding="utf-8", newline="\n")
    return path


# ---------- Formulario ----------

def preguntar_lugar(datos_iniciales: Optional[dict] = None) -> Optional[dict]:
    """
    Guía al usuario por todos los campos. Si datos_iniciales está presente,
    trabaja en modo edición.
    """
    editando = datos_iniciales is not None
    datos: dict = dict(datos_iniciales) if datos_iniciales else {}

    _sep("FORMULARIO DE CARGA - LUGAR SINGULAR")
    if editando:
        print(f"  Modo EDICIÓN: {datos.get('nombre')}  (id: {datos.get('id')})")
        print("  Enter mantiene el valor actual en cada campo.")
    else:
        print("  Modo CREACIÓN")
    print("  (Ctrl+C en cualquier momento para cancelar)\n")

    sufijo = " (Enter mantiene)" if editando else ""

    # ── 1. Información básica ──
    _sep("1/6 - Información básica")

    nombre = questionary.text(
        f"Nombre del lugar{sufijo}:",
        default=datos.get("nombre", ""),
    ).ask()
    if not nombre and not editando:
        return None
    if nombre:
        datos["nombre"] = nombre.strip()

    if editando:
        print(f"  ID (no editable en edición): {datos.get('id')}")
    else:
        slug = _slug(datos["nombre"])
        id_aceptado = questionary.text(
            "ID (slug, Enter para aceptar el sugerido):",
            default=slug,
        ).ask()
        datos["id"] = (id_aceptado or slug).strip()

    # ── 2. Clasificación ──
    _sep("2/6 - Clasificación")

    cat_actual = datos.get("categoria")
    datos["categoria"] = questionary.select(
        "Categoría:",
        choices=CATEGORIAS,
        default=cat_actual if cat_actual in CATEGORIAS else CATEGORIAS[0],
    ).ask()

    sing_actual = str(datos.get("singularidad", "3"))
    datos["singularidad"] = int(questionary.select(
        "Singularidad (1 = común, 5 = excepcional):",
        choices=["1", "2", "3", "4", "5"],
        default=sing_actual if sing_actual in ["1", "2", "3", "4", "5"] else "3",
    ).ask())

    masif_actual = datos.get("nivel_masificacion", "medio")
    datos["nivel_masificacion"] = questionary.select(
        "Nivel de masificación:",
        choices=NIVELES,
        default=masif_actual if masif_actual in NIVELES else "medio",
    ).ask()

    # ── 3. Descripciones ──
    _sep("3/6 - Descripciones")

    corta = questionary.text(
        f"Descripción corta (máx 200 caracteres){sufijo}:",
        default=datos.get("descripcion_corta", ""),
        validate=lambda x: len(x) <= 200 or "❌ Máximo 200 caracteres",
    ).ask()
    if corta is not None:
        datos["descripcion_corta"] = corta.strip()

    larga = questionary.text(
        f"Descripción larga (opcional){sufijo}:",
        default=datos.get("descripcion_larga", ""),
    ).ask()
    if larga is not None:
        if larga.strip():
            datos["descripcion_larga"] = larga.strip()
        elif not editando:
            datos.pop("descripcion_larga", None)

    # ── 4. Ubicación ──
    _sep("4/6 - Ubicación")
    print("  Las coordenadas son OPCIONALES. Podés cargarlas ahora o después.")
    print("  En Google Maps: clic derecho sobre el punto → copiar lat/lon.\n")

    direccion = questionary.text(
        f"Dirección{sufijo}:",
        default=datos.get("direccion", ""),
    ).ask()
    if direccion is not None:
        datos["direccion"] = direccion.strip()

    lat_default = f"{datos['lat']:.6f}" if datos.get("lat") else ""
    lon_default = f"{datos['lon']:.6f}" if datos.get("lon") else ""

    # En creación, intentar geocodificar automáticamente
    if not editando and datos.get("direccion"):
        print(f"\n  🔍 Intentando geocodificar '{datos['direccion']}'...")
        geo = geocodificar(datos["direccion"])
        if geo.get("ok"):
            lat_default = f"{geo['lat']:.6f}"
            lon_default = f"{geo['lon']:.6f}"
            print(f"  ✓ Coordenadas sugeridas: {lat_default}, {lon_default}")
            print("    (podés reemplazarlas por las de Google Maps si preferís)")
        else:
            print("  ⚠️  No se pudo geocodificar automáticamente.")

    print()
    lat_str = questionary.text(
        "Latitud (opcional, Enter para omitir):",
        default=lat_default,
    ).ask()
    lon_str = questionary.text(
        "Longitud (opcional, Enter para omitir):",
        default=lon_default,
    ).ask()

    # Si el usuario deja ambos en blanco, no se guardan coordenadas.
    # Si pone solo uno, avisamos y omitimos ambos.
    if lat_str and lon_str:
        try:
            datos["lat"] = float(lat_str)
            datos["lon"] = float(lon_str)
        except (ValueError, TypeError):
            print("\n  ⚠️  Coordenadas inválidas. Se omitirán.\n")
            datos.pop("lat", None)
            datos.pop("lon", None)
    elif lat_str or lon_str:
        print("\n  ⚠️  Cargaste solo una coordenada. Se omitirán las dos.\n")
        datos.pop("lat", None)
        datos.pop("lon", None)
    else:
        print("\n  ⚠️  Sin coordenadas. El lugar se guardará igual.\n")
        datos.pop("lat", None)
        datos.pop("lon", None)

    # ── 5. Detalles ──
    _sep("5/6 - Detalles")

    datos["accesible"] = questionary.confirm(
        "¿Es accesible para sillas de ruedas?",
        default=datos.get("accesible", True),
    ).ask()

    datos["gratuito"] = questionary.confirm(
        "¿La entrada es gratuita?",
        default=datos.get("gratuito", True),
    ).ask()

    motivos = questionary.text(
        f"Motivos de singularidad (separados por coma){sufijo}:",
        default=_texto_desde_lista(datos.get("motivos_singularidad")),
    ).ask()
    if motivos is not None:
        datos["motivos_singularidad"] = _lista_desde_texto(motivos)

    etiquetas = questionary.text(
        f"Etiquetas (separadas por coma){sufijo}:",
        default=_texto_desde_lista(datos.get("etiquetas")),
    ).ask()
    if etiquetas is not None:
        datos["etiquetas"] = _lista_desde_texto(etiquetas)

    curiosidades = questionary.text(
        f"Curiosidades (separadas por coma, opcional){sufijo}:",
        default=_texto_desde_lista(datos.get("curiosidades")),
    ).ask()
    if curiosidades is not None:
        datos["curiosidades"] = _lista_desde_texto(curiosidades)

    trans_actual = datos.get("transporte_recomendado", "a pie")
    datos["transporte_recomendado"] = questionary.select(
        "Transporte recomendado:",
        choices=TRANSPORTES,
        default=trans_actual if trans_actual in TRANSPORTES else "a pie",
    ).ask()

    fuente = questionary.text(
        f"Fuente{sufijo}:",
        default=datos.get("fuente", "Investigación propia"),
    ).ask()
    if fuente is not None:
        datos["fuente"] = fuente.strip()

    # ── 6. Relaciones y medios ──
    _sep("6/6 - Relaciones y medios")

    existentes = _lugares_existentes(excluir_id=datos.get("id", ""))
    if existentes:
        actuales = set(datos.get("cerca_de", []) or [])
        print(f"  Hay {len(existentes)} lugares cargados. Espacio para marcar.\n")
        choices = [
            questionary.Choice(
                title=f"{l['nombre']} ({l['categoria']})",
                value=l["id"],
                checked=(l["id"] in actuales),
            )
            for l in existentes
        ]
        seleccionados = questionary.checkbox(
            "Lugares cercanos o relacionados:",
            choices=choices,
        ).ask()
        datos["cerca_de"] = seleccionados or []
    else:
        print("  No hay otros lugares cargados todavía.")
        datos["cerca_de"] = []

    fotos = questionary.text(
        f"Fotos (rutas separadas por coma, opcional){sufijo}:",
        default=_texto_desde_lista(datos.get("fotos")),
    ).ask()
    if fotos is not None:
        datos["fotos"] = _lista_desde_texto(fotos)

    # Limpiar campos opcionales vacíos (excepto obligatorios)
    obligatorios = {"id", "nombre", "categoria", "singularidad", "direccion"}
    for k in list(datos.keys()):
        if k not in obligatorios and datos[k] in ("", None):
            del datos[k]

    return datos


# ---------- Flujos ----------

def flujo_crear() -> bool:
    datos = preguntar_lugar()
    if not datos:
        print("\n❌ Cancelado.\n")
        return False

    try:
        Lugar(**datos)
    except ValidationError as e:
        print("\n❌ Errores de validación:")
        for err in e.errors():
            campo = ".".join(str(x) for x in err["loc"])
            print(f"   - {campo}: {err['msg']}")
        return False

    _sep("VISTA PREVIA")
    print(_a_yaml(datos))

    accion = questionary.select(
        "¿Qué hacemos?",
        choices=["Guardar", "Editar desde cero", "Cancelar"],
    ).ask()

    if accion == "Guardar":
        try:
            path = _guardar(datos)
            print(f"\n✅ Guardado en {path}")
            print("   Recordá correr 'python cargar_db.py' para actualizar la base.\n")
            return True
        except FileExistsError as e:
            if questionary.confirm(
                f"Ya existe {e.args[0].name}. ¿Sobrescribir?",
                default=False,
            ).ask():
                path = _guardar(datos, sobrescribir=True)
                print(f"\n✅ Guardado en {path}\n")
                return True
    elif accion == "Editar desde cero":
        return flujo_crear()

    return False


def flujo_editar() -> bool:
    existentes = _lugares_existentes()
    if not existentes:
        print("\n⚠️  No hay lugares cargados todavía.\n")
        return False

    choices = [
        questionary.Choice(
            title=f"{l['nombre']} ({l['categoria']}) — {l['id']}",
            value=l["id"],
        )
        for l in existentes
    ]
    lugar_id = questionary.select(
        "¿Qué lugar querés editar?",
        choices=choices,
    ).ask()

    if not lugar_id:
        return False

    datos_actuales = _leer_yaml(lugar_id)
    if not datos_actuales:
        print(f"\n❌ No pude leer {lugar_id}.yaml\n")
        return False

    datos_editados = preguntar_lugar(datos_actuales)
    if not datos_editados:
        print("\n❌ Cancelado.\n")
        return False

    try:
        Lugar(**datos_editados)
    except ValidationError as e:
        print("\n❌ Errores de validación:")
        for err in e.errors():
            campo = ".".join(str(x) for x in err["loc"])
            print(f"   - {campo}: {err['msg']}")
        return False

    _sep("VISTA PREVIA (EDITADO)")
    print(_a_yaml(datos_editados))

    if not questionary.confirm(
        "¿Guardar los cambios?",
        default=True,
    ).ask():
        print("\n❌ Cambios descartados.\n")
        return False

    path = _guardar(datos_editados, sobrescribir=True)
    print(f"\n✅ Actualizado: {path}")
    print("   Recordá correr 'python cargar_db.py' para actualizar la base.\n")
    return True


def main():
    print("\n📝 Formulario de lugares singulares de Paysandú\n")

    while True:
        accion = questionary.select(
            "¿Qué querés hacer?",
            choices=[
                "Crear lugar nuevo",
                "Editar lugar existente",
                "Salir",
            ],
        ).ask()

        if accion is None or accion == "Salir":
            print("\n👋 Listo.\n")
            return

        if accion == "Crear lugar nuevo":
            flujo_crear()
        elif accion == "Editar lugar existente":
            flujo_editar()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelado.\n")
