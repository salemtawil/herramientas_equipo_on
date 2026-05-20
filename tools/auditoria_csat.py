import io
import json
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from datetime import datetime, timedelta

import pandas as pd
from flask import Blueprint, Response, render_template, request

from utils.archivos import _leer_csv_desde_bytes
from utils.archivos import leer_bytes_archivo_csv
from utils.estado_temporal import cargar_json_temporal
from utils.estado_temporal import guardar_json_temporal
from utils.estado_temporal import limpiar_estados_temporales_expirados

auditoria_csat_bp = Blueprint("auditoria_csat", __name__)
logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "Nombre del agente",
    "Calificación",
    "Comentario de opinión",
    "Nombre de Contacto",
    "Correo electrónico de contacto",
    "Número de teléfono de contacto",
    "Enlace a la conversación",
    "Fecha registrada",
    "Review Notes",
]

DISPLAY_COLUMNS = {
    "agente": "Nombre del agente",
    "calificacion": "Calificación",
    "comentario": "Comentario de opinión",
    "nombre_contacto": "Nombre de Contacto",
    "correo_contacto": "Correo electrónico de contacto",
    "telefono_contacto": "Número de teléfono de contacto",
    "enlace_conversacion": "Enlace a la conversación",
    "fecha_registrada": "Fecha registrada",
    "review_notes": "Review Notes",
}

IMPORTANT_COLUMNS = [
    "Nombre del agente",
    "Calificación",
    "Comentario de opinión",
    "Enlace a la conversación",
    "Fecha registrada",
]

JUSTIFICABLE_OPTIONS = ["NO", "TAL VEZ", "SÍ"]

COLUMN_ALIASES = {
    "agente": [
        "Nombre del agente",
        "nombre del agente",
        "agente",
        "agent",
        "agent name",
    ],
    "calificacion": [
        "Calificación",
        "calificacion",
        "rating",
        "score",
    ],
    "comentario": [
        "Comentario de opinión",
        "comentario de opinion",
        "comentario",
        "opinion",
        "feedback comment",
    ],
    "nombre_contacto": [
        "Nombre de Contacto",
        "nombre de contacto",
        "contacto",
        "contact name",
    ],
    "correo_contacto": [
        "Correo electrónico de contacto",
        "correo electronico de contacto",
        "correo",
        "email",
        "contact email",
    ],
    "telefono_contacto": [
        "Número de teléfono de contacto",
        "numero de telefono de contacto",
        "telefono",
        "phone",
        "contact phone",
    ],
    "enlace_conversacion": [
        "Enlace a la conversación",
        "enlace a la conversacion",
        "conversation link",
        "link",
    ],
    "fecha_registrada": [
        "Fecha registrada",
        "fecha registrada",
        "fecha",
        "created at",
        "registered at",
    ],
    "review_notes": [
        "Review Notes",
        "review notes",
        "notes",
    ],
}

MOTIVOS_INCONFORMIDAD = [
    "CAPTCHA",
    "CORREO",
    "MENSAJE DE APAGADO",
    "BAJO RENDIMIENTO",
    "SOLICITUD NEGADA",
    "OTRAS CONSULTAS",
    "NO PUEDE VINCULAR",
    "SISTEMA NO VISUAL",
    "CHAT SIN SOLICITUD",
    "HE LLEGADO",
    "COLEGA",
    "NO PUEDE INGRESAR",
    "CAMBIO DE FOTO Y ...",
    "OTRO",
]

TIPOS_RATING = ["Negativo", "Neutral", "Positivo", "Sin calificación válida"]
ESTADOS_AUDITORIA = ["pendiente"] + JUSTIFICABLE_OPTIONS
MAX_CASOS_REPORTE_IA = 8
ANALYSIS_TTL_HOURS = 24
STATE_NAMESPACE = "auditoria_csat"


def normalizar_texto(valor):
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def normalizar_justificable(valor):
    texto = normalizar_texto(valor)
    if texto == "no":
        return "NO"
    if texto == "tal vez":
        return "TAL VEZ"
    if texto in {"si", "sí"}:
        return "SÍ"
    return ""


