from datetime import date

from utils.incidencias_chats_store import MemoriaIncidenciasStore


def _fila(review_id, conversation_id, **extra):
    return dict({"review_id": review_id, "conversation_id": conversation_id, "estado": "pendiente"}, **extra)


def test_insertar_duplicado_no_repite():
    store = MemoriaIncidenciasStore()
    revision = store.crear_revision({"estado": "listando"})
    assert store.insertar_chats([_fila(revision["id"], 10)]) == 1
    assert store.insertar_chats([_fila(revision["id"], 10)]) == 0
    assert len(store.listar_chats(revision["id"])) == 1


def test_tomar_siguiente_no_entrega_dos_veces():
    store = MemoriaIncidenciasStore()
    revision = store.crear_revision({"estado": "evaluando"})
    store.insertar_chats([_fila(revision["id"], 1)])
    primero = store.tomar_siguiente(revision["id"], ["pendiente"], "procesando")
    assert primero["conversation_id"] == 1 and primero["estado"] == "procesando"
    assert store.tomar_siguiente(revision["id"], ["pendiente"], "procesando") is None


def test_ultima_evaluacion_ignora_misma_revision():
    store = MemoriaIncidenciasStore()
    a = store.crear_revision({"estado": "completado"})
    b = store.crear_revision({"estado": "evaluando"})
    store.insertar_chats([_fila(a["id"], 5, estado="evaluado", incidencias=[{"x": 1}])])
    store.insertar_chats([_fila(b["id"], 5, estado="evaluado")])
    previa = store.ultima_evaluacion(5, b["id"])
    assert previa["review_id"] == a["id"] and previa["incidencias"] == [{"x": 1}]
    assert store.ultima_evaluacion(5, a["id"])["review_id"] == b["id"]
    assert store.ultima_evaluacion(99, b["id"]) is None


def test_decision_por_conversacion_se_sobrescribe():
    store = MemoriaIncidenciasStore()
    store.guardar_decision(7, {"decision": "atendida", "por": "ana"})
    store.guardar_decision(7, {"decision": "falso_positivo", "por": "luis", "nota": "ok"})
    decisiones = store.decisiones([7, 8])
    assert set(decisiones) == {7}
    assert decisiones[7]["decision"] == "falso_positivo" and decisiones[7]["por"] == "luis"


def test_usos_ia_por_fecha():
    store = MemoriaIncidenciasStore()
    hoy, ayer = date(2026, 11, 26), date(2026, 11, 25)
    assert store.usos_ia(hoy) == 0
    assert store.sumar_uso_ia(hoy) == 1
    assert store.sumar_uso_ia(hoy) == 2
    assert store.usos_ia(hoy) == 2 and store.usos_ia(ayer) == 0


def test_ultima_evaluacion_elige_la_mas_reciente_por_updated_at():
    store = MemoriaIncidenciasStore()
    a = store.crear_revision({"estado": "completado"})
    b = store.crear_revision({"estado": "completado"})
    c = store.crear_revision({"estado": "evaluando"})
    store.insertar_chats([_fila(a["id"], 5, estado="evaluado")])
    store.insertar_chats([_fila(b["id"], 5, estado="evaluado")])
    vieja = next(ch for ch in store.listar_chats(a["id"]))
    store.actualizar_chat(vieja["id"], {"incidencias": [{"nuevo": True}]})
    assert store.ultima_evaluacion(5, c["id"])["review_id"] == a["id"]
