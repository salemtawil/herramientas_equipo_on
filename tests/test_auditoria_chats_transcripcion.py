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
