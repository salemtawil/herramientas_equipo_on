"""Navegación lateral: marcado accesible y comportamiento móvil.

Las pruebas de navegador requieren Playwright con Chromium (opcional); si no
está disponible se omiten. No se comparan píxeles: solo visibilidad, atributos
ARIA, foco y ausencia de desbordamiento horizontal.
"""

import re
import threading

import pytest

from app import app


def test_boton_de_menu_tiene_atributos_aria_y_etiqueta():
    html = app.test_client().get("/").get_data(as_text=True)
    boton = re.search(r"<button[^>]*data-sidebar-toggle[^>]*>(.*?)</button>", html, re.S)
    assert boton, "No se encontró el botón del menú"
    etiqueta = boton.group(0)
    assert 'aria-controls="app-sidebar-nav"' in etiqueta
    assert 'aria-expanded="true"' in etiqueta
    assert 'type="button"' in etiqueta
    assert "sidebar-icon-toggle__label" in boton.group(1)
    assert '<nav class="app-sidebar__nav" id="app-sidebar-nav" aria-label="Navegación principal">' in html


def test_script_de_cabecera_marca_js_antes_de_cargar_estilos():
    html = app.test_client().get("/").get_data(as_text=True)
    head = html[: html.index("</head>")]
    assert head.index('classList.add("js")') < head.index("styles.css")
    assert "styles.css?v=21" in head


def test_todas_las_rutas_principales_mantienen_la_navegacion():
    cliente = app.test_client()
    rutas = ["/", "/usuarios-activos/", "/reporte-agentes", "/turnos-trabajo", "/comparar-csv",
             "/usuarios-a-sheets", "/auditoria-csat", "/auditoria-salientes", "/break-admin",
             "/informe-semanal-cs"]
    for ruta in rutas:
        html = cliente.get(ruta).get_data(as_text=True)
        assert len(re.findall(r'<a class="sidebar-link[ "]', html)) == 10, ruta
        assert html.count('aria-current="page"') == 1, ruta
        assert 'href="#contenido-principal"' in html, ruta


# ---------------------------------------------------------------------------
# Navegador real (opcional)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def servidor():
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", 0, app, threaded=True)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium no disponible para Playwright: {exc}")
        yield browser
        browser.close()


def _abrir(navegador, servidor, ancho, js=True):
    contexto = navegador.new_context(viewport={"width": ancho, "height": 800}, java_script_enabled=js)
    page = contexto.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(servidor) else r.abort())
    page.goto(f"{servidor}/comparar-csv", wait_until="load")
    return contexto, page


def _sin_desbordamiento(page):
    return page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_movil_menu_cerrado_se_abre_y_cierra_con_escape(navegador, servidor):
    contexto, page = _abrir(navegador, servidor, 390)
    try:
        boton = page.locator("[data-sidebar-toggle]")
        nav = page.locator("#app-sidebar-nav")
        assert nav.is_hidden()
        assert boton.get_attribute("aria-expanded") == "false"
        assert boton.get_attribute("aria-label") == "Abrir menú"
        assert _sin_desbordamiento(page)

        boton.click()
        assert nav.is_visible()
        assert boton.get_attribute("aria-expanded") == "true"
        assert page.evaluate("document.activeElement.classList.contains('sidebar-link')")

        page.keyboard.press("Escape")
        assert nav.is_hidden()
        assert boton.get_attribute("aria-expanded") == "false"
        assert page.evaluate("document.activeElement.hasAttribute('data-sidebar-toggle')")
        assert _sin_desbordamiento(page)
    finally:
        contexto.close()


def test_movil_sin_javascript_la_navegacion_sigue_visible(navegador, servidor):
    contexto, page = _abrir(navegador, servidor, 390, js=False)
    try:
        assert page.locator("#app-sidebar-nav").is_visible()
        assert page.locator("[data-sidebar-toggle]").is_hidden()
    finally:
        contexto.close()


def test_escritorio_menu_visible_y_colapsable(navegador, servidor):
    contexto, page = _abrir(navegador, servidor, 1440)
    try:
        boton = page.locator("[data-sidebar-toggle]")
        nav = page.locator("#app-sidebar-nav")
        assert nav.is_visible()
        boton.click()
        assert nav.is_hidden()
        assert boton.get_attribute("aria-expanded") == "false"
        assert boton.is_visible()
        boton.click()
        assert nav.is_visible()
        assert boton.get_attribute("aria-expanded") == "true"
    finally:
        contexto.close()


def test_primer_tab_enfoca_saltar_al_contenido(navegador, servidor):
    contexto, page = _abrir(navegador, servidor, 1440)
    try:
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.textContent.trim()") == "Saltar al contenido"
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.id") == "contenido-principal"
    finally:
        contexto.close()
