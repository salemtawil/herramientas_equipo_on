"""Encuestas CSAT de Chatwoot convertidas en filas de auditoría, y su persistencia."""
import logging
from datetime import datetime

from utils.auditoria_chats_transcripcion import construir_transcripcion_v2, metricas_tiempos, periodo_agente
from utils.chatwoot_reportes import _obtener_timezone
from utils.errores import mensaje_error_publico

logger = logging.getLogger(__name__)

MAX_TEXTO_GUARDADO = 500


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _recortar(valor, maximo=MAX_TEXTO_GUARDADO):
    return _texto(valor)[:maximo]


def _entero_o_none(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _numero_o_none(valor):
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def filas_desde_encuestas(encuestas, chatwoot, tz_name):
    from tools.auditoria_csat import (
        calcular_flag_csat,
        clasificar_tipo_rating,
        formatear_fecha,
        parsear_calificacion,
    )

    tz = _obtener_timezone(tz_name)
    filas = []
    for encuesta in encuestas:
        survey_id = _entero_o_none(encuesta.get("id"))
        conversation_id = _entero_o_none(encuesta.get("conversation_id"))
        contacto = encuesta.get("contact") or {}
        agente_info = encuesta.get("assigned_agent") or {}
        agente = _texto(agente_info.get("available_name")) or _texto(agente_info.get("name")) or "Sin agente"

        calificacion = parsear_calificacion(encuesta.get("rating"))
        tipo_rating = clasificar_tipo_rating(calificacion)
        calificacion_visible = str(calificacion) if calificacion is not None else _texto(encuesta.get("rating"))

        creada = _entero_o_none(encuesta.get("created_at"))
        fecha_dt = datetime.fromtimestamp(creada, tz) if creada else None

        comentario = _texto(encuesta.get("feedback_message"))
        review_notes = _texto(encuesta.get("csat_review_notes"))
        nombre = _texto(contacto.get("name"))
        correo = _texto(contacto.get("email"))
        telefono = _texto(contacto.get("phone_number"))
        enlace = chatwoot.url_conversacion(conversation_id) if conversation_id is not None else ""
        fecha_visible = formatear_fecha(fecha_dt)

        filas.append(
            {
                "Nombre del agente": agente,
                "Calificación": calificacion_visible,
                "Comentario de opinión": comentario,
                "Nombre de Contacto": nombre,
                "Correo electrónico de contacto": correo,
                "Número de teléfono de contacto": telefono,
                "Enlace a la conversación": enlace,
                "Fecha registrada": fecha_visible,
                "Review Notes": review_notes,
                "row_id": str(survey_id),
                "survey_id": survey_id,
                "conversation_id": conversation_id,
                "agente_id": _entero_o_none(agente_info.get("id")),
                "agente": agente,
                "calificacion": calificacion,
                "calificacion_visible": calificacion_visible,
                "tipo_rating": tipo_rating,
                "comentario": comentario,
                "nombre_contacto": nombre,
                "correo_contacto": correo,
                "telefono_contacto": telefono,
                "enlace_conversacion": enlace,
                "fecha_registrada": fecha_visible,
                "fecha_registrada_raw": fecha_dt.isoformat() if fecha_dt else "",
                "fecha_iso": fecha_dt.isoformat() if fecha_dt else "",
                "review_notes": review_notes,
                "transcripcion_conversacion": "",
                "justificable": "",
                "comentario_auditor": "",
                "motivo_inconformidad": "",
                "estado_auditoria": "pendiente",
                "csat_flag": calcular_flag_csat(tipo_rating, ""),
                "ia_estado": "",
                "ia_confianza": "",
                "ia_explicacion": "",
                "ia_evidencia": "",
                "ia_puntaje": "",
                "ia_reglas": [],
                "ia_modelo": "",
                "ia_fecha": "",
                "ia_fuente": "",
                "ia_justificable": "",
                "ia_motivo": "",
                "origen_decision": "",
            }
        )
    return filas


def _metricas_de(mensajes, fila):
    """Tiempos del chat ya calculados para la IA; {} si no se pueden calcular."""
    agente_id = fila.get("agente_id")
    agente = fila.get("agente") or ""
    try:
        return metricas_tiempos(mensajes, periodo_agente(mensajes, agente_id, agente), agente_id, agente)
    except Exception:
        logger.exception("No se pudieron calcular los tiempos de la conversación %s", fila.get("conversation_id"))
        return {}


def cargar_transcripciones(filas, chatwoot, tz_name, max_chars=12000):
    """Trae la conversación completa (con notas internas y eventos) y sus tiempos, solo en memoria."""
    advertencias = []
    for fila in filas:
        if fila.get("transcripcion_conversacion"):
            continue
        conversation_id = fila.get("conversation_id")
        try:
            mensajes = chatwoot.mensajes_de_conversacion(conversation_id)
            fila["transcripcion_conversacion"] = construir_transcripcion_v2(mensajes, tz_name, max_chars)
            fila["metricas_tiempo"] = _metricas_de(mensajes, fila)
        except Exception as exc:
            logger.exception("Error cargando conversación %s de Chatwoot", conversation_id)
            advertencias.append(mensaje_error_publico(exc, f"No se pudo cargar la conversación {conversation_id}"))
    return advertencias


def fusionar_guardado(filas, negativos_guardados):
    from tools.auditoria_csat import calcular_flag_csat

    guardados = {}
    for guardado in negativos_guardados or []:
        survey_id = _entero_o_none(guardado.get("survey_id"))
        if survey_id is not None:
            guardados[survey_id] = guardado

    for fila in filas:
        if fila.get("tipo_rating") != "Negativo":
            continue
        guardado = guardados.get(fila.get("survey_id"))
        if not guardado:
            continue

        for clave in ("ia_justificable", "ia_motivo", "ia_confianza", "ia_evidencia"):
            valor = guardado.get(clave)
            if valor is not None:
                fila[clave] = valor
        if _texto(fila.get("ia_justificable")):
            fila["ia_estado"] = fila.get("ia_estado") or "sugerida"
            fila["ia_fuente"] = fila.get("ia_fuente") or "guardado"
        fila["justificable"] = _texto(guardado.get("decision_final"))
        fila["motivo_inconformidad"] = _texto(guardado.get("motivo_final"))
        fila["comentario_auditor"] = _texto(guardado.get("nota_auditor"))
        fila["origen_decision"] = _texto(guardado.get("origen_decision"))
        fila["estado_auditoria"] = fila["justificable"] or "pendiente"
        fila["csat_flag"] = calcular_flag_csat(fila["tipo_rating"], fila["justificable"])


def negativos_para_guardar(filas):
    return [
        {
            "survey_id": fila.get("survey_id"),
            "conversation_id": fila.get("conversation_id"),
            "agente_id": fila.get("agente_id"),
            "agente_nombre": fila.get("agente") or "",
            "rating": fila.get("calificacion"),
            "comentario": _recortar(fila.get("comentario")),
            "enlace": fila.get("enlace_conversacion") or "",
            "fecha": fila.get("fecha_iso") or None,
            "ia_justificable": fila.get("ia_justificable") or "",
            "ia_motivo": fila.get("ia_motivo") or "",
            "ia_confianza": _numero_o_none(fila.get("ia_confianza")),
            "ia_evidencia": _recortar(fila.get("ia_evidencia")),
            "decision_final": fila.get("justificable") or "",
            "motivo_final": fila.get("motivo_inconformidad") or "",
            "origen_decision": fila.get("origen_decision") or "",
            "nota_auditor": _recortar(fila.get("comentario_auditor")),
        }
        for fila in filas
        if fila.get("tipo_rating") == "Negativo"
    ]


def resumen_para_guardar(filas):
    from tools.auditoria_csat import construir_metricas, construir_resumen_por_agente

    metricas = construir_metricas(filas)
    return {
        "total_encuestas": len(filas),
        "ratings_count": {str(n): sum(1 for f in filas if f.get("calificacion") == n) for n in range(1, 6)},
        "csat_real": metricas["csat_original"],
        "csat_ajustado": metricas["csat_actualizado"],
        "por_agente": construir_resumen_por_agente(filas),
        "negativos_total": metricas["negativos"],
        "negativos_excluidos": metricas["negativos_si"],
        "negativos_pendientes": metricas["negativos_pendientes"],
    }
