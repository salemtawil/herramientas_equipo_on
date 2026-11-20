from datetime import datetime, timezone

from utils.auditoria_chats_transcripcion import (
    anonimizar,
    construir_transcripcion,
    mensajes_utiles,
    tiene_mensajes_de_agente,
)


def _ts(hora, minuto):
    # 2026-11-10 hh:mm en Caracas (UTC-4)
    return int(datetime(2026, 11, 10, hora + 4, minuto, tzinfo=timezone.utc).timestamp())


def test_anonimizar_correo_telefono_numero():
    texto = "Escribe a ana@x.com o al +58 412-555-1234, cédula 12345678"
    resultado = anonimizar(texto)
    assert "[correo]" in resultado
    assert "[teléfono]" in resultado
    assert "[número]" in resultado
    assert "ana@x.com" not in resultado
    assert "555-1234" not in resultado
    assert "12345678" not in resultado


def test_anonimizar_conserva_texto_normal_y_numeros_cortos():
    assert anonimizar("Tu pedido llega en 3 días, total 250") == "Tu pedido llega en 3 días, total 250"


def test_mensajes_utiles_descarta_privados_y_actividad():
    mensajes = [
        {"id": 1, "message_type": 0, "content": "Hola", "created_at": _ts(9, 0)},
        {"id": 2, "message_type": 2, "content": "Conversación asignada", "created_at": _ts(9, 1)},
        {"id": 3, "message_type": 1, "content": "Nota interna", "private": True, "created_at": _ts(9, 2)},
        {"id": 4, "message_type": 1, "content": "Buenos días", "created_at": _ts(9, 3)},
        {"id": 5, "message_type": 3, "content": "plantilla", "created_at": _ts(9, 4)},
        {"id": 6, "message_type": 0, "content": "   ", "created_at": _ts(9, 5)},
    ]
    assert [m["id"] for m in mensajes_utiles(mensajes)] == [1, 4]


def test_tiene_mensajes_de_agente():
    assert tiene_mensajes_de_agente([{"message_type": 1, "content": "Hola"}]) is True
    assert tiene_mensajes_de_agente([{"message_type": 0, "content": "Hola"}]) is False
    assert tiene_mensajes_de_agente([{"message_type": 1, "content": "x", "private": True}]) is False


def test_construir_transcripcion_formato_y_hora():
    mensajes = [
        {"message_type": 0, "content": "Hola, mi correo es a@b.com", "created_at": _ts(9, 5)},
        {"message_type": 1, "content": "Buenos días, ¿en qué te ayudo?", "created_at": _ts(9, 7)},
    ]
    texto = construir_transcripcion(mensajes, "America/Caracas")
    assert texto.splitlines() == [
        "[09:05] Cliente: Hola, mi correo es [correo]",
        "[09:07] Agente: Buenos días, ¿en qué te ayudo?",
    ]


def test_construir_transcripcion_recorta_a_6000():
    mensajes = [
        {"message_type": i % 2, "content": "palabra " * 40, "created_at": _ts(10, i % 60)}
        for i in range(100)
    ]
    texto = construir_transcripcion(mensajes, "America/Caracas", max_chars=6000)
    assert len(texto) <= 6000 + len("\n[…]\n")
    assert "\n[…]\n" in texto
    assert texto.startswith("[10:00] Cliente:")


def test_nota_de_voz_aparece_en_la_transcripcion():
    mensajes = [
        {"message_type": 0, "content": None, "created_at": _ts(9, 0), "attachments": [{"file_type": "audio"}]},
        {"message_type": 1, "content": "Hola, ¿me lo puedes escribir?", "created_at": _ts(9, 1)},
        {"message_type": 0, "content": "", "created_at": _ts(9, 2), "attachments": [{"file_type": "image"}]},
    ]
    assert len(mensajes_utiles(mensajes)) == 3
    assert construir_transcripcion(mensajes, "America/Caracas").splitlines() == [
        "[09:00] Cliente: [nota de voz]",
        "[09:01] Agente: Hola, ¿me lo puedes escribir?",
        "[09:02] Cliente: [imagen]",
    ]


