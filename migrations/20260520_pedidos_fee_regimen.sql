-- Régimen de comisión por pedido (legacy vs plan fijo al confirmar).
-- Aplicar en Supabase SQL Editor o: supabase db push / migration runner del proyecto.

ALTER TABLE pedidos
  ADD COLUMN IF NOT EXISTS fee_regimen TEXT;

COMMENT ON COLUMN pedidos.fee_regimen IS
  'legacy_v20260428 = comisión 3/5/7% congelada al confirmar; plan_fijo_v20260520 = 1.4/3/6% + min S/1';

-- Pedidos ya confirmados antes del deploy → legacy (no recalcular fee_monto)
UPDATE pedidos
SET fee_regimen = 'legacy_v20260428'
WHERE fee_regimen IS NULL
  AND COALESCE(fee_monto, 0) > 0
  AND estado NOT IN ('borrador', 'preventa_borrador');

-- Borradores y futuros quedan NULL hasta confirmar (el app escribe plan_fijo_v20260520)
