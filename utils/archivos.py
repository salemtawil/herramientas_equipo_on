import io
import logging
import pandas as pd

from utils.transformaciones import limpiar_texto, validar_columnas

logger = logging.getLogger(__name__)

ENCODINGS_CANDIDATOS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
SEPARADORES_CANDIDATOS = (None, ",", ";", "\t", "|")


def _leer_csv_desde_bytes(contenido):
    if not contenido:
        raise ValueError("El archivo está vacío.")

    ultimo_error = None

    for encoding in ENCODINGS_CANDIDATOS:
        try:
            texto = contenido.decode(encoding)
        except UnicodeDecodeError:
            continue

        for separador in SEPARADORES_CANDIDATOS:
            try:
                kwargs = {"engine": "python"}
                if separador is None:
                    kwargs["sep"] = None
                else:
                    kwargs["sep"] = separador

                df = pd.read_csv(io.StringIO(texto), **kwargs)
                if df is not None and len(df.columns) >= 1:
                    df.columns = [str(col).strip() for col in df.columns]
                    return df
            except Exception as exc:
                ultimo_error = exc
                logger.debug(
                    "No se pudo leer CSV con encoding=%s separador=%s",
                    encoding,
                    repr(separador),
                    exc_info=exc,
                )

    raise ValueError(f"No se pudo interpretar el CSV: {ultimo_error}")


def leer_csv_subido(file_storage):
    contenido = file_storage.read()
    if hasattr(file_storage, "seek"):
        file_storage.seek(0)

    df = _leer_csv_desde_bytes(contenido)
    df = validar_columnas(df)
    return df


def extraer_agentes(df):
    df_tmp = df.copy()
    df_tmp["First Name"] = df_tmp["First Name"].apply(limpiar_texto)
    df_tmp["Last Name"] = df_tmp["Last Name"].apply(limpiar_texto)
    df_tmp["Agente"] = (df_tmp["First Name"] + " " + df_tmp["Last Name"]).str.strip()
    return sorted(df_tmp["Agente"].dropna().unique().tolist())
