"""Almacén mínimo de auditorías CSAT: Supabase en producción y memoria en pruebas.

Solo guarda el resumen del período y los negativos con su decisión; no guarda transcripciones.
"""

import copy
import os
import uuid
from datetime import date, datetime, timedelta, timezone

TABLA_PERIODOS = "csat_audit_periods"
TABLA_NEGATIVOS = "csat_audit_negatives"
RETENCION_SEMANAS = 12

CAMPOS_RESUMEN = (
    "total_encuestas",
    "ratings_count",
    "csat_real",
    "csat_ajustado",
    "por_agente",
    "negativos_total",
    "negativos_excluidos",
    "negativos_pendientes",
)


class AuditoriaCsatStoreError(Exception):
    pass


class AuditoriaCsatConfigError(AuditoriaCsatStoreError):
    pass


def _ahora_iso():
    return datetime.now(timezone.utc).isoformat()


def _iso(valor):
    return valor.isoformat() if isinstance(valor, (date, datetime)) else valor


def _fila_periodo(tipo_periodo, inicio, fin, resumen):
    fila = {"tipo_periodo": tipo_periodo, "fecha_inicio": _iso(inicio), "fecha_fin": _iso(fin)}
    for campo in CAMPOS_RESUMEN:
        if campo in (resumen or {}):
            fila[campo] = copy.deepcopy(resumen[campo])
    return fila


def _uuid_valido(valor):
    try:
        uuid.UUID(str(valor))
    except ValueError:
        return False
    return True


def _fecha_corte(hoy, semanas):
    return (hoy - timedelta(weeks=semanas)).isoformat()


