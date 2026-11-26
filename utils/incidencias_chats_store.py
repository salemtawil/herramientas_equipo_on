"""Almacén de revisiones de Incidencias de chats: Supabase en producción y memoria en pruebas."""

import copy
import os
import uuid
from datetime import datetime, timezone

TABLA_REVISIONES = "chat_incident_reviews"
TABLA_CHATS = "chat_incident_chats"
TABLA_DECISIONES = "chat_incident_decisions"
TABLA_USO_IA = "chat_incident_ai_usage"


class IncidenciasError(Exception):
    pass


class IncidenciasConfigError(IncidenciasError):
    pass


def _ahora_iso():
    return datetime.now(timezone.utc).isoformat()


class SupabaseIncidenciasStore:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_env(cls):
        url = (os.getenv("SUPABASE_URL") or "").strip()
        service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not service_role_key:
            raise IncidenciasConfigError(
                "Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY para guardar las revisiones de incidencias."
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise IncidenciasConfigError("La dependencia 'supabase' no está instalada en el entorno.") from exc
        return cls(create_client(url, service_role_key))

    def _execute(self, query):
        try:
            response = query.execute()
        except Exception as exc:
            raise IncidenciasError(
                f"No se pudo consultar Supabase: {exc}. Verifica que existan las tablas de supabase_chat_incidents.sql."
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

    # Revisiones
    def crear_revision(self, datos):
        return self._uno(self.client.table(TABLA_REVISIONES).insert(datos))

    def obtener_revision(self, revision_id):
        return self._uno(self.client.table(TABLA_REVISIONES).select("*").eq("id", revision_id).limit(1))

    def actualizar_revision(self, revision_id, cambios):
        cambios = dict(cambios, updated_at=_ahora_iso())
        return self._uno(self.client.table(TABLA_REVISIONES).update(cambios).eq("id", revision_id))

    def listar_revisiones(self, limite=20):
        return self._execute(
            self.client.table(TABLA_REVISIONES).select("*").order("created_at", desc=True).limit(limite)
        )

    # Chats
    def insertar_chats(self, filas):
        if not filas:
            return 0
        data = self._execute(
            self.client.table(TABLA_CHATS).upsert(
                filas, on_conflict="review_id,conversation_id", ignore_duplicates=True
            )
        )
        return len(data)

    def tomar_siguiente(self, review_id, estados, nuevo_estado):
        candidatos = self._execute(
            self.client.table(TABLA_CHATS)
            .select("*")
            .eq("review_id", review_id)
            .in_("estado", list(estados))
            .order("created_at")
            .order("id")
            .limit(5)
        )
        for candidato in candidatos:
            tomado = self._uno(
                self.client.table(TABLA_CHATS)
                .update({"estado": nuevo_estado, "updated_at": _ahora_iso()})
                .eq("id", candidato["id"])
                .eq("estado", candidato["estado"])
            )
            if tomado:
                return tomado
        return None

    def actualizar_chat(self, chat_id, cambios):
        cambios = dict(cambios, updated_at=_ahora_iso())
        return self._uno(self.client.table(TABLA_CHATS).update(cambios).eq("id", chat_id))

    def listar_chats(self, review_id):
        return self._todas(
            lambda: self.client.table(TABLA_CHATS).select("*").eq("review_id", review_id).order("created_at").order("id")
        )

    def ultima_evaluacion(self, conversation_id, excluir_review_id):
        return self._uno(
            self.client.table(TABLA_CHATS)
            .select("*")
            .eq("conversation_id", int(conversation_id))
            .eq("estado", "evaluado")
            .neq("review_id", excluir_review_id)
            .order("updated_at", desc=True)
            .limit(1)
        )

    # Decisiones del manager (por conversación)
    def decisiones(self, conversation_ids):
        ids = [int(i) for i in conversation_ids]
        resultado = {}
        for desde in range(0, len(ids), 200):
            filas = self._execute(
                self.client.table(TABLA_DECISIONES).select("*").in_("conversation_id", ids[desde : desde + 200])
            )
            for fila in filas:
                resultado[int(fila["conversation_id"])] = fila
        return resultado

    def guardar_decision(self, conversation_id, datos):
        fila = dict(datos, conversation_id=int(conversation_id), decidido_at=_ahora_iso())
        return self._uno(self.client.table(TABLA_DECISIONES).upsert(fila, on_conflict="conversation_id"))

    # Cupo diario de IA
    def usos_ia(self, fecha):
        fila = self._uno(self.client.table(TABLA_USO_IA).select("usados").eq("fecha", fecha.isoformat()).limit(1))
        return int(fila["usados"]) if fila else 0

    def sumar_uso_ia(self, fecha):
        clave = fecha.isoformat()
        for _ in range(5):
            fila = self._uno(self.client.table(TABLA_USO_IA).select("usados").eq("fecha", clave).limit(1))
            if fila is None:
                # ignore_duplicates: si otro proceso insertó primero, no inserta y se reintenta.
                creada = self._execute(
                    self.client.table(TABLA_USO_IA).upsert(
                        {"fecha": clave, "usados": 1}, on_conflict="fecha", ignore_duplicates=True
                    )
                )
                if creada:
                    return 1
                continue
            actual = int(fila["usados"])
            tomado = self._uno(
                self.client.table(TABLA_USO_IA).update({"usados": actual + 1}).eq("fecha", clave).eq("usados", actual)
            )
            if tomado:
                return actual + 1
        raise IncidenciasError("No se pudo actualizar el cupo diario de IA por concurrencia; reintenta.")


class MemoriaIncidenciasStore:
    """Implementación en memoria con la misma interfaz, para pruebas."""

    def __init__(self):
        self.revisiones = {}
        self.chats = {}
        self.decisiones_guardadas = {}
        self.uso_ia = {}
        self._contador = 0

    def _orden(self):
        self._contador += 1
        return self._contador

    def crear_revision(self, datos):
        revision = dict(
            copy.deepcopy(datos), id=str(uuid.uuid4()), created_at=_ahora_iso(), updated_at=_ahora_iso(),
            _orden=self._orden(),
        )
        self.revisiones[revision["id"]] = revision
        return copy.deepcopy(revision)

    def obtener_revision(self, revision_id):
        revision = self.revisiones.get(revision_id)
        return copy.deepcopy(revision) if revision else None

    def actualizar_revision(self, revision_id, cambios):
        if revision_id not in self.revisiones:
            return None
        self.revisiones[revision_id].update(copy.deepcopy(cambios), updated_at=_ahora_iso())
        return copy.deepcopy(self.revisiones[revision_id])

    def listar_revisiones(self, limite=20):
        revisiones = sorted(self.revisiones.values(), key=lambda r: r["_orden"], reverse=True)
        return copy.deepcopy(revisiones[:limite])

    def insertar_chats(self, filas):
        existentes = {(c["review_id"], int(c["conversation_id"])) for c in self.chats.values()}
        insertados = 0
        for fila in filas:
            clave = (fila["review_id"], int(fila["conversation_id"]))
            if clave in existentes:
                continue
            chat = dict(
                copy.deepcopy(fila), id=str(uuid.uuid4()), created_at=_ahora_iso(), updated_at=_ahora_iso(),
                _orden=self._orden(),
            )
            chat["_actualizado"] = chat["_orden"]
            chat.setdefault("intentos", 0)
            self.chats[chat["id"]] = chat
            existentes.add(clave)
            insertados += 1
        return insertados

    def tomar_siguiente(self, review_id, estados, nuevo_estado):
        candidatos = sorted(
            (c for c in self.chats.values() if c.get("review_id") == review_id and c.get("estado") in estados),
            key=lambda c: c["_orden"],
        )
        if not candidatos:
            return None
        candidatos[0].update(estado=nuevo_estado, updated_at=_ahora_iso(), _actualizado=self._orden())
        return copy.deepcopy(candidatos[0])

    def actualizar_chat(self, chat_id, cambios):
        if chat_id not in self.chats:
            return None
        self.chats[chat_id].update(copy.deepcopy(cambios), updated_at=_ahora_iso(), _actualizado=self._orden())
        return copy.deepcopy(self.chats[chat_id])

    def listar_chats(self, review_id):
        chats = sorted((c for c in self.chats.values() if c.get("review_id") == review_id), key=lambda c: c["_orden"])
        return copy.deepcopy(chats)

    def ultima_evaluacion(self, conversation_id, excluir_review_id):
        candidatos = [
            c
            for c in self.chats.values()
            if int(c["conversation_id"]) == int(conversation_id)
            and c.get("estado") == "evaluado"
            and c.get("review_id") != excluir_review_id
        ]
        if not candidatos:
            return None
        # Igual que Supabase: la más reciente por updated_at (el contador desempata en el mismo instante).
        return copy.deepcopy(max(candidatos, key=lambda c: (c["updated_at"], c["_actualizado"])))

    def decisiones(self, conversation_ids):
        return {
            int(i): copy.deepcopy(self.decisiones_guardadas[int(i)])
            for i in conversation_ids
            if int(i) in self.decisiones_guardadas
        }

    def guardar_decision(self, conversation_id, datos):
        fila = dict(copy.deepcopy(datos), conversation_id=int(conversation_id), decidido_at=_ahora_iso())
        self.decisiones_guardadas[int(conversation_id)] = fila
        return copy.deepcopy(fila)

    def usos_ia(self, fecha):
        return self.uso_ia.get(fecha.isoformat(), 0)

    def sumar_uso_ia(self, fecha):
        clave = fecha.isoformat()
        self.uso_ia[clave] = self.uso_ia.get(clave, 0) + 1
        return self.uso_ia[clave]


def obtener_store():
    return SupabaseIncidenciasStore.from_env()
