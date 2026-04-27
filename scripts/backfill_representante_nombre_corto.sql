-- Backfill de representante_nombre_corto desde representante_legal (primera palabra).
-- Idempotente: no toca filas donde ya hay un nombre corto no vacío.
-- Ejecutar en Supabase SQL Editor o psql después de la migración que crea la columna.
--
-- 1) Vista previa (revisar antes del UPDATE):
-- SELECT id,
--        representante_legal,
--        left(trim(both ' .,;:' from split_part(trim(representante_legal), ' ', 1)), 80) AS propuesto
-- FROM public.bodegas
-- WHERE coalesce(trim(representante_nombre_corto), '') = ''
--   AND coalesce(trim(representante_legal), '') <> '';

BEGIN;

UPDATE public.bodegas
SET representante_nombre_corto = left(
        trim(both ' .,;:' from split_part(trim(representante_legal), ' ', 1)),
        80
    )
WHERE coalesce(trim(representante_nombre_corto), '') = ''
  AND coalesce(trim(representante_legal), '') <> ''
  AND trim(both ' .,;:' from split_part(trim(representante_legal), ' ', 1)) <> '';

-- Opcional: ver cuántas filas quedaron sin corto (sin representante_legal útil)
-- SELECT count(*) AS sin_corto
-- FROM public.bodegas
-- WHERE coalesce(trim(representante_nombre_corto), '') = '';

COMMIT;

-- Ajustes manuales puntuales (ejemplo):
-- UPDATE public.bodegas
-- SET representante_nombre_corto = 'María'
-- WHERE id = '00000000-0000-0000-0000-000000000000';
