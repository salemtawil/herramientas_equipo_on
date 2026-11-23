"""Llamadas analizadas en Multiadmin dentro de la auditoría: normalización, emparejamiento y resumen.

Nunca se guarda el teléfono del cliente, la transcripción ni el audio. Los textos que vienen de
Multiadmin se anonimizan antes de guardarse.
"""

import re
import unicodedata
from datetime import datetime, timezone

from utils.auditoria_chats_transcripcion import anonimizar

SEGUNDOS_SIN_CONVERSACION = 60
_RE_SIN_CONVERSACION = re.compile(
    r"buz[oó]n|contestadora|voicemail|no estaba disponible|sin conversaci[oó]n|accidental|no contest[oó]",
    re.IGNORECASE,
)


def _texto(valor):
    return " ".join(anonimizar(str(valor or "")).split())


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _entero(valor):
    numero = _numero(valor)
    return int(numero) if numero is not None else None


def es_sin_conversacion(duracion_seg, motivo, es_buzon=False):
    """Buzón de voz, llamada sin respuesta o contacto accidental. Se etiqueta, no se excluye."""
    if es_buzon:
        return True
    if duracion_seg is not None and duracion_seg < SEGUNDOS_SIN_CONVERSACION:
        return True
    return bool(_RE_SIN_CONVERSACION.search(str(motivo or "")))


def normalizar_resumen(item):
    """Fila de `chat_audit_calls` a partir del resumen de la lista (sin teléfono del cliente)."""
    metadata = item.get("metadata") or {}
    duracion = _entero(item.get("durationSec"))
    motivo = _texto((item.get("analytics") or {}).get("issueType"))
    creada = _entero(item.get("createdAt"))
    sentimiento = item.get("sentiment") or {}
    return {
        "record_key": str(item.get("recordKey") or ""),
        "linea": str(item.get("callId") or ""),
        "ticket_id": _entero(item.get("ticketId")),
        "agent_number": str(item.get("agentNumber") or "").strip(),
        "fecha": datetime.fromtimestamp(creada / 1000, timezone.utc).isoformat() if creada else None,
        "duracion_seg": duracion,
        "tipo": str(metadata.get("callType") or ""),
        "intencion": str(metadata.get("intent") or ""),
        "motivo": motivo,
        "puntaje": _numero((item.get("scores") or {}).get("overall")),
        "sentimiento_agente": _texto(sentimiento.get("agent")),
        "sentimiento_cliente": _texto(sentimiento.get("customer")),
        "sin_conversacion": es_sin_conversacion(duracion, motivo, bool(metadata.get("isVoicemail"))),
        "detalle_ok": False,
    }


def cambios_detalle(detalle):
    """Campos que aporta el detalle de una llamada: rúbrica, coaching, puntos clave y analítica."""
    rubrica = []
    for item in (detalle.get("rubric") or {}).get("items") or []:
        rubrica.append(
            {
                "nombre": _texto(item.get("name")),
                "peso": _numero(item.get("weightPct")),
                "pct": _numero(item.get("percentScore")),
                "justificacion": _texto(item.get("notes")),
            }
        )
    coaching = detalle.get("coaching") or {}
    analitica = detalle.get("analytics") or {}
    return {
        "rubrica": rubrica,
        "coaching": {
            "aciertos": [_texto(t) for t in coaching.get("topWins") or [] if str(t or "").strip()],
            "mejoras": [_texto(t) for t in coaching.get("topImprovements") or [] if str(t or "").strip()],
            "proximas_acciones": [_texto(t) for t in coaching.get("nextActions") or [] if str(t or "").strip()],
        },
        "puntos_clave": [
            {"titulo": _texto(p.get("label")), "texto": _texto(p.get("detail"))}
            for p in detalle.get("keyPoints") or []
            if isinstance(p, dict)
        ],
        "analitica": {
            "resolucion_primer_contacto": analitica.get("firstContactResolution"),
            "escalada": analitica.get("escalated"),
            "hablar_escuchar": _numero(analitica.get("talkListenRatio")),
            "esperas": _entero(analitica.get("holdsCount")),
            "silencio_seg": _numero(analitica.get("deadAirSecondsEstimate")),
        },
        "detalle_ok": True,
    }


def _normalizar_nombre(nombre):
    texto = unicodedata.normalize("NFKD", str(nombre or "").lower())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def emparejar(agentes_lote, nombres_multiadmin, guardados):
    """{nombre de agente en Multiadmin: id de agente de Chatwoot} para los agentes del lote.

    Lo guardado (manual o previo) gana; luego el nombre igual; luego el nombre de Chatwoot igual al
    primer nombre de Multiadmin cuando hay un único candidato. Un agente puede tener varios nombres.
    """
    ids_lote = {int(a["id"]) for a in agentes_lote}
    guardados = guardados or {}
    resultado = {n: int(i) for n, i in guardados.items() if i is not None and int(i) in ids_lote}
    todos = set(nombres_multiadmin) | set(guardados)

    for agente in agentes_lote:
        objetivo = _normalizar_nombre(agente.get("nombre"))
        if not objetivo:
            continue
        # La ambigüedad se mide sobre todos los nombres, incluidos los ya guardados.
        exactos = [n for n in todos if _normalizar_nombre(n) == objetivo]
        candidatos = exactos or [n for n in todos if _normalizar_nombre(n).split(" ")[0] == objetivo]
        if len(candidatos) == 1 and candidatos[0] not in guardados and candidatos[0] not in resultado:
            resultado[candidatos[0]] = int(agente["id"])
    return resultado
