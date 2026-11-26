from utils.incidencias_chats_reglas import (
    agente_en,
    es_respuesta_humana,
    evaluar_chat,
    fragmento,
    normalizar,
    regla_csat,
    reglas_atencion,
    reglas_cliente,
)


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


# --- Tarea 2: reportes de clientes, frustración, CSAT y evaluar_chat ---

def test_cobro_doble_con_tildes_y_mayusculas():
    incidencias = reglas_cliente([_m(1, 0, "Me COBRARON dos veces la recarga", 0)], _conv())
    assert len(incidencias) == 1
    assert incidencias[0]["tipo"] == "cliente"
    assert incidencias[0]["clave"] == "cobros"
    assert incidencias[0]["severidad"] == "alta"
    assert "COBRARON dos veces" in incidencias[0]["evidencia"]
    assert incidencias[0]["coincidencia"] == "Me COBRARON dos veces"


def test_tildes_en_el_texto_original():
    incidencias = reglas_cliente([_m(1, 0, "Pésima   atención, no me llegó nada", 0)], _conv())
    assert {"frustracion", "no_recibido"} == set(_claves(incidencias))
    assert next(i for i in incidencias if i["clave"] == "frustracion")["coincidencia"] == "Pésima atención"


def test_frase_del_agente_no_cuenta():
    assert reglas_cliente([_m(1, 1, "no funciona así", 0)], _conv()) == []


def test_una_por_categoria():
    mensajes = [_m(1, 0, "no funciona", 0), _m(2, 0, "sigue sin funcionar, no funciona", 5)]
    assert _claves(reglas_cliente(mensajes, _conv())).count("fallas_app") == 1


def test_evidencia_anonimizada_y_recortada():
    texto = "a" * 280 + " correo yo@mail.com y " + "me cobraron dos veces " + "b" * 280
    assert len(texto) > 600
    incidencia = reglas_cliente([_m(1, 0, texto, 0)], _conv())[0]
    assert len(incidencia["evidencia"]) <= 200
    assert "yo@mail.com" not in incidencia["evidencia"]
    assert "me cobraron dos veces" in incidencia["evidencia"]
    assert incidencia["evidencia"].startswith("…") and incidencia["evidencia"].endswith("…")


def test_fragmento_anonimiza_correo_cercano():
    texto = "escribi a yo@mail.com porque no funciona nada"
    inicio = texto.index("no funciona")
    resultado = fragmento(texto, inicio, inicio + len("no funciona"))
    assert "yo@mail.com" not in resultado
    assert "no funciona" in resultado


def test_frustracion_es_atencion():
    incidencias = reglas_cliente([_m(1, 0, "Nadie me responde", 0)], _conv())
    assert _claves(incidencias) == ["frustracion"]
    assert incidencias[0]["tipo"] == "atencion"
    assert incidencias[0]["severidad"] == "media"
    assert incidencias[0]["etiqueta"] == "Frustración del cliente"


def test_normalizar():
    assert normalizar("  PÉSIMA   Atención ") == "pesima atencion"


def test_csat_bajo():
    mensajes = [_m(1, 0, "Hola", 0)]
    incidencias = regla_csat(2, _conv(), mensajes)
    assert _claves(incidencias) == ["csat_bajo"]
    assert incidencias[0]["evidencia"] == "CSAT 2/5"
    assert regla_csat(3, _conv(), mensajes) == []
    assert regla_csat(None, _conv(), mensajes) == []


def test_evaluar_descarta_llamada_y_sin_cliente():
    llamada = [_m(1, 0, "Hola", 0), {"id": 2, "message_type": 2, "content": "Llamada entrante de +5491155550000", "created_at": 5}]
    resultado = evaluar_chat(llamada, _conv(), ahora=5000, csat=1)
    assert resultado["descartado"] == "llamada"
    assert resultado["incidencias"] == []
    sin_cliente = evaluar_chat([_m(1, 1, "Hola", 0)], _conv(), ahora=5000)
    assert sin_cliente["descartado"] == "sin_cliente"
    assert sin_cliente["incidencias"] == []


