-- Mensajes WA huérfanos (batch CSV sin bodega_id): vincular por teléfono.
update public.messages m
set bodega_id = b.id
from public.bodegas b
where m.bodega_id is null
  and m.telefono is not null
  and b.telefono_whatsapp is not null
  and (
    m.telefono = b.telefono_whatsapp
    or m.telefono = replace(b.telefono_whatsapp, '+', '')
    or ('+' || m.telefono) = b.telefono_whatsapp
    or m.telefono = ('+' || regexp_replace(b.telefono_whatsapp, '\D', '', 'g'))
    or regexp_replace(m.telefono, '\D', '', 'g') = regexp_replace(b.telefono_whatsapp, '\D', '', 'g')
  );
