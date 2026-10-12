-- ============================================================================
-- CIRCA · Actualización FFVV ZOOM (roster AGOSTO 2026) — PARA CONFIRMAR CON WAS
-- Proyecto Supabase: rhxqcoijzgqlecpdfhde
-- Generado: 2026-08-05
--
-- CÓMO USAR:
--   PARTE 1 = solo lectura. Córrela para CONFIRMAR el estado actual.
--   PARTE 2 = cambios propuestos. NO ejecutar hasta que WAS confirme.
--   PARTE 3 = verificación después de aplicar.
--
-- REGLA DE REEMPLAZO: el vendedor se identifica por su TELÉFONO/ruta.
-- Como cada reemplazo se hace sobre el MISMO registro interno (mismo UUID),
-- la cartera (bodega_vendedores) se transfiere sola: no hay que mover bodegas.
-- ============================================================================


-- ============================================================================
-- PARTE 1 · VERIFICACIÓN (SOLO LECTURA)
-- ============================================================================

-- 1.1  Reemplazos por teléfono: ¿quién tiene HOY cada ruta y cuántas bodegas?
SELECT right(regexp_replace(coalesce(v.celular,''),'[^0-9]','','g'),9) AS cel9,
       v.codigo, v.nombre, v.activo,
       count(bv.*) FILTER (WHERE bv.activo) AS cartera_activa
FROM vendedores v
LEFT JOIN bodega_vendedores bv ON bv.vendedor_id = v.id
WHERE right(regexp_replace(coalesce(v.celular,''),'[^0-9]','','g'),9)
      IN ('934885451','934927863','955520407')
GROUP BY 1,2,3,4
ORDER BY 1;
-- Esperado (estado actual):
--   934885451 -> VW300 JARAMILLO CASAS CORINA LUISA   (21 bodegas)  => entra TRINIDAD GONZALES STPEFANY
--   934927863 -> VW101 VASQUEZ HOSTIA ORLANDO LEONEL  (12 bodegas)  => entra HUANCA CHAVEZ FIORELLA
--   955520407 -> VW174 DULUDE VASQUEZ JOSE LUIS       (12 bodegas)  => entra PORTILLO PORRAS LUIS ENRIQUE
--   (955520407 también existe como VW330 PORTILLO, inactivo, registro viejo)

-- 1.2  Reactivaciones (activos en el roster, inactivos en la base)
SELECT codigo, nombre, celular, supervisor, activo
FROM vendedores
WHERE codigo IN ('VW74','VW78');   -- LLANOS DIAZ ERICK / CARDENAS MACHADO PATRICIA

-- 1.3  Cambio de supervisor
SELECT codigo, nombre, supervisor
FROM vendedores
WHERE codigo = 'VW205';            -- SANCHEZ ALVARADO JORGE LUIS (base=ACOSTA -> roster=URBINA)

-- 1.4  (Contexto) Las 3 bodegas ya corregidas hoy — deben aparecer con su vendedor real
SELECT b.razon_social, v.codigo, v.nombre, bv.activo
FROM bodega_vendedores bv
JOIN bodegas b     ON b.id = bv.bodega_id
JOIN vendedores v  ON v.id = bv.vendedor_id
WHERE bv.bodega_id IN ('42e33b9c-fdf4-41fa-8ab5-78667555000e',  -- Montes (CRC-094)
                       '550fa56d-71f5-4bed-8622-abdcebcd6cc8',  -- Vizarreta (CRC-095)
                       '362fc8c7-db07-4d5c-aedb-d208a35ad915')  -- Miranda (CRC-096)
ORDER BY b.razon_social, bv.activo DESC;


-- ============================================================================
-- PARTE 2 · CAMBIOS PROPUESTOS  (⚠️ NO EJECUTAR HASTA QUE WAS CONFIRME)
-- ============================================================================

BEGIN;

-- 2.1  REEMPLAZOS POR TELÉFONO (renombrar el registro; la cartera se mantiene)
--      Ruta 934885451: JARAMILLO CORINA -> TRINIDAD GONZALES STPEFANY (hereda 21 bodegas)
UPDATE vendedores SET nombre = 'TRINIDAD GONZALES STPEFANY MILAGROS'
WHERE codigo = 'VW300';

--      Ruta 934927863: VASQUEZ ORLANDO -> HUANCA CHAVEZ FIORELLA (hereda 12 bodegas)
UPDATE vendedores SET nombre = 'HUANCA CHAVEZ FIORELLA'
WHERE codigo = 'VW101';

--      Ruta 955520407: DULUDE JOSE -> PORTILLO PORRAS LUIS ENRIQUE (hereda 12 bodegas)
UPDATE vendedores SET nombre = 'PORTILLO PORRAS LUIS ENRIQUE'
WHERE codigo = 'VW174';
--      NOTA: existe un registro viejo VW330 (PORTILLO, inactivo). Queda sin uso.
--      Si WAS prefiere consolidar en VW330 en vez de renombrar VW174, avisar y se
--      arma la variante (mover cartera VW174 -> VW330 + activar VW330 + desactivar VW174).

-- 2.2  REACTIVACIONES
--      LLANOS DIAZ ERICK SAUL (GV BODEGAS 1 / ACOSTA) — celular estaba vacío
UPDATE vendedores
SET activo = true, supervisor = 'ACOSTA SERPA ANGELO LELIS',
    celular = coalesce(celular, '981444119')
WHERE codigo = 'VW74';

--      CARDENAS MACHADO PATRICIA IVONNE (GV BODEGAS 1 / ACOSTA)
--      OJO: su celular en base (…980020538) parece equivocado; roster dice 994064383.
UPDATE vendedores
SET activo = true, supervisor = 'ACOSTA SERPA ANGELO LELIS',
    celular = '994064383'
WHERE codigo = 'VW78';

-- 2.3  CAMBIO DE SUPERVISOR
--      SANCHEZ ALVARADO JORGE LUIS: ACOSTA -> URBINA (pasa a GV BODEGAS 2)
UPDATE vendedores SET supervisor = 'URBINA VELASQUEZ CESAR EDINHO'
WHERE codigo = 'VW205';

-- Revisar los resultados antes de confirmar:
--   COMMIT;   -- si todo está OK
--   ROLLBACK; -- si algo no cuadra
COMMIT;


-- ============================================================================
-- PARTE 3 · VERIFICACIÓN DESPUÉS DE APLICAR
-- ============================================================================
SELECT codigo, nombre, celular, supervisor, activo
FROM vendedores
WHERE codigo IN ('VW300','VW101','VW174','VW330','VW74','VW78','VW205')
ORDER BY codigo;

-- Reconteo de cartera tras reemplazos (deben salir 21 / 12 / 12 con el nuevo nombre)
SELECT v.codigo, v.nombre, count(bv.*) FILTER (WHERE bv.activo) AS cartera_activa
FROM vendedores v
LEFT JOIN bodega_vendedores bv ON bv.vendedor_id = v.id
WHERE v.codigo IN ('VW300','VW101','VW174')
GROUP BY 1,2 ORDER BY 1;
