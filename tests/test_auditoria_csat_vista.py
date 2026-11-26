from tools.auditoria_csat import construir_contexto_analisis
from utils.auditoria_csat_vista import (
    construir_fichas,
    construir_kpis,
    construir_pasos,
    construir_vista,
    contar_pestanas,
)


def _neg(row_id, **extra):
    fila = {
        "row_id": row_id,
        "agente": "Ana",
        "tipo_rating": "Negativo",
        "calificacion": 1,
        "fecha_iso": "2026-01-0%d" % row_id,
        "justificable": "",
        "origen_decision": "",
        "ia_justificable": "",
    }
    fila.update(extra)
    return fila


def _pos(row_id):
    return {"row_id": row_id, "agente": "Ana", "tipo_rating": "Positivo", "calificacion": 5, "justificable": ""}


def test_pasos_en_curso():
    filas = [
        _neg(1, justificable="NO", origen_decision="humana"),
        _neg(2, ia_justificable="SÍ"),
        _neg(3),
        _pos(4),
        _pos(5),
    ]
    pasos = construir_pasos(filas)
    assert [p["clave"] for p in pasos] == ["encuestas", "ia", "confirmar", "resultado"]
    assert [p["titulo"] for p in pasos] == ["Encuestas", "La IA revisa", "Tú confirmas", "Resultado"]
    assert [p["detalle"] for p in pasos[:3]] == [
        "5 encuestas · 3 negativas",
        "1 de 2 con propuesta",
        "1 de 3 confirmadas",
    ]
    assert pasos[3]["detalle"] == "CSAT final e informe"
    assert [p["estado"] for p in pasos] == ["hecho", "actual", "pendiente", "pendiente"]


def test_pasos_sin_negativos():
    filas = [_pos(1), _pos(2)]
    pasos = construir_pasos(filas)
    assert pasos[1]["detalle"] == "Sin negativos por revisar"
    assert [p["estado"] for p in pasos] == ["hecho", "hecho", "hecho", "hecho"]
    assert construir_fichas(filas) == []


def test_fichas_orden_y_textos():
    filas = [
        _neg(1, justificable="SÍ", origen_decision="ia_aceptada", ia_justificable="SÍ", ia_motivo="Fuera de control", motivo_inconformidad="", fecha_iso="2026-01-01"),
        _neg(2, ia_justificable="SÍ", ia_motivo="m", ia_confianza=0.9, ia_evidencia="e", fecha_iso="2026-01-05"),
        _pos(3),
    ]
    fichas = construir_fichas(filas)
    assert [f["row_id"] for f in fichas] == [2, 1]
    assert fichas[0]["ia"]["texto"] == "No fue culpa del agente"
    assert fichas[0]["confirmada"] is False
    assert fichas[0]["origen_texto"] == ""
    assert fichas[1]["origen_texto"] == "decidido por la IA"
    assert fichas[1]["motivo"] == "Fuera de control"
    assert fichas[1]["decision_texto"] == "No fue culpa del agente"
    assert fichas[1]["confirmada"] is True
    assert fichas[1]["estrellas"] == 1
    assert fichas[1]["conversation_id"] is None


def test_kpis():
    metricas = {"csat_original": 77.33, "csat_actualizado": 80.1, "negativos_si": 3, "negativos": 14, "negativos_pendientes": 5}
    kpis = construir_kpis(metricas)
    assert kpis["delta"] == 2.77
    assert kpis["excluidos"] == 3
    assert kpis["negativos"] == 14
    assert kpis["por_confirmar"] == 5


def test_pestanas():
    filas = [_neg(1, justificable="SÍ"), _neg(2), _pos(3)]
    assert contar_pestanas(filas) == {"por_confirmar": 1, "confirmados": 1, "todos": 2}


def test_contexto_incluye_vista():
    filas = [_neg(1), _pos(2)]
    vista = construir_contexto_analisis({"rows": filas})["vista"]
    assert set(vista) == {"kpis", "pasos", "fichas", "pestanas"}
    assert construir_vista(filas, {"csat_original": 1, "csat_actualizado": 1, "negativos_pendientes": 1})["kpis"]["por_confirmar"] == 1


def test_enlace_solo_http_o_https():
    fichas = construir_fichas(
        [
            _neg(1, enlace_conversacion="javascript:alert(1)"),
            _neg(2, enlace_conversacion="https://chat.test/c/2"),
            _neg(3, enlace_conversacion=" HTTP://chat.test/c/3"),
            _neg(4, enlace_conversacion="data:text/html,x"),
        ]
    )
    por_id = {f["row_id"]: f["enlace"] for f in fichas}
    assert por_id == {1: "", 2: "https://chat.test/c/2", 3: "HTTP://chat.test/c/3", 4: ""}


def test_ficha_lleva_puntaje_y_reglas_de_la_ia():
    fila = _neg(1, ia_justificable="NO", ia_puntaje=58, ia_reglas=["primera respuesta de 7 min"])
    ia = construir_fichas([fila])[0]["ia"]
    assert ia["puntaje"] == 58 and ia["reglas"] == ["primera respuesta de 7 min"]


def test_ficha_sin_puntaje_como_tras_reabrir():
    ia = construir_fichas([_neg(1, ia_justificable="SÍ")])[0]["ia"]
    assert ia["puntaje"] == "" and ia["reglas"] == []
