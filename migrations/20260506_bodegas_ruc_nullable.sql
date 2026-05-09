-- Permite bodegas sin RUC aún cargado (p. ej. altas solo-DNI o limpieza de prueba).
-- El bot sigue resolviendo bodega por WhatsApp; get_bodega_by_ruc solo aplica cuando el usuario envía RUC.
alter table public.bodegas
    alter column ruc drop not null;

comment on column public.bodegas.ruc is
    'RUC de la bodega; puede ser null hasta que se asigne en alta o onboarding.';
