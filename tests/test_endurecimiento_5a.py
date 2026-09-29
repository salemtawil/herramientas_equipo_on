"""Lote 5a: cabeceras, caché, robots, diagnóstico de promo y avisos de almacenamiento."""

import logging
from unittest.mock import patch

import pytest

import utils.turnos_trabajo_store as store
from app import ASSET_VERSIONS, ROBOTS_TAG, app

CABECERAS_COMUNES = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
}


@pytest.fixture
def cliente():
    return app.test_client()


# ---------- Cabeceras y rastreo ----------


@pytest.mark.parametrize("ruta", ["/", "/comparar-csv", "/usuarios-activos/api"])
def test_cabeceras_de_seguridad_en_html_y_json(cliente, ruta):
    respuesta = cliente.get(ruta)
    for nombre, valor in CABECERAS_COMUNES.items():
        assert respuesta.headers[nombre] == valor
    assert "camera=()" in respuesta.headers["Permissions-Policy"]
    assert respuesta.headers["X-Robots-Tag"] == ROBOTS_TAG
    assert respuesta.headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" not in respuesta.headers  # solo modo informe
    csp = respuesta.headers["Content-Security-Policy-Report-Only"]
    assert "default-src 'self'" in csp and "report-uri" not in csp and "report-to" not in csp
    assert "Strict-Transport-Security" not in respuesta.headers


def test_html_incluye_meta_noindex(cliente):
    assert '<meta name="robots" content="noindex, nofollow, noarchive">' in cliente.get("/").get_data(as_text=True)


def test_robots_txt_pide_no_rastrear(cliente):
    respuesta = cliente.get("/robots.txt")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "text/plain"
    assert respuesta.get_data(as_text=True) == "User-agent: *\nDisallow: /\n"


# ---------- Caché ----------


def test_estatico_con_version_vigente_tiene_cache_larga(cliente):
    for archivo, version in ASSET_VERSIONS.items():
        respuesta = cliente.get(f"/static/{archivo}?v={version}")
        assert respuesta.status_code == 200
        assert respuesta.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        respuesta.close()


def test_estatico_con_version_antigua_o_sin_version_revalida(cliente):
    for url in ("/static/styles.css?v=21", "/static/styles.css?v=22", "/static/styles.css", "/static/system-logos/compinche_48.svg"):
        respuesta = cliente.get(url)
        assert respuesta.headers["Cache-Control"] == "no-cache", url
        respuesta.close()


def test_html_referencia_las_versiones_vigentes(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert f"styles.css?v={ASSET_VERSIONS['styles.css']}" in html
    assert f"app.js?v={ASSET_VERSIONS['app.js']}" in html
    assert ASSET_VERSIONS["styles.css"] == "23"
    assert "styles.css?v=21" not in html
    assert "styles.css?v=22" not in html


def test_exportacion_no_se_cachea(cliente):
    csv = "First Name,Last Name,Calls,Outgoing calls,Missed calls,Call seconds,Outgoing call seconds,Worktime\nAna,Ruiz,1,1,0,60,60,01:00:00\n"
    import io

    respuesta = cliente.post(
        "/comparar-csv",
        data={
            "accion": "descargar_comparativa",
            "archivo_base": (io.BytesIO(csv.encode()), "a.csv"),
            "archivo_actual": (io.BytesIO(csv.encode()), "b.csv"),
        },
        content_type="multipart/form-data",
    )
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "text/csv"
    assert respuesta.headers["Cache-Control"] == "no-store"


# ---------- Diagnóstico de promo: GET → POST ----------


def test_promo_diagnostico_get_no_consulta_y_responde_405(cliente):
    with patch("tools.usuarios_activos.obtener_diagnostico_promo_compinche") as diagnostico:
        respuesta = cliente.get("/usuarios-activos/compinche/promo-diagnostico")
    assert respuesta.status_code == 405
    diagnostico.assert_not_called()


def test_promo_diagnostico_post_conserva_el_json_de_exito(cliente):
    with patch("tools.usuarios_activos.obtener_diagnostico_promo_compinche", return_value={"promo": 3}):
        respuesta = cliente.post("/usuarios-activos/compinche/promo-diagnostico")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"success": True, "data": {"promo": 3}}


# ---------- Almacenamiento visible ----------


def test_modo_local_sin_aviso(cliente):
    assert store.obtener_estado_almacenamiento()["mode"] == "local"
    html = cliente.get("/turnos-trabajo").get_data(as_text=True)
    assert "storage-banner" not in html


def test_modo_temporal_en_vercel_sin_supabase_muestra_aviso(cliente, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    estado = store.obtener_estado_almacenamiento()
    assert estado["mode"] == "temporal" and estado["persistente"] is False
    html = cliente.get("/turnos-trabajo").get_data(as_text=True)
    assert "storage-banner--temporal" in html
    assert "Supabase no está configurado" in html
    # Solo en pantallas que usan el almacenamiento de turnos.
    assert "storage-banner" not in cliente.get("/comparar-csv").get_data(as_text=True)


def test_modo_supabase_correcto_sin_aviso(cliente, monkeypatch):
    monkeypatch.setattr(store, "usar_supabase", lambda: True)
    monkeypatch.setattr(store, "_STORAGE_WARNING", "")
    estado = store.obtener_estado_almacenamiento()
    assert estado["mode"] == "supabase" and estado["persistente"] is True


def test_fallo_de_supabase_muestra_aviso_sin_detalles_internos(cliente, monkeypatch, caplog):
    secreto = "https://proyecto-secreto.supabase.co clave=sb_secret_123"
    monkeypatch.setattr(store, "usar_supabase", lambda: True)
    monkeypatch.setattr(store, "_STORAGE_WARNING", "")

    def falla():
        raise store.TurnosTrabajoStorageError("No se pudo leer") from RuntimeError(secreto)

    monkeypatch.setattr(store, "cargar_estado_supabase", falla)
    with caplog.at_level(logging.WARNING, logger=store.logger.name):
        html = cliente.get("/turnos-trabajo").get_data(as_text=True)

    assert "storage-banner--fallback" in html
    assert "Supabase no respondió" in html
    assert "proyecto-secreto" not in html and "sb_secret" not in html
    registros = "\n".join(r.getMessage() for r in caplog.records)
    assert "Supabase falló al leer (RuntimeError)" in registros
    assert "proyecto-secreto" not in registros and "sb_secret" not in registros


def test_registro_de_modo_al_iniciar_sin_secretos(caplog, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with caplog.at_level(logging.INFO, logger=store.logger.name):
        store.registrar_modo_almacenamiento()
    mensaje = caplog.records[-1].getMessage()
    assert mensaje == "Almacenamiento de turnos: modo=temporal persistente=False"
    assert caplog.records[-1].levelno == logging.WARNING
