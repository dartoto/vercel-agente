"""Genera un HTML con todos los QR listos para imprimir."""

from pathlib import Path

import yaml


BASE_URL = "https://vercel-agente-ten.vercel.app"
DATOS_DIR = Path(__file__).parent / "datos" / "lugares"
QR_DIR = Path(__file__).parent / "public" / "qr"
OUT = Path(__file__).parent / "carteles.html"


def main():
    archivos = sorted(DATOS_DIR.glob("*.yaml"))
    carteles = []

    for yaml_file in archivos:
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            lugar_id = data.get("id", yaml_file.stem)
            nombre = data.get("nombre", lugar_id)
        except Exception:
            continue

        # Ruta relativa correcta desde la raíz del proyecto
        qr_path = f"public/qr/{lugar_id}.png"
        url = f"{BASE_URL}/?lugar={lugar_id}"

        carteles.append(f"""
        <div class="cartel">
            <div class="titulo">Descubrí</div>
            <div class="nombre">{nombre}</div>
            <img src="{qr_path}" alt="QR {nombre}">
            <div class="instruccion">Escaneá con la cámara<br>del celular</div>
            <div class="url">{url}</div>
            <div class="marca">Agente de Lugares · Paysandú</div>
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Carteles QR - Paysandú</title>
<style>
    @page {{ size: A4; margin: 10mm; }}
    body {{
        font-family: system-ui, -apple-system, sans-serif;
        margin: 0; padding: 0;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10mm;
    }}
    .cartel {{
        border: 3px solid #007bff;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        page-break-inside: avoid;
        background: white;
    }}
    .titulo {{
        font-size: 14px;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 4px;
    }}
    .nombre {{
        font-size: 20px;
        font-weight: bold;
        color: #2c3e50;
        margin-bottom: 16px;
        line-height: 1.2;
    }}
    .cartel img {{
        width: 180px;
        height: 180px;
        display: block;
        margin: 0 auto 12px auto;
    }}
    .instruccion {{
        font-size: 14px;
        color: #333;
        margin-bottom: 8px;
    }}
    .url {{
        font-size: 10px;
        color: #999;
        word-break: break-all;
        margin-bottom: 8px;
    }}
    .marca {{
        font-size: 11px;
        color: #007bff;
        font-weight: 600;
        border-top: 1px solid #eee;
        padding-top: 8px;
        margin-top: 8px;
    }}
</style>
</head>
<body>
    {''.join(carteles)}
</body>
</html>
"""

    OUT.write_text(html, encoding="utf-8")
    print(f"✓ Carteles generados: {OUT}")
    print(f"  Abrilos en el navegador y usá Ctrl+P para imprimir en PDF.")


if __name__ == "__main__":
    main()
