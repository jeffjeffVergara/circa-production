-- Cómo llamar al representante legal en mensajes informales (WhatsApp), sin sustituir el nombre legal en SUNAT/RENIEC.
alter table public.bodegas
    add column if not exists representante_nombre_corto text;

comment on column public.bodegas.representante_nombre_corto is
    'Apodo o nombre corto para saludar al representante en mensajes personales; no usar para contratos ni verificación legal.';
