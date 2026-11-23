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


# --- Resumen con IA de las llamadas ---

def _fila(ticket, puntaje, agente_id=1, sin_conv=False, rubrica=None, coaching=None):
    return {
        "agente_id": agente_id, "ticket_id": ticket, "puntaje": puntaje, "tipo": "inbound", "duracion_seg": 120,
        "motivo": f"Motivo {ticket}", "sin_conversacion": sin_conv, "detalle_ok": True,
        "rubrica": rubrica or [{"nombre": "Empatia", "peso": 12, "pct": 75, "justificacion": "ok"},
                               {"nombre": "Claridad", "peso": 10, "pct": 50, "justificacion": "repetitivo"}],
        "coaching": coaching or {"aciertos": ["Cordial"], "mejoras": ["Pasos breves"], "proximas_acciones": ["Confirmar"]},
    }


def test_resumen_llamadas_por_agente_metricas_peores_y_criterios_bajos():
    filas = [_fila(1, 90), _fila(2, 60), _fila(3, 100, sin_conv=True), _fila(4, 80, agente_id=2)]
    filas[1]["tipo"] = "outbound"
    [a1, a2] = al.resumen_llamadas_por_agente(filas)
    assert a1["agente_id"] == 1 and a1["llamadas"] == 3 and a1["puntaje_medio"] == 83.3
    assert a1["sin_conversacion"] == 1 and a1["entrantes"] == 2 and a1["salientes"] == 1
    assert [p["ticket_id"] for p in a1["peores"]] == [2, 1, 3]
    assert a1["criterios_bajos"][0] == {"nombre": "Claridad", "pct": 50.0}
    assert a2["llamadas"] == 1


def test_mensajes_resumen_priorizan_las_peores_y_marcan_buzon():
    filas = [_fila(1, 95), _fila(2, 40), _fila(3, 100, sin_conv=True)]
    mensajes = al.construir_mensajes_resumen_llamadas("Julio", filas)
    usuario = mensajes[1]["content"]
    assert usuario.index("Ticket 2") < usuario.index("Ticket 1")
    assert "buzón" in usuario.lower() and "Pasos breves" in usuario and "Claridad 50" in usuario
    assert "JSON" in mensajes[0]["content"]


def test_validar_resumen_descarta_tickets_inexistentes_y_limita():
    data = {
        "puntos_fuertes": [{"texto": "Cordial", "tickets": [1, "2", 99]}],
        "areas_mejora": [{"texto": f"Mejora {i}", "tickets": [1]} for i in range(8)],
        "recomendaciones": [{"texto": "Resumir en pasos", "tickets": ["#2"]}],
        "buzon_voz": {"evaluacion": "Deja mensaje claro", "tickets": [3, 77]},
        "resumen": "Buen agente.",
    }
    r = al.validar_resumen_llamadas(data, {1, 2, 3})
    assert r["puntos_fuertes"] == [{"texto": "Cordial", "tickets": [1, 2]}]
    assert len(r["areas_mejora"]) == 5
    assert r["recomendaciones"][0]["tickets"] == [2]
    assert r["buzon_voz"] == {"evaluacion": "Deja mensaje claro", "tickets": [3]}
    assert al.validar_resumen_llamadas({"resumen": "x"}, set())["buzon_voz"] is None
