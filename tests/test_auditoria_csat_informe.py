"""Bloque CSAT para el informe semanal."""
import pytest

from app import app
from tools import auditoria_csat as herramienta_csat
from tools import informe_semanal_cs as informe
from utils.auditoria_csat_informe import bloque_desde_estado, construir_bloque_csat, datos_periodo_anterior
from utils.auditoria_csat_store import AuditoriaCsatConfigError, MemoriaCsatStore

PERIODO = {
    "tipo_periodo": "semana_pasada",
    "fecha_inicio": "2026-11-16",
    "fecha_fin": "2026-11-22",
    "total_encuestas": 50,
    "ratings_count": {"1": 5, "2": 0, "3": 5, "4": 10, "5": 30},
    "csat_real": 80.0,
    "csat_ajustado": 85.0,
    "por_agente": [
        {"Agente": "Ana", "CSAT original": 75.0, "CSAT auditado": 90.0, "Negativas": 3, "SÍ": 2},
    ],
    "negativos_total": 5,
    "negativos_excluidos": 2,
    "negativos_pendientes": 1,
}
NEGATIVOS = [
    {"survey_id": 1, "conversation_id": 501, "agente_nombre": "Ana", "comentario": "Tardaron mucho",
     "decision_final": "SÍ", "motivo_final": "Falla del sistema", "origen_decision": "humana",
     "nota_auditor": "Caída general", "ia_evidencia": ""},
    {"survey_id": 2, "conversation_id": 502, "agente_nombre": "Ana", "comentario": "Mala atención",
     "decision_final": "NO", "motivo_final": "Tiempo de respuesta", "origen_decision": "ia_aceptada",
     "nota_auditor": "", "ia_evidencia": "Esperó 40 minutos"},
    {"survey_id": 3, "conversation_id": 503, "agente_nombre": "Ana", "comentario": "Sin decidir",
     "decision_final": "", "motivo_final": "", "origen_decision": "", "nota_auditor": "", "ia_evidencia": ""},
]
ANTERIOR_SIN_AUDITAR = {"periodo": "09/11/26 al 15/11/26", "csat_real": 78.0, "csat_ajustado": None,
                        "total": 60, "auditado": False}


class ChatwootMetricas:
    def __init__(self, ratings=None, falla=False):
        self.ratings = ratings if ratings is not None else {"1": 10, "5": 40}
        self.falla = falla

    def metricas_csat(self, since, until):
        if self.falla:
            raise RuntimeError("Chatwoot caído")
        return {"total_count": sum(self.ratings.values()), "ratings_count": self.ratings}


def test_bloque_contiene_real_ajustado_y_pendientes():
    texto = construir_bloque_csat(PERIODO, NEGATIVOS, ANTERIOR_SIN_AUDITAR)
    assert "CSAT real: 80.0%" in texto and "CSAT ajustado: 85.0%" in texto
    assert "Negativos pendientes de confirmar: 1" in texto and "sin auditoría" in texto
    inicios = ["Período auditado: 16/11/26 al 22/11/26", "Total de encuestas: 50", "Distribución: ",
               "CSAT real: ", "CSAT ajustado: ", "Por agente:", "Negativos por motivo:",
               "Negativos excluidos (no atribuibles al agente): 2 de 5", "Auditados a mano: 1",
               "Aceptados de la IA: 1", "Negativos pendientes de confirmar: ", "Casos relevantes:",
               "Período anterior: 09/11/26 al 15/11/26"]
    posiciones = [texto.index(i) for i in inicios]
    assert posiciones == sorted(posiciones)
    assert "- Falla del sistema: 1" in texto
    assert "Caída general" in texto and "Esperó 40 minutos" in texto
    assert "Sin decidir" not in texto


