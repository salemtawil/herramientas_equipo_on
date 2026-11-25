import io
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from datetime import date, datetime

import pandas as pd
from flask import Blueprint, Response, current_app, has_app_context, jsonify, render_template, request, url_for

from utils import auditoria_csat_store
from utils.auditoria_chats_transcripcion import construir_transcripcion
from utils.auditoria_csat_chatwoot import (
    cargar_transcripciones,
    filas_desde_encuestas,
    fusionar_guardado,
    negativos_para_guardar,
    resumen_para_guardar,
)
from utils.auditoria_csat_informe import bloque_desde_estado
from utils.auditoria_csat_store import AuditoriaCsatConfigError
from utils.auditoria_csat_vista import TEXTO_DECISION, construir_vista
from utils.chatwoot_reportes import ChatwootClient, _obtener_timezone, _timezone, construir_rango_chatwoot_fechas
from utils.csat_periodos import TIPOS_PERIODO, formatear_periodo, resolver_periodo
from utils.archivos import _leer_csv_desde_bytes
from utils.archivos import leer_bytes_archivo_csv
from utils.errores import mensaje_error_publico
from utils.estado_temporal import cargar_estado_temporal
from utils.estado_temporal import cargar_json_temporal
from utils.estado_temporal import guardar_estado_temporal
from utils.estado_temporal import guardar_json_temporal
from utils.estado_temporal import limpiar_estados_temporales_expirados
from utils.ia_chat import IAConfigError, IARateLimitError, IARespuestaError, IATemporalError, completar_json
from utils.ia_chat import obtener_config_ia as obtener_config_ia_compartida

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
# Negativos por paso. Igual que la Auditoría de chats: una conversación por petición, para que
# Gemini responda dentro del tiempo y el respaldo alcance a intentarse.
CSAT_IA_MAX_CASOS_DEFAULT = 1
CSAT_IA_MAX_TRANSCRIPT_CHARS = 6000
# Tiempo total de IA por clic (principal + respaldo). Vercel corta a los 60 s y antes se
# traen conversaciones de Chatwoot y se guarda en Supabase, así que se deja margen.
CSAT_IA_PRESUPUESTO_SEGUNDOS = 48
CSAT_IA_RESPALDO_MINIMO_SEGUNDOS = 10


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

    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        pass

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


ESTADO_SALT = "auditoria-csat-estado"


def guardar_analisis(estado):
    """Guarda el estado de la auditoría y devuelve su identificador (`analysis_id`).

    Dentro de Flask el estado viaja firmado y comprimido en la propia página: en Vercel cada
    petición puede caer en un servidor distinto, y un archivo temporal solo existe en uno de
    ellos. Si el estado es demasiado grande, `guardar_estado_temporal` usa un archivo.
    """
    estado["updated_at"] = datetime.utcnow().isoformat()
    if not has_app_context():
        analysis_id = limpiar_texto(estado.get("analysis_id")) or str(uuid.uuid4())
        estado["analysis_id"] = analysis_id
        guardar_json_temporal(estado, namespace=STATE_NAMESPACE, state_id=analysis_id)
        return analysis_id

    estado["analysis_id"] = ""
    token = guardar_estado_temporal(
        estado,
        secret_key=current_app.secret_key,
        salt=ESTADO_SALT,
        namespace=STATE_NAMESPACE,
        ttl_hours=ANALYSIS_TTL_HOURS,
    )
    estado["analysis_id"] = token
    return token


def cargar_analisis(analysis_id):
    texto = limpiar_texto(analysis_id)
    if not texto:
        return None
    if has_app_context():
        estado = cargar_estado_temporal(
            texto, secret_key=current_app.secret_key, salt=ESTADO_SALT, namespace=STATE_NAMESPACE
        )
        if estado is not None:
            estado["analysis_id"] = texto
            return estado
    return cargar_json_temporal(texto, namespace=STATE_NAMESPACE)


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
                "ia_justificable": "",
                "ia_motivo": "",
                "origen_decision": "",
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


def obtener_ia_config():
    """Misma IA que la Auditoría de chats (AUDITORIA_CHATS_AI_*), más el tope de casos por clic."""
    try:
        max_cases = int(os.getenv("CSAT_AI_MAX_CASES", CSAT_IA_MAX_CASOS_DEFAULT))
    except (TypeError, ValueError):
        max_cases = CSAT_IA_MAX_CASOS_DEFAULT
    return dict(obtener_config_ia_compartida(), max_cases=max(1, max_cases))


def limitar_texto(valor, max_chars):
    texto = limpiar_texto(valor)
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + "\n[Texto truncado por límite operativo]"


