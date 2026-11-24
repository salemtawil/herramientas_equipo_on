-- Auditoría CSAT (Chatwoot): resumen por período y encuestas negativas con su decisión.
-- Ejecutar una vez en el editor SQL de Supabase.
-- RLS activado sin políticas: solo el backend (service role) puede leer y escribir.
-- Solo guarda lo mínimo: sin transcripciones ni datos del cliente. Retención: 12 semanas
-- (la aplicación borra los períodos vencidos; los negativos caen por on delete cascade).

create table if not exists public.csat_audit_periods (
  id uuid primary key default gen_random_uuid(),
  tipo_periodo text,
  fecha_inicio date not null,
  fecha_fin date not null,
  total_encuestas integer,
  ratings_count jsonb,
  csat_real numeric,
  csat_ajustado numeric,
  por_agente jsonb,
  negativos_total integer,
  negativos_excluidos integer,
  negativos_pendientes integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (fecha_inicio, fecha_fin)
);

create table if not exists public.csat_audit_negatives (
  id bigserial primary key,
  period_id uuid not null references public.csat_audit_periods(id) on delete cascade,
  survey_id bigint not null,
  conversation_id bigint,
  agente_id bigint,
  agente_nombre text,
  rating integer,
  comentario text,
  enlace text,
  fecha timestamptz,
  ia_justificable text,
  ia_motivo text,
  ia_confianza numeric,
  ia_evidencia text,
  decision_final text,
  motivo_final text,
  origen_decision text,
  nota_auditor text,
  updated_at timestamptz not null default now(),
  unique (period_id, survey_id)
);

create index if not exists csat_audit_periods_fin_idx on public.csat_audit_periods (fecha_fin);

alter table public.csat_audit_periods enable row level security;
alter table public.csat_audit_negatives enable row level security;
