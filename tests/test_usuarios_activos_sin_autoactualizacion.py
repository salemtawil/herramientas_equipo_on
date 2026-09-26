"""Usuarios activos: abrir la página nunca consulta sistemas externos.

Pruebas de servidor (siempre se ejecutan). El comportamiento del botón en el
navegador está en ``test_usuarios_activos_navegador.py``.
"""

import re
from unittest.mock import patch

from app import app

SNAPSHOT = {
    "data": [
        {
            "system": "Compinche",
            "active_users": 7,
            "running_users": 4,
            "updated_at": "2026-09-26 09:15:00",
            "progress": "Completado",
            "error": None,
        }
    ],
    "updated_at": "2026-09-26 09:15:00",
    "source": "snapshot",
}


def _html_usuarios_activos():
    respuesta = app.test_client().get("/usuarios-activos/")
    assert respuesta.status_code == 200
    return respuesta.get_data(as_text=True)


def test_get_no_ejecuta_la_actualizacion_externa():
    with patch("tools.servicios_usuarios_activos._ejecutar_actualizacion_total") as actualizacion, patch(
        "tools.servicios_usuarios_activos.obtener_metricas_multiadmin"
    ) as multiadmin, patch("tools.usuarios_activos.iniciar_actualizacion_dashboard") as dashboard:
        _html_usuarios_activos()
    actualizacion.assert_not_called()
    multiadmin.assert_not_called()
    dashboard.assert_not_called()
    # Además, conftest hace fallar este test si hubo cualquier intento de red.


def test_template_no_programa_una_actualizacion_al_cargar():
    html = _html_usuarios_activos()
    script = html[html.index("window.__USUARIOS_ACTIVOS_INITIAL_STATE__"):]
    assert "setTimeout(actualizarDatos" not in script
    assert "consultarEstado" not in script
    # La única llamada a actualizarDatos() está en el botón.
    assert re.findall(r"(?<!function )actualizarDatos\(\)", html) == ["actualizarDatos()"]
    assert 'onclick="actualizarDatos()"' in html


def test_snapshot_inicial_se_sigue_mostrando():
    with patch("tools.usuarios_activos.obtener_estado_inicial_dashboard", return_value=SNAPSHOT):
        html = _html_usuarios_activos()
    assert "Última actualización general (ET): 2026-09-26 09:15:00" in html
    estado = html.replace("&#34;", '"')
    assert '"source": "snapshot"' in estado
    assert '"active_users": 7' in estado


def test_texto_explica_cuando_se_consultan_los_sistemas():
    html = _html_usuarios_activos()
    assert "Al abrir se muestra el último snapshot disponible" in html
    assert "solo se consultan cuando pulsas «Actualizar datos»" in html
    assert "Si todavía no existe, muestra el estado inicial de cada sistema" in html


def test_contrato_json_de_api_y_actualizar_sin_cambios():
    cliente = app.test_client()
    with patch("tools.usuarios_activos.obtener_estado_actual_con_metadata", return_value=SNAPSHOT):
        api = cliente.get("/usuarios-activos/api")
    with patch("tools.usuarios_activos.iniciar_actualizacion_dashboard", return_value=SNAPSHOT):
        actualizar = cliente.post("/usuarios-activos/actualizar")

    for respuesta in (api, actualizar):
        assert respuesta.status_code == 200
        data = respuesta.get_json()
        assert set(data) == {"success", "data", "updated_at", "source"}
        assert data["success"] is True
        assert data["data"] == SNAPSHOT["data"]
        assert data["updated_at"] == SNAPSHOT["updated_at"]
        assert data["source"] == "snapshot"
