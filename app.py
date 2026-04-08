from flask import Flask, render_template
from tools.reporte_agentes import reporte_agentes_bp
from tools.usuarios_activos import usuarios_activos_bp
from tools.comparar_csv import comparar_csv_bp

app = Flask(__name__)
app.secret_key = "dev-secret-key-local-cambia-esto-por-algo-unico"

app.register_blueprint(reporte_agentes_bp)
app.register_blueprint(usuarios_activos_bp)
app.register_blueprint(comparar_csv_bp)

@app.route("/")
def inicio():
    return render_template("inicio.html")

if __name__ == "__main__":
    app.run(debug=True)