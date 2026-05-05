-- Onboarding: bodegueros sin RUC inscrito (solo identidad por DNI + biometría).
alter table public.bodegas
    add column if not exists solo_dni_sin_ruc boolean not null default false;

comment on column public.bodegas.solo_dni_sin_ruc is
    'Si es true, el chat salta SUNAT/RUC y entra directo a reg_dni (RENIEC + foto DNI + biometria). Marcar solo en altas previas acordadas.';