class SupabaseCsatStore:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_env(cls):
        url = (os.getenv("SUPABASE_URL") or "").strip()
        service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not service_role_key:
            raise AuditoriaCsatConfigError(
                "Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY para guardar las auditorías CSAT."
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise AuditoriaCsatConfigError("La dependencia 'supabase' no está instalada en el entorno.") from exc
        return cls(create_client(url, service_role_key))

    def _execute(self, query):
        try:
            response = query.execute()
        except Exception as exc:
            raise AuditoriaCsatStoreError(
                f"No se pudo consultar Supabase: {exc}. Verifica que existan las tablas de supabase_csat_audits.sql."
            ) from exc
        return getattr(response, "data", None) or []

    def _todas(self, construir_query, tamano=1000):
        """Lee todas las filas paginando: PostgREST devuelve como máximo 1000 por consulta."""
        filas, desde = [], 0
        while True:
            pagina = self._execute(construir_query().range(desde, desde + tamano - 1))
            filas.extend(pagina)
            if len(pagina) < tamano:
                return filas
            desde += tamano

    def _uno(self, query):
        data = self._execute(query)
        return data[0] if data else None

    # Períodos
    def guardar_periodo(self, tipo_periodo, inicio, fin, resumen):
        fila = _fila_periodo(tipo_periodo, inicio, fin, resumen)
        fila["updated_at"] = _ahora_iso()
        return self._uno(self.client.table(TABLA_PERIODOS).upsert(fila, on_conflict="fecha_inicio,fecha_fin"))

    def obtener_periodo(self, period_id):
        if not _uuid_valido(period_id):
            return None
        return self._uno(self.client.table(TABLA_PERIODOS).select("*").eq("id", period_id).limit(1))

    def buscar_periodo(self, inicio, fin):
        return self._uno(
            self.client.table(TABLA_PERIODOS)
            .select("*")
            .eq("fecha_inicio", _iso(inicio))
            .eq("fecha_fin", _iso(fin))
            .limit(1)
        )

    def listar_periodos(self, limite=20):
        return self._execute(
            self.client.table(TABLA_PERIODOS).select("*").order("fecha_fin", desc=True).limit(limite)
        )

    # Negativos
    def negativos(self, period_id):
        return self._todas(
            lambda: self.client.table(TABLA_NEGATIVOS)
            .select("*")
            .eq("period_id", period_id)
            .order("fecha")
            .order("survey_id")
        )

    def reemplazar_negativos(self, period_id, filas):
        ahora = _ahora_iso()
        filas = [dict(f, period_id=period_id, updated_at=ahora) for f in filas]
        for desde in range(0, len(filas), 200):
            self._execute(
                self.client.table(TABLA_NEGATIVOS).upsert(filas[desde : desde + 200], on_conflict="period_id,survey_id")
            )
        vigentes = {int(f["survey_id"]) for f in filas}
        existentes = self._todas(
            lambda: self.client.table(TABLA_NEGATIVOS).select("survey_id").eq("period_id", period_id).order("survey_id")
        )
        sobrantes = [int(f["survey_id"]) for f in existentes if int(f["survey_id"]) not in vigentes]
        for desde in range(0, len(sobrantes), 200):
            self._execute(
                self.client.table(TABLA_NEGATIVOS)
                .delete()
                .eq("period_id", period_id)
                .in_("survey_id", sobrantes[desde : desde + 200])
            )

    # Retención
    def borrar_vencidos(self, hoy, semanas=RETENCION_SEMANAS):
        """Borra períodos terminados hace más de `semanas`; sus negativos caen por cascade."""
        borrados = self._execute(
            self.client.table(TABLA_PERIODOS).delete().lt("fecha_fin", _fecha_corte(hoy, semanas))
        )
        return len(borrados)


class MemoriaCsatStore:
    """Implementación en memoria con la misma interfaz, para pruebas."""

    def __init__(self):
        self.periodos = {}
        self.negativos_por_periodo = {}

    def guardar_periodo(self, tipo_periodo, inicio, fin, resumen):
        fila = _fila_periodo(tipo_periodo, inicio, fin, resumen)
        existente = self.buscar_periodo(inicio, fin)
        if existente:
            periodo = self.periodos[existente["id"]]
            periodo.update(fila, updated_at=_ahora_iso())
        else:
            periodo = dict(fila, id=str(uuid.uuid4()), created_at=_ahora_iso(), updated_at=_ahora_iso())
            self.periodos[periodo["id"]] = periodo
        return copy.deepcopy(periodo)

    def obtener_periodo(self, period_id):
        periodo = self.periodos.get(period_id) if _uuid_valido(period_id) else None
        return copy.deepcopy(periodo) if periodo else None

    def buscar_periodo(self, inicio, fin):
        for periodo in self.periodos.values():
            if periodo["fecha_inicio"] == _iso(inicio) and periodo["fecha_fin"] == _iso(fin):
                return copy.deepcopy(periodo)
        return None

    def listar_periodos(self, limite=20):
        periodos = sorted(self.periodos.values(), key=lambda p: p["fecha_fin"], reverse=True)
        return copy.deepcopy(periodos[:limite])

    def negativos(self, period_id):
        filas = self.negativos_por_periodo.get(period_id, {}).values()
        return copy.deepcopy(sorted(filas, key=lambda f: (str(f.get("fecha") or ""), f["survey_id"])))

    def reemplazar_negativos(self, period_id, filas):
        nuevos = {}
        for fila in filas:
            nuevos[int(fila["survey_id"])] = dict(copy.deepcopy(fila), period_id=period_id, updated_at=_ahora_iso())
        self.negativos_por_periodo[period_id] = nuevos

    def borrar_vencidos(self, hoy, semanas=RETENCION_SEMANAS):
        corte = _fecha_corte(hoy, semanas)
        vencidos = [pid for pid, p in self.periodos.items() if p["fecha_fin"] < corte]
        for pid in vencidos:
            del self.periodos[pid]
            self.negativos_por_periodo.pop(pid, None)
        return len(vencidos)


def obtener_store_csat():
    return SupabaseCsatStore.from_env()
