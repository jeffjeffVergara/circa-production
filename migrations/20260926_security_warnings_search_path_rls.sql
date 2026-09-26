-- Warnings del linter:
--   search_path mutable, RLS USING(true) para PUBLIC, RPC security definer ejecutable por anon.
-- El backend usa service_role (bypass RLS). Se quita el acceso público.

ALTER FUNCTION public.update_flow_session_timestamp() SET search_path = public, pg_temp;
ALTER FUNCTION public.asignar_codigo_afiliado() SET search_path = public, pg_temp;
ALTER FUNCTION public.snapshot_ultimo_pedido_items() SET search_path = public, pg_temp;
ALTER FUNCTION public.cap_linea_disponible() SET search_path = public, pg_temp;
ALTER FUNCTION public.auto_progresar_preventa_pagada() SET search_path = public, pg_temp;
ALTER FUNCTION public.auto_calcular_monto_contado() SET search_path = public, pg_temp;
ALTER FUNCTION public.update_ts() SET search_path = public, pg_temp;
ALTER FUNCTION public.gen_numero_pedido(uuid) SET search_path = public, pg_temp;
ALTER FUNCTION public.liberar_linea_al_firmar_contrato() SET search_path = public, pg_temp;
ALTER FUNCTION public.relink_bodegas_zoom(boolean) SET search_path = public, pg_temp;
ALTER FUNCTION public.relink_bodegas_zoom(boolean, boolean) SET search_path = public, pg_temp;

DROP POLICY IF EXISTS svc_bod ON public.bodegas;
DROP POLICY IF EXISTS svc_ped ON public.pedidos;
DROP POLICY IF EXISTS "Service role full access" ON public.pedidos;

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'contratos',
    'financiamientos',
    'flow_sessions',
    'movimientos_linea',
    'verificaciones_identidad'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'Service role full access', t);
    IF NOT EXISTS (
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

REVOKE ALL ON FUNCTION public.fn_registrar_pago_pedido() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_registrar_pago_pedido() TO service_role;
