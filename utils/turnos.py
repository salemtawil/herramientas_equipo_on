from utils.transformaciones import limpiar_texto
from utils.turnos_trabajo_store import obtener_turnos_configurados


def cargar_turnos_fijos():
    return obtener_turnos_configurados()


def normalizar_nombre(valor):
    return limpiar_texto(valor).lower()


def obtener_primer_nombre(valor):
    texto = limpiar_texto(valor)
    if not texto:
        return ""
    return texto.split()[0].lower()


def obtener_turno(nombre_completo, turnos_config=None):
    if turnos_config is None:
        turnos_config = cargar_turnos_fijos()

    nombre_normalizado = normalizar_nombre(nombre_completo)
    primer_nombre = obtener_primer_nombre(nombre_completo)
    candidatos_primer_nombre = []

    for turno, lista_agentes in turnos_config.items():
        for agente in lista_agentes:
            agente_normalizado = normalizar_nombre(agente)

            if agente_normalizado == nombre_normalizado:
                return turno

    for turno, lista_agentes in turnos_config.items():
        for agente in lista_agentes:
            agente_normalizado = normalizar_nombre(agente)
            if agente_normalizado and nombre_normalizado.startswith(agente_normalizado + " "):
                return turno

    for turno, lista_agentes in turnos_config.items():
        for agente in lista_agentes:
            agente_primer_nombre = obtener_primer_nombre(agente)
            if agente_primer_nombre and agente_primer_nombre == primer_nombre:
                candidatos_primer_nombre.append(turno)

    if len(set(candidatos_primer_nombre)) == 1:
        return candidatos_primer_nombre[0]

    return "Sin asignar"


def detectar_repetidos(turnos_config=None):
    if turnos_config is None:
        turnos_config = cargar_turnos_fijos()

    conteo = {}
    for agentes in turnos_config.values():
        for agente in agentes:
            clave = normalizar_nombre(agente)
            conteo[clave] = conteo.get(clave, 0) + 1

    return [agente for agente, cantidad in conteo.items() if cantidad > 1]


def mapa_agente_a_turnos(turnos_config=None):
    if turnos_config is None:
        turnos_config = cargar_turnos_fijos()

    mapa = {}
    for turno, agentes in turnos_config.items():
        for agente in agentes:
            mapa.setdefault(agente, []).append(turno)

    return mapa
