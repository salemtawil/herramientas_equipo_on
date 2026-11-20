import pytest

from utils.auditoria_chats_rubrica import (
    CRITERIOS_QA,
    FALLAS_CRITICAS,
    PROCEDIMIENTOS,
    RUBRICA_TEXTO,
    calcular_qa,
    construir_mensajes_clasificacion,
    construir_mensajes_evaluacion,
    requiere_revision_qa,
    validar_clasificacion,
    validar_evaluacion,
)

CODIGOS = [c for c, _, _ in CRITERIOS_QA]


def _todo(resultado="cumple"):
    return {c: resultado for c in CODIGOS}


def test_pesos_suman_cien_y_hay_17_criterios():
    assert len(CRITERIOS_QA) == 17
    assert sum(p for _, _, p in CRITERIOS_QA) == 100
    assert len(FALLAS_CRITICAS) == 10
    assert sorted(PROCEDIMIENTOS) == [f"P{n:02d}" for n in range(1, 15)]


def test_calcular_qa_todo_cumple():
    assert calcular_qa(_todo()) == {"qa": 100.0, "pct_verificable": 100.0, "estado": "aprobado"}


def test_calcular_qa_excluye_no_aplica_y_no_verificable():
    crit = _todo()
    crit.update(B1="no_verificable", C1="no_verificable", F2="no_aplica", A1="parcial", B2="no_cumple")
    # evaluables 98, verificables 78, obtenidos 78 - 4 - 10 = 64 → 82,1
    assert calcular_qa(crit) == {"qa": 82.1, "pct_verificable": 79.6, "estado": "necesita_mejorar"}


def test_calcular_qa_cortes():
    crit = _todo()
    crit.update(A1="no_cumple", A2="no_cumple")  # 85
    assert calcular_qa(crit) == {"qa": 85.0, "pct_verificable": 100.0, "estado": "aprobado"}
    crit = _todo()
    crit.update(B1="no_cumple", B2="no_cumple", B3="no_cumple")  # 70
    assert calcular_qa(crit)["estado"] == "necesita_mejorar"
    crit["D4"] = "no_cumple"  # 67
    assert calcular_qa(crit)["estado"] == "no_aprobado"


def test_calcular_qa_sin_verificables_es_pendiente():
    r = calcular_qa(_todo("no_verificable"))
    assert r["qa"] is None and r["estado"] == "pendiente"
    r = calcular_qa(_todo("no_aplica"))
    assert r == {"qa": None, "pct_verificable": None, "estado": "pendiente"}


def test_falla_sospechosa_pendiente_y_confirmada_no_aprobado():
    assert calcular_qa(_todo(), fallas_sospechosas=1)["estado"] == "pendiente"
    r = calcular_qa(_todo(), fallas_confirmadas=1, fallas_sospechosas=1)
    assert r["estado"] == "no_aprobado" and r["qa"] == 100.0


def _evaluacion(**cambios):
    data = {
        "criterios": {c: {"resultado": "cumple", "evidencias": ["m1"], "comentario": "Bien."} for c in CODIGOS},
        "fallas_criticas": [],
        "cumplimientos": ["Saluda"],
        "incumplimientos": [],
        "recomendaciones": ["Despedirse"],
        "estado_resolucion": "resuelto",
        "responsabilidad": "agente",
        "satisfaccion_cliente": "satisfecho",
        "resumen": "Todo bien.",
        "confianza": "alta",
    }
    data.update(cambios)
    return data


def test_validar_evaluacion_filtra_evidencias_y_fallas_desconocidas():
    data = _evaluacion(
        fallas_criticas=[
            {"codigo": "CR04", "evidencias": ["m2", "m99"], "descripcion": "Insulto"},
            {"codigo": "CR99", "evidencias": [], "descripcion": "x"},
        ]
    )
    data["criterios"]["A1"]["evidencias"] = ["m1", "m77", "2"]
    r = validar_evaluacion(data, {"m1", "m2"})
    assert r["criterios"]["A1"]["evidencias"] == ["m1", "m2"]
    assert r["fallas_criticas"] == [
        {"codigo": "CR04", "evidencias": ["m2"], "descripcion": "Insulto", "estado": "sospechosa"}
    ]
    assert r["recomendaciones"] == ["Despedirse"]


