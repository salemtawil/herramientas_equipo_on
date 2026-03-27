import pandas as pd
from flask import Blueprint, redirect, render_template, request, url_for

from utils.archivos import (
    ARCHIVO_TURNOS,
    cargar_csv_guardado,
    cargar_turnos_guardados,
    extraer_agentes,
    guardar_csv_subido,
    guardar_turnos,
)
from utils.transformaciones import (
    COLUMNAS_VISIBLES,
    TRADUCCIONES,
    convertir_a_numero,
    limpiar_texto,
    segundos_a_minutos,
    validar_columnas,
)
from utils.turnos import detectar_repetidos, mapa_agente_a_turnos, obtener_turno

reporte_agentes_bp = Blueprint("reporte_agentes", __name__)


def preparar_dataframe(df, turnos_config):
    df = df.copy()
    validar_columnas(df)

    df["First Name"] = df["First Name"].apply(limpiar_texto)
    df["Last Name"] = df["Last Name"].apply(limpiar_texto)
    df["Agente"] = (df["First Name"] + " " + df["Last Name"]).str.strip()

    for col in ["Calls", "Outgoing calls", "Missed calls", "Call seconds", "Outgoing call seconds"]:
        df[col] = convertir_a_numero(df[col])

    df["Call minutes"] = df["Call seconds"].apply(segundos_a_minutos)
    df["Outgoing call minutes"] = df["Outgoing call seconds"].apply(segundos_a_minutos)
    df["Turno"] = df["Agente"].apply(lambda nombre: obtener_turno(nombre, turnos_config))

    df_final = df[
        [
            "Turno",
            "First Name",
            "Calls",
            "Outgoing calls",
            "Missed calls",
            "Call minutes",
            "Outgoing call minutes",
            "Agente",
        ]
    ].copy()

    return df_final.rename(columns=TRADUCCIONES)


def html_tabla(df):
    if df.empty:
        return None
    return df.to_dict(orient="records")


@reporte_agentes_bp.route("/reporte-agentes", methods=["GET", "POST"])
def reporte_agentes():
    mensaje = ""
    advertencia = ""
    resumen = None
    tabla_general = None
    secciones_turnos = []

    turnos_config = cargar_turnos_guardados()
    df = cargar_csv_guardado()
    lista_agentes = extraer_agentes(df) if df is not None else []

    orden_columna = request.args.get("orden_columna", "Llamadas")
    orden_direccion = request.args.get("orden_direccion", "desc")

    columnas_ordenables = [
        "Llamadas",
        "Salientes",
        "Perdidas",
        "Mins llamadas",
        "Mins salientes",
        "Nombre",
        "Turno",
    ]

    if orden_columna not in columnas_ordenables:
        orden_columna = "Llamadas"

    if orden_direccion not in ["asc", "desc"]:
        orden_direccion = "desc"

    ascendente = orden_direccion == "asc"

    if request.method == "POST":
        accion = request.form.get("accion", "procesar")

        if accion == "subir_csv":
            archivo = request.files.get("archivo")
            if not archivo or not archivo.filename:
                advertencia = "Selecciona un archivo CSV."
            else:
                try:
                    df = guardar_csv_subido(archivo)
                    lista_agentes = extraer_agentes(df)
                    mensaje = "CSV cargado correctamente."
                except Exception as e:
                    advertencia = f"No se pudo cargar el CSV: {e}"

        elif accion == "agregar_turno":
            nuevo_turno = limpiar_texto(request.form.get("nuevo_turno", ""))
            if not nuevo_turno:
                advertencia = "Escribe un nombre de turno."
            elif nuevo_turno in turnos_config:
                advertencia = "Ese turno ya existe."
            else:
                turnos_config[nuevo_turno] = []
                guardar_turnos(turnos_config)
                return redirect(
                    url_for(
                        "reporte_agentes.reporte_agentes",
                        orden_columna=orden_columna,
                        orden_direccion=orden_direccion,
                    )
                )

        elif accion.startswith("eliminar_turno:"):
            nombre_turno = accion.split(":", 1)[1]
            if nombre_turno in turnos_config:
                del turnos_config[nombre_turno]
                guardar_turnos(turnos_config)
            return redirect(
                url_for(
                    "reporte_agentes.reporte_agentes",
                    orden_columna=orden_columna,
                    orden_direccion=orden_direccion,
                )
            )

        elif accion == "guardar_turnos":
            nuevos_turnos = {}
            for turno in list(turnos_config.keys()):
                seleccion = request.form.getlist(f"turno::{turno}")
                nuevos_turnos[turno] = seleccion
            turnos_config = nuevos_turnos
            guardar_turnos(turnos_config)
            mensaje = "Turnos guardados correctamente."

        elif accion == "restablecer_turnos":
            if ARCHIVO_TURNOS.exists():
                ARCHIVO_TURNOS.unlink()
            return redirect(
                url_for(
                    "reporte_agentes.reporte_agentes",
                    orden_columna=orden_columna,
                    orden_direccion=orden_direccion,
                )
            )

    turnos_config = cargar_turnos_guardados()
    df = cargar_csv_guardado()
    lista_agentes = extraer_agentes(df) if df is not None else []
    mapa_turnos = mapa_agente_a_turnos(turnos_config)

    if df is not None:
        repetidos = detectar_repetidos(turnos_config)
        if repetidos:
            advertencia = "Estos agentes están asignados en más de un turno: " + ", ".join(repetidos)

        df_final = preparar_dataframe(df, turnos_config)
        df_final = df_final.sort_values(by=orden_columna, ascending=ascendente, kind="stable")

        resumen = {
            "Agentes": int(df_final["Agente"].nunique()),
            "Llamadas": int(df_final["Llamadas"].sum()),
            "Salientes": int(df_final["Salientes"].sum()),
            "Perdidas": int(df_final["Perdidas"].sum()),
            "Mins llamadas": int(df_final["Mins llamadas"].sum()),
            "Mins salientes": int(df_final["Mins salientes"].sum()),
        }

        tabla_general = html_tabla(df_final[COLUMNAS_VISIBLES])

        for turno in sorted(turnos_config.keys()):
            bloque = df_final[df_final["Turno"] == turno][[c for c in COLUMNAS_VISIBLES if c != "Turno"]]
            if not bloque.empty:
                secciones_turnos.append(
                    {
                        "nombre": turno,
                        "filas": html_tabla(bloque),
                    }
                )

        bloque_sin = df_final[df_final["Turno"] == "Sin asignar"][
            [c for c in COLUMNAS_VISIBLES if c != "Turno"]
        ]
        if not bloque_sin.empty:
            secciones_turnos.append(
                {
                    "nombre": "Sin asignar",
                    "filas": html_tabla(bloque_sin),
                }
            )

    return render_template(
        "reporte_agentes.html",
        mensaje=mensaje,
        advertencia=advertencia,
        turnos_config=turnos_config,
        lista_agentes=lista_agentes,
        mapa_turnos=mapa_turnos,
        resumen=resumen,
        tabla_general=tabla_general,
        columnas_visibles=COLUMNAS_VISIBLES,
        secciones_turnos=secciones_turnos,
        orden_columna=orden_columna,
        orden_direccion=orden_direccion,
    )
    