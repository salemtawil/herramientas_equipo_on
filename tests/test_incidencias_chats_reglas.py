from utils.incidencias_chats_reglas import agente_en, es_respuesta_humana, reglas_atencion


def _m(id, tipo, texto, t, sender_type="user"):
    """tipo: 0 entrante, 1 saliente, 2 actividad."""
    mensaje = {"id": id, "message_type": tipo, "content": texto, "created_at": t, "private": False}
    if tipo == 1:
        mensaje["sender_type"] = sender_type
        mensaje["sender"] = {"id": 7, "name": "Luis Gómez"}
    return mensaje


def _conv(status="resolved", asignado=None):
    conversacion = {"id": 1, "status": status, "meta": {}}
    if asignado:
        conversacion["meta"]["assignee"] = asignado
    return conversacion


def _claves(incidencias):
    return [i["clave"] for i in incidencias]


def test_bot_no_cuenta_como_respuesta():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Mensaje automático", 5, sender_type="agent_bot")]
    incidencias = reglas_atencion(mensajes, _conv("resolved"), ahora=10000)
    sin_atencion = [i for i in incidencias if i["clave"] == "sin_atencion"]
    assert len(sin_atencion) == 1
    assert sin_atencion[0]["severidad"] == "alta"
    assert sin_atencion[0]["tipo"] == "atencion"
    assert sin_atencion[0]["origen"] == "reglas"


def test_mensaje_sin_remitente_es_automatico():
    assert es_respuesta_humana({"message_type": 1, "content": "Hola"}) is False


def test_es_respuesta_humana_lee_sender_type_o_sender():
    assert es_respuesta_humana({"message_type": 1, "content": "Hola", "sender_type": "User"}) is True
    assert es_respuesta_humana({"message_type": 1, "content": "Hola", "sender": {"type": "user"}}) is True
    assert es_respuesta_humana({"message_type": 1, "content": "Hola", "sender": {"type": "captain"}}) is False
    assert es_respuesta_humana({"message_type": 1, "content": "Hola", "sender_type": "user", "private": True}) is False
    assert es_respuesta_humana({"message_type": 0, "content": "Hola", "sender_type": "user"}) is False


def test_chat_abierto_reciente_no_se_marca():
    assert reglas_atencion([_m(1, 0, "Hola", 0)], _conv("open"), ahora=420) == []


def test_chat_abierto_esperando_mucho_es_sin_atencion():
    incidencias = reglas_atencion([_m(1, 0, "Hola", 0)], _conv("open"), ahora=700)
    assert "sin_atencion" in _claves(incidencias)


def test_sin_atencion_no_duplica():
    incidencias = reglas_atencion([_m(1, 0, "Hola", 0)], _conv("open"), ahora=5000)
    assert _claves(incidencias) == ["sin_atencion"]


def test_primera_respuesta_tardia():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Buenas", 1380)]
    incidencias = reglas_atencion(mensajes, _conv("resolved"), ahora=5000)
    claves = _claves(incidencias)
    assert "primera_respuesta_tardia" in claves
    assert "espera_larga" in claves
    tardia = next(i for i in incidencias if i["clave"] == "primera_respuesta_tardia")
    assert tardia["evidencia"] == "Primera respuesta a los 23 min"
    assert tardia["severidad"] == "media"


def test_primera_respuesta_a_tiempo():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Buenas", 300)]
    claves = _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))
    assert "primera_respuesta_tardia" not in claves
    assert "espera_larga" not in claves


def test_cliente_ignorado():
    mensajes = [
        _m(1, 0, "Hola", -100),
        _m(2, 1, "Buenas", -50),
        _m(3, 0, "Sigo aquí", 0),
        _m(4, 0, "¿Hola?", 300),
        _m(5, 0, "¿Me ayudan?", 700),
    ]
    incidencias = reglas_atencion(mensajes, _conv("open"), ahora=800)
    assert "cliente_ignorado" in _claves(incidencias)
    assert "sin_atencion" not in _claves(incidencias)


def test_cierre_sin_responder_solo_resuelto():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Buenas", 60), _m(3, 0, "Gracias, pero sigo con el problema", 120)]
    resuelto = reglas_atencion(mensajes, _conv("resolved"), ahora=5000)
    assert "cierre_sin_responder" in _claves(resuelto)
    assert next(i for i in resuelto if i["clave"] == "cierre_sin_responder")["severidad"] == "alta"
    abierto = reglas_atencion(mensajes, _conv("open"), ahora=5000)
    assert "cierre_sin_responder" not in _claves(abierto)


def test_agente_por_asignacion():
    mensajes = [
        _m(1, 2, "Assigned to Ana Pérez by Admin", 0),
        _m(2, 0, "Hola", 10),
    ]
    conversacion = _conv("resolved", asignado={"id": 9, "name": "Luis Gómez"})
    incidencias = reglas_atencion(mensajes, conversacion, ahora=5000)
    assert incidencias
    assert incidencias[0]["agente_nombre"] == "Ana Pérez"


def test_agente_por_assignee_si_no_hay_asignacion():
    conversacion = _conv("resolved", asignado={"id": 9, "name": "Luis Gómez"})
    assert agente_en([_m(1, 0, "Hola", 10)], 10, conversacion) == {"id": 9, "nombre": "Luis Gómez"}


def test_sin_asignar():
    incidencias = reglas_atencion([_m(1, 0, "Hola", 0)], _conv("resolved"), ahora=5000)
    assert incidencias[0]["agente_nombre"] == "Sin asignar"
    assert incidencias[0]["agente_id"] is None
