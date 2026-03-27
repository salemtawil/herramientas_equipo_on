from flask import Flask, render_template
from tools.reporte_agentes import reporte_agentes_bp

app = Flask(__name__)
app.register_blueprint(reporte_agentes_bp)

@app.route("/")
def inicio():
    return render_template("inicio.html")