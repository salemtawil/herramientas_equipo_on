"""Motor de lotes de la auditoría de chats: un paso por petición."""

import random
import unicodedata
from datetime import datetime, time, timedelta, timezone

from utils.auditoria_chats_pauta import (
    CRITERIOS,
    PAUTA_VERSION,
    construir_mensajes,
    requiere_revision,
    validar_resultado,
)
from utils import multiadmin_llamadas
from utils.auditoria_chats_manual import codigos_para, seleccionar_secciones, version_manual
from utils.auditoria_llamadas import (
    cambios_detalle,
    construir_mensajes_resumen_llamadas,
    emparejar,
    validar_resumen_llamadas,
)
from utils.auditoria_llamadas import normalizar_resumen as normalizar_llamada_resumen
from utils.multiadmin_llamadas import MultiadminLlamadasError
from utils.auditoria_chats_rubrica import FACTOR as FACTOR_RESULTADO
from utils.auditoria_chats_rubrica import (
    CRITERIOS_QA,
    ESTADOS_QA,
    ETIQUETAS_RESULTADOS,
    PAUTA_VERSION_QA,
    calcular_qa,
    construir_mensajes_clasificacion,
    construir_mensajes_evaluacion,
    requiere_revision_qa,
    resultados_criterios,
    validar_clasificacion,
    validar_evaluacion,
)
from utils.auditoria_chats_store import AuditoriaChatsError
from utils.auditoria_chats_transcripcion import (
    construir_transcripcion,
    construir_transcripcion_v2,
    es_llamada,
    forma_mensajes,
    ids_mensajes,
    metricas_tiempos,
    periodo_agente,
    tiene_mensajes_de_agente,
)
from utils.chatwoot_reportes import _obtener_timezone, _timezone
from utils.ia_chat import IAConfigError, IARateLimitError, IARespuestaError, completar_json

CHATS_POR_AGENTE_DEFAULT = 10
CHATS_POR_AGENTE_MAX = 20
MAX_PAGINAS_MUESTREO = 10
MAX_INTENTOS_IA = 2
SEGUNDOS_PROCESANDO_ABANDONADO = 120
PORCENTAJE_CONTROL = 0.10

ESTADOS_PENDIENTES = ("pendiente", "leido", "clasificado", "procesando")
ESTADOS_AUDITADOS = ("auditado", "revisado")


def es_lote_qa(lote):
    return (lote or {}).get("pauta_version") == PAUTA_VERSION_QA


# ---------------------------------------------------------------------------
# Rango y agentes
# ---------------------------------------------------------------------------


def rango_semana_anterior(hoy, tz_name):
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    lunes_anterior = lunes_actual - timedelta(days=7)
    return lunes_anterior, lunes_anterior + timedelta(days=6)


def _normalizar_nombre(nombre):
    texto = unicodedata.normalize("NFKD", str(nombre or "").strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split())


def resolver_agentes(alcance, detalle, agentes_chatwoot, turnos):
    turno_por_nombre = {}
    for nombre_turno, nombres in (turnos or {}).items():
        for nombre in nombres:
            turno_por_nombre.setdefault(_normalizar_nombre(nombre), nombre_turno)

    candidatos = []
    for agente in agentes_chatwoot or []:
        if agente.get("id") is None:
            continue
        nombre = agente.get("name") or agente.get("available_name") or agente.get("email") or f"Agente {agente['id']}"
        candidatos.append(
            {"id": int(agente["id"]), "nombre": nombre, "turno": turno_por_nombre.get(_normalizar_nombre(nombre))}
        )

    avisos = []
    if alcance == "turno":
        turno = (detalle or {}).get("turno")
        elegidos = [a for a in candidatos if a["turno"] == turno]
        nombres_cruzados = {_normalizar_nombre(a["nombre"]) for a in elegidos}
        avisos = [n for n in (turnos or {}).get(turno, []) if _normalizar_nombre(n) not in nombres_cruzados]
        return elegidos, avisos
    if alcance == "agentes":
        ids = {int(i) for i in (detalle or {}).get("agentes", []) if str(i).strip().isdigit()}
        return [a for a in candidatos if a["id"] in ids], avisos
    return candidatos, avisos


# ---------------------------------------------------------------------------
# Lotes
# ---------------------------------------------------------------------------


def _epoch(dia, hora, tz):
    return int(datetime.combine(dia, hora, tzinfo=tz).timestamp())


def crear_lote(store, *, since, until, alcance, detalle, chats_por_agente, agentes, config_ia, pauta_version=PAUTA_VERSION):
    tz = _obtener_timezone(_timezone())
    detalle = dict(detalle or {})
    if pauta_version == PAUTA_VERSION_QA:
        version = version_manual()
        if not store.indice_manual(version):
            raise AuditoriaChatsError(
                f"El manual de procedimientos (versión {version}) no está cargado. Cárgalo con "
                "scripts/cargar_manual_auditoria.py antes de crear lotes."
            )
        detalle["manual_version"] = version
    try:
        chats_por_agente = int(chats_por_agente)
    except (TypeError, ValueError):
        chats_por_agente = CHATS_POR_AGENTE_DEFAULT
    chats_por_agente = max(1, min(CHATS_POR_AGENTE_MAX, chats_por_agente))

    descripcion = {"todos": "Todos los agentes", "turno": f"Turno {detalle.get('turno', '')}".strip()}.get(
        alcance, f"{len(agentes)} agentes"
    )
    return store.crear_lote(
        {
            "etiqueta": f"{since:%d/%m} – {until:%d/%m/%Y} · {descripcion}",
            "since": _epoch(since, time(0, 0, 0), tz),
            "until": _epoch(until, time(23, 59, 59), tz),
            "alcance": alcance,
            "alcance_detalle": detalle,
            "chats_por_agente": chats_por_agente,
            "agentes": agentes,
            "agentes_muestreados": [],
            "reservas": {},
            "estado": "muestreando",
            "modelo": config_ia.get("model", ""),
            "pauta_version": pauta_version,
        }
    )


