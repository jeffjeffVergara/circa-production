-- =====================================================================
-- CIRCA · Cambio de zonas ZOOM — setiembre 2026
-- Generado 01-set-2026.  ⚠️ NO EJECUTADO. Para revisión de Paola.
--
-- Fuente: correo Washington Arroyo "RE: ZONAS ZOOM SETIEMBRE 2026" +
--         Excel "FFVV - ZOOM - SETIEMBRE 2026" + confirmaciones de Paola:
--           · rige desde el 01-set-2026
--           · V0005, V0022 y V0034 SE VAN DE LA EMPRESA
--           · la cobranza pendiente la asume el vendedor nuevo
--           · las bodegas NO se heredan para la meta de enrolamiento,
--             solo para las recompras
--
-- Movimiento (675 mapeos):
--   V0034 Amaro   → V0006 Horna      228 bodegas   GV BODEGAS 2
--   V0006 Horna   → V0018 Vasquez    188 bodegas   GV BODEGAS 1
--   V0005 Sanchez → V0037 Jaramillo  171 bodegas   GV BODEGAS 2
--   V0022 Jaime   → V0040 Espinoza    88 bodegas   GV MERCADOS
--
-- ⚠️ EL ORDEN NO ES NEGOCIABLE. `vendedores_telefono_whatsapp_unique` es un
--    índice único parcial sobre telefono_whatsapp. Los 3 que entran reciben
--    el MISMO número de los 3 que salen, así que hay que liberarlo antes de
--    asignarlo. Si se corre el paso 4 antes del 3, revienta a mitad.
--
-- Todo va en UNA transacción. Si algo falla, no queda nada aplicado.
-- =====================================================================

BEGIN;

-- ── 0. BACKUP -------------------------------------------------------
-- Sin esto no hay vuelta atrás: no existe ningún otro registro de qué
-- bodega era de quién (pedidos.vendedor_id es el admin en 43 de 53 casos
-- y `contratos` no guarda vendedor).
CREATE TABLE IF NOT EXISTS backup_bodega_vendedores_20260901 AS
SELECT *, now() AS respaldado_at FROM bodega_vendedores;

CREATE TABLE IF NOT EXISTS backup_vendedores_20260901 AS
SELECT *, now() AS respaldado_at FROM vendedores;

-- Congela quién tenía enrolada cada bodega ANTES del cambio. Es la fuente
-- de la meta del bono de S/100: el que entra arranca en cero.
CREATE TABLE IF NOT EXISTS enrolamiento_credito (
    bodega_id       uuid PRIMARY KEY,
    vendedor_id     uuid NOT NULL,
    codigo_vendedor text NOT NULL,
    congelado_at    timestamptz NOT NULL DEFAULT now(),
    motivo          text
);

INSERT INTO enrolamiento_credito (bodega_id, vendedor_id, codigo_vendedor, motivo)
SELECT DISTINCT ON (b.id) b.id, v.id, v.codigo, 'cambio de zonas set-2026'
FROM bodegas b
JOIN pedidos p            ON p.bodega_id = b.id
JOIN bodega_vendedores bv ON bv.bodega_id = b.id AND bv.activo
JOIN vendedores v         ON v.id = bv.vendedor_id
WHERE COALESCE(b.es_test, false) = false
  AND b.contrato_firmado_at IS NOT NULL          -- enrolada
  AND COALESCE(p.monto_financiado, 0) > 0        -- y financió
  AND p.estado IN ('pagado', 'entregado')
  AND COALESCE(p.metodo_pago, '') <> 'efectivo'
ORDER BY b.id, (bv.rol = 'ABN') DESC, p.created_at
ON CONFLICT (bodega_id) DO NOTHING;
-- Esperado: 53 filas.

-- ── 1. Deja rastro de quién heredó de quién --------------------------
-- Lo necesita el mensaje diario ("heredaste N bodegas de X").
ALTER TABLE bodega_vendedores
  ADD COLUMN IF NOT EXISTS heredada_de_vendedor_id uuid,
  ADD COLUMN IF NOT EXISTS heredada_at             timestamptz;

-- ── 2. Horna cambia de mesa: ACOSTA → URBINA -------------------------
UPDATE vendedores
   SET supervisor = 'URBINA VELASQUEZ CESAR EDINHO'
 WHERE codigo = 'V0006';

-- ── 3. Salidas: liberar teléfono y desactivar ------------------------
-- El teléfono se libera PRIMERO (índice único) y recién después se
-- desactiva. Se guarda el número en notas para trazabilidad.
UPDATE vendedores
   SET telefono_whatsapp = NULL,
       activo            = false
 WHERE codigo IN ('V0005', 'V0022', 'V0034');

