"""Llamadas analizadas en Multiadmin dentro de la auditoría: normalización, emparejamiento y resumen.

Nunca se guarda el teléfono del cliente, la transcripción ni el audio. Los textos que vienen de
Multiadmin se anonimizan antes de guardarse.
"""

import json
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


# ---------------------------------------------------------------------------
# Métricas y resumen con IA por agente
# ---------------------------------------------------------------------------

MAX_PEORES = 5
MAX_CRITERIOS_BAJOS = 3
MAX_PUNTOS = 5
MAX_TEXTO_RESUMEN = 12000


def _media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None


def _es_saliente(tipo):
    return str(tipo or "").lower().startswith(("out", "sal"))


def _puntaje_medio(llamadas):
    return _media(float(l["puntaje"]) for l in llamadas if l.get("puntaje") is not None)


def resumen_llamadas_por_agente(llamadas):
    grupos = {}
    for llamada in llamadas:
        grupos.setdefault(llamada.get("agente_id"), []).append(llamada)
    filas = []
    for agente_id, grupo in grupos.items():
        con_conversacion = [l for l in grupo if not l.get("sin_conversacion")]
        buzones = [l for l in grupo if l.get("sin_conversacion")]
        # Los buzones suelen puntuar 95–100: los criterios bajos salen de las llamadas con conversación.
        por_criterio = {}
        for llamada in con_conversacion or grupo:
            for item in llamada.get("rubrica") or []:
                if item.get("pct") is not None:
                    por_criterio.setdefault(item.get("nombre"), []).append(float(item["pct"]))
        criterios = sorted(
            ({"nombre": n, "pct": _media(v)} for n, v in por_criterio.items()), key=lambda c: c["pct"]
        )
        filas.append(
            {
                "agente_id": agente_id,
                "llamadas": len(grupo),
                "puntaje_medio": _puntaje_medio(grupo),
                "puntaje_conversacion": _puntaje_medio(con_conversacion),
                "puntaje_buzon": _puntaje_medio(buzones),
                "sin_conversacion": sum(1 for l in grupo if l.get("sin_conversacion")),
                "salientes": sum(1 for l in grupo if _es_saliente(l.get("tipo"))),
                "entrantes": sum(1 for l in grupo if not _es_saliente(l.get("tipo"))),
                "peores": sorted(grupo, key=lambda l: (l.get("puntaje") is None, l.get("puntaje") or 0))[:MAX_PEORES],
                "criterios_bajos": criterios[:MAX_CRITERIOS_BAJOS],
            }
        )
    return sorted(filas, key=lambda f: str(f["agente_id"]))


def _linea_llamada(llamada):
    coaching = llamada.get("coaching") or {}
    bajos = sorted((i for i in llamada.get("rubrica") or [] if i.get("pct") is not None), key=lambda i: i["pct"])[:3]
    partes = [
        f"Ticket {llamada.get('ticket_id')} · puntaje {llamada.get('puntaje')} · "
        f"{'saliente' if _es_saliente(llamada.get('tipo')) else 'entrante'} · {llamada.get('duracion_seg')} s"
        + (" · BUZÓN DE VOZ / SIN CONVERSACIÓN" if llamada.get("sin_conversacion") else ""),
        f"Motivo: {llamada.get('motivo') or ''}",
    ]
    if coaching.get("aciertos"):
        partes.append("Aciertos: " + "; ".join(coaching["aciertos"]))
    if coaching.get("mejoras"):
        partes.append("Mejoras: " + "; ".join(coaching["mejoras"]))
    if coaching.get("proximas_acciones"):
        partes.append("Próximas acciones: " + "; ".join(coaching["proximas_acciones"]))
    if bajos:
        partes.append(
            "Criterios más bajos: " + "; ".join(f"{i['nombre']} {i['pct']:g} % ({i.get('justificacion') or ''})" for i in bajos)
        )
    return "\n".join(partes)


def construir_mensajes_resumen_llamadas(agente_nombre, llamadas):
    """Mensajes para que la IA resuma el coaching de todas las llamadas de un agente."""
    ordenadas = sorted(llamadas, key=lambda l: (l.get("puntaje") is None, l.get("puntaje") or 0))
    bloques, largo = [], 0
    for llamada in ordenadas:
        bloque = _linea_llamada(llamada)
        if largo + len(bloque) > MAX_TEXTO_RESUMEN:
            break
        bloques.append(bloque)
        largo += len(bloque) + 2
    esquema = {
        "puntos_fuertes": [{"texto": "...", "tickets": [123]}],
        "areas_mejora": [{"texto": "...", "tickets": [123]}],
        "recomendaciones": [{"texto": "...", "tickets": [123]}],
        "buzon_voz": {"evaluacion": "...", "tickets": [123]},
        "resumen": "Máximo 2 frases.",
    }
    sistema = (
        "Eres coach de calidad del equipo de soporte telefónico de Compinche. Recibes llamadas de un agente que "
        "otra IA ya auditó (puntaje, motivo, coaching y criterios más bajos). Resume el feedback para el agente:\n"
        f"- puntos_fuertes y areas_mejora: hasta {MAX_PUNTOS} cada uno, los patrones que se repiten, concretos y "
        "accionables, cada uno con los tickets donde se ve.\n"
        f"- recomendaciones: hasta {MAX_PUNTOS} acciones concretas con sus tickets.\n"
        "- buzon_voz: si hay llamadas de buzón de voz o sin conversación, evalúa si el agente deja un mensaje "
        "adecuado (motivo claro, cómo devolver el contacto, tono). Si no hubo, usa null.\n"
        "- No consideres área de mejora que el agente no diga su nombre al presentarse.\n"
        "- Usa solo números de ticket que aparezcan en los datos.\n"
        "Responde en español y SOLO con un objeto JSON con esta forma:\n"
        f"{json.dumps(esquema, ensure_ascii=False)}"
    )
    usuario = f"Agente: {agente_nombre}\nLlamadas analizadas: {len(llamadas)}\n\n" + "\n\n".join(bloques)
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def _tickets(valores, validos):
    salida = []
    for valor in valores if isinstance(valores, list) else [valores]:
        digitos = re.sub(r"\D", "", str(valor or ""))
        if digitos and int(digitos) in validos and int(digitos) not in salida:
            salida.append(int(digitos))
    return salida


def _puntos(valores, validos):
    salida = []
    for item in valores if isinstance(valores, list) else []:
        if isinstance(item, str):
            item = {"texto": item}
        if not isinstance(item, dict) or not str(item.get("texto") or "").strip():
            continue
        salida.append({"texto": _texto(item["texto"]), "tickets": _tickets(item.get("tickets") or [], validos)})
    return salida[:MAX_PUNTOS]


def validar_resumen_llamadas(data, tickets_validos):
    if not isinstance(data, dict):
        raise ValueError("La respuesta de la IA no es un objeto.")
    buzon = data.get("buzon_voz")
    if isinstance(buzon, dict) and str(buzon.get("evaluacion") or "").strip():
        buzon = {"evaluacion": _texto(buzon["evaluacion"]), "tickets": _tickets(buzon.get("tickets") or [], tickets_validos)}
    else:
        buzon = None
    return {
        "puntos_fuertes": _puntos(data.get("puntos_fuertes"), tickets_validos),
        "areas_mejora": _puntos(data.get("areas_mejora"), tickets_validos),
        "recomendaciones": _puntos(data.get("recomendaciones"), tickets_validos),
        "buzon_voz": buzon,
        "resumen": _texto(data.get("resumen")),
    }
