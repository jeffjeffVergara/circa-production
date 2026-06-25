-- Circa - SQL de carga de bodegas
-- Cada bodega es un bloque BEGIN/COMMIT independiente.

-- ====================================================
-- Bodega: MARKET TRADING SOCIEDAD ANONIMA CERRADA
-- Linea aprobada: S/100  (modelo: consumo 7d = S/85.34)
-- ====================================================
BEGIN;

-- Crear la bodega (estado inactivo, disponible 0 hasta onboarding)
INSERT INTO bodegas (
  distribuidor_id, razon_social, nombre_comercial, telefono_whatsapp,
  ruc, dni_representante, solo_dni_sin_ruc,
  direccion_fiscal, direccion_despacho, distrito,
  es_test, en_piloto, estado, linea_aprobada, linea_disponible)
SELECT 'd1a2b3c4-0001-4000-8000-000000000002', 'MARKET TRADING SOCIEDAD ANONIMA CERRADA', 'MARKET TRADING SOCIEDAD ANONIMA CERRADA', '+51949387007',
       '20606378239', NULL, false,
       'Av Comandante Espinar Nro. 852 Urb. Miraflores (ovalo Gutierrez)', 'Av Comandante Espinar Nro. 852 Urb. Miraflores (ovalo Gutierrez)', 'Miraflores',
       false, true, 'inactivo', 100, 0
WHERE NOT EXISTS (
  SELECT 1 FROM bodegas WHERE telefono_whatsapp = '+51949387007');


SELECT 'bodega' AS tipo, razon_social AS detalle,
       linea_aprobada::text AS aprob, linea_disponible::text AS disp,
       estado::text AS estado
FROM bodegas WHERE telefono_whatsapp = '+51949387007'
UNION ALL
SELECT 'mapping', b.razon_social || ' -> ' || v.codigo,
       bv.rol, bv.grupo, bv.dia_visita
FROM bodega_vendedores bv
JOIN bodegas b ON b.id = bv.bodega_id
JOIN vendedores v ON v.id = bv.vendedor_id
WHERE b.telefono_whatsapp = '+51949387007';

COMMIT;


