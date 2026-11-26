"""Criterios del equipo que usa la IA para auditar negativos de CSAT."""
import json

import tools.auditoria_csat as csat
from utils import auditoria_csat_criterios as criterios


def test_rubrica_suma_100():
    assert len(criterios.RUBRICA) == 12
    assert sum(peso for _, peso in criterios.RUBRICA) == 100


def test_definiciones_cubren_todos_los_motivos():
    assert set(criterios.DEFINICIONES_MOTIVOS) == set(csat.MOTIVOS_INCONFORMIDAD)
    assert all(texto.strip() for texto in criterios.DEFINICIONES_MOTIVOS.values())


def test_instrucciones_contienen_reglas_clave():
    texto = criterios.construir_instrucciones()
    for clave in ("5 min", "3 min", "15 min", "70%", "PMF", "ladesk", "crisp", "TAL VEZ", "metricas_tiempo"):
        assert clave in texto, clave
    assert csat.construir_instrucciones_auditoria_ia() == texto


def test_payload_incluye_definiciones():
    payload = csat.construir_payload_lote_auditoria_ia([])
    datos = json.loads(payload.split("Casos:\n", 1)[1])
    assert datos["definiciones_motivos"] == criterios.DEFINICIONES_MOTIVOS


def test_esquema_pide_puntaje_y_reglas():
    esquema = csat.esquema_auditoria_ia()
    assert {"puntaje", "reglas_incumplidas"} <= set(esquema["required"])
    assert esquema["properties"]["reglas_incumplidas"]["type"] == "array"


def _fila():
    return {"row_id": "1", "tipo_rating": "Negativo", "justificable": "", "transcripcion_conversacion": ""}


def test_aplicar_resultado_normaliza_puntaje_y_reglas():
    base = {"justificable": "NO", "motivo_inconformidad": "OTRO", "confianza": 0.5}
    fila = _fila()
    csat.aplicar_resultado_ia(fila, dict(base, puntaje=135, reglas_incumplidas=["a"] * 7), "m")
    assert fila["ia_puntaje"] == 100 and len(fila["ia_reglas"]) == 5

    fila = _fila()
    csat.aplicar_resultado_ia(fila, dict(base, puntaje="abc", reglas_incumplidas="no es lista"), "m")
    assert fila["ia_puntaje"] == "" and fila["ia_reglas"] == []

    fila = _fila()
    csat.aplicar_resultado_ia(fila, dict(base, puntaje=58.6, reglas_incumplidas=["x" * 300, "", "primera respuesta de 7 min"]), "m")
    assert fila["ia_puntaje"] == 59
    assert fila["ia_reglas"] == ["x" * 160, "primera respuesta de 7 min"]


def test_filas_nuevas_inician_sin_puntaje():
    import pandas as pd

    df = pd.DataFrame([{"Nombre del agente": "A", "Calificación": "1", "Comentario de opinión": "mal",
                        "Enlace a la conversación": "", "Fecha registrada": "2025-11-10"}])
    fila = csat.construir_estado_inicial(df, "x.csv")["rows"][0]
    assert fila["ia_puntaje"] == "" and fila["ia_reglas"] == []
