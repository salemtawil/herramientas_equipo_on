-- Auditoría de chats: lotes y chats auditados.
-- Ejecutar una vez en el editor SQL de Supabase.
-- RLS activado sin políticas: solo el backend (service role) puede leer y escribir.

create table if not exists public.chat_audit_batches (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  etiqueta text not null default '',
  since bigint not null,
  until bigint not null,
  alcance text not null check (alcance in ('todos', 'turno', 'agentes')),
  alcance_detalle jsonb not null default '{}'::jsonb,
  chats_por_agente integer not null default 10 check (chats_por_agente between 1 and 20),
  agentes jsonb not null default '[]'::jsonb,
  agentes_muestreados jsonb not null default '[]'::jsonb,
  reservas jsonb not null default '{}'::jsonb,
  estado text not null default 'muestreando'
    check (estado in ('muestreando', 'auditando', 'limite_diario', 'completado', 'con_errores')),
  modelo text not null default '',
  pauta_version text not null default ''
);

create table if not exists public.chat_audits (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.chat_audit_batches(id) on delete cascade,
  conversation_id bigint not null unique,
  agente_id bigint not null,
  agente_nombre text not null default '',
  turno text,
  conversacion_fecha timestamptz,
  estado text not null default 'pendiente'
    check (estado in ('pendiente', 'procesando', 'leido', 'auditado', 'error', 'revisado', 'descartado')),
  intentos integer not null default 0,
  transcripcion_tmp text,
  detalle jsonb, -- bandeja, motivo de descarte y forma de los mensajes (sin texto)
  ia_resultado jsonb,
  ia_nota smallint check (ia_nota between 1 and 5),
  ia_satisfaccion text,
  ia_error text,
  por_revisar boolean not null default false,
  motivo_revision text check (motivo_revision in ('marcado', 'control')),
  revisor text,
  nota_final smallint check (nota_final between 1 and 5),
  satisfaccion_final text,
  comentario_revisor text,
  revisado_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists chat_audits_batch_idx on public.chat_audits (batch_id, estado);
create index if not exists chat_audits_agente_idx on public.chat_audits (agente_id, conversacion_fecha);

alter table public.chat_audit_batches enable row level security;
alter table public.chat_audits enable row level security;

-- Para tablas creadas antes de añadir la columna:
alter table public.chat_audits add column if not exists detalle jsonb;
