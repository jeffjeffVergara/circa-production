-- Flujo «Me olvidé mi clave» (pin_reset_flow.start_pin_reset).
-- Sin este valor, upsert_session falla con: invalid input value for enum sesion_fase

alter type public.sesion_fase add value if not exists 'reset_clave';
