-- 2026-07-27  Sustentos de pago en backoffice
-- Guarda la foto/URL del sustento de (1) pago del cliente a Circa y
-- (2) pago de Circa al distribuidor. Aditivo y nullable: no afecta filas ni
-- lógica existente. Los archivos van al bucket `sustentos` en subcarpetas
-- pagos_cliente/ y pagos_distribuidor/ (mismo patrón que prueba_entrega_url).

alter table pedidos
  add column if not exists pago_cliente_sustento_url        text,
  add column if not exists pago_cliente_sustento_subido_at  timestamptz,
  add column if not exists pago_distribuidor_sustento_url        text,
  add column if not exists pago_distribuidor_sustento_subido_at  timestamptz;
