-- Teléfono WhatsApp del vendedor de campo (actor separado del bodeguero).
alter table public.vendedores
  add column if not exists telefono_whatsapp text;

create unique index if not exists vendedores_telefono_whatsapp_unique
  on public.vendedores (telefono_whatsapp)
  where telefono_whatsapp is not null;

comment on column public.vendedores.telefono_whatsapp is
  'WhatsApp del vendedor (+51...). Habilita flujo vendedor en el bot Circa.';
