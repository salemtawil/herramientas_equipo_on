from utils.transformaciones import limpiar_texto


TURNOS_BASE = {
    "Oficina": [],
    "Madrugada": [],
    "Media noche": [],
    "Tarde/Noche": [],
}


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