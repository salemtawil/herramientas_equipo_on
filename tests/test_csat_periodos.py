from datetime import date
import pytest
from utils.csat_periodos import resolver_periodo, periodo_anterior, formatear_periodo

HOY = date(2026, 11, 25)  # miércoles

@pytest.mark.parametrize("tipo,esperado", [
    ("semana_pasada", (date(2026,11,16), date(2026,11,22))),
    ("esta_semana", (date(2026,11,23), date(2026,11,25))),
    ("ultimos_7", (date(2026,11,19), date(2026,11,25))),
    ("mes_pasado", (date(2026,10,1), date(2026,10,31))),
    ("este_mes", (date(2026,11,1), date(2026,11,25))),
])
def test_resolver_presets(tipo, esperado):
    assert resolver_periodo(tipo, HOY) == esperado

def test_personalizado_y_errores():
    assert resolver_periodo("personalizado", HOY, "2026-11-01", "2026-11-10") == (date(2026,11,1), date(2026,11,10))
    with pytest.raises(ValueError): resolver_periodo("personalizado", HOY)
    with pytest.raises(ValueError): resolver_periodo("personalizado", HOY, "2026-11-10", "2026-11-01")
    with pytest.raises(ValueError): resolver_periodo("otro", HOY)

def test_periodo_anterior():
    assert periodo_anterior("semana_pasada", date(2026,11,16), date(2026,11,22)) == (date(2026,11,9), date(2026,11,15))
    assert periodo_anterior("esta_semana", date(2026,11,23), date(2026,11,25)) == (date(2026,11,16), date(2026,11,22))
    assert periodo_anterior("mes_pasado", date(2026,10,1), date(2026,10,31)) == (date(2026,9,1), date(2026,9,30))
    assert periodo_anterior("este_mes", date(2026,11,1), date(2026,11,25)) == (date(2026,10,1), date(2026,10,31))
    assert periodo_anterior("ultimos_7", date(2026,11,19), date(2026,11,25)) == (date(2026,11,12), date(2026,11,18))
    assert periodo_anterior("personalizado", date(2026,11,1), date(2026,11,10)) == (date(2026,10,22), date(2026,10,31))

def test_formatear_periodo():
    assert formatear_periodo(date(2026,6,1), date(2026,6,7)) == "01/06/26 al 07/06/26"