def _progreso(chats):
    vigentes = [c for c in chats if c.get("estado") != "descartado"]
    return {
        "total": len(vigentes),
        "auditados": sum(1 for c in vigentes if c.get("estado") in ESTADOS_AUDITADOS),
        "errores": sum(1 for c in vigentes if c.get("estado") == "error"),
        "pendientes": sum(1 for c in vigentes if c.get("estado") in ESTADOS_PENDIENTES),
    }


def _respuesta(store, lote_id, accion, mensaje="", esperar_segundos=0):
    lote = store.obtener_lote(lote_id) or {}
    return {
        "estado": lote.get("estado", ""),
        "accion": accion,
        "mensaje": mensaje,
        "esperar_segundos": int(esperar_segundos),
        "progreso": _progreso(store.listar_chats(lote_id)),
    }


def _recuperar_abandonados(store, chats):
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
            if chat.get("transcripcion_tmp") and (chat.get("detalle") or {}).get("clasificacion"):
                estado = "clasificado"
            else:
                estado = "leido" if chat.get("transcripcion_tmp") else "pendiente"
            store.actualizar_chat(chat["id"], {"estado": estado})


def _fila_chat(lote, agente, conversacion):
    created_at = int(conversacion.get("created_at") or 0)
    return {
        "batch_id": lote["id"],
        "conversation_id": int(conversacion["id"]),
        "agente_id": int(agente["id"]),
        "agente_nombre": agente.get("nombre", ""),
        "turno": agente.get("turno"),
        "conversacion_fecha": datetime.fromtimestamp(created_at, timezone.utc).isoformat() if created_at else None,
        "estado": "pendiente",
        "intentos": 0,
        "por_revisar": False,
        "detalle": {"bandeja_id": conversacion.get("inbox_id")},
    }


def _agente_ya_muestreado(store, lote_id, agente_id):
    actual = store.obtener_lote(lote_id) or {}
    if any(int(m["id"]) == int(agente_id) for m in actual.get("agentes_muestreados") or []):
        return True
    return any(int(c.get("agente_id") or 0) == int(agente_id) for c in store.listar_chats(lote_id))


def _muestrear_agente(store, lote, agente, chatwoot, rng):
    since, until = int(lote["since"]), int(lote["until"])
    bandejas = [int(b) for b in (lote.get("alcance_detalle") or {}).get("bandejas") or []]
    extra = {"inbox_ids": bandejas} if bandejas else {}

    def en_alcance(conversacion):
        if not since <= int(conversacion.get("created_at") or 0) <= until:
            return False
        bandeja = conversacion.get("inbox_id")
        return not bandejas or bandeja is None or int(bandeja) in bandejas

    conversaciones = []
    for pagina in range(1, MAX_PAGINAS_MUESTREO + 1):
        resultado = chatwoot.conversaciones_de_agente(agente["id"], since, until, page=pagina, **extra)
        if not resultado:
            break
        conversaciones.extend(c for c in resultado if en_alcance(c))

    # Otra pestaña pudo muestrear este agente mientras se listaban sus chats.
    if _agente_ya_muestreado(store, lote["id"], agente["id"]):
        return f"{agente.get('nombre')}: ya se eligieron sus chats en otra pestaña."

    por_id = {int(c["id"]): c for c in conversaciones if c.get("id") is not None}
    ya_auditadas = store.conversaciones_auditadas(list(por_id))
    disponibles = [por_id[cid] for cid in sorted(por_id) if cid not in ya_auditadas]
    rng.shuffle(disponibles)

    n = int(lote["chats_por_agente"])
    elegidas, reserva = disponibles[:n], disponibles[n:]
    store.insertar_chats([_fila_chat(lote, agente, c) for c in elegidas])

    actual = store.obtener_lote(lote["id"]) or lote
    reservas = dict(actual.get("reservas") or {})
    reservas[str(agente["id"])] = [
        {"id": int(c["id"]), "created_at": c.get("created_at"), "inbox_id": c.get("inbox_id")} for c in reserva
    ]
    muestreados = [m for m in actual.get("agentes_muestreados") or [] if int(m["id"]) != int(agente["id"])]
    muestreados.append({"id": agente["id"], "encontrados": len(disponibles), "elegidos": len(elegidas)})
    cambios = {"agentes_muestreados": muestreados, "reservas": reservas}
    if len(muestreados) >= len(lote.get("agentes") or []):
        cambios["estado"] = "auditando"
    store.actualizar_lote(lote["id"], cambios)
    return f"{agente.get('nombre')}: {len(elegidas)} chats elegidos de {len(disponibles)} disponibles."


def _reponer_desde_reserva(store, lote_id, chat):
    lote = store.obtener_lote(lote_id)
    reservas = dict(lote.get("reservas") or {})
    clave = str(chat["agente_id"])
    cola = list(reservas.get(clave) or [])
    agente = {"id": chat["agente_id"], "nombre": chat.get("agente_nombre"), "turno": chat.get("turno")}
    while cola:
        candidata = cola.pop(0)
        if store.insertar_chats([_fila_chat(lote, agente, candidata)]):
            break
    reservas[clave] = cola
    store.actualizar_lote(lote_id, {"reservas": reservas})