def construir_caso_auditoria_ia(fila):
    transcript = limitar_texto(
        fila.get("transcripcion_conversacion"),
        CSAT_IA_MAX_TRANSCRIPT_CHARS,
    )
    fuente = "transcripcion_csv" if transcript else "comentario_csv_sin_transcript"

    return {
        "row_id": fila.get("row_id"),
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


def construir_instrucciones_auditoria_ia():
    return (
        "Audita valoraciones CSAT negativas de soporte. "
        "Decide si cada negativo debe excluirse del CSAT del agente. "
        "Usa SI cuando el negativo parece injusto, no atribuible al agente, causado por sistema/política/cliente sin solicitud clara, o sin evidencia suficiente contra el agente. "
        "Usa NO cuando la conversación muestra falla atribuible al agente o mala gestión que justifica contar el negativo. "
        "Usa TAL VEZ cuando la evidencia es ambigua y requiere revisión humana. "
        "Elige un motivo exacto de la lista permitida. "
        "Si no hay transcripción completa, dilo en la explicación y baja la confianza. "
        "Devuelve un resultado por cada row_id recibido."
    )


def construir_payload_lote_auditoria_ia(filas):
    contenido = {
        "motivos_permitidos": MOTIVOS_INCONFORMIDAD,
        "casos": [construir_caso_auditoria_ia(fila) for fila in filas],
    }
    return construir_instrucciones_auditoria_ia() + "\n\nCasos:\n" + json.dumps(contenido, ensure_ascii=False, indent=2)


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


def esquema_lote_auditoria_ia():
    item_schema = esquema_auditoria_ia()
    item_schema["properties"] = {
        "row_id": {"type": "string"},
        **item_schema["properties"],
    }
    item_schema["required"] = ["row_id"] + item_schema["required"]

    return {
        "type": "object",
        "properties": {
            "resultados": {
                "type": "array",
                "items": item_schema,
            },
        },
        "required": ["resultados"],
        "additionalProperties": False,
    }


def mensajes_auditoria_ia(filas):
    esquema = json.dumps(esquema_lote_auditoria_ia(), ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "Eres auditor de calidad CSAT. Responde solo con un objeto JSON válido "
                f"que cumpla este esquema: {esquema}"
            ),
        },
        {"role": "user", "content": construir_payload_lote_auditoria_ia(filas)},
    ]


def motivo_fallo_ia(exc):
    """Motivo corto y legible de un fallo del proveedor de IA."""
    texto = str(exc).lower()
    if getattr(exc, "diario", False):
        return "cupo diario agotado"
    if "no respondió a tiempo" in texto or "timeout" in texto:
        return "tardó demasiado en responder"
    if "saturado" in texto or "(5" in texto:
        return "saturado (error 5xx)"
    if "por minuto" in texto:
        return "límite por minuto"
    return "no disponible"


def auditar_lote_con_proveedor(filas, config):
    """Audita el lote con la IA compartida; si el modelo principal está saturado o sin cupo, usa el de respaldo."""
    mensajes = mensajes_auditoria_ia(filas)
    modelos = [config["model"]]
    if config.get("model_respaldo") and config["model_respaldo"] != config["model"]:
        modelos.append(config["model_respaldo"])
    # Con respaldo, el principal usa la mitad del presupuesto; el respaldo recibe lo que sobra (mínimo fijo).
    timeout = CSAT_IA_PRESUPUESTO_SEGUNDOS // len(modelos)
    inicio = time.monotonic()
    errores = []
    data = None
    for modelo in modelos:
        if errores:
            transcurrido = time.monotonic() - inicio
            timeout = max(CSAT_IA_RESPALDO_MINIMO_SEGUNDOS, int(CSAT_IA_PRESUPUESTO_SEGUNDOS - transcurrido))
        try:
            data = completar_json(mensajes, dict(config, model=modelo), timeout=timeout)
            break
        except IARateLimitError as exc:
            errores.append((modelo, exc))
    if data is None:
        detalle = " · ".join(f"{nombre}: {motivo_fallo_ia(exc)}" for nombre, exc in errores)
        temporales = [exc for _, exc in errores if not exc.diario]
        if temporales:
            error = IATemporalError(detalle, esperar_segundos=temporales[0].esperar_segundos)
        elif len(errores) == 1:
            error = errores[0][1]
        else:
            error = IARateLimitError(f"Todos los modelos agotaron su cupo diario ({detalle}).", diario=True)
        error.modelos_probados = [nombre for nombre, _ in errores]
        raise error

    resultados = data.get("resultados")
    if not isinstance(resultados, list):
        raise IARespuestaError("La IA no devolvió la lista de resultados.")
    return [dict(resultado, _modelo=modelo) for resultado in resultados if isinstance(resultado, dict)]


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

    fila["ia_justificable"] = justificable
    fila["ia_motivo"] = motivo
    fila["ia_estado"] = "sugerida"
    fila["ia_confianza"] = formatear_porcentaje(confianza * 100)
    fila["ia_explicacion"] = explicacion
    fila["ia_evidencia"] = evidencia
    fila["ia_modelo"] = modelo
    fila["ia_fecha"] = datetime.utcnow().isoformat()
    if fila.get("survey_id") and fila.get("transcripcion_conversacion"):
        fila["ia_fuente"] = "transcripcion_chatwoot"
    else:
        fila["ia_fuente"] = "transcripcion_csv" if fila.get("transcripcion_conversacion") else "comentario_csv_sin_transcript"


