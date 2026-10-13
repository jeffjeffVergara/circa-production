-- La fecha del entrante incluye hora. El negocio opera en GMT-5:
-- un día suelto se guarda a las 00:00 America/Lima, sin correr el calendario.

alter table public.entrantes
  alter column fecha type timestamptz
  using (
    case
      when fecha is null then null
      else (fecha::timestamp at time zone 'America/Lima')
    end
  );