def _leer_chat(store, lote_id, chatwoot):
    chat = store.tomar_siguiente(lote_id, ("pendiente",), "procesando")
    if not chat:
        return None
    try:
        mensajes = chatwoot.mensajes_de_conversacion(chat["conversation_id"])
    except Exception as exc:
        store.actualizar_chat(chat["id"], {"estado": "pendiente"})
        return _respuesta(store, lote_id, "error", f"No se pudo leer el chat #{chat['conversation_id']}: {exc}")

    detalle = dict(chat.get("detalle") or {}, forma=forma_mensajes(mensajes))
    motivo = None
    if es_llamada(mensajes):
        motivo, texto = "llamada", "es una llamada"
    elif not tiene_mensajes_de_agente(mensajes):
        motivo, texto = "sin_respuesta_escrita", "sin respuesta escrita del agente"
    if motivo:
        detalle["motivo_descarte"] = motivo
        store.actualizar_chat(chat["id"], {"estado": "descartado", "transcripcion_tmp": None, "detalle": detalle})
        _reponer_desde_reserva(store, lote_id, chat)
        return _respuesta(store, lote_id, "lectura", f"Chat #{chat['conversation_id']} {texto}; se reemplaza.")

    if es_lote_qa(store.obtener_lote(lote_id)):
        periodo = periodo_agente(mensajes, chat.get("agente_id"), chat.get("agente_nombre"))
        detalle.update(
            periodo=periodo,
            metricas=metricas_tiempos(mensajes, periodo, chat.get("agente_id"), chat.get("agente_nombre") or ""),
            ids=sorted(ids_mensajes(mensajes)),
        )
        detalle.pop("clasificacion", None)
        transcripcion = construir_transcripcion_v2(mensajes, _timezone())
    else:
        transcripcion = construir_transcripcion(mensajes, _timezone())
    store.actualizar_chat(chat["id"], {"estado": "leido", "transcripcion_tmp": transcripcion, "detalle": detalle})
    return _respuesta(store, lote_id, "lectura", f"Chat #{chat['conversation_id']} leído.")


def _llamar_ia(mensajes, config_ia):
    """Llama al modelo principal y, si está saturado o sin cupo, al de respaldo.

    Devuelve (datos, modelo usado). Si todos fallan, solo se informa límite diario cuando
    todos lo agotaron; si alguno falló por algo temporal, se espera y se reintenta.
    Los errores de configuración no pasan al respaldo: hay que corregirlos.
    """
    modelos = [config_ia["model"]]
    respaldo = config_ia.get("model_respaldo")
    if respaldo and respaldo != config_ia["model"]:
        modelos.append(respaldo)

    errores = []
    for modelo in modelos:
        try:
            return completar_json(mensajes, dict(config_ia, model=modelo)), modelo
        except IARateLimitError as exc:
            errores.append(exc)
    temporales = [e for e in errores if not e.diario]
    raise temporales[0] if temporales else errores[0]


def _manejar_error_ia(store, lote_id, chat, exc, estado_previo):
    """Respuesta del paso cuando falla la IA; la fila vuelve a `estado_previo` salvo error final."""
    if isinstance(exc, IARateLimitError):
        store.actualizar_chat(chat["id"], {"estado": estado_previo})
        if exc.diario:
            store.actualizar_lote(lote_id, {"estado": "limite_diario"})
            return _respuesta(store, lote_id, "auditoria", str(exc))
        return _respuesta(store, lote_id, "espera", str(exc), esperar_segundos=exc.esperar_segundos)
    if isinstance(exc, IAConfigError):
        store.actualizar_chat(chat["id"], {"estado": estado_previo})
        return _respuesta(store, lote_id, "configuracion", str(exc))

    intentos = int(chat.get("intentos") or 0) + 1
    if intentos < MAX_INTENTOS_IA:
        store.actualizar_chat(chat["id"], {"estado": estado_previo, "intentos": intentos, "ia_error": str(exc)})
        return _respuesta(store, lote_id, "auditoria", f"Chat #{chat['conversation_id']}: se reintenta ({exc}).")
    store.actualizar_chat(
        chat["id"],
        {
            "estado": "error",
            "intentos": intentos,
            "ia_error": str(exc),
            "transcripcion_tmp": None,
            "por_revisar": True,
            "motivo_revision": "marcado",
        },
    )
    return _respuesta(store, lote_id, "auditoria", f"Chat #{chat['conversation_id']}: error de IA ({exc}).")


ERRORES_IA = (IARateLimitError, IAConfigError, ValueError, IARespuestaError)


def _clasificar_chat(store, lote, config_ia):
    chat = store.tomar_siguiente(lote["id"], ("leido",), "procesando")
    if not chat:
        return None
    version = (lote.get("alcance_detalle") or {}).get("manual_version") or version_manual()
    try:
        indice = store.indice_manual(version)
        data, modelo = _llamar_ia(construir_mensajes_clasificacion(chat.get("transcripcion_tmp") or "", indice), config_ia)
        clasificacion = validar_clasificacion(data, {s["codigo"] for s in indice})
        clasificacion["modelo"] = modelo
    except ERRORES_IA as exc:
        return _manejar_error_ia(store, lote["id"], chat, exc, "leido")

    detalle = dict(chat.get("detalle") or {}, clasificacion=clasificacion)
    store.actualizar_chat(chat["id"], {"estado": "clasificado", "detalle": detalle, "intentos": 0, "ia_error": None})
    return _respuesta(store, lote["id"], "auditoria", f"Chat #{chat['conversation_id']}: motivo identificado.")


