import pytest

from utils.auditoria_chats_pauta import (
    CRITERIOS,
    PAUTA_VERSION,
    construir_mensajes,
    requiere_revision,
    validar_resultado,
)

CLAVES = ["saludo", "comprension", "exactitud", "resolucion", "tono", "tiempos", "cierre"]


def _resultado(**cambios):
    data = {
        "criterios": {clave: 4 for clave in CLAVES},
        "nota_global": 4,
        "satisfaccion_cliente": "satisfecho",
        "resuelto": "si",
        "resumen": "Atención correcta.",
        "fortalezas": ["Saludo cordial"],
        "mejoras": [],
        "evidencias": ["Buenos días, ¿en qué te ayudo?"],
        "confianza": "alta",
    }
    data.update(cambios)
    return data


def test_criterios_y_version():
    assert PAUTA_VERSION == "1"
    assert [clave for clave, _ in CRITERIOS] == CLAVES


def test_resultado_valido_pasa():
    resultado = validar_resultado(_resultado())
    assert resultado["nota_global"] == 4
    assert resultado["criterios"]["cierre"] == 4
    assert resultado["satisfaccion_cliente"] == "satisfecho"


def test_nota_fuera_de_rango_falla():
    with pytest.raises(ValueError):
        validar_resultado(_resultado(nota_global=6))


def test_criterio_faltante_falla():
    criterios = {clave: 4 for clave in CLAVES[:-1]}
    with pytest.raises(ValueError):
        validar_resultado(_resultado(criterios=criterios))


def test_enumerado_invalido_falla():
    with pytest.raises(ValueError):
        validar_resultado(_resultado(satisfaccion_cliente="feliz"))


def test_normaliza_texto_y_acentos():
    criterios = {clave: "4" for clave in CLAVES}
    resultado = validar_resultado(
        _resultado(criterios=criterios, nota_global="5", resuelto="Sí", satisfaccion_cliente="No se puede saber")
    )
    assert resultado["criterios"]["saludo"] == 4
    assert resultado["nota_global"] == 5
    assert resultado["resuelto"] == "si"
    assert resultado["satisfaccion_cliente"] == "no_se_puede_saber"


def test_evidencias_maximo_tres():
    resultado = validar_resultado(_resultado(evidencias=["a", "b", "c", "d"]))
    assert resultado["evidencias"] == ["a", "b", "c"]


@pytest.mark.parametrize(
    "cambios",
    [
        {"nota_global": 3},
        {"satisfaccion_cliente": "insatisfecho"},
        {"confianza": "baja"},
    ],
)
def test_requiere_revision_marcados(cambios):
    assert requiere_revision(validar_resultado(_resultado(**cambios)), hubo_error=False) is True


def test_requiere_revision_por_error():
    assert requiere_revision(None, hubo_error=True) is True


def test_no_requiere_revision_si_todo_bien():
    assert requiere_revision(validar_resultado(_resultado()), hubo_error=False) is False


def test_construir_mensajes_incluye_pauta():
    mensajes = construir_mensajes("[09:00] Cliente: Hola", "Ana Pérez")
    assert [m["role"] for m in mensajes] == ["system", "user"]
    for clave in CLAVES:
        assert clave in mensajes[0]["content"]
    assert f"versión {PAUTA_VERSION}" in mensajes[0]["content"]
    assert "Ana Pérez" in mensajes[1]["content"]
    assert "[09:00] Cliente: Hola" in mensajes[1]["content"]
