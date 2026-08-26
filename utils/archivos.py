import io
import gzip
import logging
import pandas as pd

from utils.transformaciones import limpiar_texto, validar_columnas

logger = logging.getLogger(__name__)

ENCODINGS_CANDIDATOS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
SEPARADORES_CANDIDATOS = (None, ",", ";", "\t", "|")
MAX_CSV_FILE_SIZE_BYTES = 25 * 1024 * 1024


def formatear_tamano_bytes(num_bytes):
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} bytes"


def leer_bytes_archivo_csv(file_storage, max_bytes=MAX_CSV_FILE_SIZE_BYTES):
    if file_storage is None:
        raise ValueError("No se recibio ningun archivo.")

    stream = getattr(file_storage, "stream", None)
    if stream and hasattr(stream, "tell") and hasattr(stream, "seek"):
        posicion = stream.tell()
        try:
            stream.seek(0, io.SEEK_END)
            tamano = stream.tell()
        finally:
            stream.seek(posicion)

        if tamano > max_bytes:
            raise ValueError(
                f"El archivo supera el limite permitido de {formatear_tamano_bytes(max_bytes)}."
            )

    contenido = file_storage.read()
    if hasattr(file_storage, "seek"):
        file_storage.seek(0)

    if _contenido_es_gzip(contenido):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(contenido)) as archivo_gzip:
                contenido = archivo_gzip.read(max_bytes + 1)
        except OSError as exc:
            raise ValueError("No se pudo descomprimir el CSV comprimido.") from exc

    if len(contenido) > max_bytes:
        raise ValueError(
            f"El archivo supera el limite permitido de {formatear_tamano_bytes(max_bytes)}."
        )

    return contenido


def _contenido_es_gzip(contenido):
    return len(contenido) >= 2 and contenido[:2] == b"\x1f\x8b"


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
    contenido = leer_bytes_archivo_csv(file_storage)
    df = _leer_csv_desde_bytes(contenido)
    df = validar_columnas(df)
    return df


def extraer_agentes(df):
    df_tmp = df.copy()
    df_tmp["First Name"] = df_tmp["First Name"].apply(limpiar_texto)
    df_tmp["Last Name"] = df_tmp["Last Name"].apply(limpiar_texto)
    df_tmp["Agente"] = (df_tmp["First Name"] + " " + df_tmp["Last Name"]).str.strip()
    return sorted(df_tmp["Agente"].dropna().unique().tolist())
