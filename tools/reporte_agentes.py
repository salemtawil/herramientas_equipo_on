import pandas as pd
from flask import Blueprint, render_template, request

from utils.archivos import extraer_agentes, leer_csv_subido
from utils.transformaciones import (
    COLUMNAS_VISIBLES,
    TRADUCCIONES,
    convertir_a_numero,
    limpiar_texto,
    segundos_a_minutos,
    validar_columnas,
)
from utils.turnos import cargar_turnos_fijos, detectar_repetidos, obtener_turno

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
    lista_agentes = []
    agentes_sin_asignar = []
    turnos_config = cargar_turnos_fijos()

    if request.method == "POST":
        archivo = request.files.get("archivo")

        if not archivo or not archivo.filename:
            advertencia = "Selecciona un archivo CSV."
        else:
            try:
                df = leer_csv_subido(archivo)
                lista_agentes = extraer_agentes(df)

                repetidos = detectar_repetidos(turnos_config)
                if repetidos:
                    advertencia = "Estos agentes están repetidos en la configuración de turnos: " + ", ".join(repetidos)

                df_final = preparar_dataframe(df, turnos_config)

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

                agentes_configurados = set()
                for agentes in turnos_config.values():
                    for agente in agentes:
                        agentes_configurados.add(agente)

                agentes_sin_asignar = [ag for ag in lista_agentes if ag not in agentes_configurados]

                mensaje = "CSV procesado correctamente."

            except Exception as e:
                advertencia = f"No se pudo procesar el archivo: {e}"

    return render_template(
        "reporte_agentes.html",
        mensaje=mensaje,
        advertencia=advertencia,
        resumen=resumen,
        tabla_general=tabla_general,
        columnas_visibles=COLUMNAS_VISIBLES,
        secciones_turnos=secciones_turnos,
        turnos_config=turnos_config,
        agentes_sin_asignar=agentes_sin_asignar,
    )