from datetime import datetime

from flask import Blueprint, render_template, jsonify
from tools.servicios_usuarios_activos import iniciar_actualizacion, obtener_estado_actual

usuarios_activos_bp = Blueprint(
    "usuarios_activos",
    __name__,
    url_prefix="/usuarios-activos"
)

@usuarios_activos_bp.route("/")
def index():
    return render_template("usuarios_activos.html")

@usuarios_activos_bp.route("/api")
def api():
    data = obtener_estado_actual()
    return jsonify({
        "success": True,
        "data": data,
        "updated_at": datetime.now().strftime("%H:%M"),
    })

@usuarios_activos_bp.route("/actualizar", methods=["POST"])
def actualizar():
    data = iniciar_actualizacion()
    return jsonify({
        "success": True,
        "data": data,
        "updated_at": datetime.now().strftime("%H:%M"),
    })
