"""Loop de chat del agente con function calling, usando Groq."""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from herramientas import ESQUEMAS, ejecutar
from prompt import SYSTEM_PROMPT


# --- Configuración ---
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODELO = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_PASOS = 6
TEMPERATURA = 0.3
LOG_TOOL_CALLS = os.environ.get("LOG_TOOL_CALLS", "1") == "1"

PALABRAS_QUE_REQUIEREN_TOOLS = (
    "busca", "buscá", "buscame", "búscame", "encontra", "encontrá",
    "recomenda", "recomendá", "recomendame", "sugeri", "sugerí",
    "mostra", "mostrá", "mostrame", "decime", "contame", "dame",
    "histórico", "historico", "mural", "natural", "cerca",
    "gratis", "gratuito", "accesible", "raro", "singular",
    "qué hay", "que hay", "qué lugares", "que lugares",
)


def _crear_cliente() -> OpenAI:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta la variable de entorno GROQ_API_KEY. "
            "Configurala en el archivo .env o en Vercel."
        )
    return OpenAI(base_url=GROQ_BASE_URL, api_key=api_key, timeout=60.0)


def _normalizar_argumentos(args) -> str:
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    if isinstance(args, str):
        return args
    return "{}"


def _log_tool_call(nombre: str, argumentos: dict, resultado: dict) -> None:
    if not LOG_TOOL_CALLS:
        return
    ok = "✓" if resultado.get("ok") else "✗"
    total = resultado.get("total")
    detalle = f" ({total} resultados)" if total is not None else ""
    error = resultado.get("error", "")
    msg = f"  {ok} {nombre}({json.dumps(argumentos, ensure_ascii=False)}){detalle}"
    if error:
        msg += f"  → {error}"
    print(msg, file=sys.stderr)


def _ejecutar_tool(nombre: str, argumentos_json: str) -> tuple[str, dict]:
    """
    Ejecuta una herramienta y devuelve (json_string, resultado_dict).
    El primer valor va al LLM; el segundo se usa para acumular lugares.
    """
    try:
        args = json.loads(argumentos_json) if argumentos_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"JSON inválido: {e}"}), {}

    resultado = ejecutar(nombre, args)
    _log_tool_call(nombre, args, resultado)
    return json.dumps(resultado, ensure_ascii=False), resultado


def _parece_pedir_datos(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in PALABRAS_QUE_REQUIEREN_TOOLS)


def _extraer_tool_calls(msg) -> list[dict]:
    if not msg.tool_calls:
        return []
    return [
        {
            "id": tc.id or f"call_{i}",
            "name": tc.function.name,
            "arguments": _normalizar_argumentos(tc.function.arguments),
        }
        for i, tc in enumerate(msg.tool_calls)
    ]


def _parsear_tool_call_textual(contenido: str) -> dict | None:
    if not contenido:
        return None
    texto = contenido.strip()
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r'\{\s*"name"\s*:.+\}', texto, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or "name" not in data:
        return None
    args = data.get("arguments") or data.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"name": data["name"], "arguments": args}


def _acumular_lugares(resultado: dict, acumulador: list[dict]) -> None:
    """
    Extrae lugares de un resultado de herramienta y los agrega al acumulador.
    Soporta los formatos:
      - {"lugares": [...]}       (buscar_lugares, buscar_por_nombre, buscar_cerca)
      - {"lugar": {...}}         (obtener_ficha)
    """
    if not resultado.get("ok"):
        return
    if isinstance(resultado.get("lugares"), list):
        acumulador.extend(resultado["lugares"])
    elif isinstance(resultado.get("lugar"), dict):
        acumulador.append(resultado["lugar"])


def _deduplicar_lugares(lugares: list[dict]) -> list[dict]:
    """Quita duplicados por id, manteniendo el orden de aparición."""
    vistos = set()
    unicos = []
    for lugar in lugares:
        lid = lugar.get("id")
        if lid and lid not in vistos:
            vistos.add(lid)
            unicos.append(lugar)
    return unicos


