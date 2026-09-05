-- Fotos de precarga vía Integration API (SVC-02)
alter table public.bodegas
  add column if not exists foto_dueno_url text;

alter table public.bodegas
  add column if not exists foto_bodega_url text;

comment on column public.bodegas.foto_dueno_url is
  'Path Storage (sustentos) de la foto del dueño enviada por el socio en precarga.';

comment on column public.bodegas.foto_bodega_url is
  'Path Storage (sustentos) de la foto de la bodega/fachada enviada por el socio en precarga.';
