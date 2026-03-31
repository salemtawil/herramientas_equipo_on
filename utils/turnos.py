from utils.config_turnos import obtener_turnos_fijos
from utils.transformaciones import limpiar_texto


def cargar_turnos_fijos():
    return obtener_turnos_fijos()


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

    for turno, lista_agentes in turnos_config.items():
        for agente in lista_agentes:
            agente_normalizado = normalizar_nombre(agente)
            agente_primer_nombre = obtener_primer_nombre(agente)

            # Coincidencia exacta
            if agente_normalizado == nombre_normalizado:
                return turno

            # Coincidencia por primer nombre
            if agente_primer_nombre and agente_primer_nombre == primer_nombre:
                return turno

            # Coincidencia si el nombre del CSV empieza con el configurado
            if agente_normalizado and nombre_normalizado.startswith(agente_normalizado + " "):
                return turno

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