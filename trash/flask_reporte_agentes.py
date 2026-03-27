import io
import json
from pathlib import Path

import pandas as pd
from flask import Flask, redirect, render_template_string, request, url_for

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

ARCHIVO_TURNOS = DATA_DIR / "turnos.json"
ARCHIVO_CSV = DATA_DIR / "ultimo_reporte.csv"

TURNOS_BASE = {
    "Oficina": [],
    "Madrugada": [],
    "Media noche": [],
    "Tarde/Noche": [],
}

COLUMNAS_REQUERIDAS = [
    "First Name",
    "Last Name",
    "Calls",
    "Outgoing calls",
    "Missed calls",
    "Call seconds",
    "Outgoing call seconds",
]

TRADUCCIONES = {
    "Turno": "Turno",
    "First Name": "Nombre",
    "Calls": "Llamadas",
    "Outgoing calls": "Salientes",
    "Missed calls": "Perdidas",
    "Call minutes": "Mins llamadas",
    "Outgoing call minutes": "Mins salientes",
    "Agente": "Agente",
}

COLUMNAS_VISIBLES = [
    "Turno",
    "Nombre",
    "Llamadas",
    "Salientes",
    "Perdidas",
    "Mins llamadas",
    "Mins salientes",
]

PLANTILLA_BASE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ titulo }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f6f7fb; color: #222; }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 24px; }
    .card { background: white; border-radius: 14px; padding: 18px; margin-bottom: 18px; box-shadow: 0 1px 6px rgba(0,0,0,.08); }
    h1, h2, h3, h4 { margin-top: 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    .metric { background: #fafafa; border: 1px solid #eee; border-radius: 10px; padding: 12px; }
    .metric .label { font-size: 12px; color: #666; }
    .metric .value { font-size: 28px; font-weight: bold; margin-top: 6px; }
    .btn, button { background: #1f6feb; color: white; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; text-decoration: none; display: inline-block; }
    .btn.secondary { background: #666; }
    .btn.danger { background: #c0392b; }
    input[type=file], input[type=text], select { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .row-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
    .small { color: #666; font-size: 13px; }
    .warning { background: #fff4d6; border: 1px solid #f0d98a; padding: 10px; border-radius: 8px; margin-bottom: 12px; }
    .success { background: #e9f8ef; border: 1px solid #9fd5af; padding: 10px; border-radius: 8px; margin-bottom: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid #eee; padding: 10px; text-align: left; }
    th { background: #fafafa; }
    .table-wrap { overflow: auto; max-height: 480px; }
    .turno-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
    .agente-lista { max-height: 340px; overflow: auto; border: 1px solid #eee; border-radius: 10px; padding: 10px; background: #fafafa; }
    .agente-item { display: flex; align-items: center; gap: 8px; padding: 6px 4px; border-bottom: 1px solid #eee; }
    .agente-item:last-child { border-bottom: none; }
    .agente-item label { flex: 1; cursor: pointer; }
    .badge { display: inline-block; margin-left: 6px; padding: 2px 8px; border-radius: 999px; font-size: 11px; }
    .badge-usado { background: #fde7e7; color: #a32b2b; }
    .badge-actual { background: #e8f1ff; color: #295ba7; }
  </style>
</head>
<body>
  <div class="wrap">
    {{ contenido|safe }}
  </div>
</body>
</html>
"""


def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def convertir_a_numero(serie):
    return pd.to_numeric(serie, errors="coerce").fillna(0)


def segundos_a_minutos(valor):
    try:
        return int(round(float(valor) / 60))
    except Exception:
        return 0


def normalizar_turnos(turnos):
    resultado = {}
    for turno, agentes in turnos.items():
        nombre_turno = limpiar_texto(turno)
        if not nombre_turno:
            continue
        if not isinstance(agentes, list):
            agentes = []
        resultado[nombre_turno] = [limpiar_texto(x) for x in agentes if limpiar_texto(x)]
    return resultado or TURNOS_BASE.copy()


def cargar_turnos_guardados():
    if not ARCHIVO_TURNOS.exists():
        return TURNOS_BASE.copy()
    try:
        contenido = json.loads(ARCHIVO_TURNOS.read_text(encoding="utf-8"))
        if not isinstance(contenido, dict):
            return TURNOS_BASE.copy()
        return normalizar_turnos(contenido)
    except Exception:
        return TURNOS_BASE.copy()


def guardar_turnos(turnos_config):
    ARCHIVO_TURNOS.write_text(
        json.dumps(normalizar_turnos(turnos_config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validar_columnas(df):
    faltantes = [col for col in COLUMNAS_REQUERIDAS if col not in df.columns]
    if faltantes:
        raise ValueError("Faltan estas columnas en el CSV: " + ", ".join(faltantes))


def obtener_turno(nombre_completo, turnos_config):
    nombre_normalizado = limpiar_texto(nombre_completo).lower()
    for turno, lista_agentes in turnos_config.items():
        for agente in lista_agentes:
            if limpiar_texto(agente).lower() == nombre_normalizado:
                return turno
    return "Sin asignar"


def detectar_repetidos(turnos_config):
    conteo = {}
    for agentes in turnos_config.values():
        for agente in agentes:
            conteo[agente] = conteo.get(agente, 0) + 1
    return [agente for agente, cantidad in conteo.items() if cantidad > 1]


def mapa_agente_a_turnos(turnos_config):
    mapa = {}
    for turno, agentes in turnos_config.items():
        for agente in agentes:
            mapa.setdefault(agente, []).append(turno)
    return mapa


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
        return '<p class="small">No hay datos para mostrar.</p>'
    return df.to_html(index=False, border=0)


def cargar_csv_guardado():
    if not ARCHIVO_CSV.exists():
        return None
    try:
        df = pd.read_csv(ARCHIVO_CSV)
        validar_columnas(df)
        return df
    except Exception:
        return None


def guardar_csv_subido(file_storage):
    contenido = file_storage.read()
    df = pd.read_csv(io.BytesIO(contenido))
    validar_columnas(df)
    ARCHIVO_CSV.write_bytes(contenido)
    return df


def extraer_agentes(df):
    df_tmp = df.copy()
    df_tmp["First Name"] = df_tmp["First Name"].apply(limpiar_texto)
    df_tmp["Last Name"] = df_tmp["Last Name"].apply(limpiar_texto)
    df_tmp["Agente"] = (df_tmp["First Name"] + " " + df_tmp["Last Name"]).str.strip()
    return sorted(df_tmp["Agente"].dropna().unique().tolist())


@app.route("/")
def inicio():
    contenido = """
    <div class="card">
      <h1>Panel principal</h1>
      <p>Aquí puedes elegir la herramienta que necesitas usar en cada momento.</p>
    </div>
    <div class="card">
      <h2>Reporte de agentes</h2>
      <p>Carga un CSV, convierte segundos a mins y separa por turnos.</p>
      <a class="btn" href="/reporte-agentes">Abrir reporte de agentes</a>
    </div>
    """
    return render_template_string(PLANTILLA_BASE, titulo="Panel principal", contenido=contenido)


@app.route("/reporte-agentes", methods=["GET", "POST"])
def reporte_agentes():
    mensaje = ""
    advertencia = ""
    resumen_html = ""
    tabla_general_html = ""
    secciones_turnos = ""

    turnos_config = cargar_turnos_guardados()
    df = cargar_csv_guardado()
    lista_agentes = extraer_agentes(df) if df is not None else []

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
                mensaje = "Turno agregado correctamente."
            return redirect(url_for("reporte_agentes"))

        elif accion.startswith("eliminar_turno:"):
            nombre_turno = accion.split(":", 1)[1]
            if nombre_turno in turnos_config:
                del turnos_config[nombre_turno]
                guardar_turnos(turnos_config)
            return redirect(url_for("reporte_agentes"))

        elif accion == "guardar_turnos":
            nuevos_turnos = {}
            for turno in list(turnos_config.keys()):
                seleccion = request.form.getlist(f"turno::{turno}")
                nuevos_turnos[turno] = seleccion
            turnos_config = nuevos_turnos
            guardar_turnos(turnos_config)
            mensaje = "Turnos guardados correctamente."
            df = cargar_csv_guardado()
            lista_agentes = extraer_agentes(df) if df is not None else []

        elif accion == "restablecer_turnos":
            if ARCHIVO_TURNOS.exists():
                ARCHIVO_TURNOS.unlink()
            return redirect(url_for("reporte_agentes"))

    turnos_config = cargar_turnos_guardados()
    df = cargar_csv_guardado()
    lista_agentes = extraer_agentes(df) if df is not None else []
    mapa_turnos = mapa_agente_a_turnos(turnos_config)

    if df is not None:
        repetidos = detectar_repetidos(turnos_config)
        if repetidos:
            advertencia = "Estos agentes están asignados en más de un turno: " + ", ".join(repetidos)

        df_final = preparar_dataframe(df, turnos_config)

        resumen_html = f"""
        <div class="card">
          <h2>Resumen general</h2>
          <div class="grid">
            <div class="metric"><div class="label">Agentes</div><div class="value">{int(df_final["Agente"].nunique())}</div></div>
            <div class="metric"><div class="label">Llamadas</div><div class="value">{int(df_final["Llamadas"].sum())}</div></div>
            <div class="metric"><div class="label">Salientes</div><div class="value">{int(df_final["Salientes"].sum())}</div></div>
            <div class="metric"><div class="label">Perdidas</div><div class="value">{int(df_final["Perdidas"].sum())}</div></div>
            <div class="metric"><div class="label">Mins llamadas</div><div class="value">{int(df_final["Mins llamadas"].sum())}</div></div>
            <div class="metric"><div class="label">Mins salientes</div><div class="value">{int(df_final["Mins salientes"].sum())}</div></div>
          </div>
        </div>
        """

        tabla_general_html = f"""
        <div class="card">
          <h2>Tabla general</h2>
          <div class="table-wrap">{html_tabla(df_final[COLUMNAS_VISIBLES])}</div>
        </div>
        """

        bloques = []
        for turno in sorted(turnos_config.keys()):
            bloque = df_final[df_final["Turno"] == turno][[c for c in COLUMNAS_VISIBLES if c != "Turno"]]
            if not bloque.empty:
                bloques.append(f'<div class="card"><h3>{turno}</h3><div class="table-wrap">{html_tabla(bloque)}</div></div>')

        bloque_sin = df_final[df_final["Turno"] == "Sin asignar"][[c for c in COLUMNAS_VISIBLES if c != "Turno"]]
        if not bloque_sin.empty:
            bloques.append(f'<div class="card"><h3>Sin asignar</h3><div class="table-wrap">{html_tabla(bloque_sin)}</div></div>')

        secciones_turnos = "".join(bloques)

    opciones_turnos = []
    for turno, agentes_guardados in turnos_config.items():
        agentes_html = []
        for idx, agente in enumerate(lista_agentes):
            checked = "checked" if agente in agentes_guardados else ""
            otros_turnos = [t for t in mapa_turnos.get(agente, []) if t != turno]
            badges = ""
            if otros_turnos:
                badges += f'<span class="badge badge-usado">En: {", ".join(otros_turnos)}</span>'
            if agente in agentes_guardados:
                badges += '<span class="badge badge-actual">Seleccionado</span>'
            agentes_html.append(
                f'''<div class="agente-item">
                    <input type="checkbox" id="{turno}_{idx}" name="turno::{turno}" value="{agente}" {checked}>
                    <label for="{turno}_{idx}">{agente} {badges}</label>
                </div>'''
            )

        opciones_turnos.append(f"""
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
            <h3 style="margin:0;">{turno}</h3>
            <button class="btn danger" type="submit" name="accion" value="eliminar_turno:{turno}">Eliminar</button>
          </div>
          <p class="small">Haz clic en cada nombre para marcarlo o desmarcarlo.</p>
          <div class="agente-lista">{''.join(agentes_html) if agentes_html else '<p class="small">Carga primero un CSV para ver agentes.</p>'}</div>
        </div>
        """)

    alertas = ""
    if mensaje:
        alertas += f'<div class="success">{mensaje}</div>'
    if advertencia:
        alertas += f'<div class="warning">{advertencia}</div>'

    contenido = f"""
    <div class="card">
      <h1>Reporte de agentes</h1>
      <p>Sube el CSV una vez y luego podrás configurar turnos sin volver a subirlo.</p>
      {alertas}
    </div>

    <div class="card">
      <h2>1. Cargar CSV</h2>
      <form method="post" enctype="multipart/form-data">
        <div class="row">
          <div><input type="file" name="archivo" accept=".csv"></div>
          <div><button type="submit" name="accion" value="subir_csv">Cargar CSV</button></div>
        </div>
      </form>
    </div>

    <div class="card">
      <h2>2. Agregar turno</h2>
      <form method="post">
        <div class="row">
          <div><input type="text" name="nuevo_turno" placeholder="Nombre del nuevo turno"></div>
          <div><button type="submit" name="accion" value="agregar_turno">Agregar turno</button></div>
        </div>
      </form>
    </div>

    <form method="post">
      <div class="card">
        <h2>3. Configuración de turnos</h2>
        <p class="small">Ahora puedes seleccionar agentes con un clic, sin usar Ctrl.</p>
        <div class="turno-grid">
          {''.join(opciones_turnos) if opciones_turnos else '<p class="small">No hay turnos configurados.</p>'}
        </div>
        <div class="row-3" style="margin-top:16px;">
          <button type="submit" name="accion" value="guardar_turnos">Guardar turnos</button>
          <button type="submit" name="accion" value="restablecer_turnos">Restablecer turnos</button>
          <a class="btn secondary" href="/">Volver al inicio</a>
        </div>
      </div>
    </form>

    {resumen_html}
    {tabla_general_html}
    {secciones_turnos}
    """

    return render_template_string(PLANTILLA_BASE, titulo="Reporte de agentes", contenido=contenido)


if __name__ == "__main__":
    app.run(debug=True)
