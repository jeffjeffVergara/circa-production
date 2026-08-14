-- IDs externos del ERP del distribuidor (integración API v1).
-- Permite upsert/consulta sin duplicar registros entre ERP y Circa.

alter table public.bodegas
  add column if not exists external_id text;

alter table public.pedidos
  add column if not exists external_id text;

comment on column public.bodegas.external_id is
  'ID de la bodega/cliente en el ERP del distribuidor (único por distribuidor_id).';

comment on column public.pedidos.external_id is
  'ID del pedido/preventa en el ERP del distribuidor (único por distribuidor_id).';

create unique index if not exists uq_bodegas_dist_external_id
  on public.bodegas (distribuidor_id, external_id)
  where external_id is not null and external_id <> '';

create unique index if not exists uq_pedidos_dist_external_id
  on public.pedidos (distribuidor_id, external_id)
  where external_id is not null and external_id <> '';

create index if not exists idx_bodegas_external_id
  on public.bodegas (external_id)
  where external_id is not null;