def leer_csv_subido(archivo):
    contenido = leer_bytes_archivo_csv(archivo)
    return _leer_csv_desde_bytes(contenido)


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


def resolver_columnas_csv(df):
    return {
        clave: resolver_columna_por_alias(df, aliases)
        for clave, aliases in COLUMN_ALIASES.items()
    }


def parsear_calificacion(valor):
    texto = limpiar_texto(valor)
    if not texto:
        return None

    numero = pd.to_numeric(texto.replace(",", "."), errors="coerce")
    if pd.isna(numero):
        return None

    entero = int(numero)
    if entero not in {1, 2, 3, 4, 5}:
        return None
    return entero


def clasificar_tipo_rating(calificacion):
    if calificacion in (1, 2):
        return "Negativo"
    if calificacion == 3:
        return "Neutral"
    if calificacion in (4, 5):
        return "Positivo"
    return "Sin calificación válida"


def parsear_fecha(valor):
    texto = limpiar_texto(valor)
    if not texto:
        return None

    fecha = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    if pd.isna(fecha):
        fecha = pd.to_datetime(texto, errors="coerce", dayfirst=False)
    if pd.isna(fecha):
        return None
    return fecha.to_pydatetime()


def formatear_fecha(fecha):
    if not fecha:
        return ""
    return fecha.strftime("%Y-%m-%d %H:%M")


def formatear_porcentaje(valor):
    return round(float(valor or 0), 2)


def calcular_csat(positivos, total_validos):
    if not total_validos:
        return 0.0
    return formatear_porcentaje((positivos / total_validos) * 100)


def calcular_flag_csat(tipo_rating, justificable):
    if tipo_rating == "Sin calificación válida":
        return "rating_invalido"
    if tipo_rating == "Negativo" and justificable == "SÍ":
        return "excluida_por_justificable_si"
    if tipo_rating == "Negativo" and justificable == "TAL VEZ":
        return "contabiliza_tal_vez"
    return "contabiliza"


def limpiar_analisis_expirados():
    limpiar_estados_temporales_expirados(STATE_NAMESPACE, ttl_hours=ANALYSIS_TTL_HOURS)


def guardar_analisis(estado):
    analysis_id = estado.get("analysis_id")
    estado["analysis_id"] = analysis_id
    estado["updated_at"] = datetime.utcnow().isoformat()
    return guardar_json_temporal(estado, namespace=STATE_NAMESPACE, state_id=analysis_id)


def cargar_analisis(analysis_id):
    return cargar_json_temporal(analysis_id, namespace=STATE_NAMESPACE)


def construir_advertencias_columnas(df, columnas_resueltas):
    faltantes = [
        DISPLAY_COLUMNS[clave]
        for clave in DISPLAY_COLUMNS
        if not columnas_resueltas.get(clave)
    ]
    advertencias = []

    if faltantes:
        advertencias.append(
            "El CSV no trae todas las columnas esperadas. Se completaron vacías estas columnas: "
            + ", ".join(faltantes)
            + "."
        )

    faltantes_importantes = []
    if not columnas_resueltas.get("agente"):
        faltantes_importantes.append("Nombre del agente")
    if not columnas_resueltas.get("calificacion"):
        faltantes_importantes.append("Calificación")
    if not columnas_resueltas.get("comentario"):
        faltantes_importantes.append("Comentario de opinión")
    if not columnas_resueltas.get("enlace_conversacion"):
        faltantes_importantes.append("Enlace a la conversación")
    if not columnas_resueltas.get("fecha_registrada"):
        faltantes_importantes.append("Fecha registrada")

    if faltantes_importantes:
        advertencias.append(
            "Faltan columnas importantes para la auditoría: "
            + ", ".join(faltantes_importantes)
            + ". Algunas métricas o columnas visibles pueden quedar incompletas."
        )

    return advertencias, faltantes


def obtener_valor_resuelto(fila, columnas_resueltas, clave):
    columna = columnas_resueltas.get(clave)
    if not columna:
        return ""
    return fila.get(columna, "")


