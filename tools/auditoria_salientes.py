import io
import json
import logging
import re
import unicodedata

import pandas as pd
from flask import Blueprint, Response, current_app, render_template, request

from utils.archivos import _leer_csv_desde_bytes
from utils.archivos import leer_bytes_archivo_csv
from utils.turnos import cargar_turnos_fijos
from utils.turnos import obtener_turno
from utils.estado_temporal import cargar_estado_temporal
from utils.estado_temporal import guardar_estado_temporal
from utils.estado_temporal import limpiar_estados_temporales_expirados

auditoria_salientes_bp = Blueprint("auditoria_salientes", __name__)
logger = logging.getLogger(__name__)
FORM_KEY_PAYLOAD = "auditoria_salientes_payload"
MAX_FILAS_VISTA_PREVIA = 500
VENTANA_CASO_MINUTOS = 10
MAX_LLAMADAS_ESPERADAS_POR_VENTANA = 3
MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT = 10
MAX_SEGUNDO_INTENTO_SIN_VM = 14
TURNO_SIN_TURNO = "Sin turno"
STATE_NAMESPACE = "auditoria_salientes"
STATE_TTL_HOURS = 24
STATE_INLINE_LIMIT_BYTES = 8 * 1024 * 1024

ESTADO_CONTESTADA = "Cumple por contestada"
ESTADO_COMPLETO = "Cumple completo"
ESTADO_SEGUNDO_INTENTO = "Cumple segundo intento, sin voicemail probable"
ESTADO_NO_CUMPLE = "No cumple"
ESTADO_NO_AUDITABLE = "No auditable"

COLUMNAS_DETALLE = [
    "Agente",
    "Numero",
    "Hora primera llamada",
    "Llamadas en ventana",
    "Duraciones intentos",
    "Hubo contestada",
    "Voicemail probable",
    "Estado final",
    "Observacion",
    "TicketId",
]

COLUMNAS_RESUMEN_TURNO = [
    "Turno",
    "Total de casos",
    "Cumple por contestada",
    "Cumple completo",
    "Cumple segundo intento sin voicemail probable",
    "No cumple",
    "No auditable",
    "Porcentaje de cumplimiento",
]

COLUMNAS_CASOS_RAROS = [
    "Agente",
    "Numero",
    "Hora primera llamada",
    "Hora ultima llamada",
    "Llamadas en ventana",
    "Duraciones intentos",
    "TicketIds",
    "Motivo alerta",
]

COLUMNAS_CASOS_INTERNAS = COLUMNAS_DETALLE + ["_estado", "_agente"]

MOTIVO_DATOS_INSUFICIENTES = "Datos insuficientes"
MOTIVO_DUPLICADO_EXACTO = "Duplicado exacto no usado para cumplimiento"

ALIAS_COLUMNAS = {
    "agente": [
        "fromName",
        "agente",
        "agent",
        "agent name",
        "nombre agente",
        "asesor",
        "advisor",
        "usuario",
        "owner",
    ],
    "numero": [
        "toNumber",
        "numero",
        "numero llamado",
        "número",
        "número llamado",
        "telefono",
        "telefono llamado",
        "teléfono",
        "teléfono llamado",
        "phone",
        "phone number",
        "called number",
        "dialed number",
        "destination",
        "to",
    ],
    "fecha": [
        "dateCreated",
        "fecha",
        "fecha llamada",
        "hora",
        "hora llamada",
        "fecha y hora",
        "call time",
        "call date",
        "datetime",
        "timestamp",
        "started at",
        "start time",
        "created at",
    ],
    "duracion": [
        "callDuration",
        "duracion",
        "duración",
        "call duration",
        "duration",
        "seconds",
        "segundos",
        "duration seconds",
        "call seconds",
        "billsec",
        "talk time",
    ],
    "ticket_id": [
        "ticketId",
        "ticketid",
        "ticket id",
        "ticket",
        "case id",
        "caseid",
    ],
    "fecha_contestada": [
        "dateAnswered",
        "date answered",
        "answered at",
        "fecha contestada",
        "fecha atendida",
    ],
}


def normalizar_texto(valor):
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def resolver_columna_por_alias(df, aliases):
    columnas = list(df.columns)
    columnas_norm = {normalizar_texto(col): col for col in columnas}

    for alias in aliases:
        alias_norm = normalizar_texto(alias)
        if alias_norm in columnas_norm:
            return columnas_norm[alias_norm]

    for alias in aliases:
        alias_norm = normalizar_texto(alias)
        for col_norm, col_original in columnas_norm.items():
            if alias_norm and alias_norm in col_norm:
                return col_original

    return None


def resolver_columnas_historial(df):
    columnas = {
        "agente": resolver_columna_por_alias(df, ALIAS_COLUMNAS["agente"]),
        "numero": resolver_columna_por_alias(df, ALIAS_COLUMNAS["numero"]),
        "fecha": resolver_columna_por_alias(df, ALIAS_COLUMNAS["fecha"]),
        "duracion": resolver_columna_por_alias(df, ALIAS_COLUMNAS["duracion"]),
        "ticket_id": resolver_columna_por_alias(df, ALIAS_COLUMNAS["ticket_id"]),
        "fecha_contestada": resolver_columna_por_alias(df, ALIAS_COLUMNAS["fecha_contestada"]),
    }

    if not columnas["agente"] and "First Name" in df.columns and "Last Name" in df.columns:
        columnas["agente"] = "__agente_compuesto__"

    faltantes = [clave for clave in ["agente", "numero", "fecha", "duracion"] if not columnas.get(clave)]
    if faltantes:
        raise ValueError(
            "No se pudieron identificar columnas clave del CSV: " + ", ".join(faltantes)
        )

    return columnas