def test_anterior_usa_guardado_si_existe():
    store = MemoriaCsatStore()
    store.guardar_periodo("semana_pasada", "2026-11-09", "2026-11-15",
                          {"total_encuestas": 40, "csat_real": 70.0, "csat_ajustado": 74.5})
    r = datos_periodo_anterior(store, ChatwootMetricas(falla=True), PERIODO, "America/Caracas")
    assert r == {"periodo": "09/11/26 al 15/11/26", "csat_real": 70.0, "csat_ajustado": 74.5,
                 "total": 40, "auditado": True}


def test_anterior_sin_guardado_usa_metricas():
    r = datos_periodo_anterior(MemoriaCsatStore(), ChatwootMetricas(), PERIODO, "America/Caracas")
    assert r["csat_real"] == 80.0 and r["auditado"] is False and r["csat_ajustado"] is None
    assert r["total"] == 50 and r["periodo"] == "09/11/26 al 15/11/26"


def test_anterior_con_chatwoot_caido():
    r = datos_periodo_anterior(MemoriaCsatStore(), ChatwootMetricas(falla=True), PERIODO, "America/Caracas")
    assert r == {"periodo": "09/11/26 al 15/11/26", "error": "sin datos"}
    assert "Período anterior: 09/11/26 al 15/11/26 — sin datos" in construir_bloque_csat(PERIODO, NEGATIVOS, r)


def _fila(id_, rating, justificable="", origen=""):
    return {
        "survey_id": id_, "conversation_id": 500 + id_, "agente_id": 7, "agente": "Ana",
        "calificacion": rating, "tipo_rating": "Negativo" if rating <= 2 else "Positivo",
        "comentario": "x", "enlace_conversacion": "", "fecha_iso": "2026-11-17",
        "justificable": justificable, "motivo_inconformidad": "Falla del sistema" if justificable else "",
        "origen_decision": origen, "comentario_auditor": "", "estado_auditoria": justificable or "pendiente",
    }


def test_bloque_desde_estado_modo_prueba():
    estado = {"tipo_periodo": "semana_pasada", "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-22",
              "rows": [_fila(1, 1, "SÍ", "humana"), _fila(2, 1), _fila(3, 5), _fila(4, 5)]}
    texto = bloque_desde_estado(estado, ChatwootMetricas(), "America/Caracas")
    assert "Total de encuestas: 4" in texto and "CSAT real: 50.0%" in texto
    assert "CSAT ajustado: 66.7%" in texto and "Negativos pendientes de confirmar: 1" in texto
    assert "Período anterior: 09/11/26 al 15/11/26 — CSAT real 80.0% (sin auditoría)" in texto


# --- Informe semanal ---
@pytest.fixture
def store(monkeypatch):
    memoria = MemoriaCsatStore()
    monkeypatch.setattr(informe, "obtener_store_csat", lambda: memoria)
    return memoria


@pytest.fixture
def chatwoot(monkeypatch):
    falso = ChatwootMetricas()
    monkeypatch.setattr(informe, "obtener_chatwoot", lambda: falso)
    return falso


@pytest.fixture
def cliente():
    return app.test_client()


@pytest.fixture
def capturado(monkeypatch):
    capturas = {}

    def falso(datos):
        capturas["datos"] = dict(datos)
        capturas["prompt"] = informe.build_weekly_report_prompt(datos)
        return "# Informe", "fallback", []

    monkeypatch.setattr(informe, "generate_weekly_report", falso)
    return capturas


def _guardar(store):
    resumen = {k: v for k, v in PERIODO.items() if k not in ("tipo_periodo", "fecha_inicio", "fecha_fin")}
    periodo = store.guardar_periodo("semana_pasada", "2026-11-16", "2026-11-22", resumen)
    store.reemplazar_negativos(periodo["id"], NEGATIVOS)
    return periodo