def _evaluar_chat_qa(store, lote, config_ia):
    chat = store.tomar_siguiente(lote["id"], ("clasificado",), "procesando")
    if not chat:
        return None
    alcance = lote.get("alcance_detalle") or {}
    version = alcance.get("manual_version") or version_manual()
    detalle = chat.get("detalle") or {}
    clasificacion = detalle.get("clasificacion") or {}
    try:
        indice = store.indice_manual(version)
        generales, procedimientos, extra = codigos_para(clasificacion, [s["codigo"] for s in indice])
        secciones = seleccionar_secciones(
            clasificacion, store.secciones_manual(version, generales + procedimientos + extra)
        )
        canal = (alcance.get("bandejas_nombres") or {}).get(str(detalle.get("bandeja_id")), "")
        mensajes = construir_mensajes_evaluacion(
            transcripcion=chat.get("transcripcion_tmp") or "",
            agente_nombre=chat.get("agente_nombre"),
            canal=canal,
            clasificacion={k: v for k, v in clasificacion.items() if k != "modelo"},
            secciones=secciones,
            metricas=detalle.get("metricas") or {},
            periodo=detalle.get("periodo") or {},
        )
        data, modelo = _llamar_ia(mensajes, config_ia)
        resultado = validar_evaluacion(data, set(detalle.get("ids") or []))
    except ERRORES_IA as exc:
        return _manejar_error_ia(store, lote["id"], chat, exc, "clasificado")

    resultado.update(calcular_qa(resultados_criterios(resultado), 0, len(resultado["fallas_criticas"])))
    resultado.update(modelo=modelo, pauta_version=PAUTA_VERSION_QA, secciones=[s["codigo"] for s in secciones])
    marcado = requiere_revision_qa(resultado, hubo_error=False)
    store.actualizar_chat(
        chat["id"],
        {
            "estado": "auditado",
            "ia_resultado": resultado,
            "ia_qa": resultado["qa"],
            "ia_estado": resultado["estado"],
            "ia_nota": None,
            "ia_satisfaccion": resultado["satisfaccion_cliente"],
            "ia_error": None,
            "transcripcion_tmp": None,
            "por_revisar": marcado,
            "motivo_revision": "marcado" if marcado else None,
        },
    )
    return _respuesta(store, lote["id"], "auditoria", f"Chat #{chat['conversation_id']} auditado.")


def _auditar_chat(store, lote_id, config_ia):
    chat = store.tomar_siguiente(lote_id, ("leido",), "procesando")
    if not chat:
        return None
    try:
        data, modelo = _llamar_ia(
            construir_mensajes(chat.get("transcripcion_tmp") or "", chat.get("agente_nombre")), config_ia
        )
        resultado = validar_resultado(data)
        resultado["modelo"] = modelo
    except ERRORES_IA as exc:
        return _manejar_error_ia(store, lote_id, chat, exc, "leido")

    marcado = requiere_revision(resultado, hubo_error=False)
    store.actualizar_chat(
        chat["id"],
        {
            "estado": "auditado",
            "ia_resultado": resultado,
            "ia_nota": resultado["nota_global"],
            "ia_satisfaccion": resultado["satisfaccion_cliente"],
            "ia_error": None,
            "transcripcion_tmp": None,
            "por_revisar": marcado,
            "motivo_revision": "marcado" if marcado else None,
        },
    )
    return _respuesta(store, lote_id, "auditoria", f"Chat #{chat['conversation_id']} auditado.")


def _finalizar(store, lote_id, chats, rng):
    ya_hay_control = any(c.get("motivo_revision") == "control" for c in chats)
    sin_marcar = [c for c in chats if c.get("estado") == "auditado" and not c.get("por_revisar")]
    if sin_marcar and not ya_hay_control:
        cantidad = max(1, round(len(sin_marcar) * PORCENTAJE_CONTROL))
        for chat in rng.sample(sin_marcar, cantidad):
            store.actualizar_chat(chat["id"], {"por_revisar": True, "motivo_revision": "control"})
    hay_errores = any(c.get("estado") == "error" for c in chats)
    store.actualizar_lote(lote_id, {"estado": "con_errores" if hay_errores else "completado"})
    return _respuesta(store, lote_id, "fin", "Lote terminado.")


# ---------------------------------------------------------------------------
# Llamadas de Multiadmin (solo lotes QA-1.1)
# ---------------------------------------------------------------------------

LLAMADAS_TERMINADAS = ("listo", "error")
DETALLES_POR_PASO = 15
SEGUNDOS_DIA = 86400


def llamadas_pendientes(lote):
    return es_lote_qa(lote) and (lote.get("llamadas_estado") or "pendiente") not in LLAMADAS_TERMINADAS


def _dias_lote(lote):
    inicio, fin = int(lote["since"]), int(lote["until"])
    return [(d, min(d + SEGUNDOS_DIA - 1, fin)) for d in range(inicio, fin + 1, SEGUNDOS_DIA)]


def _error_llamadas(store, lote_id, exc):
    store.actualizar_lote(lote_id, {"llamadas_estado": "error", "llamadas_error": str(exc)})
    return _respuesta(store, lote_id, "llamadas", f"No se pudieron traer las llamadas: {exc}")


def _traer_dia(store, lote, multiadmin):
    progreso = dict(lote.get("llamadas_progreso") or {})
    dias = _dias_lote(lote)
    dia = int(progreso.get("dia") or 0)
    if dia >= len(dias):
        store.actualizar_lote(lote["id"], {"llamadas_estado": "detallando"})
        return _respuesta(store, lote["id"], "llamadas", "Llamadas del rango listas; leyendo su detalle.")

    desde, hasta = dias[dia]
    items = multiadmin.listar_llamadas(desde * 1000, hasta * 1000 + 999)
    guardados = {n: v.get("chatwoot_agente_id") for n, v in store.emparejamientos().items()}
    nombres = {str(i.get("agentNumber") or "").strip() for i in items} - {""}
    mapa = emparejar(lote.get("agentes") or [], nombres, guardados)

    filas, sin_emparejar = [], dict(lote.get("llamadas_sin_emparejar") or {})
    for item in items:
        nombre = str(item.get("agentNumber") or "").strip()
        if nombre in mapa:
            filas.append(dict(normalizar_llamada_resumen(item), agente_id=mapa[nombre]))
        elif nombre and guardados.get(nombre) is None:
            sin_emparejar[nombre] = int(sin_emparejar.get(nombre) or 0) + 1
    store.guardar_llamadas(lote["id"], filas)
    progreso["dia"] = dia + 1
    store.actualizar_lote(
        lote["id"],
        {"llamadas_estado": "trayendo", "llamadas_progreso": progreso, "llamadas_sin_emparejar": sin_emparejar},
    )
    return _respuesta(store, lote["id"], "llamadas", f"Llamadas del día {dia + 1} de {len(dias)}: {len(filas)} de los agentes del lote.")


