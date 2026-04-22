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

MAPEO_COLUMNAS = {
    "First Name": "First Name",
    "Nombre": "First Name",
    "Last Name": "Last Name",
    "Apellido": "Last Name",
    "Calls": "Calls",
    "Llamadas": "Calls",
    "Outgoing calls": "Outgoing calls",
    "Llamadas salientes": "Outgoing calls",
    "Missed calls": "Missed calls",
    "Llamadas perdidas": "Missed calls",
    "Call seconds": "Call seconds",
    "Segundos en llamadas": "Call seconds",
    "Outgoing call seconds": "Outgoing call seconds",
    "Segundos en salientes": "Outgoing call seconds",
    "Worktime": "Worktime",
    "worktime": "Worktime",
    "Work time": "Worktime",
    "Working time": "Worktime",
    "Tiempo de trabajo": "Worktime",
    "Horas trabajadas": "Worktime",
}


def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def convertir_a_numero(serie):
    return pd.to_numeric(serie, errors="coerce").fillna(0)


def convertir_worktime_a_segundos(serie):
    def convertir_valor(valor):
        if pd.isna(valor):
            return 0

        texto = str(valor).strip()
        if not texto:
            return 0

        if ":" in texto:
            partes = texto.split(":")
            try:
                partes = [float(parte) for parte in partes]
            except ValueError:
                return 0

            if len(partes) == 3:
                horas, minutos, segundos = partes
            elif len(partes) == 2:
                horas = 0
                minutos, segundos = partes
            else:
                return 0

            return int((horas * 3600) + (minutos * 60) + segundos)

        numero = pd.to_numeric(texto, errors="coerce")
        if pd.isna(numero):
            return 0

        return int(float(numero))

    return serie.apply(convertir_valor)


def segundos_a_minutos(valor):
    try:
        return int(round(float(valor) / 60))
    except Exception:
        return 0


def normalizar_columnas(df):
    df = df.copy()
    nuevas_columnas = {}

    for col in df.columns:
        nombre_limpio = limpiar_texto(col)
        if nombre_limpio in MAPEO_COLUMNAS:
            nuevas_columnas[col] = MAPEO_COLUMNAS[nombre_limpio]
        else:
            nuevas_columnas[col] = col

    df = df.rename(columns=nuevas_columnas)
    return df


def validar_columnas(df):
    df = normalizar_columnas(df)
    faltantes = [col for col in COLUMNAS_REQUERIDAS if col not in df.columns]
    if faltantes:
        raise ValueError("Faltan estas columnas en el CSV: " + ", ".join(faltantes))
    return df
