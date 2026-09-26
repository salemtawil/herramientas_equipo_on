import logging
import os
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from utils.archivos import formatear_tamano_bytes
from utils.env import cargar_env_local

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