def test_evaluar_junta_todo():
    mensajes = [_m(1, 0, "Me cobraron dos veces", 0), _m(2, 1, "Buenas", 1380)]
    resultado = evaluar_chat(mensajes, _conv("resolved", asignado={"id": 7, "name": "Luis Gómez"}), ahora=5000, csat=1)
    claves = _claves(resultado["incidencias"])
    assert {"cobros", "primera_respuesta_tardia", "csat_bajo"} <= set(claves)
    assert resultado["descartado"] is None
    assert resultado["resuelto"] is True
    assert resultado["agente_nombre"] == "Luis Gómez"
    assert resultado["agente_id"] == 7


def test_evidencia_de_evaluar_anonimizada_y_corta():
    texto = "mi correo es yo@mail.com " + "x " * 300 + "no funciona " + "y " * 300
    resultado = evaluar_chat([_m(1, 0, texto, 0), _m(2, 1, "Hola", 10)], _conv(), ahora=5000, csat=1)
    assert resultado["incidencias"]
    for incidencia in resultado["incidencias"]:
        assert len(incidencia["evidencia"]) <= 200
        assert "yo@mail.com" not in incidencia["evidencia"]


def test_cierre_ignora_cortesia():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Listo, ya quedó", 60), _m(3, 0, "Gracias!! 🙏", 120)]
    assert "cierre_sin_responder" not in _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))
    mensajes.append(_m(4, 0, "Muchas gracias, excelente", 130))
    assert "cierre_sin_responder" not in _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))


def test_cierre_cita_el_ultimo_mensaje_sustantivo():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Buenas", 60), _m(3, 0, "Sigo sin saldo", 120), _m(4, 0, "Gracias", 130)]
    cierre = next(i for i in reglas_atencion(mensajes, _conv("resolved"), ahora=5000) if i["clave"] == "cierre_sin_responder")
    assert "Sigo sin saldo" in cierre["evidencia"]


def test_cierre_no_duplica_ignorado():
    mensajes = [
        _m(1, 0, "Hola", 0),
        _m(2, 1, "Buenas", 30),
        _m(3, 0, "Sigo aquí", 100),
        _m(4, 0, "¿Hola?", 400),
        _m(5, 0, "¿Me ayudan?", 900),
    ]
    claves = _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))
    assert "cierre_sin_responder" in claves
    assert "cliente_ignorado" not in claves


def test_fragmento_anonimiza_correo_que_contiene_la_frase():
    texto = "mi correo es juan.reclamo@mail.com gracias"
    inicio = texto.index("reclamo")
    resultado = fragmento(texto, inicio, inicio + len("reclamo"))
    assert "@" not in resultado and "juan" not in resultado
    assert "[correo]" in resultado


def test_reglas_cliente_no_filtra_correo_con_la_frase():
    for texto in ("mi correo es juan.reclamo@mail.com gracias", "escribanme a reembolso@mail.com"):
        incidencia = reglas_cliente([_m(1, 0, texto, 0)], _conv())[0]
        assert "@" not in incidencia["evidencia"] and "mail.com" not in incidencia["evidencia"]
        assert "@" not in incidencia["coincidencia"]


def test_sin_atencion_no_se_marca_si_solo_agradece():
    mensajes = [_m(1, 0, "Muchas gracias", 0)]
    assert "sin_atencion" not in _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))


def test_sin_atencion_no_se_marca_si_solo_hay_mensajes_vacios():
    mensajes = [_m(1, 0, "", 0), _m(2, 0, "   ", 10)]
    assert "sin_atencion" not in _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))


def test_sin_atencion_con_solo_un_adjunto():
    adjunto = dict(_m(1, 0, "", 0), attachments=[{"file_type": "image"}])
    incidencias = reglas_atencion([adjunto], _conv("resolved"), ahora=5000)
    assert _claves(incidencias) == ["sin_atencion"]


def test_sin_atencion_cita_el_primer_mensaje_sustantivo():
    mensajes = [_m(1, 0, "Gracias", 0), _m(2, 0, "No me llegó el pedido", 30)]
    incidencia = reglas_atencion(mensajes, _conv("resolved"), ahora=5000)[0]
    assert incidencia["clave"] == "sin_atencion"
    assert "No me llegó el pedido" in incidencia["evidencia"]
    assert incidencia["mensaje_id"] == 2


def test_cierre_ignora_mensaje_vacio_final():
    mensajes = [_m(1, 0, "Hola", 0), _m(2, 1, "Listo, ya quedó", 60), _m(3, 0, "", 120)]
    assert "cierre_sin_responder" not in _claves(reglas_atencion(mensajes, _conv("resolved"), ahora=5000))
