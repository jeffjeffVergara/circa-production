-- Backfill: vendedores.celular → vendedores.telefono_whatsapp
-- Normaliza al formato Perú usado por la app (+51987654321).
-- Ejecutar en Supabase SQL Editor DESPUÉS de 20260603_vendedores_telefono_whatsapp.sql

-- ── 1) Vista previa (revisar antes de actualizar) ──
with normalized as (
  select
    v.id,
    v.codigo,
    v.nombre,
    v.celular,
    v.telefono_whatsapp as telefono_whatsapp_actual,
    case
      when v.celular is null or trim(v.celular) = '' then null
      when regexp_replace(trim(v.celular), '[^0-9+]', '', 'g') like '+51%'
        then regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when regexp_replace(trim(v.celular), '[^0-9]', '', 'g') like '51%'
        and length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 11
        then '+' || regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 9
        then '+51' || regexp_replace(trim(v.celular), '[^0-9]', '', 'g')
      when trim(v.celular) like '+%'
        then trim(v.celular)
      else null
    end as telefono_whatsapp_nuevo
  from public.vendedores v
)
select *
from normalized
where celular is not null
  and trim(celular) <> ''
order by codigo;

-- ── 2) Filas que NO se copiarán (formato inválido) ──
with normalized as (
  select
    v.id,
    v.codigo,
    v.nombre,
    v.celular,
    case
      when v.celular is null or trim(v.celular) = '' then null
      when regexp_replace(trim(v.celular), '[^0-9+]', '', 'g') like '+51%'
        then regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when regexp_replace(trim(v.celular), '[^0-9]', '', 'g') like '51%'
        and length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 11
        then '+' || regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 9
        then '+51' || regexp_replace(trim(v.celular), '[^0-9]', '', 'g')
      when trim(v.celular) like '+%'
        then trim(v.celular)
      else null
    end as tel_norm
  from public.vendedores v
  where (v.telefono_whatsapp is null or trim(v.telefono_whatsapp) = '')
    and v.celular is not null
    and trim(v.celular) <> ''
)
select id, codigo, nombre, celular, 'formato_invalido' as motivo
from normalized
where tel_norm is null
order by codigo;

-- ── 2b) Duplicados omitidos (mismo teléfono en varios vendedores o ya ocupado) ──
with normalized as (
  select
    v.id,
    v.codigo,
    v.nombre,
    v.celular,
    case
      when regexp_replace(trim(v.celular), '[^0-9+]', '', 'g') like '+51%'
        then regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when regexp_replace(trim(v.celular), '[^0-9]', '', 'g') like '51%'
        and length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 11
        then '+' || regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 9
        then '+51' || regexp_replace(trim(v.celular), '[^0-9]', '', 'g')
      when trim(v.celular) like '+%'
        then trim(v.celular)
      else null
    end as tel_norm
  from public.vendedores v
  where (v.telefono_whatsapp is null or trim(v.telefono_whatsapp) = '')
    and v.celular is not null
    and trim(v.celular) <> ''
),
ranked as (
  select
    n.*,
    row_number() over (partition by n.tel_norm order by n.codigo, n.id) as rn
  from normalized n
  where n.tel_norm is not null
)
select r.id, r.codigo, r.nombre, r.celular, r.tel_norm,
  case
    when exists (
      select 1 from public.vendedores v2
      where v2.telefono_whatsapp = r.tel_norm and v2.id <> r.id
    ) then 'ya_ocupado_en_otro_vendedor'
    when r.rn > 1 then 'duplicado_mismo_celular'
  end as motivo
from ranked r
where exists (
      select 1 from public.vendedores v2
      where v2.telefono_whatsapp = r.tel_norm and v2.id <> r.id
    )
   or r.rn > 1
order by r.tel_norm, r.codigo;

-- ── 3) ACTUALIZAR (solo donde telefono_whatsapp está vacío) ──
with normalized as (
  select
    v.id,
    case
      when v.celular is null or trim(v.celular) = '' then null
      when regexp_replace(trim(v.celular), '[^0-9+]', '', 'g') like '+51%'
        then regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when regexp_replace(trim(v.celular), '[^0-9]', '', 'g') like '51%'
        and length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 11
        then '+' || regexp_replace(trim(v.celular), '[^0-9+]', '', 'g')
      when length(regexp_replace(trim(v.celular), '[^0-9]', '', 'g')) = 9
        then '+51' || regexp_replace(trim(v.celular), '[^0-9]', '', 'g')
      when trim(v.celular) like '+%'
        then trim(v.celular)
      else null
    end as tel_norm
  from public.vendedores v
  where (v.telefono_whatsapp is null or trim(v.telefono_whatsapp) = '')
    and v.celular is not null
    and trim(v.celular) <> ''
),
candidates as (
  select
    n.id,
    n.tel_norm,
    row_number() over (partition by n.tel_norm order by n.id) as rn
  from normalized n
  where n.tel_norm is not null
    and not exists (
      select 1
      from public.vendedores v2
      where v2.telefono_whatsapp = n.tel_norm
        and v2.id <> n.id
    )
)
update public.vendedores v
set telefono_whatsapp = c.tel_norm
from candidates c
where v.id = c.id
  and c.rn = 1;

-- ── 4) Verificación final ──
select
  count(*) filter (where telefono_whatsapp is not null and trim(telefono_whatsapp) <> '') as con_whatsapp,
  count(*) filter (where celular is not null and trim(celular) <> ''
    and (telefono_whatsapp is null or trim(telefono_whatsapp) = '')) as celular_sin_migrar,
  count(*) as total
from public.vendedores;