def _detallar(store, lote, multiadmin):
    pendientes = store.listar_llamadas(lote["id"], solo_sin_detalle=True)
    if not pendientes:
        store.actualizar_lote(lote["id"], {"llamadas_estado": "resumiendo"})
        return _respuesta(store, lote["id"], "llamadas", "Detalle de llamadas completo.")
    tanda = pendientes[:DETALLES_POR_PASO]
    for llamada in tanda:
        detalle = multiadmin.detalle_llamada(llamada["linea"], llamada["record_key"])
        store.actualizar_llamada(llamada["id"], cambios_detalle(detalle))
    return _respuesta(store, lote["id"], "llamadas", f"Detalle de {len(tanda)} llamadas ({len(pendientes) - len(tanda)} por leer).")


def _resumir_agente(store, lote, config_ia):
    feedback = dict(lote.get("feedback_llamadas") or {})
    llamadas = store.listar_llamadas(lote["id"])
    nombres = {int(a["id"]): a.get("nombre", "") for a in lote.get("agentes") or []}
    por_agente = {}
    for llamada in llamadas:
        por_agente.setdefault(int(llamada["agente_id"]), []).append(llamada)
    pendientes = [a for a in por_agente if str(a) not in feedback]
    if not pendientes or not config_ia.get("activa"):
        store.actualizar_lote(lote["id"], {"llamadas_estado": "listo"})
        return None

    agente_id = pendientes[0]
    propias = por_agente[agente_id]
    progreso = dict(lote.get("llamadas_progreso") or {})
    intentos = dict(progreso.get("intentos") or {})
    try:
        data, modelo = _llamar_ia(construir_mensajes_resumen_llamadas(nombres.get(agente_id, ""), propias), config_ia)
        resumen = validar_resumen_llamadas(data, {l["ticket_id"] for l in propias if l.get("ticket_id") is not None})
        resumen["modelo"] = modelo
    except IARateLimitError as exc:
        if exc.diario:
            store.actualizar_lote(lote["id"], {"estado": "limite_diario"})
            return _respuesta(store, lote["id"], "auditoria", str(exc))
        return _respuesta(store, lote["id"], "espera", str(exc), esperar_segundos=exc.esperar_segundos)
    except IAConfigError as exc:
        return _respuesta(store, lote["id"], "configuracion", str(exc))
    except (ValueError, IARespuestaError) as exc:
        intentos[str(agente_id)] = int(intentos.get(str(agente_id)) or 0) + 1
        if intentos[str(agente_id)] < MAX_INTENTOS_IA:
            progreso["intentos"] = intentos
            store.actualizar_lote(lote["id"], {"llamadas_progreso": progreso})
            return _respuesta(store, lote["id"], "auditoria", f"Resumen de llamadas: se reintenta ({exc}).")
        resumen = {"error": str(exc)}

    feedback[str(agente_id)] = resumen
    store.actualizar_lote(lote["id"], {"feedback_llamadas": feedback})
    return _respuesta(store, lote["id"], "auditoria", f"Resumen de llamadas de {nombres.get(agente_id, agente_id)} listo.")


def _paso_llamadas(store, lote, multiadmin, config_ia, chats_pendientes):
    """Un paso de llamadas o None si no hay nada que hacer ahora (los chats van primero en el resumen)."""
    estado = lote.get("llamadas_estado") or "pendiente"
    try:
        if estado in ("pendiente", "trayendo"):
            return _traer_dia(store, lote, multiadmin)
        if estado == "detallando":
            return _detallar(store, lote, multiadmin)
    except MultiadminLlamadasError as exc:
        return _error_llamadas(store, lote["id"], exc)
    if estado == "resumiendo" and not chats_pendientes:
        return _resumir_agente(store, lote, config_ia)
    return None


def reiniciar_llamadas(store, lote_id, agente_id=None):
    """Vuelve a traer las llamadas (todas o las de un agente) y rehace el resumen afectado."""
    lote = store.obtener_lote(lote_id) or {}
    store.borrar_llamadas(lote_id, agente_id)
    feedback = dict(lote.get("feedback_llamadas") or {})
    if agente_id is None:
        feedback = {}
    else:
        feedback.pop(str(agente_id), None)
    store.actualizar_lote(
        lote_id,
        {
            "llamadas_estado": "pendiente",
            "llamadas_progreso": None,
            "llamadas_error": None,
            "llamadas_sin_emparejar": {},
            "feedback_llamadas": feedback,
        },
    )


