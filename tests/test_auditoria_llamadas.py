from utils import auditoria_llamadas as al
from utils.auditoria_chats_store import MemoriaAuditoriaStore

RESUMEN = {
    "callId": "compinche1",
    "recordKey": "Julio#compinche1#1795400000000",
    "ticketId": "141744",
    "agentNumber": "Julio",
    "customerNumber": "+17869138131",
    "createdAt": 1795400000000,
    "durationSec": 479.4,
    "metadata": {"callType": "inbound", "intent": "how_to", "isVoicemail": False},
    "analytics": {"issueType": "Consulta sobre filtros; escribir a ana@x.com"},
    "scores": {"overall": 73.75},
    "sentiment": {"agent": "positivo", "customer": "neutral"},
}

DETALLE = {
    "rubric": {"items": [
        {"name": "Empatia", "notes": "Fue paciente con el cliente +17869138131", "percentScore": 75, "weightPct": 12},
        {"name": "Escucha activa", "notes": "Tuvo que reformular", "percentScore": 50, "weightPct": 10},
    ]},
    "coaching": {"topWins": ["Cordial"], "topImprovements": ["Explicar en pasos"], "nextActions": ["Confirmar comprensión"]},
    "keyPoints": [{"label": "Motivo", "detail": "Configurar filtros"}],
    "analytics": {"firstContactResolution": True, "escalated": False, "talkListenRatio": 1.46, "holdsCount": 1,
                  "deadAirSecondsEstimate": 24.5, "issueType": "x"},
    "transcript": [{"speaker": "agent", "text": "Hola"}],
    "audioUrl": "https://s3/...",
}


def test_normalizar_resumen_sin_telefono_y_anonimizado():
    fila = al.normalizar_resumen(RESUMEN)
    assert fila["record_key"] == RESUMEN["recordKey"] and fila["linea"] == "compinche1"
    assert fila["ticket_id"] == 141744 and fila["agent_number"] == "Julio"
    assert fila["duracion_seg"] == 479 and fila["tipo"] == "inbound" and fila["puntaje"] == 73.75
    assert fila["fecha"].startswith("2026-")
    assert "[correo]" in fila["motivo"]
    assert fila["sin_conversacion"] is False and fila["detalle_ok"] is False
    assert "+17869138131" not in str(fila)


def test_sin_conversacion_por_buzon_duracion_o_motivo():
    assert al.es_sin_conversacion(300, "x", es_buzon=True)
    assert al.es_sin_conversacion(39, "Consulta", es_buzon=False)
    assert al.es_sin_conversacion(120, "Llamada atendida por buzón de voz", es_buzon=False)
    assert al.es_sin_conversacion(90, "Contacto accidental; no hay consulta", es_buzon=False)
    assert not al.es_sin_conversacion(120, "Consulta de pausa", es_buzon=False)


def test_completar_con_detalle_guarda_rubrica_coaching_y_no_la_transcripcion():
    cambios = al.cambios_detalle(DETALLE)
    assert cambios["detalle_ok"] is True
    assert cambios["rubrica"] == [
        {"nombre": "Empatia", "peso": 12, "pct": 75, "justificacion": "Fue paciente con el cliente +[número]"},
        {"nombre": "Escucha activa", "peso": 10, "pct": 50, "justificacion": "Tuvo que reformular"},
    ]
    assert cambios["coaching"] == {"aciertos": ["Cordial"], "mejoras": ["Explicar en pasos"],
                                   "proximas_acciones": ["Confirmar comprensión"]}
    assert cambios["puntos_clave"] == [{"titulo": "Motivo", "texto": "Configurar filtros"}]
    assert cambios["analitica"]["resolucion_primer_contacto"] is True
    assert "transcript" not in str(cambios) and "s3" not in str(cambios)


def test_emparejar_prioriza_manual_luego_nombre_y_primer_nombre_unico():
    agentes = [{"id": 1, "nombre": "Julio"}, {"id": 2, "nombre": "Ana María"}, {"id": 3, "nombre": "Luis"}, {"id": 4, "nombre": "Eva"}]
    nombres = {"Julio", "Ana Maria", "Luis Gómez", "Luis Pérez", "Eva Rojas", "Eva Torres de Eva", "Otro"}
    guardados = {"Eva Torres de Eva": 4}
    assert al.emparejar(agentes, nombres, guardados) == {"Julio": 1, "Ana Maria": 2, "Eva Torres de Eva": 4}


def test_emparejar_un_agente_puede_tener_varios_nombres_guardados():
    agentes = [{"id": 1, "nombre": "Alexander"}]
    assert al.emparejar(agentes, {"Alexander Ruiz", "Alex R"}, {"Alex R": 1}) == {"Alexander Ruiz": 1, "Alex R": 1}


def test_store_memoria_llamadas_y_emparejamientos():
    store = MemoriaAuditoriaStore()
    lote = store.crear_lote({"etiqueta": "x"})
    fila = dict(al.normalizar_resumen(RESUMEN), agente_id=1)
    store.guardar_llamadas(lote["id"], [fila, dict(fila)])
    store.guardar_llamadas(lote["id"], [dict(fila, record_key="otra", agente_id=2)])
    llamadas = store.listar_llamadas(lote["id"])
    assert len(llamadas) == 2
    store.actualizar_llamada(llamadas[0]["id"], {"detalle_ok": True})
    assert len(store.listar_llamadas(lote["id"], solo_sin_detalle=True)) == 1
    store.borrar_llamadas(lote["id"], agente_id=2)
    assert [l["agente_id"] for l in store.listar_llamadas(lote["id"])] == [1]
    store.guardar_emparejamiento("Julio", 1, manual=True)
    assert store.emparejamientos() == {"Julio": {"chatwoot_agente_id": 1, "manual": True}}
