-- Corrige pedidos asignados por error a Zoom (submit-cart hardcodeado).
-- Solo bodegas en piloto comercial (en_piloto=true, es_test=false).
-- NO toca: bodegas es_test (deben seguir en Zoom) ni fuera de piloto.

-- Vista previa (ejecutar primero):
-- SELECT p.numero, p.estado, b.nombre_comercial, b.en_piloto, b.es_test
-- FROM pedidos p
-- JOIN bodegas b ON b.id = p.bodega_id
-- WHERE b.en_piloto = true
--   AND COALESCE(b.es_test, false) = false
--   AND p.distribuidor_id = 'a1b2c3d4-0001-4000-8000-000000000001';

UPDATE pedidos p
SET distribuidor_id = 'd1a2b3c4-0001-4000-8000-000000000002'
FROM bodegas b
WHERE p.bodega_id = b.id
  AND b.en_piloto = true
  AND COALESCE(b.es_test, false) = false
  AND p.distribuidor_id = 'a1b2c3d4-0001-4000-8000-000000000001'
  AND p.estado IN (
    'borrador', 'preventa_borrador', 'confirmado', 'preventa_confirmada',
    'recibido', 'en_preparacion', 'despachado', 'en_camino', 'entregado',
    'pago_reportado'
  );