def leer_csv_historial(archivo):
    contenido = leer_bytes_archivo_csv(archivo)
    return _leer_csv_desde_bytes(contenido)


def normalizar_numero(valor):
    if pd.isna(valor):
        return ""

    if isinstance(valor, float) and pd.notna(valor) and valor.is_integer():
        valor = int(valor)

    texto = str(valor).strip()
    if not texto:
        return ""

    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".", 1)[0]

    digitos = re.sub(r"\D+", "", texto)
    return digitos or texto


def parsear_duracion_segundos(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()
    if not texto:
        return None

    if ":" in texto:
        partes = texto.split(":")
        try:
            partes_numericas = [float(parte) for parte in partes]
        except ValueError:
            return None

        if len(partes_numericas) == 3:
            horas, minutos, segundos = partes_numericas
            if any(pd.isna(parte) for parte in partes_numericas):
                return None
            return int((horas * 3600) + (minutos * 60) + segundos)

        if len(partes_numericas) == 2:
            minutos, segundos = partes_numericas
            if any(pd.isna(parte) for parte in partes_numericas):
                return None
            return int((minutos * 60) + segundos)

        return None

    numero = pd.to_numeric(texto, errors="coerce")
    if pd.isna(numero):
        texto_norm = normalizar_texto(texto)

        match_min_seg = re.fullmatch(
            r"(?:(\d+)\s*(?:min|mins|minuto|minutos))?\s*"
            r"(?:(\d+)\s*(?:seg|segs|segundo|segundos))?",
            texto_norm,
        )
        if match_min_seg:
            minutos = int(match_min_seg.group(1) or 0)
            segundos = int(match_min_seg.group(2) or 0)
            if minutos or segundos:
                return (minutos * 60) + segundos

        match_solo_seg = re.search(r"(\d+)\s*(?:seg|segs|segundo|segundos)", texto_norm)
        if match_solo_seg:
            return int(match_solo_seg.group(1))

        match_solo_min = re.search(r"(\d+)\s*(?:min|mins|minuto|minutos)", texto_norm)
        if match_solo_min:
            return int(match_solo_min.group(1)) * 60

        return None

    if pd.isna(numero):
        return None

    return int(float(numero))


def parsear_fechas(serie):
    serie_texto = serie.apply(limpiar_texto)
    fechas = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
    tiene_valor = serie_texto.ne("")
    es_iso = serie_texto.str.match(r"^\d{4}-\d{1,2}-\d{1,2}(?:[ T].*)?$", na=False)

    if (tiene_valor & es_iso).any():
        fechas.loc[tiene_valor & es_iso] = pd.to_datetime(
            serie_texto.loc[tiene_valor & es_iso],
            errors="coerce",
            format="ISO8601",
            dayfirst=False,
            utc=True,
        ).dt.tz_convert(None)

    pendientes = tiene_valor & fechas.isna() & ~es_iso
    if pendientes.any():
        fechas.loc[pendientes] = pd.to_datetime(
            serie_texto.loc[pendientes],
            errors="coerce",
            dayfirst=True,
            utc=True,
        ).dt.tz_convert(None)

    pendientes = tiene_valor & fechas.isna() & ~es_iso
    if pendientes.any():
        fechas.loc[pendientes] = pd.to_datetime(
            serie_texto.loc[pendientes],
            errors="coerce",
            dayfirst=False,
            utc=True,
        ).dt.tz_convert(None)
    return fechas


def preparar_dataframe_historial(df):
    columnas = resolver_columnas_historial(df)
    base = pd.DataFrame()

    if columnas["agente"] == "__agente_compuesto__":
        base["Agente"] = (
            df["First Name"].apply(limpiar_texto) + " " + df["Last Name"].apply(limpiar_texto)
        ).str.strip()
    else:
        base["Agente"] = df[columnas["agente"]].apply(limpiar_texto)

    base["Numero"] = df[columnas["numero"]].apply(limpiar_texto)
    base["Numero normalizado"] = base["Numero"].apply(normalizar_numero)
    base["Fecha original"] = df[columnas["fecha"]].apply(limpiar_texto)
    base["Fecha llamada"] = parsear_fechas(df[columnas["fecha"]])
    base["Duracion original"] = df[columnas["duracion"]].apply(limpiar_texto)
    base["Duracion segundos"] = df[columnas["duracion"]].apply(parsear_duracion_segundos)
    base["TicketId"] = (
        df[columnas["ticket_id"]].apply(limpiar_texto)
        if columnas.get("ticket_id")
        else ""
    )
    base["Fecha contestada"] = (
        df[columnas["fecha_contestada"]].apply(limpiar_texto)
        if columnas.get("fecha_contestada")
        else ""
    )
    base["Fue contestada"] = base["Fecha contestada"].astype(str).str.strip().ne("")

    return base, columnas


def formatear_duracion(valor):
    if valor is None or pd.isna(valor):
        return "sin dato"
    try:
        return f"{int(float(valor))} s"
    except (TypeError, ValueError, OverflowError):
        return "sin dato"


def formatear_fecha(valor, fallback=""):
    if pd.isna(valor):
        return fallback
    return valor.strftime("%Y-%m-%d %H:%M:%S")


def clasificar_caso(llamadas, min_segundo_intento_sin_vm=MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT):
    duraciones = [llamada["duracion_segundos"] for llamada in llamadas]
    hubo_contestada = any(_llamada_contestada(llamada) for llamada in llamadas)
    voicemail_probable = any(
        duracion is not None and 15 <= duracion <= 75
        for duracion in duraciones[1:]
    )
    segundo_intento_valido_sin_vm = any(
        duracion is not None
        and min_segundo_intento_sin_vm <= duracion <= MAX_SEGUNDO_INTENTO_SIN_VM
        for duracion in duraciones[1:]
    )

    if hubo_contestada:
        return ESTADO_CONTESTADA, True, voicemail_probable

    if len(llamadas) == 1:
        return ESTADO_NO_CUMPLE, False, False

    if voicemail_probable:
        return ESTADO_COMPLETO, False, True

    if segundo_intento_valido_sin_vm:
        return ESTADO_SEGUNDO_INTENTO, False, False

    return ESTADO_NO_CUMPLE, False, False


def _llamada_contestada(llamada):
    duracion = llamada.get("duracion_segundos")
    return bool(llamada.get("fue_contestada")) or (duracion is not None and duracion > 75)


def construir_caso_desde_llamadas(
    llamadas,
    observacion="",
    min_segundo_intento_sin_vm=MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT,
):
    estado, hubo_contestada, voicemail_probable = clasificar_caso(
        llamadas,
        min_segundo_intento_sin_vm=min_segundo_intento_sin_vm,
    )
    primera = llamadas[0]
    tickets = [llamada["ticket_id"] for llamada in llamadas if llamada["ticket_id"]]
    ticket_texto = ", ".join(dict.fromkeys(tickets))

    return {
        "Agente": primera["agente"] or "Sin agente",
        "Numero": primera["numero"] or "Sin numero",
        "Hora primera llamada": formatear_fecha(primera["fecha"], primera["fecha_original"]),
        "Llamadas en ventana": len(llamadas),
        "Duraciones intentos": " | ".join(formatear_duracion(llamada["duracion_segundos"]) for llamada in llamadas),
        "Hubo contestada": "Si" if hubo_contestada else "No",
        "Voicemail probable": "Si" if voicemail_probable else "No",
        "Estado final": estado,
        "Observacion": observacion,
        "TicketId": ticket_texto,
        "_estado": estado,
        "_agente": primera["agente"] or "Sin agente",
    }


def construir_caso_ambiguo_desde_fila(fila, motivo):
    llamada = {
        "agente": fila.get("Agente", ""),
        "numero": fila.get("Numero", ""),
        "fecha": fila.get("Fecha llamada"),
        "fecha_original": fila.get("Fecha original", ""),
        "duracion_segundos": fila.get("Duracion segundos"),
        "ticket_id": fila.get("TicketId", ""),
        "fue_contestada": fila.get("Fue contestada", False),
    }
    caso = construir_caso_desde_llamadas([llamada], observacion=motivo)
    caso["Hubo contestada"] = "No"
    caso["Voicemail probable"] = "No"
    caso["Estado final"] = ESTADO_NO_AUDITABLE
    caso["_estado"] = ESTADO_NO_AUDITABLE
    return caso


def analizar_casos(df_preparado, min_segundo_intento_sin_vm=MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT):
    casos = []
    validas = []
    claves_vistas = set()

    for fila in df_preparado.to_dict(orient="records"):
        faltan_datos = (
            not fila["Agente"]
            or not fila["Numero normalizado"]
            or pd.isna(fila["Fecha llamada"])
            or pd.isna(fila["Duracion segundos"])
        )

        clave_dedupe = None
        if not faltan_datos:
            fecha = fila["Fecha llamada"]
            clave_dedupe = (
                normalizar_texto(fila["Agente"]),
                fila["Numero normalizado"],
                fecha.isoformat() if pd.notna(fecha) else "",
                fila["Duracion segundos"],
                fila["TicketId"],
            )

        if faltan_datos:
            casos.append(construir_caso_ambiguo_desde_fila(fila, MOTIVO_DATOS_INSUFICIENTES))
            continue

        if clave_dedupe in claves_vistas:
            casos.append(construir_caso_ambiguo_desde_fila(fila, MOTIVO_DUPLICADO_EXACTO))
            continue

        claves_vistas.add(clave_dedupe)
        validas.append(
            {
                "agente": fila["Agente"],
                "numero": fila["Numero"],
                "numero_normalizado": fila["Numero normalizado"],
                "fecha": fila["Fecha llamada"],
                "fecha_original": fila["Fecha original"],
                "duracion_segundos": fila["Duracion segundos"],
                "ticket_id": fila["TicketId"],
                "fue_contestada": bool(fila.get("Fue contestada")) or (
                    pd.notna(fila["Duracion segundos"]) and fila["Duracion segundos"] > 75
                ),
            }
        )

    df_validas = pd.DataFrame(validas)
    if df_validas.empty:
        return pd.DataFrame(casos, columns=COLUMNAS_CASOS_INTERNAS)

    df_validas = df_validas.sort_values(
        by=["agente", "numero_normalizado", "fecha"]
    ).reset_index(drop=True)

    ventana = pd.Timedelta(minutes=VENTANA_CASO_MINUTOS)

    for (_, _), grupo in df_validas.groupby(["agente", "numero_normalizado"], sort=False):
        llamadas = grupo.to_dict(orient="records")
        indice = 0

        while indice < len(llamadas):
            primera = llamadas[indice]
            llamadas_caso = [primera]
            inicio_caso = primera["fecha"]

            siguiente = indice + 1
            while siguiente < len(llamadas) and not any(_llamada_contestada(llamada) for llamada in llamadas_caso):
                actual = llamadas[siguiente]
                if actual["fecha"] > inicio_caso + ventana:
                    break

                llamadas_caso.append(actual)
                siguiente += 1

            casos.append(
                construir_caso_desde_llamadas(
                    llamadas_caso,
                    min_segundo_intento_sin_vm=min_segundo_intento_sin_vm,
                )
            )
            indice = siguiente

    if not casos:
        return pd.DataFrame(columns=COLUMNAS_CASOS_INTERNAS)

    df_casos = pd.DataFrame(casos)
    return df_casos.sort_values(
        by=["Hora primera llamada", "Agente", "Numero"],
        ascending=[True, True, True],
    ).reset_index(drop=True)


def porcentaje_cumplimiento(cumplidos, total):
    if not total:
        return 0.0
    return round((cumplidos / total) * 100, 2)


def parsear_min_segundo_intento(valor):
    try:
        numero = int(float(str(valor or "").strip()))
    except (TypeError, ValueError):
        return MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT

    if numero < 1:
        return 1
    if numero > MAX_SEGUNDO_INTENTO_SIN_VM:
        return MAX_SEGUNDO_INTENTO_SIN_VM
    return numero


def construir_configuracion_auditoria(min_segundo_intento_sin_vm=None):
    return {
        "min_segundo_intento_sin_vm": parsear_min_segundo_intento(
            min_segundo_intento_sin_vm
            if min_segundo_intento_sin_vm is not None
            else MIN_SEGUNDO_INTENTO_SIN_VM_DEFAULT
        ),
        "max_segundo_intento_sin_vm": MAX_SEGUNDO_INTENTO_SIN_VM,
        "min_voicemail_probable": 15,
        "max_voicemail_probable": 75,
    }


def construir_resumen_general(df_casos):
    no_auditable = int((df_casos["_estado"] == ESTADO_NO_AUDITABLE).sum())
    total = int(len(df_casos) - no_auditable)
    contestada = int((df_casos["_estado"] == ESTADO_CONTESTADA).sum())
    completo = int((df_casos["_estado"] == ESTADO_COMPLETO).sum())
    segundo = int((df_casos["_estado"] == ESTADO_SEGUNDO_INTENTO).sum())
    no_cumple = int((df_casos["_estado"] == ESTADO_NO_CUMPLE).sum())
    cumplidos = contestada + completo + segundo

    return {
        "Total de casos evaluados": total,
        "No auditable": no_auditable,
        "Cumple por contestada": contestada,
        "Cumple completo": completo,
        "Cumple segundo intento sin voicemail probable": segundo,
        "No cumple": no_cumple,
        "Porcentaje general de cumplimiento": porcentaje_cumplimiento(cumplidos, total),
    }


def construir_reconciliacion(df_preparado, df_casos):
    total_filas = int(len(df_preparado))
    no_auditables = int((df_casos["_estado"] == ESTADO_NO_AUDITABLE).sum())
    datos_insuficientes = int((df_casos["Observacion"] == MOTIVO_DATOS_INSUFICIENTES).sum())
    duplicados_exactos = int((df_casos["Observacion"] == MOTIVO_DUPLICADO_EXACTO).sum())
    filas_validas_usadas = max(total_filas - datos_insuficientes - duplicados_exactos, 0)
    casos_evaluados = int(len(df_casos) - no_auditables)

    return {
        "Filas recibidas": total_filas,
        "Filas validas usadas": filas_validas_usadas,
        "Datos insuficientes": datos_insuficientes,
        "Duplicados exactos": duplicados_exactos,
        "No auditables": no_auditables,
        "Casos evaluados": casos_evaluados,
        "Casos finales totales": int(len(df_casos)),
    }


def construir_reconciliacion_desde_casos(df_casos):
    no_auditables = int((df_casos["_estado"] == ESTADO_NO_AUDITABLE).sum())
    datos_insuficientes = int((df_casos["Observacion"] == MOTIVO_DATOS_INSUFICIENTES).sum())
    duplicados_exactos = int((df_casos["Observacion"] == MOTIVO_DUPLICADO_EXACTO).sum())
    casos_evaluados = int(len(df_casos) - no_auditables)

    return {
        "Filas recibidas": "",
        "Filas validas usadas": "",
        "Datos insuficientes": datos_insuficientes,
        "Duplicados exactos": duplicados_exactos,
        "No auditables": no_auditables,
        "Casos evaluados": casos_evaluados,
        "Casos finales totales": int(len(df_casos)),
    }


def construir_advertencias_calidad(reconciliacion):
    if not reconciliacion:
        return []

    advertencias = []
    datos_insuficientes = int(reconciliacion.get("Datos insuficientes") or 0)
    duplicados_exactos = int(reconciliacion.get("Duplicados exactos") or 0)
    no_auditables = int(reconciliacion.get("No auditables") or 0)
    filas_recibidas = reconciliacion.get("Filas recibidas")
    casos_evaluados = int(reconciliacion.get("Casos evaluados") or 0)

    if datos_insuficientes:
        advertencias.append(
            f"{datos_insuficientes} fila(s) quedaron no auditables por datos insuficientes."
        )
    if duplicados_exactos:
        advertencias.append(
            f"{duplicados_exactos} duplicado(s) exactos no se usaron para calcular cumplimiento."
        )
    if no_auditables and not datos_insuficientes and not duplicados_exactos:
        advertencias.append(f"{no_auditables} caso(s) quedaron no auditables.")
    if filas_recibidas != "" and filas_recibidas is not None and int(filas_recibidas) == 0:
        advertencias.append("El CSV no contiene filas de llamadas para evaluar.")
    if casos_evaluados == 0 and no_auditables:
        advertencias.append("No hay casos evaluables; el porcentaje de cumplimiento no debe interpretarse.")

    return advertencias


def construir_advertencias_columnas(columnas):
    advertencias = []
    if not columnas.get("ticket_id"):
        advertencias.append("El CSV no trae TicketId; la trazabilidad por caso queda limitada.")
    if not columnas.get("fecha_contestada"):
        advertencias.append(
            "El CSV no trae fecha de contestación; las contestadas se inferirán solo por duración."
        )
    return advertencias


def construir_alertas_casos_raros(df_preparado):
    if df_preparado.empty:
        return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    columnas_obligatorias = [
        "Agente",
        "Numero",
        "Numero normalizado",
        "Fecha llamada",
        "Duracion segundos",
    ]
    for columna in columnas_obligatorias:
        if columna not in df_preparado.columns:
            return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    validas = df_preparado[
        df_preparado["Agente"].astype(str).str.strip().ne("")
        & df_preparado["Numero normalizado"].astype(str).str.strip().ne("")
        & df_preparado["Fecha llamada"].notna()
        & df_preparado["Duracion segundos"].notna()
    ].copy()
    if validas.empty:
        return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    validas = validas.drop_duplicates(
        subset=[
            "Agente",
            "Numero normalizado",
            "Fecha llamada",
            "Duracion segundos",
            "TicketId",
        ]
    )
    validas = validas.sort_values(
        by=["Agente", "Numero normalizado", "Fecha llamada"]
    ).reset_index(drop=True)

    alertas = []
    ventana = pd.Timedelta(minutes=VENTANA_CASO_MINUTOS)

    for (_, _), grupo in validas.groupby(["Agente", "Numero normalizado"], sort=False):
        llamadas = grupo.to_dict(orient="records")
        indice = 0

        while indice < len(llamadas):
            inicio = llamadas[indice]["Fecha llamada"]
            llamadas_ventana = [llamadas[indice]]
            siguiente = indice + 1

            while siguiente < len(llamadas):
                llamada = llamadas[siguiente]
                if llamada["Fecha llamada"] > inicio + ventana:
                    break
                llamadas_ventana.append(llamada)
                siguiente += 1

            if len(llamadas_ventana) > MAX_LLAMADAS_ESPERADAS_POR_VENTANA:
                duraciones = [
                    formatear_duracion(llamada.get("Duracion segundos"))
                    for llamada in llamadas_ventana
                ]
                ticket_ids = sorted(
                    {
                        limpiar_texto(llamada.get("TicketId"))
                        for llamada in llamadas_ventana
                        if limpiar_texto(llamada.get("TicketId"))
                    }
                )
                primera = llamadas_ventana[0]
                ultima = llamadas_ventana[-1]
                alertas.append(
                    {
                        "Agente": primera["Agente"],
                        "Numero": primera["Numero"],
                        "Hora primera llamada": formatear_fecha(
                            primera["Fecha llamada"],
                            primera.get("Fecha original", ""),
                        ),
                        "Hora ultima llamada": formatear_fecha(
                            ultima["Fecha llamada"],
                            ultima.get("Fecha original", ""),
                        ),
                        "Llamadas en ventana": len(llamadas_ventana),
                        "Duraciones intentos": " | ".join(duraciones),
                        "TicketIds": ", ".join(ticket_ids),
                        "Motivo alerta": (
                            f"Mas de {MAX_LLAMADAS_ESPERADAS_POR_VENTANA} llamadas "
                            f"al mismo numero en {VENTANA_CASO_MINUTOS} minutos"
                        ),
                    }
                )

            indice = siguiente

    return pd.DataFrame(alertas, columns=COLUMNAS_CASOS_RAROS)


def dataframe_reconciliacion(reconciliacion, advertencias_calidad=None, configuracion=None):
    filas = [
        {"Metrica": nombre, "Valor": valor}
        for nombre, valor in (reconciliacion or {}).items()
    ]

    if configuracion:
        filas.append(
            {
                "Metrica": "Minimo 2do intento sin VM",
                "Valor": configuracion.get("min_segundo_intento_sin_vm"),
            }
        )

    for indice, advertencia in enumerate(advertencias_calidad or [], start=1):
        filas.append({"Metrica": f"Advertencia {indice}", "Valor": advertencia})

    return pd.DataFrame(filas, columns=["Metrica", "Valor"])


def construir_resumen_por_agente(df_casos):
    if df_casos.empty:
        return pd.DataFrame(
            columns=[
                "Turno",
                "Agente",
                "Total de casos",
                "Cumple por contestada",
                "Cumple completo",
                "Cumple segundo intento sin voicemail probable",
                "No cumple",
                "No auditable",
                "Porcentaje de cumplimiento",
            ]
        )

    filas = []

    for agente, grupo in df_casos.groupby("_agente", dropna=False):
        no_auditable = int((grupo["_estado"] == ESTADO_NO_AUDITABLE).sum())
        total = int(len(grupo) - no_auditable)
        contestada = int((grupo["_estado"] == ESTADO_CONTESTADA).sum())
        completo = int((grupo["_estado"] == ESTADO_COMPLETO).sum())
        segundo = int((grupo["_estado"] == ESTADO_SEGUNDO_INTENTO).sum())
        no_cumple = int((grupo["_estado"] == ESTADO_NO_CUMPLE).sum())
        cumplidos = contestada + completo + segundo

        filas.append(
            {
                "Turno": grupo["_turno"].iloc[0] if "_turno" in grupo.columns and not grupo.empty else TURNO_SIN_TURNO,
                "Agente": agente,
                "Total de casos": total,
                "Cumple por contestada": contestada,
                "Cumple completo": completo,
                "Cumple segundo intento sin voicemail probable": segundo,
                "No cumple": no_cumple,
                "No auditable": no_auditable,
                "Porcentaje de cumplimiento": porcentaje_cumplimiento(cumplidos, total),
            }
        )

    return pd.DataFrame(filas).sort_values(
        by=["Porcentaje de cumplimiento", "Agente"],
        ascending=[False, True],
    )


def obtener_orden_turnos():
    return list(cargar_turnos_fijos().keys()) + [TURNO_SIN_TURNO]


def construir_mapa_agente_turno():
    mapa = {}

    for turno, agentes in cargar_turnos_fijos().items():
        for agente in agentes:
            clave = normalizar_texto(agente)
            if clave:
                mapa[clave] = turno

    return mapa


def obtener_turno_auditoria(agente, mapa_agente_turno=None, turnos_config=None):
    if mapa_agente_turno is None:
        mapa_agente_turno = construir_mapa_agente_turno()
    if turnos_config is None:
        turnos_config = cargar_turnos_fijos()

    clave = normalizar_texto(agente)
    if clave in mapa_agente_turno:
        return mapa_agente_turno[clave]

    turno = obtener_turno(agente, turnos_config)
    if turno == "Sin asignar":
        return TURNO_SIN_TURNO
    return turno


def asignar_turnos_a_casos(df_casos):
    if df_casos.empty:
        df_resultado = df_casos.reindex(columns=COLUMNAS_CASOS_INTERNAS).copy()
        df_resultado["_turno"] = []
        return df_resultado

    mapa_agente_turno = construir_mapa_agente_turno()
    turnos_config = cargar_turnos_fijos()
    df_resultado = df_casos.copy()
    df_resultado["_turno"] = df_resultado["_agente"].apply(
        lambda agente: obtener_turno_auditoria(agente, mapa_agente_turno, turnos_config)
    )
    return df_resultado


def filtrar_casos_por_turnos(df_casos, turnos_seleccionados):
    if df_casos.empty:
        return df_casos
    if turnos_seleccionados is None:
        return df_casos
    return df_casos[df_casos["_turno"].isin(turnos_seleccionados)].copy()


def construir_resumen_por_turno(df_casos):
    if df_casos.empty:
        return pd.DataFrame(columns=COLUMNAS_RESUMEN_TURNO)

    filas = []

    for turno, grupo in df_casos.groupby("_turno", dropna=False):
        no_auditable = int((grupo["_estado"] == ESTADO_NO_AUDITABLE).sum())
        total = int(len(grupo) - no_auditable)
        contestada = int((grupo["_estado"] == ESTADO_CONTESTADA).sum())
        completo = int((grupo["_estado"] == ESTADO_COMPLETO).sum())
        segundo = int((grupo["_estado"] == ESTADO_SEGUNDO_INTENTO).sum())
        no_cumple = int((grupo["_estado"] == ESTADO_NO_CUMPLE).sum())
        cumplidos = contestada + completo + segundo

        filas.append(
            {
                "Turno": turno,
                "Total de casos": total,
                "Cumple por contestada": contestada,
                "Cumple completo": completo,
                "Cumple segundo intento sin voicemail probable": segundo,
                "No cumple": no_cumple,
                "No auditable": no_auditable,
                "Porcentaje de cumplimiento": porcentaje_cumplimiento(cumplidos, total),
            }
        )

    df_resumen = pd.DataFrame(filas)
    orden_turnos = obtener_orden_turnos()
    df_resumen["__orden_turno"] = df_resumen["Turno"].apply(
        lambda turno: orden_turnos.index(turno) if turno in orden_turnos else len(orden_turnos)
    )
    return df_resumen.sort_values(by=["__orden_turno", "Turno"]).drop(columns=["__orden_turno"]).reset_index(drop=True)


def respuesta_csv_desde_df(df, nombre_archivo):
    salida = io.StringIO()
    df.to_csv(salida, index=False, encoding="utf-8-sig")
    csv_texto = salida.getvalue()

    return Response(
        csv_texto,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


def serializar_resultado_auditoria(
    df_casos,
    reconciliacion=None,
    configuracion=None,
    advertencias_calidad=None,
    df_casos_raros=None,
):
    return guardar_estado_temporal(
        {
            "casos": df_casos.to_dict(orient="records"),
            "reconciliacion": reconciliacion or construir_reconciliacion_desde_casos(df_casos),
            "configuracion": configuracion or construir_configuracion_auditoria(),
            "advertencias_calidad": advertencias_calidad or [],
            "casos_raros": (
                df_casos_raros.to_dict(orient="records")
                if df_casos_raros is not None
                else []
            ),
        },
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
        ttl_hours=STATE_TTL_HOURS,
        inline_limit_bytes=STATE_INLINE_LIMIT_BYTES,
    )


def cargar_resultado_auditoria_desde_payload(payload):
    if not payload:
        return None

    item = cargar_estado_temporal(
        payload,
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
    )

    if not item:
        return None

    if "casos" in item:
        df_casos = pd.DataFrame(item["casos"])
    elif "df_casos_json" in item:
        df_casos = pd.DataFrame(json.loads(item["df_casos_json"]))
    else:
        return None
    if df_casos.empty:
        return pd.DataFrame(columns=COLUMNAS_CASOS_INTERNAS)

    for columna in COLUMNAS_CASOS_INTERNAS:
        if columna not in df_casos.columns:
            df_casos[columna] = ""

    return df_casos


def cargar_reconciliacion_desde_payload(payload, df_casos=None):
    if not payload:
        return None

    item = cargar_estado_temporal(
        payload,
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
    )
    if not item:
        return construir_reconciliacion_desde_casos(df_casos) if df_casos is not None else None

    reconciliacion = item.get("reconciliacion") if isinstance(item, dict) else None
    if isinstance(reconciliacion, dict):
        return reconciliacion

    return construir_reconciliacion_desde_casos(df_casos) if df_casos is not None else None


def cargar_configuracion_desde_payload(payload):
    if not payload:
        return construir_configuracion_auditoria()

    item = cargar_estado_temporal(
        payload,
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
    )
    if not item or not isinstance(item, dict):
        return construir_configuracion_auditoria()

    configuracion = item.get("configuracion")
    if not isinstance(configuracion, dict):
        return construir_configuracion_auditoria()

    return construir_configuracion_auditoria(
        configuracion.get("min_segundo_intento_sin_vm")
    )


def cargar_advertencias_calidad_desde_payload(payload, reconciliacion=None):
    if not payload:
        return construir_advertencias_calidad(reconciliacion)

    item = cargar_estado_temporal(
        payload,
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
    )
    if isinstance(item, dict) and isinstance(item.get("advertencias_calidad"), list):
        return item["advertencias_calidad"]

    return construir_advertencias_calidad(reconciliacion)


def cargar_casos_raros_desde_payload(payload):
    if not payload:
        return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    item = cargar_estado_temporal(
        payload,
        secret_key=current_app.secret_key,
        salt="auditoria-salientes-payload",
        namespace=STATE_NAMESPACE,
    )
    if not isinstance(item, dict):
        return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    casos_raros = item.get("casos_raros")
    if not isinstance(casos_raros, list):
        return pd.DataFrame(columns=COLUMNAS_CASOS_RAROS)

    df_casos_raros = pd.DataFrame(casos_raros)
    for columna in COLUMNAS_CASOS_RAROS:
        if columna not in df_casos_raros.columns:
            df_casos_raros[columna] = ""

    return df_casos_raros[COLUMNAS_CASOS_RAROS]


@auditoria_salientes_bp.route("/auditoria-salientes", methods=["GET", "POST"])
def auditoria_salientes():
    limpiar_estados_temporales_expirados(STATE_NAMESPACE, ttl_hours=STATE_TTL_HOURS)

    mensaje = ""
    advertencia = ""
    resumen_general = None
    resumen_agente = None
    resumen_turno = None
    detalle_casos = None
    casos_raros = None
    casos_raros_total = 0
    columnas_resumen_agente = None
    columnas_resumen_turno = COLUMNAS_RESUMEN_TURNO
    columnas_detalle = COLUMNAS_DETALLE
    columnas_casos_raros = COLUMNAS_CASOS_RAROS
    reconciliacion = None
    advertencias_calidad = []
    configuracion_auditoria = construir_configuracion_auditoria()
    payload_cache = ""
    turnos_disponibles = obtener_orden_turnos()
    turnos_seleccionados = turnos_disponibles.copy()

    if request.method == "POST":
        accion = (request.form.get("accion") or "analizar_csv").strip()

        try:
            if accion == "analizar_csv":
                archivo = request.files.get("archivo")

                if not archivo or not archivo.filename:
                    advertencia = "Selecciona un archivo CSV."
                else:
                    configuracion_auditoria = construir_configuracion_auditoria(
                        request.form.get("min_segundo_intento_sin_vm")
                    )
                    df = leer_csv_historial(archivo)
                    df_preparado, _columnas = preparar_dataframe_historial(df)
                    df_casos = asignar_turnos_a_casos(
                        analizar_casos(
                            df_preparado,
                            min_segundo_intento_sin_vm=configuracion_auditoria[
                                "min_segundo_intento_sin_vm"
                            ],
                        )
                    )
                    df_casos_raros = construir_alertas_casos_raros(df_preparado)
                    reconciliacion = construir_reconciliacion(df_preparado, df_casos)
                    advertencias_calidad = (
                        construir_advertencias_calidad(reconciliacion)
                        + construir_advertencias_columnas(_columnas)
                    )
                    payload_cache = serializar_resultado_auditoria(
                        df_casos,
                        reconciliacion,
                        configuracion_auditoria,
                        advertencias_calidad,
                        df_casos_raros,
                    )

                    resumen_general = construir_resumen_general(df_casos)

                    df_resumen_agente = construir_resumen_por_agente(df_casos)
                    columnas_resumen_agente = list(df_resumen_agente.columns)
                    resumen_agente = df_resumen_agente.to_dict(orient="records")

                    detalle_casos = (
                        df_casos[COLUMNAS_DETALLE]
                        .head(MAX_FILAS_VISTA_PREVIA)
                        .to_dict(orient="records")
                    )
                    casos_raros = (
                        df_casos_raros.head(MAX_FILAS_VISTA_PREVIA).to_dict(orient="records")
                    )
                    casos_raros_total = len(df_casos_raros)

                    mensaje = "CSV analizado correctamente."
                    if len(df_casos) > MAX_FILAS_VISTA_PREVIA:
                        mensaje += f" Mostrando los primeros {MAX_FILAS_VISTA_PREVIA} casos en el detalle."
                    if len(df_casos_raros) > MAX_FILAS_VISTA_PREVIA:
                        mensaje += f" Mostrando las primeras {MAX_FILAS_VISTA_PREVIA} alertas de casos raros."

            else:
                payload_cache = (request.form.get(FORM_KEY_PAYLOAD) or "").strip()
                df_casos = cargar_resultado_auditoria_desde_payload(payload_cache)
                df_casos_raros = cargar_casos_raros_desde_payload(payload_cache)
                reconciliacion = cargar_reconciliacion_desde_payload(payload_cache, df_casos)
                configuracion_auditoria = cargar_configuracion_desde_payload(payload_cache)
                advertencias_calidad = cargar_advertencias_calidad_desde_payload(
                    payload_cache,
                    reconciliacion,
                )
                if request.form.get("usar_filtro_turnos") == "1":
                    turnos_seleccionados = request.form.getlist("turnos")
                elif accion == "limpiar_filtro_turnos":
                    turnos_seleccionados = turnos_disponibles.copy()
                else:
                    turnos_seleccionados = request.form.getlist("turnos") or turnos_disponibles.copy()
                df_casos_filtrado_turnos = filtrar_casos_por_turnos(df_casos, turnos_seleccionados) if df_casos is not None else None
                if df_casos is None:
                    advertencia = "Primero analiza un CSV."
                elif accion == "descargar_resumen_agente":
                    df_resumen_agente = construir_resumen_por_agente(df_casos)
                    return respuesta_csv_desde_df(
                        df_resumen_agente,
                        "auditoria_salientes_resumen_agente.csv",
                    )
                elif accion == "descargar_detalle_casos":
                    return respuesta_csv_desde_df(
                        df_casos[COLUMNAS_DETALLE],
                        "auditoria_salientes_detalle_casos.csv",
                    )
                elif accion == "descargar_resumen_turno":
                    return respuesta_csv_desde_df(
                        construir_resumen_por_turno(df_casos_filtrado_turnos),
                        "auditoria_salientes_resumen_turno.csv",
                    )
                elif accion == "descargar_reconciliacion":
                    return respuesta_csv_desde_df(
                        dataframe_reconciliacion(
                            reconciliacion,
                            advertencias_calidad,
                            configuracion_auditoria,
                        ),
                        "auditoria_salientes_reconciliacion.csv",
                    )
                elif accion == "descargar_no_auditables":
                    return respuesta_csv_desde_df(
                        df_casos[df_casos["_estado"] == ESTADO_NO_AUDITABLE][COLUMNAS_DETALLE],
                        "auditoria_salientes_no_auditables.csv",
                    )
                elif accion == "descargar_casos_raros":
                    return respuesta_csv_desde_df(
                        df_casos_raros[COLUMNAS_CASOS_RAROS],
                        "auditoria_salientes_casos_raros.csv",
                    )
                elif accion == "filtrar_turnos":
                    pass
                elif accion == "limpiar_filtro_turnos":
                    pass
                else:
                    advertencia = "Accion no valida."

            if payload_cache:
                df_casos = cargar_resultado_auditoria_desde_payload(payload_cache)
                if df_casos is not None:
                    resumen_general = construir_resumen_general(df_casos)
                    if reconciliacion is None:
                        reconciliacion = cargar_reconciliacion_desde_payload(payload_cache, df_casos)
                    advertencias_calidad = cargar_advertencias_calidad_desde_payload(
                        payload_cache,
                        reconciliacion,
                    )
                    df_resumen_agente = construir_resumen_por_agente(df_casos)
                    columnas_resumen_agente = list(df_resumen_agente.columns)
                    resumen_agente = df_resumen_agente.to_dict(orient="records")
                    df_casos_filtrado_turnos = filtrar_casos_por_turnos(df_casos, turnos_seleccionados)
                    df_resumen_turno = construir_resumen_por_turno(df_casos_filtrado_turnos)
                    resumen_turno = df_resumen_turno.to_dict(orient="records")
                    df_casos_raros = cargar_casos_raros_desde_payload(payload_cache)
                    casos_raros = (
                        df_casos_raros.head(MAX_FILAS_VISTA_PREVIA).to_dict(orient="records")
                    )
                    casos_raros_total = len(df_casos_raros)
                    detalle_casos = (
                        df_casos[COLUMNAS_DETALLE]
                        .head(MAX_FILAS_VISTA_PREVIA)
                        .to_dict(orient="records")
                    )

        except Exception as e:
            logger.exception("Error procesando auditoria_salientes")
            advertencia = f"No se pudo procesar el archivo: {e}"

    return render_template(
        "auditoria_salientes.html",
        mensaje=mensaje,
        advertencia=advertencia,
        resumen_general=resumen_general,
        resumen_agente=resumen_agente,
        columnas_resumen_agente=columnas_resumen_agente,
        resumen_turno=resumen_turno,
        columnas_resumen_turno=columnas_resumen_turno,
        detalle_casos=detalle_casos,
        columnas_detalle=columnas_detalle,
        casos_raros=casos_raros,
        casos_raros_total=casos_raros_total,
        columnas_casos_raros=columnas_casos_raros,
        reconciliacion=reconciliacion,
        advertencias_calidad=advertencias_calidad,
        configuracion_auditoria=configuracion_auditoria,
        payload_cache=payload_cache,
        turnos_disponibles=turnos_disponibles,
        turnos_seleccionados=turnos_seleccionados,
    )
