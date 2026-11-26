"""Motor por pasos de Incidencias de chats: listar, CSAT, evaluar con reglas y reutilizar.

Cada petición HTTP ejecuta un paso acotado (apto para Vercel); todo el estado vive en el store.
"""

import time
from datetime import datetime, timedelta, timezone

from utils.chatwoot_reportes import _obtener_timezone, _timezone
from utils.incidencias_chats_reglas import REGLAS_VERSION, evaluar_chat
from utils.incidencias_chats_store import IncidenciasError, MemoriaIncidenciasStore

MAX_HORAS = 72
PRESUPUESTO_PASO = 8.0
MAX_INTENTOS = 3
MAX_PAGINAS_LISTADO = 200
# Un paso nunca dura más de 60 s (límite de Vercel): pasado ese margen, el chat «procesando» quedó abandonado.
SEGUNDOS_PROCESANDO_ABANDONADO = 75
# Las encuestas CSAT llegan después del chat: se piden hasta 3 días después del fin del rango.
DIAS_EXTRA_CSAT = 3
ESTADOS_TERMINALES = ("completado", "con_errores")
ORDEN_SEVERIDAD = {"alta": 0, "media": 1}
COLUMNAS_CSV = [
    "Chat", "Enlace", "Fecha", "Agente", "Tipo", "Categoría", "Severidad",
    "Evidencia", "IA", "Decisión", "Decidido por", "Nota",
]
TIPOS_VISIBLES = {"cliente": "Cliente", "atencion": "Atención"}


def crear_revision(store, *, since, until, bandejas, usar_ia, creado_por):
    since, until = int(since), int(until)
    if until <= since:
        raise ValueError("La fecha de fin debe ser posterior a la de inicio.")
    if until - since > MAX_HORAS * 3600:
        raise ValueError(f"El rango no puede superar las {MAX_HORAS} horas.")
    return store.crear_revision(
        {
            "since": since,
            "until": until,
            "bandejas": [int(b) for b in bandejas or []],
            "usar_ia": bool(usar_ia),
            "estado": "listando",
            "pagina_listado": 1,
            "contadores": {},
            "csat": None,
            "csat_error": None,
            "reglas_version": REGLAS_VERSION,
            "creado_por": creado_por or "",
        }
    )


def _progreso(chats):
    evaluados = [c for c in chats if c.get("estado") == "evaluado"]
    return {
        "total": len(chats),
        "evaluados": len(evaluados),
        "descartados": sum(1 for c in chats if c.get("estado") == "descartado"),
        "con_incidencias": sum(1 for c in evaluados if c.get("incidencias")),
        "errores": sum(1 for c in chats if c.get("estado") == "error"),
    }


def _respuesta(store, review_id, accion, mensaje="", esperar_segundos=0):
    revision = store.obtener_revision(review_id) or {}
    return {
        "accion": accion,
        "estado": revision.get("estado", ""),
        "mensaje": mensaje,
        "esperar_segundos": int(esperar_segundos),
        "progreso": _progreso(store.listar_chats(review_id)),
    }


def _recuperar_abandonados(store, chats):
    # Se compara con el reloj real: `updated_at` lo pone el store, no el `ahora` del paso.
    limite = datetime.now(timezone.utc) - timedelta(seconds=SEGUNDOS_PROCESANDO_ABANDONADO)
    for chat in chats:
        if chat.get("estado") != "procesando":
            continue
        try:
            actualizado = datetime.fromisoformat(str(chat.get("updated_at")))
        except ValueError:
            actualizado = limite
        if actualizado.tzinfo is None:
            actualizado = actualizado.replace(tzinfo=timezone.utc)
        if actualizado <= limite:
            # Cuenta como intento: un chat que siempre tumba la petición termina en `error`.
            _registrar_error(store, chat)


# ---------------------------------------------------------------------------
# CSAT
# ---------------------------------------------------------------------------


