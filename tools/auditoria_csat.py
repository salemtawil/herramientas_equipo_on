import io
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime

import pandas as pd
import requests
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
    "transcripcion_conversacion": "Transcripcion de conversacion",
}

IMPORTANT_COLUMNS = [
    "Nombre del agente",
    "Calificación",
    "Comentario de opinión",
    "Enlace a la conversación",
    "Fecha registrada",
]

JUSTIFICABLE_OPTIONS = ["NO", "TAL VEZ", "SÍ"]
OPTIONAL_COLUMNS = {"transcripcion_conversacion"}

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
    "transcripcion_conversacion": [
        "Transcripcion de conversacion",
        "transcripcion",
        "transcript",
        "conversation transcript",
        "conversacion",
        "conversation",
        "mensajes",
        "messages",
        "chat",
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
RATING_CATEGORIAS = {
    5: {"label": "Excelente", "tipo": "Positivo"},
    4: {"label": "Bueno", "tipo": "Positivo"},
    3: {"label": "Promedio", "tipo": "Neutral"},
    2: {"label": "Justo", "tipo": "Negativo"},
    1: {"label": "Pobre", "tipo": "Negativo"},
}
MAX_CASOS_REPORTE_IA = 8
ANALYSIS_TTL_HOURS = 24
STATE_NAMESPACE = "auditoria_csat"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_CSAT_MODEL_DEFAULT = "gpt-4.1-mini"
OPENAI_CSAT_MAX_CASES_DEFAULT = 15
OPENAI_CSAT_MAX_TRANSCRIPT_CHARS = 6000
OPENAI_REQUEST_TIMEOUT = 45


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


def formatear_delta(valor, sufijo=""):
    valor = formatear_porcentaje(valor)
    if valor > 0:
        return f"+{valor}{sufijo}"
    return f"{valor}{sufijo}"


def formatear_delta_entero(valor):
    if valor > 0:
        return f"+{valor}"
    return str(valor)


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
    analysis_id = limpiar_texto(estado.get("analysis_id")) or str(uuid.uuid4())
    estado["updated_at"] = datetime.utcnow().isoformat()
    estado["analysis_id"] = analysis_id
    guardar_json_temporal(
        estado,
        namespace=STATE_NAMESPACE,
        state_id=analysis_id,
    )
    return analysis_id


def cargar_analisis(analysis_id):
    return cargar_json_temporal(analysis_id, namespace=STATE_NAMESPACE)


def construir_advertencias_columnas(df, columnas_resueltas):
    faltantes = [
        DISPLAY_COLUMNS[clave]
        for clave in DISPLAY_COLUMNS
        if clave not in OPTIONAL_COLUMNS
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
                "transcripcion_conversacion": limpiar_texto(obtener_valor_resuelto(fila, columnas_resueltas, "transcripcion_conversacion")),
                "justificable": "",
                "comentario_auditor": "",
                "motivo_inconformidad": "",
                "estado_auditoria": "pendiente",
                "csat_flag": calcular_flag_csat(tipo_rating, ""),
                "ia_estado": "",
                "ia_confianza": "",
                "ia_explicacion": "",
                "ia_evidencia": "",
                "ia_modelo": "",
                "ia_fecha": "",
                "ia_fuente": "",
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


def obtener_openai_config():
    try:
        max_cases = int(os.getenv("OPENAI_CSAT_MAX_CASES", OPENAI_CSAT_MAX_CASES_DEFAULT))
    except (TypeError, ValueError):
        max_cases = OPENAI_CSAT_MAX_CASES_DEFAULT

    return {
        "api_key": limpiar_texto(os.getenv("OPENAI_API_KEY")),
        "model": limpiar_texto(os.getenv("OPENAI_CSAT_MODEL")) or OPENAI_CSAT_MODEL_DEFAULT,
        "max_cases": max(1, max_cases),
    }


def limitar_texto(valor, max_chars):
    texto = limpiar_texto(valor)
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + "\n[Texto truncado por límite operativo]"


def construir_payload_auditoria_ia(fila):
    transcript = limitar_texto(
        fila.get("transcripcion_conversacion"),
        OPENAI_CSAT_MAX_TRANSCRIPT_CHARS,
    )
    fuente = "transcripcion_csv" if transcript else "comentario_csv_sin_transcript"

    contenido = {
        "rating": fila.get("calificacion_visible"),
        "tipo_rating": fila.get("tipo_rating"),
        "agente": fila.get("agente"),
        "fecha": fila.get("fecha_registrada") or fila.get("fecha_registrada_raw"),
        "comentario_csat": fila.get("comentario"),
        "review_notes": fila.get("review_notes"),
        "transcripcion_conversacion": transcript,
        "enlace_conversacion": fila.get("enlace_conversacion"),
        "fuente_disponible": fuente,
        "motivos_permitidos": MOTIVOS_INCONFORMIDAD,
    }

    instrucciones = (
        "Audita una valoración CSAT negativa de soporte. "
        "Decide si debe excluirse del CSAT del agente. "
        "Usa SI cuando el negativo parece injusto, no atribuible al agente, causado por sistema/política/cliente sin solicitud clara, o sin evidencia suficiente contra el agente. "
        "Usa NO cuando la conversación muestra falla atribuible al agente o mala gestión que justifica contar el negativo. "
        "Usa TAL VEZ cuando la evidencia es ambigua y requiere revisión humana. "
        "Elige un motivo exacto de la lista permitida. "
        "Si no hay transcripción completa, dilo en la explicación y baja la confianza."
    )

    return instrucciones + "\n\nCaso:\n" + json.dumps(contenido, ensure_ascii=False, indent=2)


def esquema_auditoria_ia():
    return {
        "type": "object",
        "properties": {
            "justificable": {
                "type": "string",
                "enum": ["NO", "TAL VEZ", "SI"],
            },
            "motivo_inconformidad": {
                "type": "string",
                "enum": MOTIVOS_INCONFORMIDAD,
            },
            "confianza": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "explicacion": {
                "type": "string",
            },
            "evidencia": {
                "type": "string",
            },
        },
        "required": [
            "justificable",
            "motivo_inconformidad",
            "confianza",
            "explicacion",
            "evidencia",
        ],
        "additionalProperties": False,
    }


def extraer_texto_respuesta_openai(data):
    if data.get("output_text"):
        return data["output_text"]

    textos = []
    for item in data.get("output", []):
        for contenido in item.get("content", []):
            texto = contenido.get("text")
            if texto:
                textos.append(texto)
    return "\n".join(textos).strip()


def auditar_fila_con_ia(fila, config):
    payload = {
        "model": config["model"],
        "input": [
            {
                "role": "system",
                "content": "Eres auditor de calidad CSAT. Responde solo con JSON válido según el esquema.",
            },
            {
                "role": "user",
                "content": construir_payload_auditoria_ia(fila),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "auditoria_csat",
                "strict": True,
                "schema": esquema_auditoria_ia(),
            }
        },
        "max_output_tokens": 600,
    }

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=OPENAI_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    texto = extraer_texto_respuesta_openai(response.json())
    return json.loads(texto)


def aplicar_resultado_ia(fila, resultado, modelo):
    justificable = normalizar_justificable(resultado.get("justificable"))
    if not justificable:
        justificable = "TAL VEZ"

    motivo = limpiar_texto(resultado.get("motivo_inconformidad"))
    if motivo not in MOTIVOS_INCONFORMIDAD:
        motivo = "OTRO"

    confianza = resultado.get("confianza")
    try:
        confianza = max(0, min(1, float(confianza)))
    except (TypeError, ValueError):
        confianza = 0

    explicacion = limitar_texto(resultado.get("explicacion"), 900)
    evidencia = limitar_texto(resultado.get("evidencia"), 700)

    fila["justificable"] = justificable
    fila["comentario_auditor"] = f"IA: {explicacion}" if explicacion else "IA: sin explicación"
    fila["motivo_inconformidad"] = motivo
    fila["estado_auditoria"] = justificable
    fila["csat_flag"] = calcular_flag_csat(fila.get("tipo_rating"), justificable)
    fila["ia_estado"] = "sugerida"
    fila["ia_confianza"] = formatear_porcentaje(confianza * 100)
    fila["ia_explicacion"] = explicacion
    fila["ia_evidencia"] = evidencia
    fila["ia_modelo"] = modelo
    fila["ia_fecha"] = datetime.utcnow().isoformat()
    fila["ia_fuente"] = "transcripcion_csv" if fila.get("transcripcion_conversacion") else "comentario_csv_sin_transcript"


def auditar_estado_con_ia(estado):
    config = obtener_openai_config()
    if not config["api_key"]:
        return 0, ["Configura OPENAI_API_KEY para usar la auditoría con IA."]

    candidatos = [
        fila for fila in estado.get("rows", [])
        if fila.get("tipo_rating") == "Negativo"
        and not fila.get("justificable")
    ][:config["max_cases"]]

    if not candidatos:
        return 0, ["No hay negativas pendientes para auditar con IA."]

    advertencias = []
    auditadas = 0
    for fila in candidatos:
        try:
            resultado = auditar_fila_con_ia(fila, config)
            aplicar_resultado_ia(fila, resultado, config["model"])
            auditadas += 1
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {401, 403}:
                advertencias.append(
                    "OpenAI rechazó la credencial. Revisa que OPENAI_API_KEY sea una secret key válida, "
                    "que no tenga espacios/comillas extra, y reinicia Flask después de configurarla."
                )
                break
            logger.exception("Error auditando fila CSAT con IA")
            advertencias.append(
                f"No se pudo auditar con IA la fila {fila.get('row_id')}: {exc}"
            )
        except Exception as exc:
            logger.exception("Error auditando fila CSAT con IA")
            advertencias.append(
                f"No se pudo auditar con IA la fila {fila.get('row_id')}: {exc}"
            )

    return auditadas, advertencias


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


def construir_distribucion_calificaciones(filas, auditada=False):
    conteo = {rating: 0 for rating in RATING_CATEGORIAS}

    for fila in filas:
        calificacion = fila.get("calificacion")
        if calificacion not in conteo:
            continue
        if (
            auditada
            and fila.get("tipo_rating") == "Negativo"
            and fila.get("justificable") == JUSTIFICABLE_OPTIONS[-1]
        ):
            continue
        conteo[calificacion] += 1

    total = sum(conteo.values())
    return {
        "total": total,
        "barras": [
            {
                "rating": rating,
                "label": data["label"],
                "tipo": data["tipo"],
                "value": conteo[rating],
                "percent": calcular_csat(conteo[rating], total),
            }
            for rating, data in RATING_CATEGORIAS.items()
        ],
    }


def construir_distribuciones_graficos(filas, resumen_agente, resumen_motivo):
    rating_counts = {str(rating): 0 for rating in range(1, 6)}
    audit_counts = {estado: 0 for estado in JUSTIFICABLE_OPTIONS}

    for fila in filas:
        if fila.get("calificacion") in {1, 2, 3, 4, 5}:
            rating_counts[str(fila["calificacion"])] += 1
        if fila.get("tipo_rating") == "Negativo" and fila.get("justificable") in audit_counts:
            audit_counts[fila["justificable"]] += 1

    ratings_original = construir_distribucion_calificaciones(filas)
    ratings_auditada = construir_distribucion_calificaciones(filas, auditada=True)
    originales_por_rating = {
        item["rating"]: item for item in ratings_original["barras"]
    }
    for item in ratings_auditada["barras"]:
        original = originales_por_rating.get(item["rating"], {})
        delta_value = item["value"] - original.get("value", 0)
        delta_percent = item["percent"] - original.get("percent", 0)
        item["delta_value"] = delta_value
        item["delta_percent"] = formatear_porcentaje(delta_percent)
        item["delta_value_label"] = formatear_delta_entero(delta_value)
        item["delta_percent_label"] = formatear_delta(delta_percent, "%")
        item["delta_class"] = "is-up" if delta_percent > 0 else "is-down" if delta_percent < 0 else "is-flat"

    return {
        "ratings": [{"label": clave, "value": valor} for clave, valor in rating_counts.items()],
        "ratings_original": ratings_original,
        "ratings_auditada": ratings_auditada,
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
        "ia_disponible": bool(obtener_openai_config()["api_key"]),
        "ia_modelo": obtener_openai_config()["model"],
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
                "ia_estado": fila.get("ia_estado", ""),
                "ia_confianza": fila.get("ia_confianza", ""),
                "ia_explicacion": fila.get("ia_explicacion", ""),
                "ia_evidencia": fila.get("ia_evidencia", ""),
                "ia_modelo": fila.get("ia_modelo", ""),
                "ia_fecha": fila.get("ia_fecha", ""),
                "ia_fuente": fila.get("ia_fuente", ""),
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
                    advertencia = (
                        "El análisis activo ya no está disponible. "
                        "Puede ocurrir si Flask se reinició o si el estado temporal fue limpiado. "
                        "Vuelve a cargar el CSV y ejecuta la auditoría con IA desde esa misma pantalla."
                    )
                else:
                    estado = actualizar_estado_desde_formulario(estado, request.form)
                    guardar_analisis(estado)

                    if accion == "guardar_auditoria":
                        mensaje = "Auditoría actualizada."
                        contexto_analisis = construir_contexto_analisis(estado)
                    elif accion == "auditar_con_ia":
                        auditadas, advertencias_ia = auditar_estado_con_ia(estado)
                        guardar_analisis(estado)
                        if auditadas:
                            mensaje = f"IA auditó {auditadas} negativa(s) pendiente(s). Revisa y confirma o corrige la tabla."
                        if advertencias_ia:
                            advertencia = " ".join(advertencias_ia)
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