def construir_filas_desde_dataframe(df, columnas_resueltas):
    filas = []
    registros = df.fillna("").to_dict(orient="records")

    for indice, fila in enumerate(registros):
        calificacion = parsear_calificacion(obtener_valor_resuelto(fila, columnas_resueltas, "calificacion"))
        tipo_rating = clasificar_tipo_rating(calificacion)
        fecha_dt = parsear_fecha(obtener_valor_resuelto(fila, columnas_resueltas, "fecha_registrada"))
        review_notes = limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "review_notes"))

        item = {col: limpiar_texto(fila.get(col, "")) for col in df.columns}
        for col in EXPECTED_COLUMNS:
            item.setdefault(col, "")

        item.update(
            {
                "row_id": str(indice),
                "agente": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "agente")),
                "calificacion": calificacion,
                "calificacion_visible": str(calificacion) if calificacion is not None else limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "calificacion")),
                "tipo_rating": tipo_rating,
                "comentario": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "comentario")),
                "nombre_contacto": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "nombre_contacto")),
                "correo_contacto": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "correo_contacto")),
                "telefono_contacto": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "telefono_contacto")),
                "enlace_conversacion": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "enlace_conversacion")),
                "fecha_registrada": formatear_fecha(fecha_dt),
                "fecha_registrada_raw": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "fecha_registrada")),
                "fecha_iso": fecha_dt.isoformat() if fecha_dt else "",
                "review_notes": review_notes,
                "justificable": "",
                "comentario_auditor": "",
                "motivo_inconformidad": "",
                "estado_auditoria": "pendiente",
                "csat_flag": calcular_flag_csat(tipo_rating, ""),
            }
        )
        filas.append(item)

    return filas


def construir_estado_inicial(df, nombre_archivo):
    columnas_resueltas = resolver_columnas_csv(df)
    advertencias, faltantes = construir_advertencias_columnas(df, columnas_resueltas)
    filas = construir_filas_desde_dataframe(df, columnas_resueltas)

    return {
        "analysis_id": "",
        "source_filename": nombre_archivo,
        "created_at": datetime.utcnow().isoformat(),
        "original_columns": list(df.columns),
        "resolved_columns": columnas_resueltas,
        "missing_columns": faltantes,
        "warnings": advertencias,
        "rows": filas,
    }


def actualizar_estado_desde_formulario(estado, form):
    for fila in estado.get("rows", []):
        row_id = fila["row_id"]
        justificable = normalizar_justificable(form.get(f"justificable__{row_id}"))
        comentario_auditor = limpiar_texto(form.get(f"comentario_auditor__{row_id}"))
        motivo = limpiar_texto(form.get(f"motivo_inconformidad__{row_id}"))

        if motivo and motivo not in MOTIVOS_INCONFORMIDAD:
            motivo = ""

        fila["justificable"] = justificable
        fila["comentario_auditor"] = comentario_auditor
        fila["motivo_inconformidad"] = motivo
        fila["estado_auditoria"] = justificable or "pendiente"
        fila["csat_flag"] = calcular_flag_csat(fila.get("tipo_rating"), justificable)

    return estado


def inferir_periodo(filas):
    fechas = [parsear_fecha(fila.get("fecha_iso") or fila.get("fecha_registrada_raw")) for fila in filas]
    fechas_validas = sorted(fecha for fecha in fechas if fecha)
    if not fechas_validas:
        return "No se pudo inferir"

    inicio = fechas_validas[0]
    fin = fechas_validas[-1]
    if inicio.date() == fin.date():
        return inicio.strftime("%Y-%m-%d")
    return f"{inicio.strftime('%Y-%m-%d')} a {fin.strftime('%Y-%m-%d')}"


