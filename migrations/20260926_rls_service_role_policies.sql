-- Cierra el aviso rls_enabled_no_policy sin abrir el API público.
-- anon/authenticated siguen sin política (RLS niega). service_role es el rol del backend.

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'abonos',
    'backoffice_audit_log',
    'backup_bodega_vendedores_20260901',
    'backup_vendedores_20260901',
    'batch_runs',
    'batch_schedules',
    'biometria_auditoria',
    'bodega_distribuidores',
    'bodega_scoring_diario',
    'bodega_vendedores',
    'bodega_vendedores_backup_13jul',
    'bodega_vendedores_backup_ago05',
    'bonificaciones_distribuidor',
    'catalogo_distribuidor',
    'catalogo_distribuidor_unidades_backup_20260422',
    'enrolamiento_credito',
    'events',
    'historico_washington',
    'historico_washington_clientes',
    'historico_zoom',
    'kpi_snapshots',
    'kpi_snapshots_diario',
    'merchant_snapshot',
    'messages',
    'preventas',
    'productos_circa',
    'promociones_distribuidor',
    'sku_master',
    'vendedores',
    'vendedores_backup_ago05'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    IF EXISTS (
      SELECT 1 FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relname = t AND c.relkind = 'r'
    ) AND NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t AND policyname = 'service_role_all'
    ) THEN
      EXECUTE format(
        'CREATE POLICY service_role_all ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
        t
      );
    END IF;
  END LOOP;
END $$;
