"""Reglas puras de mala atención para Incidencias de chats (sin red ni IA)."""

from utils.auditoria_chats_transcripcion import (
    MENSAJE_ENTRANTE,
    MENSAJE_SALIENTE,
    _asignado_a,
    _es_cliente,
    _mismo_nombre,
    _ordenados,
    _texto,
    _ts_mensaje,
    anonimizar,
    es_llamada,
)

REGLAS_VERSION = "1"
PRIMERA_RESPUESTA_MAX = 600
ESPERA_MAX = 900
IGNORADO_MENSAJES = 3
IGNORADO_SEGUNDOS = 600
SIN_ATENCION_ESPERA = 600

ETIQUETAS = {
    "sin_atencion": ("Sin atención", "alta"),
    "cierre_sin_responder": ("Cierre sin responder", "alta"),
    "cliente_ignorado": ("Cliente ignorado", "media"),
    "primera_respuesta_tardia": ("Primera respuesta tardía", "media"),
    "espera_larga": ("Espera larga", "media"),
}
SIN_ASIGNAR = "Sin asignar"
MAX_CITA = 120


def es_respuesta_humana(mensaje):
    """Saliente, público, con texto y escrito por un usuario (no bot, captain ni sin remitente)."""
    if mensaje.get("message_type") != MENSAJE_SALIENTE or mensaje.get("private") or not _texto(mensaje):
        return False
    sender = mensaje.get("sender")
    tipo = mensaje.get("sender_type") or (sender.get("type") if isinstance(sender, dict) else None)
    return str(tipo or "").strip().lower() == "user"


def agente_en(mensajes, ts, conversacion):
    """Agente a cargo en el instante `ts`: última asignación previa, o el asignado actual."""
    nombre = None
    for mensaje in _ordenados(mensajes):
        if _ts_mensaje(mensaje) >= ts:
            break
        asignado = _asignado_a(mensaje)
        if asignado:
            nombre = asignado

    assignee = ((conversacion or {}).get("meta") or {}).get("assignee") or {}
    assignee = assignee if isinstance(assignee, dict) else {}
    if not nombre:
        nombre = assignee.get("name")
    if not nombre:
        return {"id": None, "nombre": SIN_ASIGNAR}

    agente_id = None
    for mensaje in mensajes or []:
        sender = mensaje.get("sender")
        if es_respuesta_humana(mensaje) and isinstance(sender, dict) and _mismo_nombre(sender.get("name"), nombre):
            agente_id = sender.get("id")
            break
    if agente_id is None and _mismo_nombre(assignee.get("name"), nombre):
        agente_id = assignee.get("id")
    return {"id": agente_id, "nombre": nombre}


def _incidencia(clave, evidencia, mensaje, mensajes, conversacion):
    etiqueta, severidad = ETIQUETAS[clave]
    ts = _ts_mensaje(mensaje)
    agente = agente_en(mensajes, ts, conversacion)
    return {
        "tipo": "atencion",
        "clave": clave,
        "etiqueta": etiqueta,
        "severidad": severidad,
        "evidencia": evidencia,
        "coincidencia": "",
        "mensaje_id": mensaje.get("id"),
        "ts": ts,
        "agente_id": agente["id"],
        "agente_nombre": agente["nombre"],
        "origen": "reglas",
    }


def _cita(mensaje):
    texto = " ".join(anonimizar(_texto(mensaje)).split())
    if len(texto) > MAX_CITA:
        texto = texto[: MAX_CITA - 1] + "…"
    return f"«{texto}»" if texto else "un mensaje sin texto"


def _minutos(segundos):
    return int(segundos // 60)


def reglas_atencion(mensajes, conversacion, ahora):
    conversacion = conversacion or {}
    ordenados = _ordenados(mensajes)
    if es_llamada(ordenados):
        return []

    # Solo cuentan los mensajes públicos del cliente y las respuestas humanas.
    eventos = [m for m in ordenados if _es_cliente(m) or es_respuesta_humana(m)]
    clientes = [m for m in eventos if m.get("message_type") == MENSAJE_ENTRANTE]
    if not clientes:
        return []

    abierto = str(conversacion.get("status") or "") != "resolved"
    resuelto = str(conversacion.get("status") or "") == "resolved"
    incidencias = []

    def agregar(clave, evidencia, mensaje):
        incidencias.append(_incidencia(clave, evidencia, mensaje, ordenados, conversacion))

    primero = clientes[0]
    if not any(es_respuesta_humana(m) for m in eventos):
        # Sin ninguna respuesta humana solo se marca sin_atencion, que absorbe las demás reglas.
        espera = ahora - _ts_mensaje(primero)
        if resuelto or (abierto and espera > SIN_ATENCION_ESPERA):
            if resuelto:
                evidencia = f"Chat cerrado sin respuesta de un agente. Cliente: {_cita(primero)}"
            else:
                evidencia = f"Cliente esperando {_minutos(espera)} min sin respuesta de un agente"
            agregar("sin_atencion", evidencia, primero)
        return incidencias

    # Esperas: del primer mensaje sin responder hasta la siguiente respuesta humana.
    esperas = []
    ignorado = None
    pendientes = []
    for mensaje in eventos:
        if mensaje.get("message_type") == MENSAJE_ENTRANTE:
            pendientes.append(mensaje)
            continue
        if pendientes:
            duracion = _ts_mensaje(mensaje) - _ts_mensaje(pendientes[0])
            esperas.append((duracion, pendientes[0]))
            if ignorado is None and len(pendientes) >= IGNORADO_MENSAJES and duracion >= IGNORADO_SEGUNDOS:
                ignorado = (duracion, pendientes[0], len(pendientes))
        pendientes = []

    if pendientes:
        if abierto:
            duracion = ahora - _ts_mensaje(pendientes[0])
            esperas.append((duracion, pendientes[0]))
        else:
            duracion = _ts_mensaje(pendientes[-1]) - _ts_mensaje(pendientes[0])
            agregar("cierre_sin_responder", f"El chat se cerró sin responder a {_cita(pendientes[-1])}", pendientes[-1])
        if ignorado is None and len(pendientes) >= IGNORADO_MENSAJES and duracion >= IGNORADO_SEGUNDOS:
            ignorado = (duracion, pendientes[0], len(pendientes))

    if ignorado:
        duracion, mensaje, cantidad = ignorado
        agregar("cliente_ignorado", f"{cantidad} mensajes del cliente sin respuesta en {_minutos(duracion)} min", mensaje)

    primera = next((m for m in eventos if es_respuesta_humana(m) and _ts_mensaje(m) >= _ts_mensaje(primero)), None)
    if primera:
        segundos = _ts_mensaje(primera) - _ts_mensaje(primero)
        if segundos > PRIMERA_RESPUESTA_MAX:
            agregar("primera_respuesta_tardia", f"Primera respuesta a los {_minutos(segundos)} min", primero)

    largas = [e for e in esperas if e[0] > ESPERA_MAX]
    if largas:
        duracion, mensaje = max(largas, key=lambda e: e[0])
        agregar("espera_larga", f"Espera de {_minutos(duracion)} min sin respuesta", mensaje)

    return incidencias