def construir_metricas(filas):
    ratings_validos = [fila for fila in filas if fila.get("tipo_rating") != "Sin calificación válida"]
    negativos = [fila for fila in filas if fila.get("tipo_rating") == "Negativo"]
    neutrales = [fila for fila in filas if fila.get("tipo_rating") == "Neutral"]
    positivos = [fila for fila in filas if fila.get("tipo_rating") == "Positivo"]

    negativos_no = [fila for fila in negativos if fila.get("justificable") == "NO"]
    negativos_tal_vez = [fila for fila in negativos if fila.get("justificable") == "TAL VEZ"]
    negativos_si = [fila for fila in negativos if fila.get("justificable") == "SÍ"]
    negativos_pendientes = [fila for fila in negativos if fila.get("estado_auditoria") == "pendiente"]

    total_validos_original = len(ratings_validos)
    total_validos_auditados = total_validos_original - len(negativos_si)
    total_validos_auditados = max(total_validos_auditados, 0)

    csat_original = calcular_csat(len(positivos), total_validos_original)
    csat_actualizado = calcular_csat(len(positivos), total_validos_auditados)

    total_negativos = len(negativos)
    return {
        "periodo": inferir_periodo(filas),
        "total_respuestas": len(filas),
        "total_validos": total_validos_original,
        "ratings_invalidos": len(filas) - total_validos_original,
        "negativos": total_negativos,
        "neutrales": len(neutrales),
        "positivos": len(positivos),
        "csat_original": csat_original,
        "csat_actualizado": csat_actualizado,
        "negativos_no": len(negativos_no),
        "negativos_tal_vez": len(negativos_tal_vez),
        "negativos_si": len(negativos_si),
        "negativos_pendientes": len(negativos_pendientes),
        "porcentaje_no": calcular_csat(len(negativos_no), total_negativos),
        "porcentaje_tal_vez": calcular_csat(len(negativos_tal_vez), total_negativos),
        "porcentaje_si": calcular_csat(len(negativos_si), total_negativos),
        "total_validos_auditados": total_validos_auditados,
    }


def construir_resumen_por_agente(filas):
    if not filas:
        return []

    df = pd.DataFrame(filas)
    resumen = []

    for agente, grupo in df.groupby("agente", dropna=False):
        negativos = grupo[grupo["tipo_rating"] == "Negativo"]
        positivos = grupo[grupo["tipo_rating"] == "Positivo"]
        validos = grupo[grupo["tipo_rating"] != "Sin calificación válida"]
        validos_auditados = len(validos) - int((negativos["justificable"] == "SÍ").sum())

        resumen.append(
            {
                "Agente": agente or "Sin agente",
                "Total de valoraciones": int(len(grupo)),
                "Negativas": int((grupo["tipo_rating"] == "Negativo").sum()),
                "Neutrales": int((grupo["tipo_rating"] == "Neutral").sum()),
                "Positivas": int((grupo["tipo_rating"] == "Positivo").sum()),
                "NO": int((negativos["justificable"] == "NO").sum()),
                "TAL VEZ": int((negativos["justificable"] == "TAL VEZ").sum()),
                "SÍ": int((negativos["justificable"] == "SÍ").sum()),
                "CSAT original": calcular_csat(len(positivos), len(validos)),
                "CSAT auditado": calcular_csat(len(positivos), max(validos_auditados, 0)),
            }
        )

    return sorted(
        resumen,
        key=lambda fila: (-fila["Total de valoraciones"], fila["Agente"]),
    )


def construir_resumen_por_motivo(filas):
    relevantes = [
        fila for fila in filas
        if fila.get("motivo_inconformidad")
    ]
    total = len(relevantes)
    conteo = {}

    for fila in relevantes:
        motivo = fila["motivo_inconformidad"]
        conteo[motivo] = conteo.get(motivo, 0) + 1

    resumen = []
    for motivo, cantidad in sorted(conteo.items(), key=lambda item: (-item[1], item[0])):
        resumen.append(
            {
                "Motivo": motivo,
                "Cantidad": cantidad,
                "Porcentaje": calcular_csat(cantidad, total),
            }
        )

    return resumen


def construir_distribuciones_graficos(filas, resumen_agente, resumen_motivo):
    rating_counts = {str(rating): 0 for rating in range(1, 6)}
    audit_counts = {estado: 0 for estado in JUSTIFICABLE_OPTIONS}

    for fila in filas:
        if fila.get("calificacion") in {1, 2, 3, 4, 5}:
            rating_counts[str(fila["calificacion"])] += 1
        if fila.get("tipo_rating") == "Negativo" and fila.get("justificable") in audit_counts:
            audit_counts[fila["justificable"]] += 1

    return {
        "ratings": [{"label": clave, "value": valor} for clave, valor in rating_counts.items()],
        "auditoria": [{"label": clave, "value": valor} for clave, valor in audit_counts.items()],
        "motivos": [
            {"label": fila["Motivo"], "value": fila["Cantidad"]}
            for fila in resumen_motivo[:8]
        ],
        "agentes": [
            {"label": fila["Agente"], "value": fila["Total de valoraciones"]}
            for fila in resumen_agente[:10]
        ],
    }


