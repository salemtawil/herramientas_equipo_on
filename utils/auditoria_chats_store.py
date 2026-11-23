"""Almacén de lotes y chats auditados: Supabase en producción y memoria en pruebas."""

import copy
import os
import uuid
from datetime import datetime, timezone

TABLA_LOTES = "chat_audit_batches"
TABLA_CHATS = "chat_audits"
TABLA_MANUAL = "chat_audit_manual"
TABLA_LLAMADAS = "chat_audit_calls"
TABLA_EMPAREJAMIENTOS = "chat_audit_agentes_llamadas"


class AuditoriaChatsError(Exception):
    pass


class AuditoriaChatsConfigError(AuditoriaChatsError):
    pass


def _ahora_iso():
    return datetime.now(timezone.utc).isoformat()


class SupabaseAuditoriaStore:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_env(cls):
        url = (os.getenv("SUPABASE_URL") or "").strip()
        service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not service_role_key:
            raise AuditoriaChatsConfigError(
                "Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY para guardar las auditorías de chats."
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise AuditoriaChatsConfigError("La dependencia 'supabase' no está instalada en el entorno.") from exc
        return cls(create_client(url, service_role_key))

    def _execute(self, query):
        try:
            response = query.execute()
        except Exception as exc:
            raise AuditoriaChatsError(
                f"No se pudo consultar Supabase: {exc}. Verifica que existan las tablas de supabase_chat_audits.sql."
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

    # Lotes
    def crear_lote(self, datos):
        return self._uno(self.client.table(TABLA_LOTES).insert(datos))

    def obtener_lote(self, lote_id):
        return self._uno(self.client.table(TABLA_LOTES).select("*").eq("id", lote_id).limit(1))

    def actualizar_lote(self, lote_id, cambios):
        cambios = dict(cambios, updated_at=_ahora_iso())
        return self._uno(self.client.table(TABLA_LOTES).update(cambios).eq("id", lote_id))

    def listar_lotes(self, limite=20):
        return self._execute(
            self.client.table(TABLA_LOTES).select("*").order("created_at", desc=True).limit(limite)
        )

    def borrar_lote(self, lote_id):
        self._execute(self.client.table(TABLA_LOTES).delete().eq("id", lote_id))

    # Chats
    def conversaciones_auditadas(self, ids):
        ids = [int(i) for i in ids]
        if not ids:
            return set()
        data = self._execute(
            self.client.table(TABLA_CHATS).select("conversation_id").in_("conversation_id", ids)
        )
        return {int(fila["conversation_id"]) for fila in data}

    def insertar_chats(self, filas):
        if not filas:
            return 0
        data = self._execute(
            self.client.table(TABLA_CHATS).upsert(filas, on_conflict="conversation_id", ignore_duplicates=True)
        )
        return len(data)

    def tomar_siguiente(self, lote_id, estados, nuevo_estado):
        candidatos = self._execute(
            self.client.table(TABLA_CHATS)
            .select("*")
            .eq("batch_id", lote_id)
            .in_("estado", list(estados))
            .order("created_at")
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

    def obtener_chat(self, chat_id):
        return self._uno(self.client.table(TABLA_CHATS).select("*").eq("id", chat_id).limit(1))

    def listar_chats(self, lote_id):
        return self._todas(
            lambda: self.client.table(TABLA_CHATS).select("*").eq("batch_id", lote_id).order("created_at").order("id")
        )

    def chats_para_historial(self, desde_iso):
        return self._todas(
            lambda: self.client.table(TABLA_CHATS)
            .select("*")
            .gte("conversacion_fecha", desde_iso)
            .order("conversacion_fecha")
            .order("id")
        )

    # Manual de procedimientos
    def indice_manual(self, version):
        filas = self._todas(
            lambda: self.client.table(TABLA_MANUAL).select("codigo,titulo,orden").eq("version", version).order("orden")
        )
        return [{"codigo": f["codigo"], "titulo": f["titulo"]} for f in filas]

    def secciones_manual(self, version, codigos):
        if not codigos:
            return []
        return self._execute(
            self.client.table(TABLA_MANUAL)
            .select("codigo,titulo,texto,orden")
            .eq("version", version)
            .in_("codigo", list(codigos))
            .order("orden")
        )

    def guardar_manual(self, version, secciones):
        filas = [dict(s, version=version) for s in secciones]
        for desde in range(0, len(filas), 50):
            self._execute(self.client.table(TABLA_MANUAL).upsert(filas[desde : desde + 50], on_conflict="version,codigo"))

    # Llamadas de Multiadmin
    def guardar_llamadas(self, lote_id, filas):
        filas = [dict(f, batch_id=lote_id) for f in filas]
        for desde in range(0, len(filas), 200):
            self._execute(
                self.client.table(TABLA_LLAMADAS).upsert(
                    filas[desde : desde + 200], on_conflict="batch_id,record_key", ignore_duplicates=True
                )
            )

    def listar_llamadas(self, lote_id, solo_sin_detalle=False):
        def query():
            q = self.client.table(TABLA_LLAMADAS).select("*").eq("batch_id", lote_id)
            if solo_sin_detalle:
                q = q.eq("detalle_ok", False)
            return q.order("fecha").order("id")

        return self._todas(query)

    def actualizar_llamada(self, llamada_id, cambios):
        return self._uno(self.client.table(TABLA_LLAMADAS).update(cambios).eq("id", llamada_id))

    def borrar_llamadas(self, lote_id, agente_id=None):
        query = self.client.table(TABLA_LLAMADAS).delete().eq("batch_id", lote_id)
        if agente_id is not None:
            query = query.eq("agente_id", agente_id)
        self._execute(query)

    def emparejamientos(self):
        filas = self._todas(lambda: self.client.table(TABLA_EMPAREJAMIENTOS).select("*").order("agent_number"))
        return {
            f["agent_number"]: {"chatwoot_agente_id": f.get("chatwoot_agente_id"), "manual": bool(f.get("manual"))}
            for f in filas
        }

    def guardar_emparejamiento(self, agent_number, chatwoot_agente_id, manual=False):
        self._execute(
            self.client.table(TABLA_EMPAREJAMIENTOS).upsert(
                {
                    "agent_number": agent_number,
                    "chatwoot_agente_id": chatwoot_agente_id,
                    "manual": bool(manual),
                    "updated_at": _ahora_iso(),
                },
                on_conflict="agent_number",
            )
        )


class MemoriaAuditoriaStore:
    """Implementación en memoria con la misma interfaz, para pruebas."""

    def __init__(self):
        self.lotes = {}
        self.chats = {}
        self.manual = {}
        self.llamadas = {}
        self.emparejados = {}
        self._contador = 0

    def _orden(self):
        self._contador += 1
        return self._contador

    def crear_lote(self, datos):
        lote = dict(datos, id=str(uuid.uuid4()), created_at=_ahora_iso(), updated_at=_ahora_iso(), _orden=self._orden())
        self.lotes[lote["id"]] = lote
        return copy.deepcopy(lote)

    def obtener_lote(self, lote_id):
        lote = self.lotes.get(lote_id)
        return copy.deepcopy(lote) if lote else None

    def actualizar_lote(self, lote_id, cambios):
        if lote_id not in self.lotes:
            return None
        self.lotes[lote_id].update(cambios, updated_at=_ahora_iso())
        return copy.deepcopy(self.lotes[lote_id])

    def listar_lotes(self, limite=20):
        lotes = sorted(self.lotes.values(), key=lambda l: l["_orden"], reverse=True)
        return copy.deepcopy(lotes[:limite])

    def borrar_lote(self, lote_id):
        self.lotes.pop(lote_id, None)
        for chat_id in [c["id"] for c in self.chats.values() if c.get("batch_id") == lote_id]:
            del self.chats[chat_id]
        self.borrar_llamadas(lote_id)

    def conversaciones_auditadas(self, ids):
        existentes = {int(c["conversation_id"]) for c in self.chats.values()}
        return {int(i) for i in ids} & existentes

    def insertar_chats(self, filas):
        existentes = {int(c["conversation_id"]) for c in self.chats.values()}
        insertados = 0
        for fila in filas:
            conversation_id = int(fila["conversation_id"])
            if conversation_id in existentes:
                continue
            chat = dict(fila, id=str(uuid.uuid4()), created_at=_ahora_iso(), updated_at=_ahora_iso(), _orden=self._orden())
            chat.setdefault("intentos", 0)
            self.chats[chat["id"]] = chat
            existentes.add(conversation_id)
            insertados += 1
        return insertados

    def tomar_siguiente(self, lote_id, estados, nuevo_estado):
        candidatos = sorted(
            (c for c in self.chats.values() if c.get("batch_id") == lote_id and c.get("estado") in estados),
            key=lambda c: c["_orden"],
        )
        if not candidatos:
            return None
        candidatos[0].update(estado=nuevo_estado, updated_at=_ahora_iso())
        return copy.deepcopy(candidatos[0])

    def actualizar_chat(self, chat_id, cambios):
        if chat_id not in self.chats:
            return None
        self.chats[chat_id].update(cambios, updated_at=_ahora_iso())
        return copy.deepcopy(self.chats[chat_id])

    def obtener_chat(self, chat_id):
        chat = self.chats.get(chat_id)
        return copy.deepcopy(chat) if chat else None

    def listar_chats(self, lote_id):
        chats = sorted(
            (c for c in self.chats.values() if c.get("batch_id") == lote_id), key=lambda c: c["_orden"]
        )
        return copy.deepcopy(chats)

    def chats_para_historial(self, desde_iso):
        chats = [c for c in self.chats.values() if str(c.get("conversacion_fecha") or "") >= desde_iso]
        return copy.deepcopy(sorted(chats, key=lambda c: c.get("conversacion_fecha") or ""))

    def indice_manual(self, version):
        filas = sorted(self.manual.get(version, {}).values(), key=lambda s: s.get("orden", 0))
        return [{"codigo": s["codigo"], "titulo": s["titulo"]} for s in filas]

    def secciones_manual(self, version, codigos):
        filas = [s for c, s in self.manual.get(version, {}).items() if c in set(codigos or [])]
        return copy.deepcopy(sorted(filas, key=lambda s: s.get("orden", 0)))

    def guardar_manual(self, version, secciones):
        destino = self.manual.setdefault(version, {})
        for seccion in secciones:
            destino[seccion["codigo"]] = dict(seccion, version=version)

    def guardar_llamadas(self, lote_id, filas):
        for fila in filas:
            clave = (lote_id, fila["record_key"])
            if clave not in self.llamadas:
                self.llamadas[clave] = dict(fila, id=str(uuid.uuid4()), batch_id=lote_id, _orden=self._orden())

    def listar_llamadas(self, lote_id, solo_sin_detalle=False):
        filas = [
            f
            for (lote, _), f in self.llamadas.items()
            if lote == lote_id and not (solo_sin_detalle and f.get("detalle_ok"))
        ]
        return copy.deepcopy(sorted(filas, key=lambda f: (f.get("fecha") or "", f["_orden"])))

    def actualizar_llamada(self, llamada_id, cambios):
        for fila in self.llamadas.values():
            if fila["id"] == llamada_id:
                fila.update(copy.deepcopy(cambios))
                return copy.deepcopy(fila)
        return None

    def borrar_llamadas(self, lote_id, agente_id=None):
        for clave in [k for k, f in self.llamadas.items() if k[0] == lote_id and agente_id in (None, f.get("agente_id"))]:
            del self.llamadas[clave]

    def emparejamientos(self):
        return copy.deepcopy(self.emparejados)

    def guardar_emparejamiento(self, agent_number, chatwoot_agente_id, manual=False):
        self.emparejados[agent_number] = {"chatwoot_agente_id": chatwoot_agente_id, "manual": bool(manual)}


def obtener_store():
    return SupabaseAuditoriaStore.from_env()