def ia_disponible(config):
    return bool(config.get("activa"))


def candidatos_para_ia(filas, max_cases):
    return [
        fila for fila in filas
        if fila.get("tipo_rating") == "Negativo"
        and not fila.get("ia_justificable")
        and not fila.get("justificable")
        and fila.get("origen_decision") != "humana"
    ][:max_cases]


def contar_pendientes_ia(filas):
    """Negativos que la IA todavía no revisó y que nadie decidió a mano."""
    return len(candidatos_para_ia(filas, len(filas) + 1))


def auditar_estado_con_ia(estado, info=None):
    """Audita una tanda de negativos pendientes. Devuelve (auditadas, advertencias).

    Si se pasa `info` (dict), se rellena con `esperar_segundos` (> 0 cuando conviene reintentar:
    proveedor saturado o límite por minuto) y `detener` (configuración o cupo diario agotado).
    """
    info = info if info is not None else {}
    info.update(esperar_segundos=0, detener=False)
    config = obtener_ia_config()
    if not ia_disponible(config):
        info["detener"] = True
        return 0, [
            "Configura AUDITORIA_CHATS_AI_API_KEY (la misma IA de la Auditoría de chats) "
            "para usar la auditoría con IA."
        ]

    candidatos = candidatos_para_ia(estado.get("rows", []), config["max_cases"])

    if not candidatos:
        return 0, ["No hay negativas pendientes para auditar con IA."]

    advertencias = []
    auditadas = 0
    filas_por_id = {str(fila.get("row_id")): fila for fila in candidatos}

    try:
        resultados = auditar_lote_con_proveedor(candidatos, config)
        for resultado in resultados:
            fila = filas_por_id.get(str(resultado.get("row_id")))
            if not fila:
                continue
            aplicar_resultado_ia(fila, resultado, resultado.get("_modelo") or config["model"])
            auditadas += 1
    except IAConfigError as exc:
        info["detener"] = True
        advertencias.append(str(exc))
    except IATemporalError as exc:
        info["esperar_segundos"] = exc.esperar_segundos
        aviso = f"La IA no respondió ({exc}). No es por falta de cupo."
        if len(getattr(exc, "modelos_probados", [config["model"]])) < 2:
            aviso += (
                " No hay modelo de respaldo: configura AUDITORIA_CHATS_AI_MODEL_RESPALDO en Vercel "
                "para que entre otro modelo cuando este se sature."
            )
        advertencias.append(aviso)
    except IARateLimitError as exc:
        if exc.diario:
            info["detener"] = True
            advertencias.append(f"{exc} El cupo es compartido con la Auditoría de chats.")
        else:
            info["esperar_segundos"] = exc.esperar_segundos
            advertencias.append(str(exc))
    except IARespuestaError:
        logger.exception("Respuesta inválida de la IA en auditoría CSAT")
        advertencias.append("La IA respondió con un formato inesperado. Intenta de nuevo.")
    except Exception as exc:
        logger.exception("Error auditando lote CSAT con IA")
        advertencias.append(mensaje_error_publico(exc, "No se pudo auditar el lote con IA"))

    return auditadas, advertencias


def actualizar_estado_desde_formulario(estado, form):
    for fila in estado.get("rows", []):
        row_id = fila["row_id"]
        if f"justificable__{row_id}" not in form:
            continue  # la fila no vino en el formulario: no se toca su decisión
        justificable = normalizar_justificable(form.get(f"justificable__{row_id}"))
        comentario_auditor = limpiar_texto(form.get(f"comentario_auditor__{row_id}"))
        motivo = limpiar_texto(form.get(f"motivo_inconformidad__{row_id}"))

        if motivo and motivo not in MOTIVOS_INCONFORMIDAD:
            motivo = ""

        cambio = (
            justificable != fila.get("justificable", "")
            or motivo != fila.get("motivo_inconformidad", "")
            or comentario_auditor != fila.get("comentario_auditor", "")
        )

        fila["justificable"] = justificable
        fila["comentario_auditor"] = comentario_auditor
        fila["motivo_inconformidad"] = motivo
        fila["estado_auditoria"] = justificable or "pendiente"
        fila["csat_flag"] = calcular_flag_csat(fila.get("tipo_rating"), justificable)
        if cambio:
            fila["origen_decision"] = "humana" if justificable else ""

    return estado


