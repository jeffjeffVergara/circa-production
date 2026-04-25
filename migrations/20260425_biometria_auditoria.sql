-- Biometric verification audit trail (DNI anverso + selfie)
create extension if not exists pgcrypto;

create table if not exists public.biometria_auditoria (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    bodega_id uuid null references public.bodegas(id) on delete set null,
    telefono text not null,
    etapa text not null check (etapa in ('dni_anverso', 'selfie')),
    hit boolean not null,
    reason text not null default '',
    reason_code text not null default '',
    confidence text not null default '',
    provider text not null default '',
    model text not null default '',
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists idx_biometria_auditoria_bodega_id
    on public.biometria_auditoria (bodega_id);

create index if not exists idx_biometria_auditoria_telefono_created_at
    on public.biometria_auditoria (telefono, created_at desc);

create index if not exists idx_biometria_auditoria_etapa_hit
    on public.biometria_auditoria (etapa, hit, created_at desc);

alter table public.biometria_auditoria enable row level security;

-- No public policies by default. Service role can still write/read.