def ejecutar_paso(store, lote_id, chatwoot, config_ia, rng=None, multiadmin=None):
    rng = rng or random.Random()
    multiadmin = multiadmin or multiadmin_llamadas
    lote = store.obtener_lote(lote_id)
    if not lote:
        raise AuditoriaChatsError("El lote no existe.")
    if lote.get("estado") in ("completado", "con_errores") and not any(
        c.get("estado") in ESTADOS_PENDIENTES for c in store.listar_chats(lote_id)
    ):
        if llamadas_pendientes(lote):
            respuesta = _paso_llamadas(store, lote, multiadmin, config_ia, chats_pendientes=False)
            if respuesta:
                return respuesta
        return _respuesta(store, lote_id, "fin", "Lote terminado.")
    if lote.get("estado") == "limite_diario":
        store.actualizar_lote(lote_id, {"estado": "auditando"})
        lote = store.obtener_lote(lote_id)

    _recuperar_abandonados(store, store.listar_chats(lote_id))

    muestreados = {int(m["id"]) for m in lote.get("agentes_muestreados") or []}
    pendientes_muestreo = [a for a in lote.get("agentes") or [] if int(a["id"]) not in muestreados]
    if pendientes_muestreo:
        try:
            mensaje = _muestrear_agente(store, lote, pendientes_muestreo[0], chatwoot, rng)
        except Exception as exc:
            return _respuesta(store, lote_id, "error", f"No se pudieron listar los chats de {pendientes_muestreo[0].get('nombre')}: {exc}")
        return _respuesta(store, lote_id, "muestreo", mensaje)

    if lote.get("estado") == "muestreando":
        store.actualizar_lote(lote_id, {"estado": "auditando"})

    if es_lote_qa(lote) and (lote.get("llamadas_estado") or "pendiente") in ("pendiente", "trayendo", "detallando"):
        respuesta = _paso_llamadas(store, lote, multiadmin, config_ia, chats_pendientes=True)
        if respuesta:
            return respuesta

    if config_ia.get("activa"):
        # Otra pestaña puede llevarse el último chat leído: entonces se sigue con la lectura.
        # En la pauta QA cada paso hace como mucho una llamada: evaluar o, si no hay, clasificar.
        if es_lote_qa(lote):
            respuesta = _evaluar_chat_qa(store, lote, config_ia) or _clasificar_chat(store, lote, config_ia)
        else:
            respuesta = _auditar_chat(store, lote_id, config_ia)
        if respuesta:
            return respuesta

    respuesta = _leer_chat(store, lote_id, chatwoot)
    if respuesta:
        return respuesta

    chats = store.listar_chats(lote_id)
    if any(c.get("estado") == "procesando" for c in chats):
        return _respuesta(store, lote_id, "espera", "Hay un chat en proceso en otra pestaña.", esperar_segundos=5)
    if any(c.get("estado") in ("leido", "clasificado") for c in chats):
        return _respuesta(
            store, lote_id, "configuracion", "Configura AUDITORIA_CHATS_AI_API_KEY para auditar los chats leídos."
        )
    if llamadas_pendientes(lote):
        respuesta = _paso_llamadas(store, store.obtener_lote(lote_id), multiadmin, config_ia, chats_pendientes=False)
        if respuesta:
            return respuesta
    return _finalizar(store, lote_id, chats, rng)


# ---------------------------------------------------------------------------
# Resúmenes y exportación
# ---------------------------------------------------------------------------


def nota_efectiva(chat):
    if chat.get("nota_final") is not None:
        return chat["nota_final"]
    return chat.get("ia_nota")


def qa_efectivo(chat):
    """QA del revisor si existe; si no, el de la IA (pauta QA-1.1)."""
    valor = chat.get("qa_final") if chat.get("qa_final") is not None else chat.get("ia_qa")
    return float(valor) if valor is not None else None


def estado_efectivo(chat):
    return chat.get("estado_final") or chat.get("ia_estado")


def criterios_efectivos(chat):
    """Resultado por criterio con las correcciones del revisor aplicadas."""
    criterios = resultados_criterios(chat.get("ia_resultado"))
    criterios.update((chat.get("revision") or {}).get("criterios") or {})
    return criterios


def _conteo_estados(grupo):
    conteo = {clave: 0 for clave in ESTADOS_QA}
    for chat in grupo:
        estado = estado_efectivo(chat)
        if estado in conteo and chat.get("estado") in ESTADOS_AUDITADOS:
            conteo[estado] += 1
    return conteo


def _satisfaccion_efectiva(chat):
    return chat.get("satisfaccion_final") or chat.get("ia_satisfaccion")


def _media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None


def _porcentaje(parte, total):
    return round(parte * 100 / total, 1) if total else 0.0


def resumen_por_agente(chats):
    grupos = {}
    for chat in chats:
        if chat.get("estado") == "descartado":
            continue
        grupos.setdefault(chat.get("agente_id"), []).append(chat)

    filas = []
    for agente_id, grupo in grupos.items():
        satisfacciones = [s for s in (_satisfaccion_efectiva(c) for c in grupo) if s]
        filas.append(
            {
                "agente_id": agente_id,
                "agente_nombre": grupo[0].get("agente_nombre", ""),
                "chats": len(grupo),
                "nota_ia_media": _media(c.get("ia_nota") for c in grupo),
                "nota_efectiva_media": _media(nota_efectiva(c) for c in grupo),
                "pct_satisfechos": _porcentaje(sum(1 for s in satisfacciones if s == "satisfecho"), len(satisfacciones)),
                "por_revisar": sum(1 for c in grupo if c.get("por_revisar") and c.get("estado") != "revisado"),
                "revisados": sum(1 for c in grupo if c.get("estado") == "revisado"),
                "errores": sum(1 for c in grupo if c.get("estado") == "error"),
                "qa_media": _media(qa_efectivo(c) for c in grupo),
                "estados": _conteo_estados(grupo),
            }
        )
    return sorted(filas, key=lambda f: _normalizar_nombre(f["agente_nombre"]))


VALORACIONES = {"buena": "Buena atención", "regular": "Atención regular", "mala": "Mala atención"}
MAX_CRITERIOS_FEEDBACK = 3
MAX_TEXTOS_FEEDBACK = 8


