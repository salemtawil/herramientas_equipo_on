-- Incidencias de chats: revisiones, chats evaluados, decisiones del manager y cupo diario de IA.
-- Ejecutar una vez en el editor SQL de Supabase.
-- RLS activado sin políticas: solo el backend (service role) puede leer y escribir.

create table if not exists public.chat_incident_reviews (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  since bigint not null,
  until bigint not null,
  bandejas jsonb not null default '[]'::jsonb,
  usar_ia boolean not null default false,
  estado text not null default 'listando'
    check (estado in ('listando', 'evaluando', 'ia', 'completado', 'con_errores')),
  pagina_listado integer not null default 1,
  contadores jsonb not null default '{}'::jsonb,
  csat jsonb, -- mapa conversación -> puntuación; null mientras no se haya pedido
  csat_error text,
  reglas_version text not null default '',
  modelo text not null default '',
  creado_por text
);

create table if not exists public.chat_incident_chats (
  id uuid primary key default gen_random_uuid(),
  review_id uuid not null references public.chat_incident_reviews(id) on delete cascade,
  conversation_id bigint not null,
  agente_id bigint,
  agente_nombre text not null default '',
  inbox_id bigint,
  conversacion_fecha timestamptz,
  resuelto boolean not null default false,
  status text, -- estado de la conversación en Chatwoot al listar
  last_activity_at bigint, -- epoch de la última actividad al listar, para decidir la reutilización
  estado text not null default 'pendiente'
    check (estado in ('pendiente', 'procesando', 'evaluado', 'descartado', 'error')),
  intentos integer not null default 0,
  motivo_descarte text,
  incidencias jsonb not null default '[]'::jsonb,
  metricas jsonb,
  ia_estado text,
  ia_resultado jsonb,
  transcripcion_tmp text,
  reglas_version text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists chat_incident_chats_review_conv_idx
  on public.chat_incident_chats (review_id, conversation_id);
create index if not exists chat_incident_chats_conv_idx
  on public.chat_incident_chats (conversation_id, updated_at);
create index if not exists chat_incident_chats_estado_idx
  on public.chat_incident_chats (review_id, estado);

-- La decisión del manager es por conversación, no por revisión.
create table if not exists public.chat_incident_decisions (
  conversation_id bigint primary key,
  decision text not null check (decision in ('atendida', 'falso_positivo')),
  por text,
  nota text,
  review_id uuid,
  decidido_at timestamptz not null default now()
);

-- Cupo diario de IA: un contador por fecha.
create table if not exists public.chat_incident_ai_usage (
  fecha date primary key,
  usados integer not null default 0
);

alter table public.chat_incident_reviews enable row level security;
alter table public.chat_incident_chats enable row level security;
alter table public.chat_incident_decisions enable row level security;
alter table public.chat_incident_ai_usage enable row level security;