def aplicar_decision(estado, row_id, justificable, motivo, nota):
    """Aplica la decisión humana a UN negativo. Devuelve '' si aplicó o el error en español."""
    fila = next(
        (
            f
            for f in estado.get("rows", [])
            if str(f.get("row_id")) == str(row_id) and f.get("tipo_rating") == "Negativo"
        ),
        None,
    )
    if fila is None:
        return "No se encontró ese negativo."
    decision = normalizar_justificable(justificable)
    if not decision:
        return "Elige una decisión válida."
    motivo = limpiar_texto(motivo)
    if motivo not in MOTIVOS_INCONFORMIDAD:
        motivo = ""
    fila["justificable"] = decision
    fila["motivo_inconformidad"] = motivo
    fila["comentario_auditor"] = limpiar_texto(nota)[:500]
    fila["origen_decision"] = "humana"
    fila["estado_auditoria"] = decision
    fila["csat_flag"] = calcular_flag_csat(fila.get("tipo_rating"), decision)
    return ""


def estado_decision(estado, row_id):
    return next(
        (f.get("justificable", "") for f in estado.get("rows", []) if str(f.get("row_id")) == str(row_id)), ""
    )


def respuesta_decision(estado, row_id, ok, error, advertencia, analysis_id):
    filas = estado.get("rows", []) if estado else []
    vista = construir_vista(filas, construir_metricas(filas))
    ficha = next((f for f in vista["fichas"] if str(f.get("row_id")) == str(row_id)), None)
    return {
        "ok": ok,
        "error": error,
        "advertencia": advertencia,
        "analysis_id": analysis_id,
        "ficha": ficha,
        "kpis": vista["kpis"],
        "pasos": vista["pasos"],
        "pestanas": vista["pestanas"],
    }