def test_chat_solo_con_audios_del_agente_no_cuenta_como_respuesta_escrita():
    mensajes = [
        {"message_type": 0, "content": "Hola", "created_at": _ts(9, 0)},
        {"message_type": 1, "content": None, "created_at": _ts(9, 1), "attachments": [{"file_type": "audio"}]},
    ]
    assert tiene_mensajes_de_agente(mensajes) is False


# ---------------------------------------------------------------------------
# Llamadas frente a notas de voz
# ---------------------------------------------------------------------------

from utils.auditoria_chats_transcripcion import es_llamada, forma_mensajes  # noqa: E402


def test_mensaje_de_tipo_llamada_es_llamada():
    assert es_llamada([{"message_type": 2, "content_type": "voice_call", "content": None}]) is True


def test_atributos_de_llamada_es_llamada():
    mensajes = [{"message_type": 1, "content": "", "content_attributes": {"call_status": "completed", "duration": 42}}]
    assert es_llamada(mensajes) is True


def test_texto_de_registro_de_llamada_es_llamada():
    assert es_llamada([{"message_type": 2, "content": "Llamada entrante finalizada (2:13)"}]) is True
    assert es_llamada([{"message_type": 2, "content": "Missed call from +1 555"}]) is True


def test_nota_de_voz_no_es_llamada():
    mensajes = [
        {"message_type": 0, "content": None, "attachments": [{"file_type": "audio"}]},
        {"message_type": 1, "content": "Te escuché, ya lo reviso", "attachments": []},
        {"message_type": 0, "content": "¿me puedes llamar?"},
    ]
    assert es_llamada(mensajes) is False


def test_forma_mensajes_sin_texto():
    mensajes = [
        {"message_type": 0, "content": "Mi correo es a@b.com", "content_type": "text"},
        {"message_type": 1, "content": None, "attachments": [{"file_type": "audio", "data_url": "https://x"}],
         "content_attributes": {"call_status": "x"}, "private": True},
    ]
    forma = forma_mensajes(mensajes)
    assert forma == [
        {"tipo": 0, "content_type": "text", "con_texto": True, "adjuntos": [], "atributos": [], "privado": False},
        {"tipo": 1, "content_type": None, "con_texto": False, "adjuntos": ["audio"], "atributos": ["call_status"], "privado": True},
    ]
    assert "a@b.com" not in str(forma) and "https://x" not in str(forma)


# --- Transcripción v2, período del agente y tiempos (pauta QA-1.1) ---

from utils.auditoria_chats_transcripcion import (  # noqa: E402
    construir_transcripcion_v2,
    ids_mensajes,
    metricas_tiempos,
    periodo_agente,
)

T0 = int(datetime(2026, 11, 10, 14, 0, 0, tzinfo=timezone.utc).timestamp())  # 10:00:00 en Caracas


def _m(mid, seg, tipo, texto="", sender=None, private=False):
    return {
        "id": mid, "created_at": T0 + seg, "message_type": tipo, "content": texto,
        "private": private, "sender": sender, "attachments": [],
    }


ANA = {"id": 7, "name": "Ana Pérez", "type": "user"}
LUIS = {"id": 8, "name": "Luis Gómez", "type": "user"}
CLIENTE = {"id": 99, "name": "Cliente", "type": "contact"}


def test_transcripcion_v2_con_ids_segundos_notas_y_sistema():
    mensajes = [
        _m(1, 0, 0, "Hola, mi correo es a@b.com", CLIENTE),
        _m(2, 5, 2, "Assigned to Ana Pérez by Admin"),
        _m(3, 65, 1, "Hola, soy Ana de Compinche", ANA),
        _m(4, 70, 1, "Cliente pide pausa", ANA, private=True),
        _m(5, 80, 1, "", ANA),
    ]
    texto = construir_transcripcion_v2(mensajes, "America/Caracas")
    assert texto.splitlines() == [
        "[m1 10:00:00] Cliente: Hola, mi correo es [correo]",
        "[m2 10:00:05] Sistema: Assigned to Ana Pérez by Admin",
        "[m3 10:01:05] Agente (Ana Pérez): Hola, soy Ana de Compinche",
        "[m4 10:01:10] Nota interna (Ana Pérez): Cliente pide pausa",
    ]
    assert ids_mensajes(mensajes) == {"m1", "m2", "m3", "m4"}