def valoracion(chat):
    """Veredicto simple de la atención según la nota efectiva: 4-5 buena, 3 regular, 1-2 mala."""
    nota = nota_efectiva(chat)
    if nota is None:
        return None
    if nota >= 4:
        return "buena"
    return "regular" if nota == 3 else "mala"


def _textos_unicos(listas, maximo=MAX_TEXTOS_FEEDBACK):
    vistos, salida = set(), []
    for lista in listas:
        for texto in lista or []:
            texto = " ".join(str(texto or "").split())
            clave = texto.lower()
            if texto and clave not in vistos:
                vistos.add(clave)
                salida.append(texto)
    return salida[:maximo]


def feedback_por_agente(chats):
    """Puntos fuertes, áreas de mejora y comentarios de cada agente para darle feedback."""
    grupos = {}
    for chat in chats:
        if chat.get("estado") in ESTADOS_AUDITADOS and nota_efectiva(chat) is not None:
            grupos.setdefault(chat.get("agente_id"), []).append(chat)

    filas = []
    for agente_id, grupo in grupos.items():
        resultados = [c.get("ia_resultado") or {} for c in grupo]
        criterios = []
        for clave, etiqueta in CRITERIOS:
            media = _media((r.get("criterios") or {}).get(clave) for r in resultados)
            if media is not None:
                criterios.append({"clave": clave, "etiqueta": etiqueta, "media": media})
        valoraciones = {clave: 0 for clave in VALORACIONES}
        for chat in grupo:
            valoraciones[valoracion(chat)] += 1
        filas.append(
            {
                "agente_id": agente_id,
                "agente_nombre": grupo[0].get("agente_nombre", ""),
                "auditados": len(grupo),
                "nota_media": _media(nota_efectiva(c) for c in grupo),
                "valoraciones": valoraciones,
                "puntos_fuertes": sorted(
                    (c for c in criterios if c["media"] >= 4), key=lambda c: -c["media"]
                )[:MAX_CRITERIOS_FEEDBACK],
                "areas_mejora": sorted(
                    (c for c in criterios if c["media"] < 4), key=lambda c: c["media"]
                )[:MAX_CRITERIOS_FEEDBACK],
                "fortalezas": _textos_unicos(r.get("fortalezas") for r in resultados),
                "mejoras": _textos_unicos(r.get("mejoras") for r in resultados),
                "comentarios": _textos_unicos([c.get("comentario_revisor")] for c in grupo),
            }
        )
    return sorted(filas, key=lambda f: _normalizar_nombre(f["agente_nombre"]))


CORTE_PUNTO_FUERTE = 80
RESULTADOS_A_MEJORAR = ("no_cumple", "parcial")


def _ref_chat(chat):
    return {"id": chat.get("id"), "conversation_id": chat.get("conversation_id")}


def _textos_con_chats(grupo, clave, maximo=MAX_TEXTOS_FEEDBACK):
    """Textos de la IA sin duplicados (sin distinguir mayúsculas), con los chats donde aparecen."""
    por_clave = {}
    for chat in grupo:
        for texto in (chat.get("ia_resultado") or {}).get(clave) or []:
            texto = " ".join(str(texto or "").split())
            if not texto:
                continue
            item = por_clave.setdefault(texto.lower(), {"texto": texto, "chats": []})
            if _ref_chat(chat) not in item["chats"]:
                item["chats"].append(_ref_chat(chat))
    return list(por_clave.values())[:maximo]


def feedback_por_agente_qa(chats):
    """Feedback por agente con la rúbrica QA-1.1: % de cumplimiento por criterio sobre lo verificable."""
    grupos = {}
    for chat in chats:
        if chat.get("estado") in ESTADOS_AUDITADOS and (chat.get("ia_resultado") or {}).get("criterios"):
            grupos.setdefault(chat.get("agente_id"), []).append(chat)

    filas = []
    for agente_id, grupo in grupos.items():
        por_chat = [criterios_efectivos(c) for c in grupo]
        criterios = []
        for codigo, etiqueta, _ in CRITERIOS_QA:
            valores = [FACTOR_RESULTADO[r[codigo]] for r in por_chat if r.get(codigo) in FACTOR_RESULTADO]
            if valores:
                criterios.append(
                    {
                        "codigo": codigo,
                        "etiqueta": etiqueta,
                        "pct": round(sum(valores) * 100 / len(valores), 1),
                        "chats": [
                            _ref_chat(chat)
                            for chat, r in zip(grupo, por_chat)
                            if r.get(codigo) in RESULTADOS_A_MEJORAR
                        ],
                    }
                )
        fallas_confirmadas = sum(
            1 for c in grupo for v in ((c.get("revision") or {}).get("fallas") or {}).values() if v == "confirmada"
        )
        filas.append(
            {
                "agente_id": agente_id,
                "agente_nombre": grupo[0].get("agente_nombre", ""),
                "auditados": len(grupo),
                "qa_media": _media(qa_efectivo(c) for c in grupo),
                "estados": _conteo_estados(grupo),
                "fallas_confirmadas": fallas_confirmadas,
                "puntos_fuertes": sorted(
                    (c for c in criterios if c["pct"] >= CORTE_PUNTO_FUERTE), key=lambda c: -c["pct"]
                )[:MAX_CRITERIOS_FEEDBACK],
                "areas_mejora": sorted(
                    (c for c in criterios if c["pct"] < CORTE_PUNTO_FUERTE), key=lambda c: c["pct"]
                )[:MAX_CRITERIOS_FEEDBACK],
                "cumplimientos": _textos_con_chats(grupo, "cumplimientos"),
                "incumplimientos": _textos_con_chats(grupo, "incumplimientos"),
                "recomendaciones": _textos_con_chats(grupo, "recomendaciones"),
                "comentarios": _textos_unicos([c.get("comentario_revisor")] for c in grupo),
            }
        )
    return sorted(filas, key=lambda f: _normalizar_nombre(f["agente_nombre"]))


