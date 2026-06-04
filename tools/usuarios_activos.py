from flask import Blueprint, render_template, jsonify
from tools.api_compinche import obtener_diagnostico_promo_compinche
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
        source_inicial=estado_inicial.get("source", "base"),
    )

@usuarios_activos_bp.route("/api")
def api():
    estado = obtener_estado_actual_con_metadata()
    data = estado.get("data")
    if data is None:
        data = obtener_estado_actual()

    return jsonify({
        "success": True,
        "data": data,
        "updated_at": estado.get("updated_at", "-"),
        "source": estado.get("source", "base"),
    })

@usuarios_activos_bp.route("/actualizar", methods=["POST"])
def actualizar():
    estado = iniciar_actualizacion_dashboard()
    data = estado.get("data")
    if data is None:
        data = iniciar_actualizacion()

    return jsonify({
        "success": True,
        "data": data,
        "updated_at": estado.get("updated_at", "-"),
        "source": estado.get("source", "snapshot"),
    })

@usuarios_activos_bp.route("/compinche/promo-diagnostico")
def compinche_promo_diagnostico():
    try:
        diagnostico = obtener_diagnostico_promo_compinche()
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500

    return jsonify({
        "success": True,
        "data": diagnostico,
    })
