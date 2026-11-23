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

-- Pauta QA-1.1 (noviembre 2026): manual de procedimientos, estado «clasificado» y resultados QA.
create table if not exists public.chat_audit_manual (
  version text not null,
  codigo text not null,
  titulo text not null default '',
  texto text not null default '',
  orden integer not null default 0,
  primary key (version, codigo)
);
alter table public.chat_audit_manual enable row level security;

alter table public.chat_audits add column if not exists ia_qa numeric(4,1);
alter table public.chat_audits add column if not exists ia_estado text;
alter table public.chat_audits add column if not exists qa_final numeric(4,1);
alter table public.chat_audits add column if not exists estado_final text;
alter table public.chat_audits add column if not exists revision jsonb;

alter table public.chat_audits drop constraint if exists chat_audits_estado_check;
alter table public.chat_audits add constraint chat_audits_estado_check
  check (estado in ('pendiente', 'procesando', 'leido', 'clasificado', 'auditado', 'error', 'revisado', 'descartado'));

-- Llamadas analizadas en Multiadmin (noviembre 2026). Sin teléfono del cliente ni transcripción.
create table if not exists public.chat_audit_calls (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.chat_audit_batches(id) on delete cascade,
  agente_id bigint not null,
  record_key text not null,
  linea text,
  ticket_id bigint,
  agent_number text,
  fecha timestamptz,
  duracion_seg integer,
  tipo text,
  intencion text,
  motivo text,
  puntaje numeric(5,2),
  sentimiento_agente text,
  sentimiento_cliente text,
  sin_conversacion boolean not null default false,
  detalle_ok boolean not null default false,
  analitica jsonb,
  rubrica jsonb,
  puntos_clave jsonb,
  coaching jsonb,
  created_at timestamptz not null default now(),
  unique (batch_id, record_key)
);
create index if not exists chat_audit_calls_lote_idx on public.chat_audit_calls (batch_id, agente_id);
alter table public.chat_audit_calls enable row level security;

create table if not exists public.chat_audit_agentes_llamadas (
  agent_number text primary key,
  chatwoot_agente_id bigint,
  manual boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.chat_audit_agentes_llamadas enable row level security;

alter table public.chat_audit_batches add column if not exists llamadas_estado text not null default 'pendiente';
alter table public.chat_audit_batches add column if not exists llamadas_progreso jsonb;
alter table public.chat_audit_batches add column if not exists llamadas_error text;
alter table public.chat_audit_batches add column if not exists feedback_llamadas jsonb;
alter table public.chat_audit_batches add column if not exists llamadas_sin_emparejar jsonb;
