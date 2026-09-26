"""Confirmaciones de acciones destructivas y protección contra doble envío.

Requiere Playwright con Chromium (opcional); si no está disponible se omite.
Los POST se interceptan en el navegador: el servidor nunca los recibe, así que
estas pruebas no modifican datos.
"""

import threading
from urllib.parse import parse_qs

import pytest

from app import app


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


def _pagina(navegador, servidor, ruta, envios, respuesta="<p>ok</p>", cabeceras=None):
    contexto = navegador.new_context(viewport={"width": 1280, "height": 900})
    page = contexto.new_page()

    def manejar(route):
        req = route.request
        if not req.url.startswith(servidor):
            route.abort()
            return
        if req.method == "POST":
            envios.append({"url": req.url, "datos": req.post_data or ""})
            route.fulfill(status=200, body=respuesta, headers=cabeceras or {"Content-Type": "text/html"})
            return
        route.continue_()

    page.route("**/*", manejar)
    page.goto(f"{servidor}{ruta}", wait_until="load")
    return contexto, page


def _abrir_detalles(page, selector_form):
    page.evaluate(
        "sel => { const f = document.querySelector(sel); let d = f && f.closest('details'); if (d) d.open = true; }",
        selector_form,
    )


FORM_LIMPIAR = 'form[action$="/limpiar-asignaciones"]'


def test_cancelar_confirmacion_no_envia_y_devuelve_el_foco(navegador, servidor):
    envios = []
    contexto, page = _pagina(navegador, servidor, "/turnos-trabajo", envios)
    try:
        _abrir_detalles(page, FORM_LIMPIAR)
        boton = page.locator(f"{FORM_LIMPIAR} button[type=submit]")
        boton.click()
        dialogo = page.locator("#confirm-dialog")
        assert dialogo.is_visible()
        assert "Sin turno" in page.locator("#confirm-dialog-text").inner_text()
        assert page.locator("#confirm-dialog [data-confirm-accept]").inner_text().strip() == "Limpiar turnos"
        page.keyboard.press("Escape")
        assert not dialogo.is_visible()
        page.wait_for_timeout(200)
        assert envios == []
        assert page.evaluate("document.activeElement.textContent.trim()") == "Limpiar turnos"
        # Cancelar con el botón tampoco envía.
        boton.click()
        page.locator("#confirm-dialog [data-confirm-cancel]").click()
        page.wait_for_timeout(200)
        assert envios == []
    finally:
        contexto.close()


def test_aceptar_confirmacion_envia_una_sola_vez(navegador, servidor):
    envios = []
    contexto, page = _pagina(navegador, servidor, "/turnos-trabajo", envios)
    try:
        _abrir_detalles(page, FORM_LIMPIAR)
        page.fill("#confirmar-limpieza", "SI")
        page.locator(f"{FORM_LIMPIAR} button[type=submit]").click()
        page.locator("#confirm-dialog [data-confirm-accept]").click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(300)
        assert len(envios) == 1
        assert parse_qs(envios[0]["datos"]).get("confirmacion") == ["SI"]
    finally:
        contexto.close()


def test_doble_clic_en_envio_produce_un_solo_post_y_conserva_el_boton(navegador, servidor):
    envios = []
    contexto, page = _pagina(navegador, servidor, "/usuarios-a-sheets", envios)
    try:
        boton = page.locator('button[name="accion"]').first
        valor = boton.get_attribute("value")
        page.evaluate(
            """() => {
                const b = document.querySelector('button[name="accion"]');
                b.click(); b.click(); b.click();
            }"""
        )
        page.wait_for_load_state("load")
        page.wait_for_timeout(300)
        assert len(envios) == 1
        assert f'name="accion"\r\n\r\n{valor}' in envios[0]["datos"]
    finally:
        contexto.close()


def test_descarga_en_formulario_multiboton_conserva_accion_y_libera_el_formulario(navegador, servidor):
    envios = []
    contexto, page = _pagina(
        navegador, servidor, "/comparar-csv", envios, respuesta="a,b\n1,2\n",
        cabeceras={"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=x.csv"},
    )
    try:
        with page.expect_download():
            page.locator('button[value="descargar_comparativa"]').click()
        assert len(envios) == 1
        assert "descargar_comparativa" in envios[0]["datos"]
        assert not page.locator("#global-processing-overlay").evaluate("el => el.classList.contains('is-visible')")
        page.wait_for_timeout(2800)
        assert page.locator('button[value="comparar_csv"]').is_enabled()
        assert page.locator('button[value="descargar_comparativa"]').is_enabled()
        assert page.evaluate("!document.querySelector('form[data-submitting]')")
    finally:
        contexto.close()
