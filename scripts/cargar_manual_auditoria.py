"""Carga el Manual de Procedimientos en Supabase para la auditoría de chats.

Uso local (no se ejecuta en Vercel):
    pip install -r requirements-dev.txt
    python scripts/cargar_manual_auditoria.py "Manual.pdf" --version 3.0 [--dry-run]

Necesita SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY del proyecto en el entorno o en .env.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auditoria_chats_manual import cortar_manual, version_manual  # noqa: E402


def leer_paginas(ruta_pdf):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("Instala pypdf: pip install -r requirements-dev.txt")
    return [pagina.extract_text() or "" for pagina in PdfReader(ruta_pdf).pages]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf")
    parser.add_argument("--version", default=version_manual())
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra las secciones, no guarda nada.")
    args = parser.parse_args()

    secciones = cortar_manual(leer_paginas(args.pdf))
    for seccion in secciones:
        print(f"{seccion['codigo']:<8} {len(seccion['texto']):>6}  {seccion['titulo']}")
    print(f"{len(secciones)} secciones, {sum(len(s['texto']) for s in secciones)} caracteres (versión {args.version}).")
    if args.dry_run:
        return

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    from utils.auditoria_chats_store import SupabaseAuditoriaStore

    SupabaseAuditoriaStore.from_env().guardar_manual(args.version, secciones)
    print("Manual guardado en Supabase.")


if __name__ == "__main__":
    main()