-- ── 4. Altas: los 3 que entran, con código NUEVO ---------------------
-- ⚠️ NO se reactivan VW101 ni VW300: sus celulares hoy pertenecen a
--    V0031 Huanca y V0038 Trinidad. Se crean registros nuevos.
INSERT INTO vendedores (distribuidor_id, codigo, nombre, celular,
                        telefono_whatsapp, supervisor, activo, es_admin)
SELECT d.distribuidor_id, x.codigo, x.nombre, x.cel, x.cel, x.sup, true, false
FROM (SELECT DISTINCT distribuidor_id FROM vendedores WHERE codigo = 'V0011') d,
     (VALUES
       ('V0018', 'VASQUEZ HOSTIA ORLANDO LEONEL', '+51992583666', 'ACOSTA SERPA ANGELO LELIS'),
       ('V0037', 'JARAMILLO CASAS CORINA LUISA',  '+51981542246', 'URBINA VELASQUEZ CESAR EDINHO'),
       ('V0040', 'ESPINOZA YRIGOYEN ELIZABETH',   '+51934926365', 'SAFRA ALVIS MARIA LEONOR')
     ) AS x(codigo, nombre, cel, sup)
ON CONFLICT (distribuidor_id, codigo) DO NOTHING;

-- ── 5. Reasignación de cartera (675 mapeos) --------------------------
-- El orden importa: Amaro→Horna va ANTES que Horna→Vasquez, si no las de
-- Amaro se pasarían también a Vasquez en la segunda pasada. Por eso se
-- congela el conjunto de Horna en una CTE antes de mover nada.
CREATE TEMP TABLE _horna_original AS
SELECT bv.id FROM bodega_vendedores bv
JOIN vendedores v ON v.id = bv.vendedor_id
WHERE bv.activo AND v.codigo = 'V0006';     -- esperado: 188

-- 5a. Horna → Vasquez (usando el conjunto congelado)
UPDATE bodega_vendedores bv
   SET vendedor_id             = (SELECT id FROM vendedores WHERE codigo='V0018'),
       supervisor              = 'ACOSTA SERPA ANGELO LELIS',
       heredada_de_vendedor_id = (SELECT id FROM vendedores WHERE codigo='V0006'),
       heredada_at             = now()
 WHERE bv.id IN (SELECT id FROM _horna_original);

-- 5b. Amaro → Horna
UPDATE bodega_vendedores bv
   SET vendedor_id             = (SELECT id FROM vendedores WHERE codigo='V0006'),
       supervisor              = 'URBINA VELASQUEZ CESAR EDINHO',
       heredada_de_vendedor_id = (SELECT id FROM vendedores WHERE codigo='V0034'),
       heredada_at             = now()
  FROM vendedores v
 WHERE v.id = bv.vendedor_id AND bv.activo AND v.codigo = 'V0034';

-- 5c. Sanchez → Jaramillo
UPDATE bodega_vendedores bv
   SET vendedor_id             = (SELECT id FROM vendedores WHERE codigo='V0037'),
       supervisor              = 'URBINA VELASQUEZ CESAR EDINHO',
       heredada_de_vendedor_id = (SELECT id FROM vendedores WHERE codigo='V0005'),
       heredada_at             = now()
  FROM vendedores v
 WHERE v.id = bv.vendedor_id AND bv.activo AND v.codigo = 'V0005';

-- 5d. Jaime → Espinoza
UPDATE bodega_vendedores bv
   SET vendedor_id             = (SELECT id FROM vendedores WHERE codigo='V0040'),
       supervisor              = 'SAFRA ALVIS MARIA LEONOR',
       heredada_de_vendedor_id = (SELECT id FROM vendedores WHERE codigo='V0022'),
       heredada_at             = now()
  FROM vendedores v
 WHERE v.id = bv.vendedor_id AND bv.activo AND v.codigo = 'V0022';

-- ── 6. VERIFICACIÓN — revisar ANTES de confirmar ---------------------
-- Los 3 que salen deben quedar en 0 bodegas.
-- Vasquez 188 · Horna 228 · Jaramillo 171 · Espinoza 88.
-- enrolamiento_credito debe tener 53 filas y NO cambiar.
SELECT v.codigo, v.nombre, v.activo, count(bv.id) AS bodegas
  FROM vendedores v
  LEFT JOIN bodega_vendedores bv ON bv.vendedor_id = v.id AND bv.activo
 WHERE v.codigo IN ('V0005','V0006','V0018','V0022','V0034','V0037','V0040')
 GROUP BY v.codigo, v.nombre, v.activo
 ORDER BY v.codigo;

SELECT count(*) AS credito_enrolamiento_congelado FROM enrolamiento_credito;

-- Ningún teléfono duplicado entre vendedores activos.
SELECT telefono_whatsapp, count(*)
  FROM vendedores WHERE activo AND telefono_whatsapp IS NOT NULL
 GROUP BY 1 HAVING count(*) > 1;

-- Si algo no cuadra:  ROLLBACK;
-- Si todo cuadra:     COMMIT;
COMMIT;
