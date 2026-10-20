-- La sesión de WhatsApp se guarda por teléfono (+51..., 12 caracteres) o,
-- si Meta omite el número, por el identificador de usuario (PE.xxx, hasta ~131).
-- varchar(15) rechazaba el identificador y el bot respondía "Hubo un error".

alter table public.sesiones alter column telefono type text;

comment on column public.sesiones.telefono is
  'Teléfono +51... o identificador de usuario de WhatsApp (PE.xxx) cuando Meta omite el número.';
