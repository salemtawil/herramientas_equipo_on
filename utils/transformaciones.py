import pandas as pd

COLUMNAS_REQUERIDAS = [
    "First Name",
    "Last Name",
    "Calls",
    "Outgoing calls",
    "Missed calls",
    "Call seconds",
    "Outgoing call seconds",
]

TRADUCCIONES = {
    "Turno": "Turno",
    "First Name": "Nombre",
    "Calls": "Llamadas",
    "Outgoing calls": "Salientes",
    "Missed calls": "Perdidas",
    "Call minutes": "Mins llamadas",
    "Outgoing call minutes": "Mins salientes",
    "Agente": "Agente",
}

COLUMNAS_VISIBLES = [
    "Turno",
    "Nombre",
    "Llamadas",
    "Salientes",
    "Perdidas",
    "Mins llamadas",
    "Mins salientes",
]


def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def convertir_a_numero(serie):
    return pd.to_numeric(serie, errors="coerce").fillna(0)


def segundos_a_minutos(valor):
    try:
        return int(round(float(valor) / 60))
    except Exception:
        return 0


def validar_columnas(df):
    faltantes = [col for col in COLUMNAS_REQUERIDAS if col not in df.columns]
    if faltantes:
        raise ValueError("Faltan estas columnas en el CSV: " + ", ".join(faltantes))