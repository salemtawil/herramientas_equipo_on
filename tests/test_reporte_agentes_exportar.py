"""Descarga del reporte de agentes (Word, PDF y texto) desde los datos ya cargados."""

import io
import json
import re
import threading
import zipfile

import pytest

from app import ASSET_VERSIONS, app

CSV = (
    "First Name,Last Name,Calls,Outgoing calls,Missed calls,Call seconds,Outgoing call seconds,Worktime\n"
    "Ana,Ruiz,10,70,1,600,1200,01:00:00\n"
    "Beto,Paz,5,2,0,300,60,01:00:00\n"
)


def _enviar_csv(cliente):
    return cliente.post(
        "/reporte-agentes",
        data={"accion": "procesar_csv", "archivo": (io.BytesIO(CSV.encode()), "reporte.csv")},
        content_type="multipart/form-data",
    )


def _datos(html):
    bloque = re.search(r'<script type="application/json" id="reporte-datos-exportacion"[^>]*>(.*?)</script>', html, re.S)
    assert bloque, "No se encontraron los datos de exportación"
    return json.loads(bloque.group(1))


def test_sin_reporte_no_hay_descarga():
    html = app.test_client().get("/reporte-agentes").get_data(as_text=True)
    assert "data-exportar-reporte" not in html
    assert "reporte_exportar.js" not in html


def test_con_reporte_aparecen_botones_y_datos_completos():
    html = _enviar_csv(app.test_client()).get_data(as_text=True)
    for formato in ("docx", "pdf", "txt"):
        assert f'data-exportar-reporte="{formato}"' in html
    assert f"reporte_exportar.js?v={ASSET_VERSIONS['reporte_exportar.js']}" in html
    assert f"reporte_impresion.css?v={ASSET_VERSIONS['reporte_impresion.css']}" in html

    datos = _datos(html)
    resumen = dict(datos["resumen"])
    assert resumen["Agentes"] == 2 and resumen["Llamadas"] == 15 and resumen["Salientes"] == 72
    assert datos["resumen_turnos"]["columnas"][0] == "Turno"
    assert datos["resumen_turnos"]["total"][0] == "TOTAL"
    assert datos["resumen_turnos"]["total"][2] == 15
    assert datos["fuente"] == "CSV reporte.csv"
    nombres = [fila[0] for turno in datos["turnos"] for fila in turno["filas"]]
    assert sorted(nombres) == ["Ana", "Beto"]
    for turno in datos["turnos"]:
        assert turno["columnas"][0] == "Nombre"
        assert turno["total"][0] == "TOTAL"


# ---------------------------------------------------------------------------
# Navegador real (opcional): genera los archivos y comprueba su contenido.
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


def test_descargas_word_y_texto(navegador, servidor, tmp_path):
    archivo = tmp_path / "reporte.csv"
    archivo.write_text(CSV, encoding="utf-8")
    contexto = navegador.new_context(accept_downloads=True)
    page = contexto.new_page()
    errores = []
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(servidor) else r.abort())
    try:
        page.goto(f"{servidor}/reporte-agentes")
        page.set_input_files("input[name=archivo]", str(archivo))
        with page.expect_navigation():
            page.evaluate("() => { const f = document.querySelector('input[name=archivo]').form; f.requestSubmit(f.querySelector('button[type=submit]')); }")

        with page.expect_download() as descarga:
            page.click('[data-exportar-reporte="txt"]')
        texto = open(descarga.value.path(), encoding="utf-8-sig").read()
        assert descarga.value.suggested_filename.endswith(".txt")
        assert "RESUMEN GENERAL" in texto and "RESUMEN POR TURNO" in texto
        assert "Ana" in texto and "Beto" in texto and "TOTAL" in texto

        with page.expect_download() as descarga:
            page.click('[data-exportar-reporte="docx"]')
        assert descarga.value.suggested_filename.endswith(".docx")
        with zipfile.ZipFile(descarga.value.path()) as docx:
            assert docx.testzip() is None
            documento = docx.read("word/document.xml").decode("utf-8")
            assert "word/styles.xml" in docx.namelist()
        assert "Resumen por turno" in documento and "Ana" in documento and "Beto" in documento

        page.click('[data-exportar-reporte="pdf"]')
        page.wait_for_function("() => { const f = document.querySelector('iframe'); return f && f.contentDocument && f.contentDocument.querySelector('h1'); }")
        assert "Resumen general" in page.evaluate("() => document.querySelector('iframe').contentDocument.body.textContent")
        assert errores == []
    finally:
        contexto.close()
