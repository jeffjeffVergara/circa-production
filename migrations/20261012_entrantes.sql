-- Entrantes: pedido del distribuidor antes de entrar al flujo de pre-venta.
-- No reserva línea ni crea fila en pedidos.

create table if not exists public.entrantes (
  id uuid primary key default gen_random_uuid(),
  distribuidor_id uuid not null references public.distribuidores(id),
  es_test boolean not null default false,
  external_id text not null,
  bodega_nombre text not null,
  fecha date,
  items jsonb not null default '[]'::jsonb,
  total_pedido numeric(12,2) not null default 0,
  descuento_prorrateado numeric(12,2) not null default 0,
  monto_productos numeric(12,2) not null default 0,
  bodega_id uuid references public.bodegas(id),
  match_score integer,
  candidatos jsonb not null default '[]'::jsonb,
  existe_en_circa boolean not null default false,
  bodega_activa boolean not null default false,
  monto_credito numeric(12,2),
  pago_confirmado boolean not null default false,
  estado text not null default 'sin_match',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint entrantes_estado_chk check (
    estado in ('sin_match', 'pendiente_monto', 'pendiente_pago', 'lista', 'descartada')
  )
);

create unique index if not exists uq_entrantes_dist_modo_external
  on public.entrantes (distribuidor_id, es_test, external_id);

create index if not exists idx_entrantes_estado
  on public.entrantes (estado, created_at desc);

comment on table public.entrantes is
  'Pedido entrante del distribuidor. No es una pre-venta Circa hasta que ops lo pase al flujo normal.';

alter table public.entrantes enable row level security;

drop policy if exists service_role_all on public.entrantes;
create policy service_role_all on public.entrantes
  for all to service_role
  using (true)
  with check (true);
