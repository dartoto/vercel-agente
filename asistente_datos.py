"""Asistente de carga de datos. Chat para agregar lugares a la base."""

import json
import os
import sys

from openai import OpenAI

from herramientas_datos import ESQUEMAS, ejecutar
from prompt_datos import SYSTEM_PROMPT


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODELO = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_PASOS = 8                # más pasos: buscar, geocodificar, validar, guardar
TEMPERATURA = 0.2            # muy bajo: queremos consistencia, no creatividad
LOG_TOOL_CALLS = os.environ.get("LOG_TOOL_CALLS", "1") == "1"


def _crear_cliente() -> OpenAI:
    return OpenAI(
        base_url=GROQ_BASE_URL,
        api_key=os.environ["GROQ_API_KEY"]  # Lee la clave que guardaste
    )


def _log(nombre: str, args: dict, resultado: dict) -> None:
    if not LOG_TOOL_CALLS:
        return
    ok = "✓" if resultado.get("ok") else "✗"
    resumen = ""
    if resultado.get("ok"):
        if "titulo" in resultado:
            resumen = f" → {resultado['titulo']}"
        elif "lat" in resultado:
            resumen = f" → {resultado['lat']:.4f}, {resultado['lon']:.4f}"
        elif "total" in resultado:
            resumen = f" ({resultado['total']})"
        elif "etiquetas" in resultado:
            resumen = f" ({len(resultado['etiquetas'])})"
        elif "lugar" in resultado:
            resumen = f" → {resultado['lugar'].get('nombre', '')}"
    error = resultado.get("error", "")
    linea = f"  {ok} {nombre}({json.dumps(args, ensure_ascii=False)}){resumen}"
    if error:
        linea += f"  → {error}"
    print(linea, file=sys.stderr)


def _normalizar_args(args) -> str:
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    return args or "{}"


def _ejecutar_tool(nombre: str, args_json: str) -> str:
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"JSON inválido: {e}"})
    resultado = ejecutar(nombre, args)
    _log(nombre, args, resultado)
    return json.dumps(resultado, ensure_ascii=False)


def _extraer_tool_calls(msg) -> list[dict]:
    if not msg.tool_calls:
        return []
    return [
        {
            "id": tc.id or f"call_{i}",
            "name": tc.function.name,
            "arguments": _normalizar_args(tc.function.arguments),
        }
        for i, tc in enumerate(msg.tool_calls)
    ]


def chat(mensajes: list[dict], cliente: OpenAI | None = None) -> str:
    cliente = cliente or _crear_cliente()

    for paso in range(MAX_PASOS):
        try:
            respuesta = cliente.chat.completions.create(
                model=MODELO,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *mensajes],
                tools=ESQUEMAS,
                tool_choice="auto",
                temperature=TEMPERATURA,
            )
        except Exception as e:
            print(f"\n⚠️  Error: {type(e).__name__}: {e}", file=sys.stderr)
            return "Hubo un problema al conectar con el modelo."

        msg = respuesta.choices[0].message
        tool_calls = _extraer_tool_calls(msg)

        if not tool_calls:
            contenido = msg.content or ""
            mensajes.append({"role": "assistant", "content": contenido})
            return contenido

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
            resultado_json = _ejecutar_tool(tc["name"], tc["arguments"])
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": resultado_json,
            })

    return "No pude completar la tarea en los pasos previstos."


def main():
    print("📝 Asistente de carga de lugares de Paysandú")
    print(f"   Modelo: {MODELO}")
    print("   Escribí el nombre de un lugar para empezar.")
    print("   Comandos: 'salir' para terminar, 'lista' para ver lo cargado.\n")

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

        # Atajo: 'lista' muestra lo ya cargado sin gastar tokens del modelo
        if entrada.lower() in {"lista", "listar"}:
            from herramientas_datos import listar_lugares_existentes
            r = listar_lugares_existentes()
            for l in r["lugares"]:
                print(f"  - {l['id']:35} {l['nombre']}")
            print()
            continue

        mensajes.append({"role": "user", "content": entrada})
        respuesta = chat(mensajes, cliente=cliente)
        print(f"\n🤖 {respuesta}\n")


if __name__ == "__main__":
    main()