def test_validar_evaluacion_normaliza_resultados():
    data = _evaluacion()
    data["criterios"]["B1"]["resultado"] = "NO VERIFICABLE"
    data["criterios"]["B2"]["resultado"] = "No cumple"
    r = validar_evaluacion(data, {"m1"})
    assert r["criterios"]["B1"]["resultado"] == "no_verificable"
    assert r["criterios"]["B2"]["resultado"] == "no_cumple"


def test_validar_evaluacion_criterio_faltante_o_invalido_lanza():
    data = _evaluacion()
    del data["criterios"]["E3"]
    with pytest.raises(ValueError):
        validar_evaluacion(data, {"m1"})
    data = _evaluacion()
    data["criterios"]["E3"]["resultado"] = "excelente"
    with pytest.raises(ValueError):
        validar_evaluacion(data, {"m1"})


def test_validar_clasificacion_descarta_codigos_desconocidos_y_limita_extra():
    data = {
        "motivo_principal": "Pide una pausa",
        "motivos_secundarios": ["Pregunta por precios"],
        "procedimientos": ["P03", "p07", "P99"],
        "secciones_extra": ["1.1.5", "1.1.6", "9.9", "1.5.1", "1.5.2", "1.5.3"],
        "servicio": "Compinche",
    }
    r = validar_clasificacion(data, {"1.1.5", "1.1.6", "1.5.1", "1.5.2", "1.5.3"})
    assert r["procedimientos"] == ["P03", "P07"]
    assert r["secciones_extra"] == ["1.1.5", "1.1.6", "1.5.1", "1.5.2"]
    assert r["motivo_principal"] == "Pide una pausa"
    with pytest.raises(ValueError):
        validar_clasificacion({"procedimientos": []}, set())


def test_requiere_revision_qa():
    base = {"estado": "aprobado", "confianza": "alta"}
    assert requiere_revision_qa(base, False) is False
    assert requiere_revision_qa(dict(base, estado="necesita_mejorar"), False) is True
    assert requiere_revision_qa(dict(base, confianza="baja"), False) is True
    assert requiere_revision_qa(None, True) is True


def test_mensajes_clasificacion_incluyen_indice_y_procedimientos():
    mensajes = construir_mensajes_clasificacion("[m1 10:00:00] Cliente: hola", [{"codigo": "1.4.1", "titulo": "Criterios para pausas"}])
    texto = mensajes[0]["content"] + mensajes[1]["content"]
    assert "1.4.1 Criterios para pausas" in texto and "P03" in texto and "[m1 10:00:00]" in texto


def test_mensajes_evaluacion_incluyen_rubrica_secciones_y_metricas():
    mensajes = construir_mensajes_evaluacion(
        transcripcion="[m1 10:00:00] Cliente: hola",
        agente_nombre="LuisM",
        canal="WhatsApp",
        clasificacion={"motivo_principal": "Pausa", "procedimientos": ["P03"]},
        secciones=[{"codigo": "1.4.1", "titulo": "Criterios para pausas", "texto": "Texto de la pausa"}],
        metricas={"primera_respuesta": {"segundos": 90}},
        periodo={"desde": "m1", "hasta": None, "inferido": True},
    )
    assert mensajes[0]["content"].startswith(RUBRICA_TEXTO[:40])
    usuario = mensajes[1]["content"]
    for esperado in ("LuisM", "WhatsApp", "Texto de la pausa", "1.4.1", '"segundos": 90', "m1"):
        assert esperado in usuario


def test_documentacion_f2_nunca_se_evalua_desde_el_chat():
    data = _evaluacion()
    data["criterios"]["F2"]["resultado"] = "no_cumple"
    r = validar_evaluacion(data, {"m1"})
    assert r["criterios"]["F2"]["resultado"] == "no_aplica"
    assert calcular_qa({c: v["resultado"] for c, v in r["criterios"].items()})["qa"] == 100.0


def test_prompt_no_exige_saludo_con_nombre_ni_notas():
    sistema = construir_mensajes_evaluacion(
        transcripcion="", agente_nombre="A", canal="", clasificacion={}, secciones=[], metricas={}, periodo={}
    )[0]["content"]
    assert "AJUSTES DE COMPINCHE" in sistema
    assert "no exijas que el agente se presente con su nombre" in sistema.lower()
    assert "notas obligatorias" in sistema.lower()
