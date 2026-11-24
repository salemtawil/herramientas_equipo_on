from datetime import date

import pytest

from utils.auditoria_csat_store import (
    AuditoriaCsatConfigError,
    MemoriaCsatStore,
    SupabaseCsatStore,
    obtener_store_csat,
)

D1, D7 = date(2026, 11, 16), date(2026, 11, 22)


@pytest.fixture
def store():
    return MemoriaCsatStore()


def test_guardar_periodo_es_upsert_por_fechas(store):
    a = store.guardar_periodo("semana_pasada", D1, D7, {"csat_real": 80.0})
    b = store.guardar_periodo("semana_pasada", D1, D7, {"csat_real": 82.0})
    assert a["id"] == b["id"]
    assert store.obtener_periodo(a["id"])["csat_real"] == 82.0
    assert len(store.listar_periodos()) == 1


def test_fechas_se_guardan_como_iso_y_se_busca_por_fechas(store):
    p = store.guardar_periodo("semana_pasada", D1, D7, {"total_encuestas": 10})
    assert p["fecha_inicio"] == "2026-11-16" and p["fecha_fin"] == "2026-11-22"
    assert store.buscar_periodo(D1, D7)["id"] == p["id"]
    assert store.buscar_periodo(D1, date(2026, 11, 30)) is None
    assert store.obtener_periodo("no-existe") is None


def test_listar_periodos_mas_recientes_primero_y_limite(store):
    store.guardar_periodo("a", date(2026, 10, 1), date(2026, 10, 7), {})
    store.guardar_periodo("b", D1, D7, {})
    assert [p["fecha_fin"] for p in store.listar_periodos()] == ["2026-11-22", "2026-10-07"]
    assert len(store.listar_periodos(limite=1)) == 1


def test_reemplazar_negativos_borra_los_que_ya_no_vienen(store):
    pid = store.guardar_periodo("semana_pasada", D1, D7, {})["id"]
    store.reemplazar_negativos(pid, [{"survey_id": 1}, {"survey_id": 2}])
    store.reemplazar_negativos(pid, [{"survey_id": 1}])
    assert [n["survey_id"] for n in store.negativos(pid)] == [1]


def test_reemplazar_negativos_actualiza_existentes(store):
    pid = store.guardar_periodo("semana_pasada", D1, D7, {})["id"]
    store.reemplazar_negativos(pid, [{"survey_id": 1, "decision_final": None}])
    store.reemplazar_negativos(pid, [{"survey_id": 1, "decision_final": "excluir"}])
    filas = store.negativos(pid)
    assert len(filas) == 1 and filas[0]["decision_final"] == "excluir"


def test_negativos_son_por_periodo(store):
    p1 = store.guardar_periodo("a", D1, D7, {})["id"]
    p2 = store.guardar_periodo("b", date(2026, 10, 1), date(2026, 10, 7), {})["id"]
    store.reemplazar_negativos(p1, [{"survey_id": 1}])
    store.reemplazar_negativos(p2, [{"survey_id": 1}, {"survey_id": 2}])
    store.reemplazar_negativos(p1, [])
    assert store.negativos(p1) == []
    assert len(store.negativos(p2)) == 2


def test_borrar_vencidos_respeta_12_semanas(store):
    viejo = store.guardar_periodo("semana_pasada", date(2026, 8, 1), date(2026, 8, 7), {})["id"]
    store.guardar_periodo("semana_pasada", D1, D7, {})
    store.reemplazar_negativos(viejo, [{"survey_id": 9}])
    assert store.borrar_vencidos(date(2026, 11, 25)) == 1
    assert len(store.listar_periodos()) == 1
    assert store.negativos(viejo) == []


def test_obtener_store_csat_sin_config_da_error_en_espanol(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(AuditoriaCsatConfigError, match="SUPABASE_URL"):
        obtener_store_csat()
    assert SupabaseCsatStore is not None
