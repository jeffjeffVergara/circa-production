-- Cierra hallazgos del linter de Supabase:
--   security_definer_view, rls_disabled_in_public, sensitive_columns_exposed
-- El backend entra con service_role (bypass RLS). anon/authenticated dejan de leer estas vistas y tablas.

DO $$
DECLARE
  v text;
  views text[] := ARRAY[
    'bodega_features_v1',
    'pedidos_inconsistencias_fee',
    'vw_historico_washington_mensual',
    'vw_hist_bodega_semanal',
    'vw_hist_bodega_resumen',
    'vw_hist_bodega_producto',
    'vw_kpi_pedidos',
    'vw_modelo_distribuidor',
    'vw_kpi_bodega',
    'vw_kpi_bodega_vs_historico',
    'vw_bodega_estado_uso',
    'vw_kpi_elegible_incremento',
    'vw_norte_50k',
    'vw_enrolamiento_dia',
    'vw_kpi_por_periodo',
    'vw_tiers',
    'vw_activas',
    'vw_bodega_comercial',
    'vw_tiers_resumen',
    'vw_recompra',
    'vw_kpi_diario_v2',
    'vw_kpi_pipeline_v2',
    'vw_kpi_dq_v2',
    'vw_kpi_lineas_v2',
    'vw_kpi_ultima_compra_v2',
    'v_bodegas_ops',
    'v_tracker_bodegas',
    'v_tracker_pedidos_fin',
    'vw_conciliacion_pagos',
    'v_campana_target_frio',
    'v_pedidos_admin',
    'v_cobranzas'
  ];
  tables text[] := ARRAY[
    'vendedores_backup_ago05',
    'bodega_vendedores_backup_ago05',
    'sku_master',
    'merchant_snapshot',
    'historico_zoom',
    'backup_bodega_vendedores_20260901',
    'backup_vendedores_20260901',
    'enrolamiento_credito'
  ];
BEGIN
  FOREACH v IN ARRAY views LOOP
    IF EXISTS (
      SELECT 1 FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relname = v AND c.relkind = 'v'
    ) THEN
      EXECUTE format('ALTER VIEW public.%I SET (security_invoker = true)', v);
      EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', v);
      EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role', v);
    END IF;
  END LOOP;

  FOREACH v IN ARRAY tables LOOP
    IF EXISTS (
      SELECT 1 FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relname = v AND c.relkind = 'r'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', v);
      EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', v);
      EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', v);
    END IF;
  END LOOP;
END $$;
