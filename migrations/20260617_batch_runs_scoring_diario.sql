-- Centro de procesos batch: ejecuciones y historial diario de score.

create table if not exists public.batch_runs (
    id uuid primary key default gen_random_uuid(),
    job_id text not null,
    status text not null check (status in ('running', 'ok', 'partial', 'failed')),
    trigger text not null default 'manual',
    test_filter text,
    dry_run boolean not null default false,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    stats jsonb,
    error text,
    user_email text,
    comment text
);

create index if not exists idx_batch_runs_job_started
    on public.batch_runs (job_id, started_at desc);

create table if not exists public.bodega_scoring_diario (
    id uuid primary key default gen_random_uuid(),
    bodega_id uuid not null references public.bodegas (id) on delete cascade,
    fecha date not null,
    score int not null,
    grade text,
    breakdown jsonb,
    linea_aprobada numeric,
    linea_disponible numeric,
    unique (bodega_id, fecha)
);

create index if not exists idx_bodega_scoring_diario_fecha
    on public.bodega_scoring_diario (fecha desc);

create index if not exists idx_bodega_scoring_diario_bodega
    on public.bodega_scoring_diario (bodega_id, fecha desc);
