"""Confirmación opcional con IA de las incidencias de chats, con cupo diario.

Un paso procesa un solo chat (una llamada a la IA), apto para el límite de Vercel.
"""

import os
from datetime import datetime, timedelta, timezone

from utils.auditoria_chats_transcripcion import anonimizar
from utils.ia_chat import IAConfigError, IARateLimitError, IARespuestaError, IATemporalError, completar_json
from utils.incidencias_chats_reglas import fragmento

CUPO_DEFECTO = 10
MAX_EXTRAS = 5
MAX_REINTENTOS_IA = 3
# Una llamada a la IA cabe en un paso (<60 s): pasado este margen, el claim «procesando» quedó abandonado.
SEGUNDOS_IA_ABANDONADA = 90
# Tiempo total para la IA dentro de un paso (Vercel corta a los 60 s); se reparte entre principal y respaldo.
PRESUPUESTO_IA_SEGUNDOS = 45

PROMPT_IA = """Eres un auditor de calidad de atención al cliente. Recibirás la transcripción anonimizada de un chat \
de soporte y una lista numerada de incidencias que un sistema de reglas detectó en él.

Tu tarea:
1. Confirma o descarta CADA incidencia numerada, usando únicamente lo que dice el chat.
2. No inventes hechos, mensajes ni incidencias. Si no hay evidencia clara en el texto, no confirmes.
3. En cada «motivo» cita brevemente el texto del chat que justifica tu decisión.
4. Solo si ves un problema claro que las reglas no detectaron, agrégalo en «incidencias_extra» \
(tipo «cliente» o «atencion»); si no, deja la lista vacía.
5. Escribe todo en español.

Responde SOLO con un JSON, sin texto adicional, con esta forma exacta:
{"incidencias": [{"indice": 1, "confirmada": true, "motivo": "..."}],
 "resumen": "una o dos frases",
 "incidencias_extra": [{"tipo": "cliente", "etiqueta": "...", "evidencia": "..."}]}"""


def cupo_ia():
    try:
        valor = int(str(os.getenv("INCIDENCIAS_CHATS_AI_CUPO_DIARIO", "")).strip())
    except ValueError:
        return CUPO_DEFECTO
    return valor if valor >= 0 else CUPO_DEFECTO


def _respuesta(store, review_id, accion, mensaje="", esperar_segundos=0):
    # Import tardío: el motor importa este módulo.
    from utils.incidencias_chats_motor import _respuesta as respuesta_motor

    return respuesta_motor(store, review_id, accion, mensaje, esperar_segundos)


def _es_alta(chat):
    return any(i.get("severidad") == "alta" for i in chat.get("incidencias") or [])


def _antiguo(chat, segundos):
    try:
        actualizado = datetime.fromisoformat(str(chat.get("updated_at")))
    except ValueError:
        return True
    if actualizado.tzinfo is None:
        actualizado = actualizado.replace(tzinfo=timezone.utc)
    return actualizado <= datetime.now(timezone.utc) - timedelta(seconds=segundos)


def _recuperar_abandonados_ia(store, chats):
    """Un claim abandonado vuelve a `pendiente` una vez; si se abandona otra vez, queda en `error`."""
    for chat in chats:
        if chat.get("ia_estado") != "procesando" or not _antiguo(chat, SEGUNDOS_IA_ABANDONADA):
            continue
        if (chat.get("ia_resultado") or {}).get("recuperado"):
            store.actualizar_chat(chat["id"], {"ia_estado": "error", "ia_resultado": None, "transcripcion_tmp": None})
        else:
            store.actualizar_chat(chat["id"], {"ia_estado": "pendiente", "ia_resultado": {"recuperado": True}})


def _a_sin_cupo(store, chats):
    for chat in chats:
        store.actualizar_chat(chat["id"], {"ia_estado": "sin_cupo", "ia_resultado": None, "transcripcion_tmp": None})


def _mensajes(chat):
    lista = "\n".join(
        f"{n}. {i.get('etiqueta', '')}: {i.get('evidencia', '')}" for n, i in enumerate(chat.get("incidencias") or [], 1)
    )
    contenido = f"Incidencias detectadas:\n{lista}\n\nTranscripción:\n{chat.get('transcripcion_tmp') or ''}"
    return [{"role": "system", "content": PROMPT_IA}, {"role": "user", "content": contenido}]


def _texto(valor, maximo=500):
    # Lo que escribe la IA puede repetir datos del chat: se anonimiza antes de guardarlo.
    return " ".join(anonimizar(str(valor or "")).split())[:maximo]


def _normalizar(data, total):
    """Valida la salida de la IA; lo que no cumpla la forma se descarta."""
    if not isinstance(data.get("incidencias"), list):
        raise IARespuestaError("La IA no devolvió el formato esperado.")
    confirmaciones = []
    for item in data["incidencias"]:
        if not isinstance(item, dict):
            continue
        try:
            indice = int(item.get("indice"))
        except (TypeError, ValueError):
            continue
        if 1 <= indice <= total:
            confirmaciones.append(
                {"indice": indice, "confirmada": item.get("confirmada") is True, "motivo": _texto(item.get("motivo"))}
            )
    extras = []
    brutas = data.get("incidencias_extra")
    for item in brutas if isinstance(brutas, list) else []:
        if isinstance(item, dict) and _texto(item.get("etiqueta")) and _texto(item.get("evidencia")):
            tipo = item.get("tipo") if item.get("tipo") in ("cliente", "atencion") else "atencion"
            extras.append({"tipo": tipo, "etiqueta": _texto(item["etiqueta"], 80), "evidencia": _texto(item["evidencia"])})
    return {"incidencias": confirmaciones, "resumen": _texto(data.get("resumen")), "incidencias_extra": extras[:MAX_EXTRAS]}


