-- ═══════════════════════════════════════════════════════════════
-- Backoffice: paginación/filtrado/conteo server-side de bodegas
-- Vista que pre-calcula por bodega: vendedor/supervisor/día, stats de
-- pedidos (n, venta, financiado, saldo, días de mora, monto vencido),
-- sesión (fase_bot), línea usada, enrolada y tipo.
-- Reemplaza el tope .limit(1000) del handler por range()+count sobre esta vista.
-- 2026-08-12
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW public.v_bodegas_ops AS
WITH bv AS (
  SELECT DISTINCT ON (x.bodega_id) x.bodega_id, x.supervisor, x.grupo, x.rol,
         x.dia_visita, x.dia_entrega, v.codigo AS vendedor_codigo, v.nombre AS vendedor_nombre,
         COALESCE(v.telefono_whatsapp, v.celular) AS vendedor_telefono
  FROM bodega_vendedores x JOIN vendedores v ON v.id = x.vendedor_id
  WHERE x.activo = true
  ORDER BY x.bodega_id, x.created_at DESC NULLS LAST
),
ses AS (
  SELECT DISTINCT ON (bodega_id) bodega_id, fase::text AS fase_bot, last_activity
  FROM sesiones ORDER BY bodega_id, last_activity DESC NULLS LAST
),
ped AS (
  SELECT p.bodega_id,
    count(*) AS n_pedidos,
    max(p.created_at) AS ultimo_pedido,
    COALESCE(sum(p.total_pedido),0) AS venta_total,
    COALESCE(sum(p.monto_financiado),0) AS financiado_total,
    COALESCE(sum(CASE WHEN p.monto_financiado>0 AND p.estado<>'pagado'
                 THEN p.monto_financiado + COALESCE(p.fee_monto,0) ELSE 0 END),0) AS saldo,
    COALESCE(max(CASE WHEN p.monto_financiado>0 AND p.estado<>'pagado' AND p.fecha_vencimiento IS NOT NULL
                 THEN GREATEST(0, ((now() AT TIME ZONE 'America/Lima')::date - p.fecha_vencimiento::date)) ELSE 0 END),0) AS dias_mora,
    COALESCE(sum(CASE WHEN p.monto_financiado>0 AND p.estado<>'pagado' AND p.fecha_vencimiento IS NOT NULL
                 AND ((now() AT TIME ZONE 'America/Lima')::date - p.fecha_vencimiento::date)>0
                 THEN p.monto_financiado + COALESCE(p.fee_monto,0) ELSE 0 END),0) AS monto_vencido
  FROM pedidos p
  WHERE p.estado IN ('entregado','pagado','recibido','preventa_aceptada','confirmado','en_preparacion','despachado','en_camino')
  GROUP BY p.bodega_id
)
SELECT b.id, b.razon_social, b.nombre_comercial, b.representante_legal, b.representante_nombre_corto,
       b.telefono_whatsapp, b.ruc, b.dni_representante, b.solo_dni_sin_ruc, b.direccion_fiscal,
       b.distrito, b.estado, b.es_test, b.en_piloto, b.linea_aprobada, b.linea_disponible,
       b.onboarding_fase, b.kyc_nivel, b.created_at,
       bv.vendedor_codigo, bv.vendedor_nombre, bv.vendedor_telefono, bv.supervisor, bv.grupo, bv.rol,
       bv.dia_visita, bv.dia_entrega,
       COALESCE(ses.fase_bot,'sin_sesion') AS fase_bot, ses.last_activity,
       COALESCE(ped.n_pedidos,0) AS n_pedidos, ped.ultimo_pedido,
       COALESCE(ped.venta_total,0) AS venta_total, COALESCE(ped.financiado_total,0) AS financiado_total,
       COALESCE(ped.saldo,0) AS saldo, COALESCE(ped.dias_mora,0) AS dias_mora,
       COALESCE(ped.monto_vencido,0) AS monto_vencido,
       (COALESCE(b.linea_aprobada,0) - COALESCE(b.linea_disponible,0)) AS linea_usada,
       (b.estado='activo') AS enrolada,
       CASE WHEN upper(COALESCE(bv.grupo,'')) LIKE '%MERCADO%' THEN 'mercado' ELSE 'bodega' END AS tipo
FROM bodegas b
LEFT JOIN bv  ON bv.bodega_id  = b.id
LEFT JOIN ses ON ses.bodega_id = b.id
LEFT JOIN ped ON ped.bodega_id = b.id;

GRANT SELECT ON public.v_bodegas_ops TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