def construir_top_hallazgos(filas, metricas, resumen_agente, resumen_motivo):
    hallazgos = []

    if resumen_motivo:
        principal = resumen_motivo[0]
        hallazgos.append(
            f"Motivo principal: {principal['Motivo']} con {principal['Cantidad']} caso(s), {principal['Porcentaje']}% de los registros con motivo."
        )

    if resumen_agente:
        top_agente = max(resumen_agente, key=lambda fila: fila["Negativas"])
        if top_agente["Negativas"]:
            hallazgos.append(
                f"Agente con más negativas: {top_agente['Agente']} con {top_agente['Negativas']} negativa(s)."
            )

    if metricas["negativos_si"]:
        hallazgos.append(
            f"Negativas excluidas del CSAT auditado por SÍ justificable: {metricas['negativos_si']}."
        )

    if metricas["negativos_pendientes"]:
        hallazgos.append(
            f"Negativas pendientes de auditar: {metricas['negativos_pendientes']}."
        )

    if metricas["ratings_invalidos"]:
        hallazgos.append(
            f"Filas con calificación inválida o vacía: {metricas['ratings_invalidos']}."
        )

    return hallazgos


def construir_casos_destacados(filas):
    prioridades = {"NO": 0, "TAL VEZ": 1, "SÍ": 2, "pendiente": 3}
    candidatos = [
        fila for fila in filas
        if fila.get("tipo_rating") == "Negativo"
        and (
            fila.get("comentario_auditor")
            or fila.get("comentario")
            or fila.get("motivo_inconformidad")
        )
    ]
    candidatos.sort(key=lambda fila: (prioridades.get(fila.get("estado_auditoria"), 99), fila.get("agente", "")))
    return candidatos[:MAX_CASOS_REPORTE_IA]


def construir_contexto_analisis(estado):
    filas = estado.get("rows", [])
    metricas = construir_metricas(filas)
    resumen_agente = construir_resumen_por_agente(filas)
    resumen_motivo = construir_resumen_por_motivo(filas)
    graficos = construir_distribuciones_graficos(filas, resumen_agente, resumen_motivo)
    hallazgos = construir_top_hallazgos(filas, metricas, resumen_agente, resumen_motivo)
    casos_destacados = construir_casos_destacados(filas)

    agentes = sorted({fila.get("agente", "") for fila in filas if fila.get("agente")})

    return {
        "analysis_id": estado.get("analysis_id", ""),
        "source_filename": estado.get("source_filename", ""),
        "warnings": estado.get("warnings", []),
        "metricas": metricas,
        "filas": filas,
        "resumen_agente": resumen_agente,
        "resumen_motivo": resumen_motivo,
        "graficos": graficos,
        "hallazgos": hallazgos,
        "casos_destacados": casos_destacados,
        "filtros": {
            "agentes": agentes,
            "calificaciones": ["1", "2", "3", "4", "5", "Sin calificación válida"],
            "tipos_rating": TIPOS_RATING,
            "estados": ESTADOS_AUDITORIA,
            "motivos": MOTIVOS_INCONFORMIDAD,
        },
        "motivos_catalogo": MOTIVOS_INCONFORMIDAD,
        "justificable_options": JUSTIFICABLE_OPTIONS,
    }