def _incidencia_extra(extra, chat):
    return {
        "tipo": extra["tipo"],
        "clave": "ia_extra",
        "etiqueta": extra["etiqueta"],
        "severidad": "media",
        "evidencia": fragmento(extra["evidencia"], 0, 0),
        "coincidencia": "",
        "mensaje_id": None,
        "ts": None,
        "agente_id": chat.get("agente_id"),
        "agente_nombre": chat.get("agente_nombre") or "",
        "origen": "ia",
    }


def _llamar_ia(mensajes, config_ia):
    """Modelo principal y, si está saturado o sin cupo, el de respaldo (como `auditoria_chats_motor`).

    El tiempo total se reparte entre los modelos para que el paso no supere el límite de Vercel.
    """
    modelos = [config_ia.get("model")]
    respaldo = config_ia.get("model_respaldo")
    if respaldo and respaldo != modelos[0]:
        modelos.append(respaldo)
    timeout = PRESUPUESTO_IA_SEGUNDOS // len(modelos)
    errores = []
    for modelo in modelos:
        try:
            return completar_json(mensajes, dict(config_ia, model=modelo), timeout=timeout)
        except IARateLimitError as exc:
            errores.append((modelo, exc))
    if len(errores) == 1:
        raise errores[0][1]
    detalle = " · ".join(f"{modelo}: {exc}" for modelo, exc in errores)
    temporales = [e for _, e in errores if not e.diario]
    if temporales:
        raise IATemporalError(f"Ningún modelo respondió ({detalle})", esperar_segundos=temporales[0].esperar_segundos)
    raise IARateLimitError(f"Todos los modelos agotaron su cupo diario ({detalle})", diario=True)


def _fallo(store, chat, mensaje):
    store.actualizar_chat(chat["id"], {"ia_estado": "error", "ia_resultado": None, "transcripcion_tmp": None})
    return _respuesta(store, chat["review_id"], "ia", mensaje)


def paso_ia(store, revision, config_ia, hoy):
    """Procesa un chat con IA. Devuelve la respuesta del motor, o None si no hay nada que hacer."""
    review_id = revision["id"]
    _recuperar_abandonados_ia(store, store.listar_chats(review_id))
    chats = store.listar_chats(review_id)
    pendientes = [c for c in chats if c.get("ia_estado") == "pendiente" and c.get("estado") == "evaluado"]
    if not pendientes:
        if any(c.get("ia_estado") == "procesando" for c in chats):
            return _respuesta(store, review_id, "espera", "Hay un chat con la IA en otra pestaña.", esperar_segundos=5)
        return None

    if not (config_ia or {}).get("activa"):
        _a_sin_cupo(store, pendientes)
        return _respuesta(store, review_id, "ia", "La IA no está configurada: los chats quedan sin confirmar.")
    if store.usos_ia(hoy) >= cupo_ia():
        _a_sin_cupo(store, pendientes)
        return _respuesta(store, review_id, "ia", "Sin cupo de IA hoy: los chats restantes quedan sin confirmar.")

    pendientes.sort(key=lambda c: 0 if _es_alta(c) else 1)  # estable: respeta el orden dentro de cada grupo
    # Sin transcripción no hay nada que enviar: no se gasta cupo.
    for sin in [c for c in pendientes if not c.get("transcripcion_tmp")]:
        store.actualizar_chat(sin["id"], {"ia_estado": None, "ia_resultado": None})
    pendientes = [c for c in pendientes if c.get("transcripcion_tmp")]
    if not pendientes:
        return _respuesta(store, review_id, "ia", "Chats sin transcripción: no se revisan con IA.")
    chat = None
    for candidato in pendientes:
        chat = store.reclamar_ia(candidato["id"], "pendiente", "procesando")
        if chat:
            break
    if not chat:
        return _respuesta(store, review_id, "espera", "Otro proceso está tomando el siguiente chat.", esperar_segundos=2)

    try:
        resultado = _normalizar(_llamar_ia(_mensajes(chat), config_ia), len(chat.get("incidencias") or []))
    except IARateLimitError as exc:
        if exc.diario:
            _a_sin_cupo(store, pendientes + [chat] if chat not in pendientes else pendientes)
            return _respuesta(store, review_id, "ia", f"{exc} Los chats restantes quedan sin confirmar.")
        marcas = dict(chat.get("ia_resultado") or {})
        marcas["reintentos"] = int(marcas.get("reintentos") or 0) + 1
        if marcas["reintentos"] >= MAX_REINTENTOS_IA:
            return _fallo(store, chat, f"La IA falló {MAX_REINTENTOS_IA} veces seguidas en el chat #{chat['conversation_id']}: {exc}")
        store.actualizar_chat(chat["id"], {"ia_estado": "pendiente", "ia_resultado": marcas})
        return _respuesta(store, review_id, "espera", str(exc), esperar_segundos=exc.esperar_segundos)
    except (IAConfigError, IARespuestaError) as exc:
        return _fallo(store, chat, f"La IA no pudo revisar el chat #{chat['conversation_id']}: {exc}")
    except Exception as exc:
        return _fallo(store, chat, f"Fallo inesperado de la IA en el chat #{chat['conversation_id']}: {exc}")

    incidencias = list(chat.get("incidencias") or []) + [_incidencia_extra(e, chat) for e in resultado["incidencias_extra"]]
    store.actualizar_chat(
        chat["id"],
        {"ia_estado": "hecha", "ia_resultado": resultado, "incidencias": incidencias, "transcripcion_tmp": None},
    )
    store.sumar_uso_ia(hoy)
    return _respuesta(store, review_id, "ia", f"Chat #{chat['conversation_id']} confirmado con IA.")
