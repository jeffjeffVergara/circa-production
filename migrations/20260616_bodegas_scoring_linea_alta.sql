-- Snapshot al alta: línea y score proxy (tier DIMAX) para comparar con score operativo actual.
alter table public.bodegas
    add column if not exists linea_alta numeric,
    add column if not exists scoring_alta numeric;

comment on column public.bodegas.linea_alta is 'Línea aprobada al momento del alta (snapshot).';
comment on column public.bodegas.scoring_alta is 'Score proxy 0-100 al alta según tier DIMAX; no es el score operativo Circa.';

-- Backfill aproximado para bodegas ya existentes.
update public.bodegas
set linea_alta = linea_aprobada
where linea_alta is null and linea_aprobada is not null;

update public.bodegas
set scoring_alta = case
    when coalesce(linea_aprobada, 0) <= 100 then 58
    when linea_aprobada <= 200 then 68
    when linea_aprobada <= 300 then 76
    when linea_aprobada <= 400 then 84
    else 90
end
where scoring_alta is null and linea_aprobada is not null and linea_aprobada > 0;
