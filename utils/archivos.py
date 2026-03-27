import io
import json
from pathlib import Path

import pandas as pd

from utils.transformaciones import validar_columnas, limpiar_texto
from utils.turnos import TURNOS_BASE, normalizar_turnos

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

ARCHIVO_TURNOS = DATA_DIR / "turnos.json"
ARCHIVO_CSV = DATA_DIR / "ultimo_reporte.csv"


def cargar_turnos_guardados():
    if not ARCHIVO_TURNOS.exists():
        return TURNOS_BASE.copy()
    try:
        contenido = json.loads(ARCHIVO_TURNOS.read_text(encoding="utf-8"))
        if not isinstance(contenido, dict):
            return TURNOS_BASE.copy()
        return normalizar_turnos(contenido)
    except Exception:
        return TURNOS_BASE.copy()


def guardar_turnos(turnos_config):
    ARCHIVO_TURNOS.write_text(
        json.dumps(normalizar_turnos(turnos_config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cargar_csv_guardado():
    if not ARCHIVO_CSV.exists():
        return None
    try:
        df = pd.read_csv(ARCHIVO_CSV)
        validar_columnas(df)
        return df
    except Exception:
        return None


def guardar_csv_subido(file_storage):
    contenido = file_storage.read()
    df = pd.read_csv(io.BytesIO(contenido))
    validar_columnas(df)
    ARCHIVO_CSV.write_bytes(contenido)
    return df


def extraer_agentes(df):
    df_tmp = df.copy()
    df_tmp["First Name"] = df_tmp["First Name"].apply(limpiar_texto)
    df_tmp["Last Name"] = df_tmp["Last Name"].apply(limpiar_texto)
    df_tmp["Agente"] = (df_tmp["First Name"] + " " + df_tmp["Last Name"]).str.strip()
    return sorted(df_tmp["Agente"].dropna().unique().tolist())