def _puntuacion(valor):
    try:
        numero = int(float(str(valor).replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return numero if 1 <= numero <= 5 else None


def _mapa_csat(encuestas):
    """Conversación (texto, por ser JSON) -> puntuación 1..5; mismas claves que `filas_desde_encuestas`."""
    mapa = {}
    for encuesta in encuestas or []:
        conversation_id, puntuacion = encuesta.get("conversation_id"), _puntuacion(encuesta.get("rating"))
        if conversation_id is not None and puntuacion is not None:
            mapa[str(int(conversation_id))] = puntuacion
    return mapa


def _paso_csat(store, revision, chatwoot):
    try:
        encuestas = chatwoot.respuestas_csat(int(revision["since"]), int(revision["until"]) + DIAS_EXTRA_CSAT * 86400)
    except Exception as exc:
        store.actualizar_revision(revision["id"], {"csat": {}, "csat_error": str(exc) or exc.__class__.__name__})
        return _respuesta(store, revision["id"], "csat", f"No se pudo leer el CSAT ({exc}); se sigue sin él.")
    mapa = _mapa_csat(encuestas)
    store.actualizar_revision(revision["id"], {"csat": mapa, "csat_error": None})
    return _respuesta(store, revision["id"], "csat", f"{len(mapa)} respuestas CSAT leídas.")


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------


def _en_alcance(conversacion, since, until, bandejas):
    if not since <= int(conversacion.get("created_at") or 0) <= until:
        return False
    bandeja = conversacion.get("inbox_id")
    return not bandejas or bandeja is None or int(bandeja) in bandejas


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _fila_chat(revision, conversacion):
    """Fila nueva del listado. Todas las filas llevan las mismas claves (requisito de PostgREST)."""
    created_at = int(conversacion.get("created_at") or 0)
    assignee = (conversacion.get("meta") or {}).get("assignee") or {}
    assignee = assignee if isinstance(assignee, dict) else {}
    return {
        "review_id": revision["id"],
        "conversation_id": int(conversacion["id"]),
        "agente_id": _entero(assignee.get("id")),
        "agente_nombre": assignee.get("name") or "",
        "inbox_id": _entero(conversacion.get("inbox_id")),
        "conversacion_fecha": datetime.fromtimestamp(created_at, timezone.utc).isoformat() if created_at else None,
        "resuelto": False,
        "status": conversacion.get("status"),
        "last_activity_at": _entero(conversacion.get("last_activity_at")),
        "estado": "pendiente",
        "intentos": 0,
        "incidencias": [],
        "ia_estado": None,
        "ia_resultado": None,
        "reglas_version": "",
    }


def _reutilizar(store, fila):
    """Copia la evaluación previa si el chat ya estaba resuelto y no tuvo actividad nueva."""
    if fila["status"] != "resolved" or fila["last_activity_at"] is None:
        return fila
    previa = store.ultima_evaluacion(fila["conversation_id"], fila["review_id"])
    if (
        not previa
        or previa.get("resuelto") is not True
        or previa.get("reglas_version") != REGLAS_VERSION
        or _entero(previa.get("last_activity_at")) != fila["last_activity_at"]
    ):
        return fila
    return dict(
        fila,
        estado="evaluado",
        resuelto=True,
        incidencias=previa.get("incidencias") or [],
        ia_estado=previa.get("ia_estado"),
        ia_resultado=previa.get("ia_resultado"),
        reglas_version=REGLAS_VERSION,
        agente_id=previa.get("agente_id"),
        agente_nombre=previa.get("agente_nombre") or fila["agente_nombre"],
    )


def _listar_pagina(store, revision, chatwoot, maximo=None):
    """Lista una página. Con `maximo`, deja de insertar al llegar a ese total de chats."""
    since, until = int(revision["since"]), int(revision["until"])
    bandejas = [int(b) for b in revision.get("bandejas") or []]
    pagina = int(revision.get("pagina_listado") or 1)
    conversaciones = chatwoot.conversaciones_en_rango(since, until, page=pagina, inbox_ids=bandejas or None)
    en_rango = [c for c in conversaciones or [] if c.get("id") is not None and _en_alcance(c, since, until, bandejas)]
    if maximo is not None:
        cupo = max(0, maximo - len(store.listar_chats(revision["id"])))
        elegidas = en_rango[:cupo]
    else:
        elegidas = en_rango
    insertados = store.insertar_chats([_reutilizar(store, _fila_chat(revision, c)) for c in elegidas])

    terminado = not conversaciones or pagina >= MAX_PAGINAS_LISTADO
    cambios = {"pagina_listado": pagina + 1}
    contadores = revision.get("contadores") or {}
    if contadores.get("fallos_listado"):
        cambios["contadores"] = dict(contadores, fallos_listado=0)
    if terminado:
        cambios["estado"] = "evaluando"
    store.actualizar_revision(revision["id"], cambios)
    return {"vistos": len(en_rango), "insertados": insertados, "terminado": terminado, "pagina": pagina}


def _paso_listado(store, revision, chatwoot):
    try:
        resultado = _listar_pagina(store, revision, chatwoot)
    except Exception as exc:
        mensaje = f"No se pudo listar la página {revision.get('pagina_listado')}: {exc}"
        contadores = dict(revision.get("contadores") or {})
        contadores["fallos_listado"] = int(contadores.get("fallos_listado") or 0) + 1
        if contadores["fallos_listado"] < MAX_INTENTOS:
            store.actualizar_revision(revision["id"], {"contadores": contadores})
            return _respuesta(store, revision["id"], "error", mensaje, esperar_segundos=5)
        contadores["error_listado"] = mensaje
        store.actualizar_revision(revision["id"], {"estado": "con_errores", "contadores": contadores})
        return _respuesta(
            store, revision["id"], "error",
            f"{mensaje}. Se dejó de listar tras {MAX_INTENTOS} intentos; la revisión queda con errores.",
        )
    if resultado["terminado"]:
        mensaje = "Listado completo; se empiezan a evaluar los chats."
    else:
        mensaje = f"Página {resultado['pagina']}: {resultado['insertados']} chats nuevos."
    return _respuesta(store, revision["id"], "listado", mensaje)


# ---------------------------------------------------------------------------
# Evaluación con reglas
# ---------------------------------------------------------------------------


def _conversacion_de(chat):
    assignee = {"id": chat.get("agente_id"), "name": chat.get("agente_nombre")} if chat.get("agente_nombre") else {}
    return {"id": chat["conversation_id"], "status": chat.get("status"), "meta": {"assignee": assignee}}


def _registrar_error(store, chat):
    intentos = int(chat.get("intentos") or 0) + 1
    estado = "error" if intentos >= MAX_INTENTOS else "pendiente"
    store.actualizar_chat(chat["id"], {"estado": estado, "intentos": intentos})
    return estado


def _evaluar_uno(store, revision, chat, chatwoot, ahora):
    mensajes = chatwoot.mensajes_de_conversacion(chat["conversation_id"])
    csat = (revision.get("csat") or {}).get(str(int(chat["conversation_id"])))
    resultado = evaluar_chat(mensajes, _conversacion_de(chat), ahora, csat=csat)
    cambios = {
        "agente_id": resultado["agente_id"],
        "agente_nombre": resultado["agente_nombre"] or "",
        "resuelto": resultado["resuelto"],
        "status": chat.get("status"),
        "last_activity_at": chat.get("last_activity_at"),
        "reglas_version": REGLAS_VERSION,
    }
    if resultado["descartado"]:
        cambios.update(estado="descartado", motivo_descarte=resultado["descartado"], incidencias=[])
    else:
        cambios.update(estado="evaluado", incidencias=resultado["incidencias"])
    store.actualizar_chat(chat["id"], cambios)


def _paso_evaluacion(store, revision, chatwoot, ahora, reloj):
    inicio = reloj()
    evaluados, fallo = 0, None
    while reloj() - inicio < PRESUPUESTO_PASO:
        chat = store.tomar_siguiente(revision["id"], ("pendiente",), "procesando")
        if not chat:
            break
        try:
            _evaluar_uno(store, revision, chat, chatwoot, ahora)
        except Exception as exc:
            estado = _registrar_error(store, chat)
            fallo = f"No se pudo leer el chat #{chat['conversation_id']} ({estado}): {exc}"
            break
        evaluados += 1
    if fallo:
        return _respuesta(store, revision["id"], "error", fallo, esperar_segundos=2)
    if evaluados:
        return _respuesta(store, revision["id"], "evaluacion", f"{evaluados} chats evaluados en este paso.")
    return None


def _paso_ia(store, revision, config_ia, ahora):
    """Paso de IA (Task 5): revisa con IA los chats evaluados. Sin implementar: `ia_estado` queda en None."""
    return None


def _finalizar(store, review_id):
    chats = store.listar_chats(review_id)
    contadores = (store.obtener_revision(review_id) or {}).get("contadores") or {}
    con_errores = contadores.get("error_listado") or any(c.get("estado") == "error" for c in chats)
    estado = "con_errores" if con_errores else "completado"
    store.actualizar_revision(review_id, {"estado": estado, "contadores": dict(contadores, **_progreso(chats))})
    return _respuesta(store, review_id, "fin", "Revisión terminada.")


def ejecutar_paso(store, review_id, chatwoot, config_ia, ahora=None, reloj=time.monotonic):
    ahora = int(time.time()) if ahora is None else int(ahora)
    revision = store.obtener_revision(review_id)
    if not revision:
        raise IncidenciasError("La revisión no existe.")

    # 1. Chats que otra petición dejó a medias.
    chats = store.listar_chats(review_id)
    _recuperar_abandonados(store, chats)
    if revision.get("estado") in ESTADOS_TERMINALES and not any(
        c.get("estado") in ("pendiente", "procesando") for c in store.listar_chats(review_id)
    ):
        return _respuesta(store, review_id, "fin", "Revisión terminada.")

    # 2. CSAT, una sola vez por revisión.
    if revision.get("csat") is None:
        return _paso_csat(store, revision, chatwoot)

    # 3. Listado, una página por paso.
    if revision.get("estado") == "listando":
        return _paso_listado(store, revision, chatwoot)

    # 4. Evaluación con reglas hasta agotar el presupuesto del paso.
    respuesta = _paso_evaluacion(store, revision, chatwoot, ahora, reloj)
    if respuesta:
        return respuesta
    if any(c.get("estado") == "procesando" for c in store.listar_chats(review_id)):
        return _respuesta(store, review_id, "espera", "Hay un chat en proceso en otra pestaña.", esperar_segundos=5)

    # 5. IA (Task 5): único punto donde corre, entre la evaluación y el final.
    respuesta = _paso_ia(store, store.obtener_revision(review_id), config_ia, ahora)
    if respuesta:
        return respuesta

    # 6. Final.
    return _finalizar(store, review_id)


def reintentar_errores(store, review_id):
    vueltos = 0
    for chat in store.listar_chats(review_id):
        if chat.get("estado") == "error":
            store.actualizar_chat(chat["id"], {"estado": "pendiente", "intentos": 0})
            vueltos += 1
    if vueltos:
        store.actualizar_revision(review_id, {"estado": "evaluando"})
    return vueltos


# ---------------------------------------------------------------------------
# Listas para la pantalla y exportación
# ---------------------------------------------------------------------------


def _partir(evidencia, coincidencia):
    evidencia = evidencia or ""
    pos = evidencia.find(coincidencia) if coincidencia else -1
    if pos < 0 and coincidencia:
        pos = evidencia.lower().find(coincidencia.lower())
    if pos < 0:
        return evidencia, "", ""
    fin = pos + len(coincidencia)
    return evidencia[:pos], evidencia[pos:fin], evidencia[fin:]


def _filas_incidencias(chats, decisiones):
    for chat in chats:
        for incidencia in chat.get("incidencias") or []:
            antes, marca, despues = _partir(incidencia.get("evidencia"), incidencia.get("coincidencia"))
            yield {
                **incidencia,
                "conversation_id": chat.get("conversation_id"),
                "chat_id": chat.get("id"),
                "status": chat.get("status"),
                "ia_estado": chat.get("ia_estado"),
                "ia_motivo": (chat.get("ia_resultado") or {}).get("motivo", ""),
                "decision": decisiones.get(int(chat.get("conversation_id") or 0)),
                "antes": antes,
                "marca": marca,
                "despues": despues,
            }


def _orden_fila(fila):
    return (ORDEN_SEVERIDAD.get(fila.get("severidad"), 9), int(fila.get("ts") or 0))


def listas_revision(chats, decisiones, agente="", clave=""):
    todas = list(_filas_incidencias(chats, decisiones or {}))
    agentes = sorted({f.get("agente_nombre") for f in todas if f.get("agente_nombre")})
    claves = sorted({(f.get("clave"), f.get("etiqueta")) for f in todas if f.get("clave")})
    filtradas = sorted(
        (f for f in todas if (not agente or f.get("agente_nombre") == agente) and (not clave or f.get("clave") == clave)),
        key=_orden_fila,
    )
    return {
        "cliente": [f for f in filtradas if f.get("tipo") == "cliente"],
        "atencion": [f for f in filtradas if f.get("tipo") != "cliente"],
        "agentes": agentes,
        "claves": claves,
    }


def _celda_segura(valor):
    """Evita que una hoja de cálculo interprete un texto como fórmula (igual que auditoria_chats_motor)."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def _fecha_local(ts, tz):
    return datetime.fromtimestamp(int(ts), tz).strftime("%Y-%m-%d %H:%M") if ts else ""


def filas_csv(revision, chats, decisiones, url_conversacion):
    """Encabezado y una fila por incidencia."""
    tz = _obtener_timezone(_timezone())
    filas = [list(COLUMNAS_CSV)]
    for fila in sorted(_filas_incidencias(chats, decisiones or {}), key=_orden_fila):
        decision = fila["decision"] or {}
        cid = fila["conversation_id"]
        filas.append(
            [
                cid,
                url_conversacion(cid) if url_conversacion else "",
                _fecha_local(fila.get("ts"), tz),
                fila.get("agente_nombre") or "",
                TIPOS_VISIBLES.get(fila.get("tipo"), fila.get("tipo") or ""),
                fila.get("etiqueta") or "",
                fila.get("severidad") or "",
                fila.get("evidencia") or "",
                fila.get("ia_estado") or "",
                decision.get("decision") or "",
                decision.get("por") or "",
                decision.get("nota") or "",
            ]
        )
    return [filas[0]] + [[_celda_segura(valor) for valor in fila] for fila in filas[1:]]


# ---------------------------------------------------------------------------
# Revisión rápida en memoria
# ---------------------------------------------------------------------------


def revision_en_memoria(chatwoot, *, since, until, bandejas, maximo=30):
    """Revisión sin Supabase ni IA: lista hasta `maximo` chats, los evalúa y devuelve todo."""
    store = MemoriaIncidenciasStore()
    revision = crear_revision(store, since=since, until=until, bandejas=bandejas, usar_ia=False, creado_por="")
    review_id = revision["id"]
    vistos, parcial = 0, False
    for _ in range(MAX_PAGINAS_LISTADO + 10_000):
        revision = store.obtener_revision(review_id)
        if revision.get("estado") == "listando" and revision.get("csat") is not None:
            resultado = _listar_pagina(store, revision, chatwoot, maximo=maximo)
            vistos += resultado["vistos"]
            if not resultado["terminado"] and len(store.listar_chats(review_id)) >= maximo:
                # Parcial si se vieron chats en rango que quedaron fuera por el máximo.
                parcial = vistos > len(store.listar_chats(review_id))
                store.actualizar_revision(review_id, {"estado": "evaluando"})
            continue
        if ejecutar_paso(store, review_id, chatwoot, {})["accion"] == "fin":
            break
    return {
        "revision": store.obtener_revision(review_id),
        "chats": store.listar_chats(review_id),
        "parcial": parcial,
        "vistos": vistos,
    }