def construir_dataframe_exportable(filas, columnas_originales):
    columnas_exportacion = []
    columnas_norm = set()

    for columna in columnas_originales + EXPECTED_COLUMNS:
        columna_norm = normalizar_texto(columna)
        if columna_norm in columnas_norm:
            continue
        columnas_norm.add(columna_norm)
        columnas_exportacion.append(columna)

    registros = []
    for fila in filas:
        item = {col: fila.get(col, "") for col in columnas_exportacion}
        item.update(
            {
                "tipo_rating": fila.get("tipo_rating", ""),
                "justificable": fila.get("justificable", ""),
                "comentario_auditor": fila.get("comentario_auditor", ""),
                "motivo_inconformidad": fila.get("motivo_inconformidad", ""),
                "csat_flag": fila.get("csat_flag", ""),
                "estado_auditoria": fila.get("estado_auditoria", ""),
            }
        )
        registros.append(item)

    return pd.DataFrame(registros)


def respuesta_csv(df, nombre_archivo):
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, encoding="utf-8-sig")
    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


def construir_reporte_ia_markdown(estado):
    contexto = construir_contexto_analisis(estado)
    metricas = contexto["metricas"]
    lineas = [
        "# Reporte de auditoría CSAT",
        "",
        "## Resumen ejecutivo base",
        f"- Archivo fuente: {contexto['source_filename'] or 'sin nombre'}",
        f"- Período: {metricas['periodo']}",
        f"- Total de respuestas: {metricas['total_respuestas']}",
        f"- Ratings válidos: {metricas['total_validos']}",
        f"- Ratings inválidos o vacíos: {metricas['ratings_invalidos']}",
        f"- CSAT original: {metricas['csat_original']}%",
        f"- CSAT actualizado: {metricas['csat_actualizado']}%",
        f"- Negativos: {metricas['negativos']}",
        f"- Neutrales: {metricas['neutrales']}",
        f"- Positivos: {metricas['positivos']}",
        "",
        "## Resultado de auditoría",
        f"- NO: {metricas['negativos_no']} ({metricas['porcentaje_no']}% de negativas)",
        f"- TAL VEZ: {metricas['negativos_tal_vez']} ({metricas['porcentaje_tal_vez']}% de negativas)",
        f"- SÍ: {metricas['negativos_si']} ({metricas['porcentaje_si']}% de negativas)",
        f"- Pendientes: {metricas['negativos_pendientes']}",
        "",
        "## Regla usada para el CSAT actualizado",
        "- Las calificaciones 4 y 5 cuentan como positivas.",
        "- Las calificaciones 1 y 2 cuentan como negativas.",
        "- Las calificaciones 3 quedan como neutrales dentro del denominador.",
        "- Una negativa marcada como SÍ justificable se excluye del denominador del CSAT auditado.",
        "- Una negativa marcada como NO sigue contando como negativa válida.",
        "- Una negativa marcada como TAL VEZ no altera el cálculo y sigue contando hasta nueva definición.",
        "- Las filas sin calificación válida se excluyen del cálculo.",
        "",
        "## Hallazgos principales",
    ]

    if contexto["hallazgos"]:
        lineas.extend([f"- {hallazgo}" for hallazgo in contexto["hallazgos"]])
    else:
        lineas.append("- No se detectaron hallazgos automáticos relevantes.")

    lineas.extend(["", "## Resumen por agente"])
    if contexto["resumen_agente"]:
        lineas.append("| Agente | Total | Negativas | Neutrales | Positivas | NO | TAL VEZ | SÍ | CSAT original | CSAT auditado |")
        lineas.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for fila in contexto["resumen_agente"]:
            lineas.append(
                f"| {fila['Agente']} | {fila['Total de valoraciones']} | {fila['Negativas']} | {fila['Neutrales']} | {fila['Positivas']} | {fila['NO']} | {fila['TAL VEZ']} | {fila['SÍ']} | {fila['CSAT original']}% | {fila['CSAT auditado']}% |"
            )
    else:
        lineas.append("- Sin datos por agente.")

    lineas.extend(["", "## Resumen por motivo"])
    if contexto["resumen_motivo"]:
        lineas.append("| Motivo | Cantidad | Porcentaje |")
        lineas.append("| --- | ---: | ---: |")
        for fila in contexto["resumen_motivo"]:
            lineas.append(f"| {fila['Motivo']} | {fila['Cantidad']} | {fila['Porcentaje']}% |")
    else:
        lineas.append("- No hay motivos capturados.")

    lineas.extend(["", "## Casos destacados"])
    if contexto["casos_destacados"]:
        for fila in contexto["casos_destacados"]:
            lineas.extend(
                [
                    f"### {fila.get('agente') or 'Sin agente'} | {fila.get('estado_auditoria')} | Rating {fila.get('calificacion_visible') or 'sin dato'}",
                    f"- Fecha: {fila.get('fecha_registrada') or fila.get('fecha_registrada_raw') or 'sin fecha'}",
                    f"- Contacto: {fila.get('nombre_contacto') or 'sin nombre'} | {fila.get('correo_contacto') or 'sin correo'} | {fila.get('telefono_contacto') or 'sin teléfono'}",
                    f"- Motivo: {fila.get('motivo_inconformidad') or 'sin motivo'}",
                    f"- Comentario cliente: {fila.get('comentario') or 'sin comentario'}",
                    f"- Comentario auditor: {fila.get('comentario_auditor') or 'sin comentario'}",
                    f"- Link: {fila.get('enlace_conversacion') or 'sin enlace'}",
                    "",
                ]
            )
    else:
        lineas.append("- No hay casos destacados con comentarios suficientes.")

    lineas.extend(
        [
            "## Prompt sugerido para IA",
            "Usa este reporte para generar:",
            "- Resumen ejecutivo",
            "- Hallazgos principales",
            "- Análisis por agente",
            "- Patrones de inconformidad",
            "- Recomendaciones accionables",
        ]
    )

    return "\n".join(lineas)


