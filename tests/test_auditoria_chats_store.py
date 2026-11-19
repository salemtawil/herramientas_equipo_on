from utils.auditoria_chats_store import MemoriaAuditoriaStore, SupabaseAuditoriaStore


def _chat(conversation_id, **extra):
    fila = {"conversation_id": conversation_id, "agente_id": 7, "agente_nombre": "Ana", "estado": "pendiente"}
    fila.update(extra)
    return fila


def _store_con_lote():
    store = MemoriaAuditoriaStore()
    lote = store.crear_lote({"etiqueta": "Semana", "estado": "muestreando"})
    return store, lote


def test_crear_obtener_y_listar_lotes():
    store, lote = _store_con_lote()
    assert lote["id"]
    assert store.obtener_lote(lote["id"])["etiqueta"] == "Semana"
    segundo = store.crear_lote({"etiqueta": "Otra"})
    assert [l["id"] for l in store.listar_lotes()] == [segundo["id"], lote["id"]]
    assert store.obtener_lote("no-existe") is None


def test_actualizar_lote():
    store, lote = _store_con_lote()
    store.actualizar_lote(lote["id"], {"estado": "auditando"})
    assert store.obtener_lote(lote["id"])["estado"] == "auditando"


def test_insertar_chats_ignora_conversacion_repetida():
    store, lote = _store_con_lote()
    assert store.insertar_chats([dict(_chat(1), batch_id=lote["id"]), dict(_chat(2), batch_id=lote["id"])]) == 2
    assert store.insertar_chats([dict(_chat(2), batch_id=lote["id"]), dict(_chat(3), batch_id=lote["id"])]) == 1
    assert sorted(c["conversation_id"] for c in store.listar_chats(lote["id"])) == [1, 2, 3]


def test_conversaciones_auditadas():
    store, lote = _store_con_lote()
    store.insertar_chats([dict(_chat(1), batch_id=lote["id"])])
    assert store.conversaciones_auditadas([1, 2]) == {1}


def test_tomar_siguiente_no_repite_fila():
    store, lote = _store_con_lote()
    store.insertar_chats([dict(_chat(1), batch_id=lote["id"]), dict(_chat(2), batch_id=lote["id"])])
    primero = store.tomar_siguiente(lote["id"], ("pendiente",), "procesando")
    segundo = store.tomar_siguiente(lote["id"], ("pendiente",), "procesando")
    assert primero["conversation_id"] != segundo["conversation_id"]
    assert store.tomar_siguiente(lote["id"], ("pendiente",), "procesando") is None
    assert store.obtener_chat(primero["id"])["estado"] == "procesando"


def test_actualizar_chat_cambia_updated_at():
    store, lote = _store_con_lote()
    store.insertar_chats([dict(_chat(1), batch_id=lote["id"])])
    chat = store.listar_chats(lote["id"])[0]
    actualizado = store.actualizar_chat(chat["id"], {"estado": "auditado", "ia_nota": 4})
    assert actualizado["ia_nota"] == 4
    assert actualizado["updated_at"] >= chat["updated_at"]


def test_borrar_lote_libera_conversaciones():
    store, lote = _store_con_lote()
    store.insertar_chats([dict(_chat(1), batch_id=lote["id"])])
    store.borrar_lote(lote["id"])
    assert store.obtener_lote(lote["id"]) is None
    assert store.conversaciones_auditadas([1]) == set()


def test_chats_para_historial_filtra_por_fecha():
    store, lote = _store_con_lote()
    store.insertar_chats(
        [
            dict(_chat(1, conversacion_fecha="2026-11-01T10:00:00+00:00"), batch_id=lote["id"]),
            dict(_chat(2, conversacion_fecha="2026-09-01T10:00:00+00:00"), batch_id=lote["id"]),
        ]
    )
    assert [c["conversation_id"] for c in store.chats_para_historial("2026-10-01T00:00:00+00:00")] == [1]


class _Respuesta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    def __init__(self, registro, tabla, operacion, valores=None):
        self.registro = registro
        self.llamada = {"tabla": tabla, "operacion": operacion, "valores": valores, "filtros": []}
        registro.append(self.llamada)

    def select(self, *args):
        return self

    def eq(self, columna, valor):
        self.llamada["filtros"].append((columna, valor))
        return self

    def in_(self, columna, valores):
        self.llamada["filtros"].append((columna, tuple(valores)))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args):
        return self

    def execute(self):
        if self.llamada["operacion"] == "select":
            return _Respuesta([{"id": "c1", "estado": "pendiente"}])
        if self.llamada["operacion"] == "update":
            return _Respuesta([{"id": "c1", "estado": "procesando"}])
        return _Respuesta([])


class _Tabla:
    def __init__(self, registro, nombre):
        self.registro = registro
        self.nombre = nombre

    def select(self, *args):
        return _Consulta(self.registro, self.nombre, "select")

    def update(self, valores):
        return _Consulta(self.registro, self.nombre, "update", valores)


class _Cliente:
    def __init__(self):
        self.registro = []

    def table(self, nombre):
        return _Tabla(self.registro, nombre)


def test_supabase_tomar_siguiente_actualiza_condicionado_al_estado_anterior():
    cliente = _Cliente()
    store = SupabaseAuditoriaStore(cliente)
    fila = store.tomar_siguiente("lote-1", ("pendiente",), "procesando")
    assert fila["estado"] == "procesando"
    update = [l for l in cliente.registro if l["operacion"] == "update"][0]
    assert update["tabla"] == "chat_audits"
    assert update["valores"]["estado"] == "procesando"
    assert ("id", "c1") in update["filtros"]
    assert ("estado", "pendiente") in update["filtros"]