def chat(
    mensajes: list[dict],
    cliente: OpenAI | None = None,
    devolver_lugares: bool = False,
):
    """
    Procesa la conversación y devuelve la respuesta final del agente.

    Si `devolver_lugares=True`, devuelve un dict:
        {"respuesta": str, "lugares": [ {...}, ... ]}
    Si no, devuelve solo el string de la respuesta (comportamiento clásico).

    `mensajes` se modifica in-place para conservar el historial entre turnos.
    """
    cliente = cliente or _crear_cliente()

    lugares_encontrados: list[dict] = []

    ultimo_usuario = next(
        (m["content"] for m in reversed(mensajes) if m["role"] == "user"),
        "",
    )
    forzar_tools_primera_vez = _parece_pedir_datos(ultimo_usuario)

    for paso in range(MAX_PASOS):
        tool_choice = "auto"
        if paso == 0 and forzar_tools_primera_vez:
            tool_choice = "required"

        try:
            respuesta = cliente.chat.completions.create(
                model=MODELO,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *mensajes],
                tools=ESQUEMAS,
                tool_choice=tool_choice,
                temperature=TEMPERATURA,
            )
        except Exception as e:
            print(f"\n⚠️  Error al llamar a Groq: {type(e).__name__}: {e}", file=sys.stderr)
            msg_error = "Tuve un problema al conectar con el modelo. Verificá tu API key y tu conexión."
            if devolver_lugares:
                return {"respuesta": msg_error, "lugares": []}
            return msg_error

        msg = respuesta.choices[0].message

        # --- Tool calls nativas ---
        tool_calls = _extraer_tool_calls(msg)

        # --- Tool call escrita como texto ---
        if not tool_calls and msg.content:
            parseada = _parsear_tool_call_textual(msg.content)
            if parseada:
                print(
                    "  ⚠️  Tool call detectada como texto. Ejecutando de todos modos.",
                    file=sys.stderr,
                )
                tool_calls = [{
                    "id": "call_textual_0",
                    "name": parseada["name"],
                    "arguments": json.dumps(parseada["arguments"], ensure_ascii=False),
                }]

        # --- Respuesta final sin herramientas ---
        if not tool_calls:
            contenido = msg.content or ""
            mensajes.append({"role": "assistant", "content": contenido})
            if devolver_lugares:
                return {
                    "respuesta": contenido,
                    "lugares": _deduplicar_lugares(lugares_encontrados),
                }
            return contenido

        # --- Ejecutar herramientas ---
        mensajes.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            resultado_json, resultado_dict = _ejecutar_tool(tc["name"], tc["arguments"])
            _acumular_lugares(resultado_dict, lugares_encontrados)
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": resultado_json,
            })

        forzar_tools_primera_vez = False

        if paso == MAX_PASOS - 1:
            print(
                f"\n⚠️  Alcanzado el máximo de {MAX_PASOS} pasos sin respuesta final.",
                file=sys.stderr,
            )

    msg_max = "No pude completar la consulta en los pasos previstos."
    if devolver_lugares:
        return {"respuesta": msg_max, "lugares": _deduplicar_lugares(lugares_encontrados)}
    return msg_max


def main():
    print("🤖 Agente de lugares singulares de Paysandú")
    print(f"   Modelo: {MODELO}")
    print(f"   Endpoint: {GROQ_BASE_URL}")
    print("   (escribí 'salir' para terminar)\n")

    cliente = _crear_cliente()
    mensajes: list[dict] = []

    while True:
        try:
            entrada = input("vos > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not entrada:
            continue
        if entrada.lower() in {"salir", "exit", "quit"}:
            break

        mensajes.append({"role": "user", "content": entrada})
        respuesta = chat(mensajes, cliente=cliente)
        print(f"\n🤖 {respuesta}\n")


if __name__ == "__main__":
    main()