@auditoria_csat_bp.route("/auditoria-csat", methods=["GET", "POST"])
def auditoria_csat():
    limpiar_analisis_expirados()

    mensaje = ""
    advertencia = ""
    contexto_analisis = None

    try:
        if request.method == "POST":
            accion = limpiar_texto(request.form.get("accion")) or "analizar_csv"

            if accion == "analizar_csv":
                archivo = request.files.get("archivo")
                if not archivo or not archivo.filename:
                    advertencia = "Selecciona un archivo CSV para iniciar la auditoría."
                else:
                    df = leer_csv_subido(archivo)
                    estado = construir_estado_inicial(df, archivo.filename)
                    guardar_analisis(estado)
                    contexto_analisis = construir_contexto_analisis(estado)
                    mensaje = "CSV cargado y auditoría preparada."
            else:
                analysis_id = limpiar_texto(request.form.get("analysis_id"))
                estado = cargar_analisis(analysis_id)
                if not estado:
                    advertencia = "No se encontró el análisis activo. Vuelve a cargar el CSV."
                else:
                    estado = actualizar_estado_desde_formulario(estado, request.form)
                    guardar_analisis(estado)

                    if accion == "guardar_auditoria":
                        mensaje = "Auditoría actualizada."
                        contexto_analisis = construir_contexto_analisis(estado)
                    elif accion == "descargar_csv_auditado":
                        df_export = construir_dataframe_exportable(
                            estado["rows"],
                            estado.get("original_columns", []),
                        )
                        return respuesta_csv(df_export, "auditoria_csat_auditada.csv")
                    elif accion == "descargar_reporte_ia":
                        reporte = construir_reporte_ia_markdown(estado)
                        return Response(
                            reporte,
                            mimetype="text/markdown; charset=utf-8",
                            headers={
                                "Content-Disposition": "attachment; filename=auditoria_csat_reporte_ia.md"
                            },
                        )
                    else:
                        advertencia = "Acción no válida."
                        contexto_analisis = construir_contexto_analisis(estado)
        else:
            analysis_id = limpiar_texto(request.args.get("analysis_id"))
            if analysis_id:
                estado = cargar_analisis(analysis_id)
                if estado:
                    contexto_analisis = construir_contexto_analisis(estado)
                else:
                    advertencia = "El análisis solicitado ya no está disponible. Carga el CSV de nuevo."
    except Exception as exc:
        logger.exception("Error procesando auditoria_csat")
        advertencia = f"No se pudo procesar la auditoría CSAT: {exc}"

    return render_template(
        "auditoria_csat.html",
        mensaje=mensaje,
        advertencia=advertencia,
        contexto=contexto_analisis,
    )
