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
from utils.auditoria_chats_store import AuditoriaChatsError
from utils.auditoria_chats_transcripcion import (
    construir_transcripcion,
    es_llamada,
    forma_mensajes,
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

ESTADOS_PENDIENTES = ("pendiente", "leido", "procesando")
ESTADOS_AUDITADOS = ("auditado", "revisado")


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


def crear_lote(store, *, since, until, alcance, detalle, chats_por_agente, agentes, config_ia):
    tz = _obtener_timezone(_timezone())
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
            "alcance_detalle": detalle or {},
            "chats_por_agente": chats_por_agente,
            "agentes": agentes,
            "agentes_muestreados": [],
            "reservas": {},
            "estado": "muestreando",
            "modelo": config_ia.get("model", ""),
            "pauta_version": PAUTA_VERSION,
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
            store.actualizar_chat(chat["id"], {"estado": "leido" if chat.get("transcripcion_tmp") else "pendiente"})


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

    store.actualizar_chat(
        chat["id"],
        {"estado": "leido", "transcripcion_tmp": construir_transcripcion(mensajes, _timezone()), "detalle": detalle},
    )
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
    except IARateLimitError as exc:
        store.actualizar_chat(chat["id"], {"estado": "leido"})
        if exc.diario:
            store.actualizar_lote(lote_id, {"estado": "limite_diario"})
            return _respuesta(store, lote_id, "auditoria", str(exc))
        return _respuesta(store, lote_id, "espera", str(exc), esperar_segundos=exc.esperar_segundos)
    except IAConfigError as exc:
        store.actualizar_chat(chat["id"], {"estado": "leido"})
        return _respuesta(store, lote_id, "configuracion", str(exc))
    except (ValueError, IARespuestaError) as exc:
        intentos = int(chat.get("intentos") or 0) + 1
        if intentos < MAX_INTENTOS_IA:
            store.actualizar_chat(chat["id"], {"estado": "leido", "intentos": intentos, "ia_error": str(exc)})
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


def ejecutar_paso(store, lote_id, chatwoot, config_ia, rng=None):
    rng = rng or random.Random()
    lote = store.obtener_lote(lote_id)
    if not lote:
        raise AuditoriaChatsError("El lote no existe.")
    if lote.get("estado") in ("completado", "con_errores") and not any(
        c.get("estado") in ESTADOS_PENDIENTES for c in store.listar_chats(lote_id)
    ):
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

    if config_ia.get("activa"):
        # Otra pestaña puede llevarse el último chat leído: entonces se sigue con la lectura.
        respuesta = _auditar_chat(store, lote_id, config_ia)
        if respuesta:
            return respuesta

    respuesta = _leer_chat(store, lote_id, chatwoot)
    if respuesta:
        return respuesta

    chats = store.listar_chats(lote_id)
    if any(c.get("estado") == "procesando" for c in chats):
        return _respuesta(store, lote_id, "espera", "Hay un chat en proceso en otra pestaña.", esperar_segundos=5)
    if any(c.get("estado") == "leido" for c in chats):
        return _respuesta(
            store, lote_id, "configuracion", "Configura AUDITORIA_CHATS_AI_API_KEY para auditar los chats leídos."
        )
    return _finalizar(store, lote_id, chats, rng)


# ---------------------------------------------------------------------------
# Resúmenes y exportación
# ---------------------------------------------------------------------------


def nota_efectiva(chat):
    if chat.get("nota_final") is not None:
        return chat["nota_final"]
    return chat.get("ia_nota")


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
        if chat.get("estado") not in ESTADOS_AUDITADOS or nota_efectiva(chat) is None:
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
            }
        )
    return sorted(filas, key=lambda f: (_normalizar_nombre(f["agente_nombre"]), f["semana"]))


def _celda_segura(valor):
    """Evita que una hoja de cálculo interprete un texto como fórmula."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def filas_csv(lote, chats, url_conversacion=None):
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