def aceptar_propuestas_ia(estado):
    aceptadas = 0
    for fila in estado.get("rows", []):
        propuesta = fila.get("ia_justificable")
        if not propuesta or fila.get("justificable"):
            continue
        fila["justificable"] = propuesta
        fila["motivo_inconformidad"] = fila.get("ia_motivo", "")
        fila["origen_decision"] = "ia_aceptada"
        fila["estado_auditoria"] = propuesta
        fila["csat_flag"] = calcular_flag_csat(fila.get("tipo_rating"), propuesta)
        aceptadas += 1
    return aceptadas


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
            f"Negativas excluidas del CSAT ajustado porque no fueron culpa del agente: {metricas['negativos_si']}."
        )

    if metricas["negativos_pendientes"]:
        hallazgos.append(
            f"Negativas por confirmar: {metricas['negativos_pendientes']}."
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
    ia_config = obtener_ia_config()
    metricas = construir_metricas(filas)
    resumen_agente = construir_resumen_por_agente(filas)
    resumen_motivo = construir_resumen_por_motivo(filas)
    graficos = construir_distribuciones_graficos(filas, resumen_agente, resumen_motivo)
    hallazgos = construir_top_hallazgos(filas, metricas, resumen_agente, resumen_motivo)
    casos_destacados = construir_casos_destacados(filas)

    negativos = [fila for fila in filas if fila.get("tipo_rating") == "Negativo"]

    return {
        "analysis_id": estado.get("analysis_id", ""),
        "modo": estado.get("modo") or "csv",
        "prueba": bool(estado.get("prueba")),
        "period_id": estado.get("period_id") or "",
        "periodo_texto": estado.get("periodo_texto") or "",
        "auditados_humana": sum(1 for fila in negativos if fila.get("origen_decision") == "humana"),
        "aceptados_ia": sum(1 for fila in negativos if fila.get("origen_decision") == "ia_aceptada"),
        "source_filename": estado.get("source_filename", ""),
        "warnings": estado.get("warnings", []),
        "ia_disponible": ia_disponible(ia_config),
        "ia_modelo": ia_config["model"],
        "ia_tanda": ia_config["max_cases"],
        "metricas": metricas,
        "vista": construir_vista(filas, metricas),
        "resumen_agente": resumen_agente,
        "resumen_motivo": resumen_motivo,
        "graficos": graficos,
        "hallazgos": hallazgos,
        "casos_destacados": casos_destacados,
        "motivos_catalogo": MOTIVOS_INCONFORMIDAD,
        "texto_decision": TEXTO_DECISION,
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
                "ia_justificable": fila.get("ia_justificable", ""),
                "ia_motivo": fila.get("ia_motivo", ""),
                "origen_decision": fila.get("origen_decision", ""),
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
        f"- CSAT real: {metricas['csat_original']}%",
        f"- CSAT ajustado: {metricas['csat_actualizado']}%",
        f"- Negativos: {metricas['negativos']}",
        f"- Neutrales: {metricas['neutrales']}",
        f"- Positivos: {metricas['positivos']}",
        "",
        "## Resultado de auditoría",
        f"- Sí fue culpa del agente: {metricas['negativos_no']} ({metricas['porcentaje_no']}% de negativas)",
        f"- Dudoso: {metricas['negativos_tal_vez']} ({metricas['porcentaje_tal_vez']}% de negativas)",
        f"- No fue culpa del agente: {metricas['negativos_si']} ({metricas['porcentaje_si']}% de negativas)",
        f"- Pendientes: {metricas['negativos_pendientes']}",
        "",
        "## Regla usada para el CSAT ajustado",
        "- Las calificaciones 4 y 5 cuentan como positivas.",
        "- Las calificaciones 1 y 2 cuentan como negativas.",
        "- Las calificaciones 3 quedan como neutrales dentro del denominador.",
        "- Una negativa marcada como «No fue culpa del agente» se excluye del denominador del CSAT ajustado.",
        "- Una negativa marcada como «Sí fue culpa del agente» sigue contando como negativa válida.",
        "- Una negativa marcada como «Dudoso» no altera el cálculo y sigue contando hasta nueva definición.",
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
        lineas.append("| Agente | Total | Negativas | Neutrales | Positivas | Sí fue culpa | Dudoso | No fue culpa | CSAT real | CSAT ajustado |")
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
                    f"### {fila.get('agente') or 'Sin agente'} | {TEXTO_DECISION.get(fila.get('estado_auditoria'), 'Pendiente')} | Rating {fila.get('calificacion_visible') or 'sin dato'}",
                    f"- Fecha: {fila.get('fecha_registrada') or fila.get('fecha_registrada_raw') or 'sin fecha'}",
                    f"- Contacto: {fila.get('nombre_contacto') or 'sin nombre'} | {fila.get('correo_contacto') or 'sin correo'} | {fila.get('telefono_contacto') or 'sin teléfono'}",
                    f"- Motivo: {fila.get('motivo_inconformidad') or 'sin motivo'}",
                    f"- Comentario cliente: {fila.get('comentario') or 'sin comentario'}",
                    f"- Comentario auditor: {fila.get('comentario_auditor') or 'sin comentario'}",
                    f"- Propuesta IA: {TEXTO_DECISION.get(fila.get('ia_justificable'), 'sin propuesta')} | {fila.get('ia_motivo') or 'sin motivo'}",
                    f"- Origen de la decisión: {fila.get('origen_decision') or 'sin decidir'}",
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


# ---------------------------------------------------------------------------
# Modo Chatwoot: traer encuestas del período, guardar en Supabase o modo prueba
# ---------------------------------------------------------------------------

MENSAJE_ESTADO_NO_DISPONIBLE = (
    "El análisis activo ya no está disponible. "
    "Puede ocurrir si Flask se reinició o si el estado temporal fue limpiado. "
    "Vuelve a cargar el CSV o a traer el período de Chatwoot y continúa desde esa misma pantalla."
)


def obtener_chatwoot():
    return ChatwootClient(timeout=15)


def obtener_store_csat():
    return auditoria_csat_store.obtener_store_csat()


def hoy_chatwoot():
    return datetime.now(_obtener_timezone(_timezone())).date()


def mensaje_store_no_configurado(exc):
    return f"{exc} Mientras tanto, usa «Modo prueba (no se guarda)» para trabajar sin guardar."


def es_modo_guardado(estado):
    return estado.get("modo") == "chatwoot" and not estado.get("prueba")


def _fecha_de_periodo(valor):
    return date.fromisoformat(str(valor)[:10])


def traer_filas_chatwoot(inicio, fin):
    rango = construir_rango_chatwoot_fechas(inicio.isoformat(), fin.isoformat())
    chatwoot = obtener_chatwoot()
    encuestas = chatwoot.respuestas_csat(rango.since, rango.until)
    return filas_desde_encuestas(encuestas, chatwoot, _timezone())


def construir_estado_chatwoot(filas, tipo_periodo, inicio, fin, prueba):
    periodo_texto = formatear_periodo(inicio, fin)
    return {
        "analysis_id": "",
        "modo": "chatwoot",
        "prueba": bool(prueba),
        "tipo_periodo": tipo_periodo,
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": fin.isoformat(),
        "periodo_texto": periodo_texto,
        "period_id": "",
        "source_filename": f"Chatwoot {periodo_texto}",
        "created_at": datetime.utcnow().isoformat(),
        "original_columns": list(EXPECTED_COLUMNS),
        "resolved_columns": {},
        "missing_columns": [],
        "warnings": [],
        "rows": filas,
    }


def sincronizar_periodo(estado, retencion=True):
    """Guarda resumen y negativos del período en Supabase. Nunca en modo prueba."""
    if not es_modo_guardado(estado):
        return
    store = obtener_store_csat()
    filas = estado.get("rows", [])
    # La retención va antes del guardado para no borrar el período recién guardado.
    if retencion:
        store.borrar_vencidos(hoy_chatwoot())
    periodo = store.guardar_periodo(
        estado.get("tipo_periodo") or "personalizado",
        _fecha_de_periodo(estado["fecha_inicio"]),
        _fecha_de_periodo(estado["fecha_fin"]),
        resumen_para_guardar(filas),
    )
    store.reemplazar_negativos(periodo["id"], negativos_para_guardar(filas))
    estado["period_id"] = periodo["id"]


def persistir_estado(estado, retencion=True):
    """Guarda el estado temporal y, si corresponde, lo sincroniza. Devuelve una advertencia o ''."""
    advertencia = ""
    if es_modo_guardado(estado):
        try:
            sincronizar_periodo(estado, retencion=retencion)
        except AuditoriaCsatConfigError as exc:
            advertencia = mensaje_store_no_configurado(exc)
        except Exception as exc:
            logger.exception("Error guardando auditoría CSAT en Supabase")
            advertencia = mensaje_error_publico(exc, "No se pudo guardar la auditoría en Supabase")
    guardar_analisis(estado)
    return advertencia


def traer_de_chatwoot(form):
    """Devuelve (estado, mensaje, advertencia)."""
    tipo_periodo = limpiar_texto(form.get("tipo_periodo")) or "semana_pasada"
    prueba = bool(limpiar_texto(form.get("prueba")))
    try:
        inicio, fin = resolver_periodo(
            tipo_periodo,
            hoy_chatwoot(),
            limpiar_texto(form.get("fecha_inicio")) or None,
            limpiar_texto(form.get("fecha_fin")) or None,
        )
    except ValueError as exc:
        return None, "", str(exc)

    store = None
    if not prueba:
        try:
            store = obtener_store_csat()
        except AuditoriaCsatConfigError as exc:
            return None, "", mensaje_store_no_configurado(exc)

    try:
        filas = traer_filas_chatwoot(inicio, fin)
    except Exception as exc:
        logger.exception("Error trayendo encuestas CSAT de Chatwoot")
        return None, "", mensaje_error_publico(exc, "No se pudieron traer las encuestas de Chatwoot")

    periodo_texto = formatear_periodo(inicio, fin)
    if not filas:
        return None, "", f"No hay encuestas en el período {periodo_texto}."

    estado = construir_estado_chatwoot(filas, tipo_periodo, inicio, fin, prueba)
    if store is not None:
        try:
            existente = store.buscar_periodo(inicio, fin)
            if existente:
                fusionar_guardado(filas, store.negativos(existente["id"]))
        except Exception as exc:
            logger.exception("Error leyendo auditoría CSAT guardada")
            return None, "", mensaje_error_publico(exc, "No se pudo leer la auditoría guardada")

    advertencia = persistir_estado(estado)
    sufijo = "Modo prueba: no se guarda." if prueba else "Auditoría guardada."
    if advertencia:
        sufijo = "No se guardó."
    mensaje = f"Se trajeron {len(filas)} encuesta(s) de Chatwoot del {periodo_texto}. {sufijo}"
    return estado, mensaje, advertencia


def reconstruir_estado_guardado(period_id):
    """Re-trae de Chatwoot el período guardado y le aplica las decisiones guardadas."""
    store = obtener_store_csat()
    periodo = store.obtener_periodo(period_id)
    if not periodo:
        return None
    inicio = _fecha_de_periodo(periodo["fecha_inicio"])
    fin = _fecha_de_periodo(periodo["fecha_fin"])
    filas = traer_filas_chatwoot(inicio, fin)
    fusionar_guardado(filas, store.negativos(periodo["id"]))
    estado = construir_estado_chatwoot(filas, periodo.get("tipo_periodo") or "personalizado", inicio, fin, False)
    estado["period_id"] = periodo["id"]
    guardar_analisis(estado)
    return estado


def cargar_estado_chatwoot(fuente):
    """Estado temporal por analysis_id; si falta y hay period_id, lo reconstruye desde lo guardado."""
    estado = cargar_analisis(limpiar_texto(fuente.get("analysis_id")))
    if estado:
        return estado
    period_id = limpiar_texto(fuente.get("period_id"))
    if period_id:
        return reconstruir_estado_guardado(period_id)
    return None


def preparar_transcripciones_ia(estado):
    """En modo Chatwoot trae la conversación solo de los negativos que irá a ver la IA."""
    config = obtener_ia_config()
    if estado.get("modo") != "chatwoot" or not ia_disponible(config):
        return []
    candidatos = candidatos_para_ia(estado.get("rows", []), config["max_cases"])
    if not candidatos:
        return []
    return cargar_transcripciones(candidatos, obtener_chatwoot(), _timezone(), CSAT_IA_MAX_TRANSCRIPT_CHARS)


def listar_guardadas():
    """Devuelve (periodos, aviso). Nunca rompe la pantalla."""
    try:
        periodos = obtener_store_csat().listar_periodos()
    except AuditoriaCsatConfigError as exc:
        return [], f"{exc} La pantalla sigue funcionando en modo prueba y con CSV."
    except Exception as exc:
        logger.exception("Error listando auditorías CSAT guardadas")
        return [], mensaje_error_publico(exc, "No se pudieron listar las auditorías guardadas")
    return [
        dict(
            periodo,
            periodo_texto=formatear_periodo(
                _fecha_de_periodo(periodo["fecha_inicio"]), _fecha_de_periodo(periodo["fecha_fin"])
            ),
        )
        for periodo in periodos
    ], ""


def unir_advertencias(*textos):
    return " ".join(texto for texto in textos if texto)


def quiere_json():
    mejor = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return mejor == "application/json" and request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


def ejecutar_paso_ia(estado, advertencia_previa=""):
    """Audita una tanda de negativos pendientes y guarda. Devuelve el resultado del paso (apto para JSON)."""
    filas_chatwoot = (
        candidatos_para_ia(estado.get("rows", []), obtener_ia_config()["max_cases"])
        if estado.get("modo") == "chatwoot"
        else []
    )
    advertencias_transcripcion = preparar_transcripciones_ia(estado)
    info = {}
    auditadas, advertencias_ia = auditar_estado_con_ia(estado, info)
    # La conversación solo se usa en memoria para la IA; no queda en el estado temporal.
    for fila in filas_chatwoot:
        fila["transcripcion_conversacion"] = ""
    advertencia = unir_advertencias(
        advertencia_previa, *advertencias_transcripcion, *advertencias_ia, persistir_estado(estado)
    )

    filas = estado.get("rows", [])
    pendientes = contar_pendientes_ia(filas)
    total_negativos = sum(1 for fila in filas if fila.get("tipo_rating") == "Negativo")
    mensaje = ""
    if auditadas:
        mensaje = f"La IA revisó {auditadas} negativo(s)."
        if pendientes:
            mensaje += f" Quedan {pendientes} por revisar."
        else:
            mensaje += " Ya revisó todos los pendientes: confirma o corrige sus propuestas en la tabla."
    # Se termina si no queda nada, si hay que detenerse o si una tanda no avanzó sin motivo para reintentar.
    fin = not pendientes or info.get("detener") or (not auditadas and not info.get("esperar_segundos"))
    return {
        "auditadas": auditadas,
        "pendientes": pendientes,
        "total_negativos": total_negativos,
        "mensaje": mensaje,
        "advertencia": advertencia,
        "esperar_segundos": 0 if fin else info.get("esperar_segundos", 0),
        "fin": bool(fin),
        "analysis_id": estado.get("analysis_id") or "",
        "url": url_for("auditoria_csat.auditoria_csat", period_id=estado.get("period_id") or None),
    }


@auditoria_csat_bp.route("/auditoria-csat", methods=["GET", "POST"])
def auditoria_csat():
    limpiar_analisis_expirados()

    mensaje = ""
    advertencia = ""
    contexto_analisis = None
    estado = None
    formulario = {
        "tipo_periodo": limpiar_texto(request.values.get("tipo_periodo")) or "semana_pasada",
        "fecha_inicio": limpiar_texto(request.values.get("fecha_inicio")),
        "fecha_fin": limpiar_texto(request.values.get("fecha_fin")),
        "prueba": bool(limpiar_texto(request.values.get("prueba"))),
    }

    accion = ""
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
            elif accion == "traer_chatwoot":
                estado, mensaje, advertencia = traer_de_chatwoot(request.form)
                if estado:
                    contexto_analisis = construir_contexto_analisis(estado)
            else:
                estado = cargar_estado_chatwoot(request.form)
                if not estado:
                    advertencia = MENSAJE_ESTADO_NO_DISPONIBLE
                elif accion == "ver_estado":
                    # Solo muestra el estado recibido (p. ej. al terminar la auditoría con IA), sin tocar decisiones.
                    contexto_analisis = construir_contexto_analisis(estado)
                elif accion == "decidir":
                    row_id = limpiar_texto(request.form.get("row_id"))
                    error = aplicar_decision(
                        estado,
                        row_id,
                        request.form.get("justificable"),
                        request.form.get("motivo"),
                        request.form.get("nota"),
                    )
                    analysis_id = limpiar_texto(request.form.get("analysis_id"))
                    if not error:
                        advertencia = persistir_estado(estado, retencion=False)
                        analysis_id = estado.get("analysis_id") or analysis_id
                    if quiere_json():
                        return jsonify(
                            respuesta_decision(
                                estado, row_id, not error, error, "" if error else advertencia, analysis_id
                            )
                        )
                    if error:
                        advertencia = error
                    else:
                        mensaje = f"Confirmado: {TEXTO_DECISION.get(estado_decision(estado, row_id), '')}."
                    contexto_analisis = construir_contexto_analisis(estado)
                else:
                    if accion == "guardar_auditoria":
                        estado = actualizar_estado_desde_formulario(estado, request.form)
                    advertencia = persistir_estado(estado)

                    if accion == "guardar_auditoria":
                        if not advertencia:
                            mensaje = "Auditoría actualizada."
                        contexto_analisis = construir_contexto_analisis(estado)
                    elif accion == "auditar_con_ia":
                        paso = ejecutar_paso_ia(estado, advertencia)
                        if quiere_json():
                            return jsonify(paso)
                        advertencia = paso["advertencia"]
                        if paso["esperar_segundos"]:
                            advertencia = unir_advertencias(advertencia, "Vuelve a pulsar en unos segundos.")
                        mensaje = paso["mensaje"]
                        contexto_analisis = construir_contexto_analisis(estado)
                    elif accion == "aceptar_propuestas_ia":
                        aceptadas = aceptar_propuestas_ia(estado)
                        advertencia = unir_advertencias(advertencia, persistir_estado(estado))
                        if aceptadas:
                            mensaje = f"Se aceptaron {aceptadas} propuesta(s) de la IA como decisión confirmada."
                        else:
                            advertencia = unir_advertencias(advertencia, "No hay propuestas de la IA pendientes de aceptar.")
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
                    elif accion == "descargar_bloque_informe" and estado.get("modo") == "chatwoot" and estado.get("prueba"):
                        bloque = bloque_desde_estado(estado, obtener_chatwoot(), _timezone())
                        return Response(
                            bloque,
                            mimetype="text/plain; charset=utf-8",
                            headers={"Content-Disposition": "attachment; filename=bloque_csat_informe.txt"},
                        )
                    else:
                        advertencia = "Acción no válida."
                        contexto_analisis = construir_contexto_analisis(estado)
        else:
            if limpiar_texto(request.args.get("analysis_id")) or limpiar_texto(request.args.get("period_id")):
                estado = cargar_estado_chatwoot(request.args)
                if estado:
                    contexto_analisis = construir_contexto_analisis(estado)
                else:
                    advertencia = "El análisis solicitado ya no está disponible. Carga el CSV o trae el período de nuevo."
    except AuditoriaCsatConfigError as exc:
        advertencia = mensaje_store_no_configurado(exc)
    except Exception as exc:
        logger.exception("Error procesando auditoria_csat")
        advertencia = mensaje_error_publico(exc, "No se pudo procesar la auditoría CSAT")

    if request.method == "POST" and accion == "decidir" and quiere_json():
        # Fallo antes de poder decidir (estado perdido, Supabase no configurado, etc.).
        return jsonify(
            respuesta_decision(
                estado,
                limpiar_texto(request.form.get("row_id")),
                False,
                advertencia or "No se pudo guardar la decisión.",
                "",
                limpiar_texto(request.form.get("analysis_id")),
            )
        )

    if request.method == "POST" and quiere_json():
        # El paso a paso de la IA espera JSON también cuando algo falla antes de auditar.
        return jsonify(
            {
                "auditadas": 0,
                "pendientes": 0,
                "total_negativos": 0,
                "mensaje": "",
                "advertencia": advertencia or "No se pudo continuar la auditoría con IA.",
                "esperar_segundos": 0,
                "fin": True,
                "url": url_for("auditoria_csat.auditoria_csat"),
            }
        )

    if estado and estado.get("modo") == "chatwoot":
        formulario.update(
            tipo_periodo=estado.get("tipo_periodo") or formulario["tipo_periodo"],
            fecha_inicio=estado.get("fecha_inicio") or "",
            fecha_fin=estado.get("fecha_fin") or "",
            prueba=bool(estado.get("prueba")),
        )

    # En modo prueba la pantalla no consulta el almacén: nada de esa request toca Supabase.
    if formulario["prueba"]:
        periodos_guardados, aviso_guardadas = [], "En modo prueba no se consultan las auditorías guardadas."
    else:
        periodos_guardados, aviso_guardadas = listar_guardadas()

    return render_template(
        "auditoria_csat.html",
        mensaje=mensaje,
        advertencia=advertencia,
        contexto=contexto_analisis,
        formulario=formulario,
        tipos_periodo=TIPOS_PERIODO,
        periodos_guardados=periodos_guardados,
        aviso_guardadas=aviso_guardadas,
    )


@auditoria_csat_bp.route("/auditoria-csat/conversacion/<int:conversation_id>")
def conversacion_csat(conversation_id):
    """Conversación traída en vivo de Chatwoot, anonimizada y sin guardar."""
    lineas = []
    url_chatwoot = ""
    error = ""
    try:
        chatwoot = obtener_chatwoot()
        url_chatwoot = chatwoot.url_conversacion(conversation_id)
        transcripcion = construir_transcripcion(
            chatwoot.mensajes_de_conversacion(conversation_id), _timezone(), max_chars=20000
        )
        lineas = [
            {"texto": linea, "es_agente": "] Agente:" in linea}
            for linea in transcripcion.splitlines()
            if linea.strip()
        ]
    except Exception as exc:
        logger.exception("Error trayendo conversación CSAT de Chatwoot")
        error = mensaje_error_publico(exc, "No se pudo cargar la conversación")

    return render_template(
        "auditoria_csat_conversacion.html",
        conversation_id=conversation_id,
        lineas=lineas,
        url_chatwoot=url_chatwoot,
        error=error,
    )
