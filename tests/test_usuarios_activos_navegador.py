"""Comportamiento del botón «Actualizar datos» en un navegador real.

Requiere Playwright con Chromium (dependencia opcional de desarrollo, no está
en requirements.txt). Si no está instalado, estas pruebas se omiten.

La app corre en un servidor local (127.0.0.1) dentro del mismo proceso, así que
el bloqueo de red de conftest sigue activo; el navegador además aborta toda
petición que no vaya a ese servidor. Los servicios externos están simulados.
"""

import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server  # noqa: E402

import tools.usuarios_activos as usuarios_activos  # noqa: E402
from app import app  # noqa: E402


def _estado(activos, source="snapshot"):
    return {
        "data": [
            {
                "system": "Compinche",
                "active_users": activos,
                "running_users": 3,
                "active_by_promo_users": 0,
                "updated_at": "2026-09-26 09:15:00",
                "progress": "Completado",
                "error": None,
            }
        ],
        "updated_at": "2026-09-26 09:15:00",
        "source": source,
    }


CONFIG = {"llamadas": 0, "demora": 0.0, "falla": False}


def _actualizar_simulado():
    CONFIG["llamadas"] += 1
    time.sleep(CONFIG["demora"])
    if CONFIG["falla"]:
        raise RuntimeError("fallo simulado")
    return _estado(250)


@pytest.fixture(scope="module")
def servidor():
    parches = [
        pytest.MonkeyPatch(),
    ]
    mp = parches[0]
    mp.setattr(usuarios_activos, "obtener_estado_inicial_dashboard", lambda: _estado(120))
    mp.setattr(usuarios_activos, "iniciar_actualizacion_dashboard", _actualizar_simulado)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    mp.undo()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # Chromium no instalado
            pytest.skip(f"Chromium no disponible para Playwright: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def pagina(navegador, servidor):
    CONFIG.update(llamadas=0, demora=0.0, falla=False)
    contexto = navegador.new_context()
    page = contexto.new_page()
    posts = []
    errores = []

    def ruteo(route):
        if not route.request.url.startswith(servidor):
            return route.abort()
        if route.request.method == "POST" and route.request.url.endswith("/usuarios-activos/actualizar"):
            posts.append(time.monotonic())
        return route.continue_()

    page.route("**/*", ruteo)
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.goto(f"{servidor}/usuarios-activos/", wait_until="networkidle")
    yield page, posts, errores
    contexto.close()


def test_abrir_la_pagina_no_genera_post_de_actualizacion(pagina):
    page, posts, errores = pagina
    page.wait_for_timeout(600)
    assert posts == []
    assert CONFIG["llamadas"] == 0
    assert page.text_content("#summary-total-active").strip() == "120"
    assert errores == []


def test_un_clic_genera_exactamente_un_post_y_muestra_exito(pagina):
    page, posts, errores = pagina
    with page.expect_response(lambda r: r.url.endswith("/usuarios-activos/actualizar")):
        page.click("#actualizar-btn")
    page.wait_for_function("document.getElementById('actualizar-btn').disabled === false")
    assert len(posts) == 1
    assert CONFIG["llamadas"] == 1
    assert page.text_content("#summary-total-active").strip() == "250"
    assert page.text_content("#actualizar-feedback").strip() == "Datos actualizados."
    assert errores == []


def test_doble_clic_no_genera_actualizaciones_concurrentes_y_deshabilita_el_boton(pagina):
    page, posts, errores = pagina
    CONFIG["demora"] = 0.8
    page.dblclick("#actualizar-btn")
    page.wait_for_timeout(150)
    assert page.evaluate("document.getElementById('actualizar-btn').disabled") is True
    assert page.text_content("#actualizar-btn").strip() == "Actualizando..."
    # Una llamada directa mientras hay otra en curso también se ignora.
    page.evaluate("actualizarDatos()")
    page.wait_for_function("document.getElementById('actualizar-btn').disabled === false", timeout=5000)
    assert len(posts) == 1
    assert CONFIG["llamadas"] == 1
    assert page.text_content("#actualizar-btn").strip() == "Actualizar datos"
    assert errores == []


def test_error_restaura_el_ultimo_estado_y_reactiva_el_boton(pagina):
    page, posts, errores = pagina
    CONFIG["falla"] = True
    with page.expect_response(lambda r: r.url.endswith("/usuarios-activos/actualizar")):
        page.click("#actualizar-btn")
    page.wait_for_function("document.getElementById('actualizar-btn').disabled === false")
    assert len(posts) == 1
    assert "No se pudieron actualizar los datos" in page.text_content("#actualizar-feedback")
    # Se mantiene el snapshot anterior y el estado de la tarjeta no queda en «Atención».
    assert page.text_content("#summary-total-active").strip() == "120"
    assert page.text_content("#compinche-status").strip() == "Operativo"
    assert errores == []