def test_informe_con_auditoria_incluye_bloque_en_prompt(cliente, store, chatwoot, capturado):
    periodo = _guardar(store)
    r = cliente.post("/informe-semanal-cs", data={"auditoria_csat_id": periodo["id"], "bitacora": "x"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "CSAT ajustado: 85.0%" in capturado["datos"]["auditoria_csat"]
    assert capturado["datos"]["periodo"] == "16/11/26 al 22/11/26"
    assert "Auditoría CSAT (datos confirmados):" in capturado["prompt"]
    assert "CSAT ajustado: 85.0%" in capturado["prompt"]
    assert "La auditoría CSAT tiene 1 negativos sin confirmar." in html


def test_informe_respeta_periodo_escrito(cliente, store, chatwoot, capturado):
    periodo = _guardar(store)
    cliente.post("/informe-semanal-cs", data={"auditoria_csat_id": periodo["id"], "periodo": "Semana 47"})
    assert capturado["datos"]["periodo"] == "Semana 47"


def test_informe_sin_auditoria_seleccionada(cliente, store, capturado):
    cliente.post("/informe-semanal-cs", data={"bitacora": "x"})
    assert capturado["datos"]["auditoria_csat"] == ""
    assert "Sin auditoría CSAT seleccionada." in capturado["prompt"]


def test_informe_muestra_select_con_pendientes(cliente, store):
    _guardar(store)
    html = cliente.get("/informe-semanal-cs").get_data(as_text=True)
    assert 'name="auditoria_csat_id"' in html and "Sin auditoría CSAT" in html
    assert "16/11/26 al 22/11/26 — 1 pendientes" in html


def test_informe_sin_supabase_sigue_funcionando(cliente, monkeypatch):
    def sin_config():
        raise AuditoriaCsatConfigError("sin config")

    monkeypatch.setattr(informe, "obtener_store_csat", sin_config)
    r = cliente.get("/informe-semanal-cs")
    assert r.status_code == 200 and 'name="auditoria_csat_id"' not in r.get_data(as_text=True)


def test_fallback_considera_auditoria_como_csat():
    datos = {"nombre_informe": "", "periodo": "", "informe_anterior": "", "bitacora": "Actividad",
             "archivos_adicionales": "", "notas": "", "auditoria_csat": "CSAT real: 80.0%"}
    assert "CSAT real: 80.0%" in informe.generar_informe_fallback(datos)


# --- Descarga desde la auditoría (modo prueba) ---
def test_descargar_bloque_informe_en_modo_prueba(monkeypatch):
    from tests.test_auditoria_csat_ruta import ChatwootFalso, _hidden, _traer

    falso = ChatwootFalso()
    falso.metricas_csat = lambda since, until: {"total_count": 10, "ratings_count": {"1": 2, "5": 8}}
    monkeypatch.setattr(herramienta_csat, "obtener_chatwoot", lambda: falso)
    monkeypatch.setattr(herramienta_csat, "obtener_store_csat", lambda: pytest.fail("no debe usarse"))
    cliente = app.test_client()
    html = _traer(cliente, prueba="1").get_data(as_text=True)
    assert 'value="descargar_bloque_informe"' in html
    r = cliente.post("/auditoria-csat", data={
        "accion": "descargar_bloque_informe", "analysis_id": _hidden(html, "analysis_id"), "prueba": "1"})
    assert r.status_code == 200 and r.mimetype == "text/plain"
    assert "bloque_csat_informe.txt" in r.headers["Content-Disposition"]
    texto = r.get_data(as_text=True)
    assert "Período auditado: " in texto and "CSAT real: 66.7%" in texto
    assert "Período anterior: " in texto and "CSAT real 80.0%" in texto


def test_boton_bloque_no_aparece_si_no_es_prueba(monkeypatch):
    from tests.test_auditoria_csat_ruta import ChatwootFalso, _traer

    monkeypatch.setattr(herramienta_csat, "obtener_chatwoot", lambda: ChatwootFalso())
    monkeypatch.setattr(herramienta_csat, "obtener_store_csat", lambda: MemoriaCsatStore())
    html = _traer(app.test_client()).get_data(as_text=True)
    assert "descargar_bloque_informe" not in html
