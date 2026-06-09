-- Fases de sesión para flujo vendedor por WhatsApp (vend_*).
-- Sin estos valores, upsert_session falla con: invalid input value for enum sesion_fase

alter type public.sesion_fase add value if not exists 'vend_menu';
alter type public.sesion_fase add value if not exists 'vend_preventa_buscar';
alter type public.sesion_fase add value if not exists 'vend_preventa_bodega';
alter type public.sesion_fase add value if not exists 'vend_cartera_pick';
