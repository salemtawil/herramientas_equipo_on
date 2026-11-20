from utils.auditoria_chats_manual import (
    cortar_manual,
    expandir_codigos,
    seleccionar_secciones,
    version_manual,
)
from utils.auditoria_chats_store import MemoriaAuditoriaStore

PAGINAS = [
    "MANUAL DE PROCESOS Versión 3.0",
    "ÍNDICE\n 1.  Departamento  de  Customer  Service.  5 1.1  Principios  de  atención.  5 "
    "1.1.1  Atención  por  chat.  5 1.1.2  Solicitud  de  llamada.  6 1.7  He  llegado.  7 "
    "1.7.1  Tipos  de  he  llegado.  7 1.7.2  Selfie.  8",
    "2.  Departamento  de  Desarrollo  9 2.1  Stack  9 4.  Departamento  de  Finanzas  10 "
    "4.3  Política  de  Reembolso  10 4.5  Historial  de  pagos  11 Recursos  Audiovisuales  12",
    "1.  Departamento  de  Customer  Service.\n1.1  Principios  de  atención.\n"
    "1.1.1  Atención  por  chat.  Objetivo:  responder  en  menos  de\n2\nminutos.",
    "Ver también 1.1.2 Solicitud de llamada en otro caso. 1.1.2  Solicitud  de  llamada.  Ofrecer  contacto  directo.",
    "1.7  He  llegado.  1.7.1  Tipos  de  he  llegado.  Texto  A.  1.7.2  Selfie.  Texto  B.",
    "2.  Departamento  de  Desarrollo  2.1  Stack  Python.",
    "4.  Departamento  de  Finanzas  4.3  Política  de  Reembolso  Remitir  al  Manager.  "
    "4.5  Historial  de  pagos  Revisar  pagos.  Recursos  Audiovisuales  Videos.",
]


def _por_codigo(secciones):
    return {s["codigo"]: s for s in secciones}


def test_cortar_manual_extrae_secciones_del_cuerpo_sin_indice():
    secciones = cortar_manual(PAGINAS)
    codigos = [s["codigo"] for s in secciones]
    assert codigos == ["1.1", "1.1.1", "1.1.2", "1.7", "1.7.1", "1.7.2", "4.3", "4.5"]
    s = _por_codigo(secciones)
    assert s["1.1.1"]["titulo"] == "Atención por chat"
    assert s["1.1.1"]["texto"] == "Objetivo: responder en menos de 2 minutos. Ver también 1.1.2 Solicitud de llamada en otro caso."
    assert s["1.1.2"]["texto"] == "Ofrecer contacto directo."
    assert s["1.7.2"]["texto"] == "Texto B."
    assert s["4.3"]["texto"] == "Remitir al Manager."
    assert s["4.5"]["texto"] == "Revisar pagos."
    assert [x["orden"] for x in secciones] == list(range(len(secciones)))


def test_expandir_codigos_incluye_subsecciones():
    disponibles = ["1.1", "1.1.1", "1.7", "1.7.1", "1.7.2", "1.10", "1.10.1"]
    assert expandir_codigos(["1.7"], disponibles) == ["1.7", "1.7.1", "1.7.2"]
    assert expandir_codigos(["1.1"], disponibles) == ["1.1", "1.1.1"]
    assert expandir_codigos(["1.10", "9.9"], disponibles) == ["1.10", "1.10.1"]


def _sec(codigo, largo):
    return {"codigo": codigo, "titulo": codigo, "texto": "x" * largo}


def test_seleccionar_secciones_orden_y_tope():
    secciones = [_sec(c, 100) for c in ("1.1.1", "1.1.3", "1.1.8", "1.2.5", "1.4.1", "1.1.5", "1.9.6", "4.4")]
    clasificacion = {"procedimientos": ["P03", "P07"], "secciones_extra": ["1.1.5"]}
    elegidas = seleccionar_secciones(clasificacion, secciones)
    assert [s["codigo"] for s in elegidas] == ["1.1.1", "1.1.3", "1.1.8", "1.2.5", "1.4.1", "1.9.6", "4.4", "1.1.5"]
    # tope chico: se van primero las extra y luego los procedimientos desde el final; nunca las generales
    recortadas = seleccionar_secciones(clasificacion, secciones, tope=6 * 102)
    assert [s["codigo"] for s in recortadas] == ["1.1.1", "1.1.3", "1.1.8", "1.2.5", "1.4.1", "1.9.6"]
    minimas = seleccionar_secciones(clasificacion, secciones, tope=10)
    assert [s["codigo"] for s in minimas] == ["1.1.1", "1.1.3", "1.1.8", "1.2.5"]


def test_store_memoria_guarda_e_indexa_manual():
    store = MemoriaAuditoriaStore()
    assert store.indice_manual("3.0") == []
    store.guardar_manual("3.0", cortar_manual(PAGINAS))
    store.guardar_manual("3.0", [{"codigo": "4.5", "titulo": "Historial de pagos", "texto": "Nuevo.", "orden": 7}])
    indice = store.indice_manual("3.0")
    assert indice[0] == {"codigo": "1.1", "titulo": "Principios de atención"}
    assert len(indice) == 8
    textos = {s["codigo"]: s["texto"] for s in store.secciones_manual("3.0", ["4.5", "1.1.2"])}
    assert textos == {"4.5": "Nuevo.", "1.1.2": "Ofrecer contacto directo."}
    assert store.indice_manual("9.9") == []


def test_version_manual(monkeypatch):
    monkeypatch.delenv("AUDITORIA_CHATS_MANUAL_VERSION", raising=False)
    assert version_manual() == "3.0"
    monkeypatch.setenv("AUDITORIA_CHATS_MANUAL_VERSION", " 3.1 ")
    assert version_manual() == "3.1"
