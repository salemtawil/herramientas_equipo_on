create table if not exists public.work_shift_state (
  id text primary key,
  state jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.work_shift_state disable row level security;

insert into public.work_shift_state (id, state)
values (
  'main',
  '{
    "version": 1,
    "created_at": "",
    "updated_at": "",
    "shifts": [],
    "agents": {},
    "assignments": {},
    "history": []
  }'::jsonb
)
on conflict (id) do nothing;
