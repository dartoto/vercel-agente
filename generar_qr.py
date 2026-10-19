"""Genera un QR code por cada lugar, con la URL de la ficha."""

from pathlib import Path

import qrcode
import yaml
from qrcode.constants import ERROR_CORRECT_H

BASE_URL = "https://vercel-agente-ten.vercel.app"
DATOS_DIR = Path(__file__).parent / "datos" / "lugares"
OUT_DIR = Path(__file__).parent / "public" / "qr"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    archivos = sorted(DATOS_DIR.glob("*.yaml"))
    print(f"Generando {len(archivos)} QR codes en {OUT_DIR}/\n")

    for yaml_file in archivos:
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            lugar_id = data.get("id", yaml_file.stem)
            nombre = data.get("nombre", lugar_id)
        except Exception as e:
            print(f"✗ {yaml_file.name}: {e}")
            continue

        url = f"{BASE_URL}/?lugar={lugar_id}"

        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_H,  # Alta tolerancia a daño
            box_size=12,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        out = OUT_DIR / f"{lugar_id}.png"
        img.save(out)
        print(f"✓ {out.name}  →  {url}")

    print(f"\nListo. {len(archivos)} QRs generados.")


if __name__ == "__main__":
    main()
