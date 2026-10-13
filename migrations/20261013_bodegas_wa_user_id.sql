-- Identificador de WhatsApp (BSUID) cuando Meta omite el teléfono
-- porque la persona usa un nombre de usuario.

alter table public.bodegas
  add column if not exists wa_user_id text;

comment on column public.bodegas.wa_user_id is
  'BSUID de WhatsApp. Sirve para reconocer a la bodega cuando el webhook llega sin teléfono.';

create unique index if not exists uq_bodegas_wa_user_id
  on public.bodegas (wa_user_id)
  where wa_user_id is not null and wa_user_id <> '';
