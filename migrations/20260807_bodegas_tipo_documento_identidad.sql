-- Tipo de documento del representante: dni (8) | ce (carné de extranjería, 9).
-- El número sigue en dni_representante; este campo distingue el flujo KYC.
alter table public.bodegas
  add column if not exists tipo_documento_identidad text;

comment on column public.bodegas.tipo_documento_identidad is
  'dni | ce. CE = carné de extranjería (9 dígitos), sin validación RENIEC.';

-- Backfill: 9 dígitos → ce; 8 → dni; resto NULL
update public.bodegas
set tipo_documento_identidad = 'ce'
where tipo_documento_identidad is null
  and dni_representante ~ '^[0-9]{9}$';

update public.bodegas
set tipo_documento_identidad = 'dni'
where tipo_documento_identidad is null
  and dni_representante ~ '^[0-9]{8}$';