def _lunes_local(fecha_iso, tz):
    fecha = datetime.fromisoformat(str(fecha_iso)).astimezone(tz).date()
    return fecha - timedelta(days=fecha.weekday())


def historial_semanal(chats, tz_name):
    tz = _obtener_timezone(tz_name)
    grupos = {}
    for chat in chats:
        if chat.get("estado") not in ESTADOS_AUDITADOS or (nota_efectiva(chat) is None and qa_efectivo(chat) is None):
            continue
        if not chat.get("conversacion_fecha"):
            continue
        clave = (chat.get("agente_id"), _lunes_local(chat["conversacion_fecha"], tz))
        grupos.setdefault(clave, []).append(chat)

    filas = []
    for (agente_id, lunes), grupo in grupos.items():
        filas.append(
            {
                "agente_id": agente_id,
                "agente_nombre": grupo[0].get("agente_nombre", ""),
                "semana": lunes.isoformat(),
                "chats": len(grupo),
                "nota_efectiva_media": _media(nota_efectiva(c) for c in grupo),
                "pct_revisado": _porcentaje(sum(1 for c in grupo if c.get("estado") == "revisado"), len(grupo)),
                "qa_media": _media(qa_efectivo(c) for c in grupo),
            }
        )
    return sorted(filas, key=lambda f: (_normalizar_nombre(f["agente_nombre"]), f["semana"]))


def _celda_segura(valor):
    """Evita que una hoja de cálculo interprete un texto como fórmula."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def _texto_fallas(chat):
    resultado = chat.get("ia_resultado") or {}
    revisadas = (chat.get("revision") or {}).get("fallas") or {}
    return ", ".join(
        f"{f['codigo']} ({revisadas.get(f['codigo'], f.get('estado', 'sospechosa'))})"
        for f in resultado.get("fallas_criticas") or []
    )


def _filas_csv_qa(chats, url_conversacion=None):
    columnas = [
        "Conversación", "Enlace", "Agente", "Turno", "Fecha", "Estado", "Motivo", "Procedimientos",
        "QA IA", "% verificable", "Estado IA", "QA final", "Estado final",
        *[f"{codigo} {etiqueta}" for codigo, etiqueta, _ in CRITERIOS_QA],
        "Fallas críticas", "Resolución", "Satisfacción IA", "Satisfacción final", "Revisor", "Comentario", "Resumen IA",
    ]

    def vacio_si_none(valor):
        return "" if valor is None else valor

    filas = []
    for chat in chats:
        if chat.get("estado") == "descartado":
            continue
        resultado = chat.get("ia_resultado") or {}
        clasificacion = (chat.get("detalle") or {}).get("clasificacion") or {}
        criterios = criterios_efectivos(chat)
        filas.append(
            [
                chat.get("conversation_id"),
                url_conversacion(chat["conversation_id"]) if url_conversacion else "",
                chat.get("agente_nombre", ""),
                chat.get("turno") or "",
                chat.get("conversacion_fecha") or "",
                chat.get("estado", ""),
                clasificacion.get("motivo_principal", ""),
                ", ".join(clasificacion.get("procedimientos") or []),
                vacio_si_none(chat.get("ia_qa")),
                vacio_si_none(resultado.get("pct_verificable")),
                ESTADOS_QA.get(chat.get("ia_estado"), ""),
                vacio_si_none(chat.get("qa_final")),
                ESTADOS_QA.get(chat.get("estado_final"), ""),
                *[ETIQUETAS_RESULTADOS.get(criterios.get(codigo), "") for codigo, _, _ in CRITERIOS_QA],
                _texto_fallas(chat),
                resultado.get("estado_resolucion", ""),
                chat.get("ia_satisfaccion") or "",
                chat.get("satisfaccion_final") or "",
                chat.get("revisor") or "",
                chat.get("comentario_revisor") or "",
                resultado.get("resumen", ""),
            ]
        )
    return columnas, [[_celda_segura(valor) for valor in fila] for fila in filas]


def filas_csv(lote, chats, url_conversacion=None):
    if es_lote_qa(lote):
        return _filas_csv_qa(chats, url_conversacion)
    columnas = [
        "Conversación", "Enlace", "Agente", "Turno", "Fecha", "Estado",
        "Nota IA", "Satisfacción IA", "Resuelto",
        *[etiqueta for _, etiqueta in CRITERIOS],
        "Nota final", "Satisfacción final", "Revisor", "Comentario", "Resumen IA",
    ]
    filas = []
    for chat in chats:
        if chat.get("estado") == "descartado":
            continue
        resultado = chat.get("ia_resultado") or {}
        criterios = resultado.get("criterios") or {}
        filas.append(
            [
                chat.get("conversation_id"),
                url_conversacion(chat["conversation_id"]) if url_conversacion else "",
                chat.get("agente_nombre", ""),
                chat.get("turno") or "",
                chat.get("conversacion_fecha") or "",
                chat.get("estado", ""),
                chat.get("ia_nota") if chat.get("ia_nota") is not None else "",
                chat.get("ia_satisfaccion") or "",
                resultado.get("resuelto", ""),
                *[criterios.get(clave, "") for clave, _ in CRITERIOS],
                chat.get("nota_final") if chat.get("nota_final") is not None else "",
                chat.get("satisfaccion_final") or "",
                chat.get("revisor") or "",
                chat.get("comentario_revisor") or "",
                resultado.get("resumen", ""),
            ]
        )
    return columnas, [[_celda_segura(valor) for valor in fila] for fila in filas]
