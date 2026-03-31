import io
import pandas as pd

from utils.transformaciones import limpiar_texto, validar_columnas


def leer_csv_subido(file_storage):
    contenido = file_storage.read()
    df = pd.read_csv(io.BytesIO(contenido))
    validar_columnas(df)
    return df


def extraer_agentes(df):
    df_tmp = df.copy()
    df_tmp["First Name"] = df_tmp["First Name"].apply(limpiar_texto)
    df_tmp["Last Name"] = df_tmp["Last Name"].apply(limpiar_texto)
    df_tmp["Agente"] = (df_tmp["First Name"] + " " + df_tmp["Last Name"]).str.strip()
    return sorted(df_tmp["Agente"].dropna().unique().tolist())