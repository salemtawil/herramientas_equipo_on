import logging
import os
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from utils.archivos import formatear_tamano_bytes
from utils.env import cargar_env_local
from utils.navegacion import grupos_de_navegacion, herramienta_activa

cargar_env_local()

from tools.auditoria_csat import auditoria_csat_bp
from tools.auditoria_salientes import auditoria_salientes_bp
from tools.break_admin import break_admin_bp
from tools.informe_semanal_cs import informe_semanal_cs_bp
from tools.reporte_agentes import reporte_agentes_bp
from tools.turnos_trabajo import turnos_trabajo_bp
from tools.usuarios_activos import usuarios_activos_bp
from tools.comparar_csv import comparar_csv_bp
from tools.usuarios_a_sheets import usuarios_a_sheets_bp
from utils.turnos_trabajo_store import obtener_estado_almacenamiento, registrar_modo_almacenamiento

app = Flask(__name__)
# Límite total del cuerpo de la petición (archivos + campos). Flask responde 413 si se supera.
app.config["MAX_CONTENT_LENGTH"] = int(
    os.getenv("MAX_CONTENT_LENGTH", str(50 * 1024 * 1024))
)
app.config["MAX_FORM_MEMORY_SIZE"] = int(
    os.getenv("MAX_FORM_MEMORY_SIZE", str(8 * 1024 * 1024))
)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

flask_secret_key = os.getenv("FLASK_SECRET_KEY")
is_production = (
    os.getenv("VERCEL_ENV") == "production"
    or os.getenv("FLASK_ENV") == "production"
)

if is_production and not flask_secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is required in production.")

app.secret_key = flask_secret_key or "dev-local-key"

app.register_blueprint(reporte_agentes_bp)
app.register_blueprint(turnos_trabajo_bp)
app.register_blueprint(usuarios_activos_bp)
app.register_blueprint(comparar_csv_bp)
app.register_blueprint(usuarios_a_sheets_bp)
app.register_blueprint(auditoria_csat_bp)
app.register_blueprint(auditoria_salientes_bp)
app.register_blueprint(break_admin_bp)
app.register_blueprint(informe_semanal_cs_bp)

registrar_modo_almacenamiento()

# Versión vigente de cada recurso estático versionado. Súbela al cambiar el archivo:
# solo la versión vigente recibe caché larga (una URL con otra versión no se cachea).
ASSET_VERSIONS = {"styles.css": "22", "app.js": "7"}

# Endpoints cuyas pantallas dependen del almacenamiento de turnos.
ENDPOINTS_CON_AVISO_DE_ALMACENAMIENTO = ("inicio", "turnos_trabajo.", "reporte_agentes.")

# Cabeceras comunes. Son medidas contra usos accidentales o incrustación; la
# aplicación es pública por decisión y NINGUNA de estas cabeceras es control de acceso.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": (
        "accelerometer=(), autoplay=(), bluetooth=(), camera=(), display-capture=(), "
        "geolocation=(), gyroscope=(), hid=(), magnetometer=(), microphone=(), midi=(), "
        "payment=(), serial=(), usb=(), xr-spatial-tracking=()"
    ),
    # Solo informe: el navegador avisa en la consola, no bloquea nada y no se envían reportes.
    "Content-Security-Policy-Report-Only": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'self'; "
        "base-uri 'self'; object-src 'none'"
    ),
}
ROBOTS_TAG = "noindex, nofollow, noarchive"


@app.context_processor
def contexto_global():
    def estado_almacenamiento_visible():
        endpoint = request.endpoint or ""
        if not any(endpoint == e or (e.endswith(".") and endpoint.startswith(e)) for e in ENDPOINTS_CON_AVISO_DE_ALMACENAMIENTO):
            return None
        estado = obtener_estado_almacenamiento()
        return estado if estado["mode"] in ("temporal", "fallback") else None

    return {
        "grupos_navegacion": grupos_de_navegacion,
        "herramienta_activa": herramienta_activa,
        "estado_almacenamiento_visible": estado_almacenamiento_visible,
        "asset_version": lambda nombre: ASSET_VERSIONS.get(nombre, "0"),
    }


@app.after_request
def aplicar_cabeceras(respuesta):
    for nombre, valor in SECURITY_HEADERS.items():
        respuesta.headers.setdefault(nombre, valor)

    if request.endpoint == "static":
        archivo = (request.view_args or {}).get("filename", "")
        version = request.args.get("v")
        if version and ASSET_VERSIONS.get(archivo) == version:
            respuesta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            respuesta.headers["Vercel-CDN-Cache-Control"] = "public, max-age=86400"
        else:
            # Sin versión vigente: el navegador revalida (ETag/Last-Modified) en cada uso.
            respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta

    if request.endpoint == "robots_txt":
        respuesta.headers["Cache-Control"] = "public, max-age=3600"
        return respuesta

    # HTML, JSON, exportaciones y errores: nunca en caché y fuera de buscadores.
    respuesta.headers["Cache-Control"] = "no-store"
    respuesta.headers["X-Robots-Tag"] = ROBOTS_TAG
    return respuesta


@app.route("/robots.txt")
def robots_txt():
    # Pide a los buscadores no rastrear la app. Es una petición, no un control de acceso.
    return app.response_class("User-agent: *\nDisallow: /\n", mimetype="text/plain")


def _espera_json():
    if request.path.startswith("/usuarios-activos/"):
        return True
    mejor = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return request.is_json or mejor == "application/json"


@app.errorhandler(RequestEntityTooLarge)
def solicitud_demasiado_grande(error):
    limite = formatear_tamano_bytes(app.config.get("MAX_CONTENT_LENGTH") or 0)
    mensaje = (
        f"El archivo o formulario enviado supera el límite permitido de {limite}. "
        "Reduce el tamaño del archivo o divídelo e inténtalo de nuevo."
    )
    if _espera_json():
        return jsonify({"success": False, "error": mensaje}), 413
    return (
        render_template("error.html", titulo="Archivo demasiado grande", mensaje=mensaje),
        413,
    )


@app.route("/")
def inicio():
    return render_template("inicio.html")


if __name__ == "__main__":
    app.run(debug=True)
