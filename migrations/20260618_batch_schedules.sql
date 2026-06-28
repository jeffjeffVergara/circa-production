-- Programación de procesos batch (frecuencias horarias, diarias, semanales).

create table if not exists public.batch_schedules (
    id uuid primary key default gen_random_uuid(),
    job_id text not null,
    label text,
    activo boolean not null default true,
    frecuencia text not null check (frecuencia in ('hourly', 'every_n_hours', 'daily', 'weekly')),
    hour smallint not null default 6 check (hour >= 0 and hour <= 23),
    minute smallint not null default 0 check (minute >= 0 and minute <= 59),
    interval_hours smallint check (interval_hours is null or (interval_hours >= 1 and interval_hours <= 24)),
    weekdays smallint[] default '{}',
    test_filter text not null default 'real' check (test_filter in ('real', 'test')),
    timezone text not null default 'America/Lima',
    next_run_at timestamptz,
    last_run_at timestamptz,
    last_run_status text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_batch_schedules_next
    on public.batch_schedules (activo, next_run_at)
    where activo = true;

create index if not exists idx_batch_schedules_job
    on public.batch_schedules (job_id);
