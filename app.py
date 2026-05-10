import logging
import os
from flask import Flask, render_template
from tools.reporte_agentes import reporte_agentes_bp
from tools.usuarios_activos import usuarios_activos_bp
from tools.comparar_csv import comparar_csv_bp
from tools.usuarios_a_sheets import usuarios_a_sheets_bp

app = Flask(__name__)
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
app.register_blueprint(usuarios_activos_bp)
app.register_blueprint(comparar_csv_bp)
app.register_blueprint(usuarios_a_sheets_bp)


@app.route("/")
def inicio():
    return render_template("inicio.html")


if __name__ == "__main__":
    app.run(debug=True)
