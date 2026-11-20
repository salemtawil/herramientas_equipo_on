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
