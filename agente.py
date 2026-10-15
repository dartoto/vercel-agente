"""Loop de chat del agente con function calling, usando Groq."""

import json
import os
import re
import sys
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from openai import OpenAI

from herramientas import ESQUEMAS, ejecutar
from prompt import SYSTEM_PROMPT


# --- Configuración ---
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODELO = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_PASOS = 6
TEMPERATURA = 0.3
LOG_TOOL_CALLS = os.environ.get("LOG_TOOL_CALLS", "1") == "1"

# Palabras que sugieren que el usuario pide datos concretos.
# Si aparecen y el modelo no llamó herramientas, forzamos tool_choice.
PALABRAS_QUE_REQUIEREN_TOOLS = (
    "busca", "buscá", "buscame", "búscame", "encontra", "encontrá",
    "recomenda", "recomendá", "recomendame", "sugeri", "sugerí",
    "mostra", "mostrá", "mostrame", "decime", "contame", "dame",
    "histórico", "historico", "mural", "natural", "cerca",
    "gratis", "gratuito", "accesible", "raro", "singular",
    "qué hay", "que hay", "qué lugares", "que lugares",
)


def _crear_cliente() -> OpenAI:
    """Cliente apuntando a Groq."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta la variable de entorno GROQ_API_KEY. "
            "Configurala en el archivo .env o en Vercel (Settings → Environment Variables)."
        )
    return OpenAI(
        base_url=GROQ_BASE_URL,
        api_key=api_key,
        timeout=60.0,
    )


def _normalizar_argumentos(args) -> str:
    """Acepta argumentos como dict o string y devuelve string JSON."""
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    if isinstance(args, str):
        return args
    return "{}"


def _log_tool_call(nombre: str, argumentos: dict, resultado: dict) -> None:
    """Imprime en stderr un resumen de cada tool call, para depurar."""
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


def _ejecutar_tool(nombre: str, argumentos_json: str) -> str:
    """Ejecuta una herramienta y devuelve JSON string para el LLM."""
    try:
        args = json.loads(argumentos_json) if argumentos_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"JSON inválido: {e}"})

    resultado = ejecutar(nombre, args)
    _log_tool_call(nombre, args, resultado)
    return json.dumps(resultado, ensure_ascii=False)


def _parece_pedir_datos(texto: str) -> bool:
    """Heurística: ¿el mensaje del usuario parece requerir consultar la base?"""
    t = texto.lower()
    return any(p in t for p in PALABRAS_QUE_REQUIEREN_TOOLS)


def _extraer_tool_calls(msg) -> list[dict]:
    """Convierte los tool_calls nativos del mensaje a formato uniforme."""
    if not msg.tool_calls:
        return []
    resultado = []
    for i, tc in enumerate(msg.tool_calls):
        resultado.append({
            "id": tc.id or f"call_{i}",
            "name": tc.function.name,
            "arguments": _normalizar_argumentos(tc.function.arguments),
        })
    return resultado


def _parsear_tool_call_textual(contenido: str) -> dict | None:
    """
    Detecta si el modelo escribió un tool call como texto JSON en vez de
    emitirlo como tool_call nativa. Devuelve {"name": ..., "arguments": ...}
    o None si no parece un tool call.
    """
    if not contenido:
        return None

    texto = contenido.strip()

    # Limpiar posibles bloques markdown ```json ... ```
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)

    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        # Intentar extraer el JSON embebido
        match = re.search(r'\{\s*"name"\s*:.+\}', texto, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict) or "name" not in data:
        return None

    # Normalizar arguments / parameters
    args = data.get("arguments") or data.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    return {"name": data["name"], "arguments": args}


def chat(mensajes: list[dict], cliente: OpenAI | None = None) -> str:
    """
    Procesa la conversación y devuelve la respuesta final del agente.
    `mensajes` se modifica in-place, así conserva el historial entre turnos.
    """
    cliente = cliente or _crear_cliente()

    # ¿El último mensaje del usuario parece pedir datos concretos?
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
            return (
                "Tuve un problema al conectar con el modelo. "
                "Verificá tu API key y tu conexión a internet."
            )

        msg = respuesta.choices[0].message

        # --- Caso 1: tool calls nativas ---
        tool_calls = _extraer_tool_calls(msg)

        # --- Caso 2: tool call escrita como texto en content ---
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

        # --- Caso 3: respuesta final sin herramientas ---
        if not tool_calls:
            contenido = msg.content or ""
            if paso == 0 and forzar_tools_primera_vez and contenido:
                print(
                    "  ⚠️  El modelo respondió sin consultar la base. "
                    "Puede contener datos no verificados.",
                    file=sys.stderr,
                )
            mensajes.append({"role": "assistant", "content": contenido})
            return contenido

        # Ejecutar las herramientas (nativas o parseadas)
        mensajes.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            resultado_json = _ejecutar_tool(tc["name"], tc["arguments"])
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": resultado_json,
            })

        # Después del primer paso, dejamos que el modelo decida libremente
        forzar_tools_primera_vez = False

        if paso == MAX_PASOS - 1:
            print(
                f"\n⚠️  Alcanzado el máximo de {MAX_PASOS} pasos sin respuesta final.",
                file=sys.stderr,
            )

    return "No pude completar la consulta en los pasos previstos."


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
