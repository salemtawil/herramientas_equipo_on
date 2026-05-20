from flask import Blueprint, render_template, jsonify
from tools.servicios_usuarios_activos import (
    iniciar_actualizacion,
    obtener_estado_actual,
    obtener_estado_actual_con_metadata,
    obtener_estado_inicial_dashboard,
    iniciar_actualizacion_dashboard,
)

usuarios_activos_bp = Blueprint(
    "usuarios_activos",
    __name__,
    url_prefix="/usuarios-activos"
)

@usuarios_activos_bp.route("/")
def index():
    estado_inicial = obtener_estado_inicial_dashboard()
    return render_template(
        "usuarios_activos.html",
        estado_inicial=estado_inicial.get("data", []),
        updated_at_inicial=estado_inicial.get("updated_at", "-"),
    )

@usuarios_activos_bp.route("/api")
def api():
    estado = obtener_estado_actual_con_metadata()
    return jsonify({
        "success": True,
        "data": estado.get("data", obtener_estado_actual()),
        "updated_at": estado.get("updated_at", "-"),
    })

@usuarios_activos_bp.route("/actualizar", methods=["POST"])
def actualizar():
    estado = iniciar_actualizacion_dashboard()
    return jsonify({
        "success": True,
        "data": estado.get("data", iniciar_actualizacion()),
        "updated_at": estado.get("updated_at", "-"),
    })