def test_periodo_con_traspaso_termina_en_la_asignacion_al_colega():
    mensajes = [
        _m(1, 0, 0, "Hola", CLIENTE),
        _m(2, 5, 2, "Assigned to Ana Pérez by Admin"),
        _m(3, 60, 1, "Hola, soy Ana", ANA),
        _m(4, 300, 2, "Asignado a Luis Gómez por Admin"),
        _m(5, 320, 1, "Hola, soy Luis", LUIS),
        _m(6, 900, 2, "Conversation was marked resolved by Luis Gómez"),
    ]
    assert periodo_agente(mensajes, 7, "Ana Pérez") == {"desde": "m2", "hasta": "m4", "inferido": True}
    assert periodo_agente(mensajes, 8, "Luis Gómez") == {"desde": "m4", "hasta": "m6", "inferido": True}


def test_periodo_sin_eventos_usa_primer_mensaje_del_agente_o_todo_el_chat():
    mensajes = [_m(1, 0, 0, "Hola", CLIENTE), _m(2, 30, 1, "Hola", ANA)]
    assert periodo_agente(mensajes, 7, "Ana Pérez") == {"desde": "m2", "hasta": None, "inferido": True}
    assert periodo_agente(mensajes, 5, "Otra") == {"desde": None, "hasta": None, "inferido": False}


def test_metricas_primera_respuesta_y_esperas_atribuibles():
    mensajes = [
        _m(1, 0, 0, "Hola", CLIENTE),
        _m(2, 30, 2, "Assigned to Luis Gómez by Admin"),
        _m(3, 90, 1, "Hola, soy Luis", LUIS),
        _m(4, 100, 0, "Necesito ayuda", CLIENTE),
        _m(5, 300, 1, "Ya reviso", LUIS),          # espera de 200 s del colega
        _m(6, 310, 2, "Assigned to Ana Pérez by Admin"),
        _m(7, 320, 0, "¿Sigues?", CLIENTE),
        _m(8, 400, 1, "Hola, soy Ana", ANA),
        _m(9, 410, 0, "Gracias", CLIENTE),
        _m(10, 700, 1, "Listo, tu pausa quedó", ANA),  # espera de 290 s de Ana
    ]
    periodo = periodo_agente(mensajes, 7, "Ana Pérez")
    metricas = metricas_tiempos(mensajes, periodo, 7)
    assert metricas["primera_respuesta"] == {"segundos": 90, "desde": "m1", "hasta": "m3"}
    assert metricas["primera_respuesta_agente"] == {"segundos": 80, "desde": "m7", "hasta": "m8"}
    assert metricas["esperas_largas_oficiales"] == [
        {"desde": "m4", "hasta": "m5", "segundos": 200},
        {"desde": "m9", "hasta": "m10", "segundos": 290},
    ]
    assert metricas["esperas_largas"] == [{"desde": "m9", "hasta": "m10", "segundos": 290}]


def test_metricas_inactividad_seguimiento_y_cierre():
    mensajes = [
        _m(1, 0, 0, "Hola", CLIENTE),
        _m(2, 60, 1, "Listo, ya está", ANA),
        _m(3, 360, 1, "¿Sigues en línea?", ANA),
        _m(4, 960, 1, "Parece que te desconectaste", ANA),
        _m(5, 970, 2, "Conversation was marked resolved by Ana Pérez"),
    ]
    metricas = metricas_tiempos(mensajes, periodo_agente(mensajes, 7, "Ana Pérez"), 7)
    assert metricas["inactividad"] == {
        "ultimo_cliente": "m1",
        "mensajes_agente": [
            {"id": "m2", "segundos_desde_anterior": 60},
            {"id": "m3", "segundos_desde_anterior": 300},
            {"id": "m4", "segundos_desde_anterior": 600},
        ],
        "cierre": {"id": "m5", "segundos_desde_ultimo_mensaje": 10, "cerro": "agente"},
    }


def test_metricas_sin_respuestas_no_fallan():
    mensajes = [_m(1, 0, 0, "Hola", CLIENTE)]
    metricas = metricas_tiempos(mensajes, periodo_agente(mensajes, 7, "Ana"), 7)
    assert metricas["primera_respuesta"] is None and metricas["primera_respuesta_agente"] is None
    assert metricas["esperas_largas"] == [] and metricas["inactividad"]["cierre"] is None
