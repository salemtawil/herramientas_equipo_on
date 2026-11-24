import pytest

from utils.auditoria_csat_chatwoot import (
    cargar_transcripciones,
    filas_desde_encuestas,
    fusionar_guardado,
    negativos_para_guardar,
    resumen_para_guardar,
)

TZ = "America/Caracas"


class ChatwootFalso:
    def url_conversacion(self, conversation_id):
        return f"https://chat.example.com/app/accounts/1/conversations/{conversation_id}"

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        if conversation_id == 502:
            raise RuntimeError("boom")
        return [
            {"id": 1, "message_type": 0, "content": "Hola", "created_at": 1700000000},
            {"id": 2, "message_type": 1, "content": "Buen día", "created_at": 1700000060},
        ]


def enc(id_, rating=1, assigned_agent="default", conversation_id=None, feedback="Mal servicio"):
    if assigned_agent == "default":
        assigned_agent = {"id": 7, "name": "Ana Perez", "available_name": "Ana P."}
    return {
        "id": id_,
        "rating": rating,
        "feedback_message": feedback,
        "csat_review_notes": "nota",
        "conversation_id": conversation_id or 500 + id_,
        "assigned_agent": assigned_agent,
        "contact": {"name": "Cli", "email": "c@x.com", "phone_number": "+58412"},
        "created_at": 1700000000 + id_,
    }


def test_filas_desde_encuestas():
    filas = filas_desde_encuestas([enc(1, rating=1), enc(2, rating=5)], ChatwootFalso(), TZ)
    assert filas[0]["row_id"] == "1" and filas[0]["tipo_rating"] == "Negativo"
    assert filas[0]["enlace_conversacion"].endswith("/conversations/501")
    assert filas[1]["tipo_rating"] == "Positivo"
    f = filas[0]
    assert f["survey_id"] == 1 and f["conversation_id"] == 501 and f["agente_id"] == 7
    assert f["agente"] == "Ana P." and f["Nombre del agente"] == "Ana P."
    assert f["Calificación"] == "1" and f["correo_contacto"] == "c@x.com"
    assert f["estado_auditoria"] == "pendiente" and f["csat_flag"] == "contabiliza"
    assert f["origen_decision"] == "" and f["fecha_iso"]
    assert f["fecha_registrada"] == "2023-11-14 18:13"


def test_encuesta_sin_agente():
    fila = filas_desde_encuestas([enc(3, rating=2, assigned_agent=None)], ChatwootFalso(), TZ)[0]
    assert fila["agente"] == "Sin agente" and fila["agente_id"] is None


def _filas_con_transcripcion():
    filas = filas_desde_encuestas([enc(1, feedback="x" * 900), enc(2, rating=5)], ChatwootFalso(), TZ)
    cargar_transcripciones(filas, ChatwootFalso(), TZ)
    filas[0]["ia_evidencia"] = "e" * 900
    filas[0]["ia_confianza"] = 90.0
    return filas


def test_negativos_para_guardar_no_incluye_contacto_ni_transcripcion():
    datos = negativos_para_guardar(_filas_con_transcripcion())
    assert len(datos) == 1
    assert set(datos[0]) == {
        "survey_id", "conversation_id", "agente_id", "agente_nombre", "rating", "comentario",
        "enlace", "fecha", "ia_justificable", "ia_motivo", "ia_confianza", "ia_evidencia",
        "decision_final", "motivo_final", "origen_decision", "nota_auditor",
    }
    assert len(datos[0]["comentario"]) <= 500 and len(datos[0]["ia_evidencia"]) <= 500
    assert datos[0]["ia_confianza"] == 90.0 and datos[0]["rating"] == 1


def test_confianza_vacia_es_none():
    datos = negativos_para_guardar(filas_desde_encuestas([enc(1)], ChatwootFalso(), TZ))
    assert datos[0]["ia_confianza"] is None


def test_fusionar_conserva_decision_humana():
    filas = filas_desde_encuestas([enc(1, rating=1)], ChatwootFalso(), TZ)
    fusionar_guardado(filas, [{"survey_id": 1, "decision_final": "SÍ", "motivo_final": "CAPTCHA",
                               "origen_decision": "humana", "nota_auditor": "n",
                               "ia_justificable": "TAL VEZ", "ia_confianza": 80.0}])
    f = filas[0]
    assert f["justificable"] == "SÍ" and f["csat_flag"] == "excluida_por_justificable_si"
    assert f["estado_auditoria"] == "SÍ" and f["comentario_auditor"] == "n"
    assert f["motivo_inconformidad"] == "CAPTCHA" and f["ia_confianza"] == 80.0


def test_fusionar_ignora_no_negativos_y_desconocidos():
    filas = filas_desde_encuestas([enc(2, rating=5)], ChatwootFalso(), TZ)
    fusionar_guardado(filas, [{"survey_id": 2, "decision_final": "SÍ"}, {"survey_id": 99, "decision_final": "NO"}])
    assert filas[0]["justificable"] == "" and filas[0]["csat_flag"] == "contabiliza"


def test_roundtrip_guardar_fusionar():
    filas = _filas_con_transcripcion()
    filas[0].update(justificable="NO", motivo_inconformidad="OTRO", origen_decision="humana")
    guardado = negativos_para_guardar(filas)
    nuevas = filas_desde_encuestas([enc(1, feedback="x" * 900)], ChatwootFalso(), TZ)
    fusionar_guardado(nuevas, guardado)
    assert nuevas[0]["justificable"] == "NO" and nuevas[0]["ia_confianza"] == 90.0


def test_cargar_transcripciones_sigue_si_una_falla():
    filas = filas_desde_encuestas([enc(1), enc(2, conversation_id=502)], ChatwootFalso(), TZ)
    advertencias = cargar_transcripciones(filas, ChatwootFalso(), TZ)
    assert len(advertencias) == 1 and filas[0]["transcripcion_conversacion"]
    assert not filas[1]["transcripcion_conversacion"]


def test_cargar_transcripciones_no_repite_las_existentes():
    filas = filas_desde_encuestas([enc(2, conversation_id=502)], ChatwootFalso(), TZ)
    filas[0]["transcripcion_conversacion"] = "ya"
    assert cargar_transcripciones(filas, ChatwootFalso(), TZ) == []


def test_resumen_para_guardar():
    filas = filas_desde_encuestas([enc(1, rating=1), enc(2, rating=5), enc(3, rating=5)], ChatwootFalso(), TZ)
    fusionar_guardado(filas, [{"survey_id": 1, "decision_final": "SÍ"}])
    r = resumen_para_guardar(filas)
    assert r["total_encuestas"] == 3 and r["ratings_count"] == {"1": 1, "2": 0, "3": 0, "4": 0, "5": 2}
    assert r["csat_real"] == 66.67 and r["csat_ajustado"] == 100.0
    assert r["negativos_total"] == 1 and r["negativos_excluidos"] == 1 and r["negativos_pendientes"] == 0
    assert r["por_agente"][0]["Agente"] == "Ana P."
