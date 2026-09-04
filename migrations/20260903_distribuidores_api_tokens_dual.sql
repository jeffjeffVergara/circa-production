-- Credenciales API socios: token de prueba + client credentials para /auth/token.
alter table public.distribuidores
  add column if not exists api_token_test text;

alter table public.distribuidores
  add column if not exists api_client_id text;

alter table public.distribuidores
  add column if not exists api_client_secret text;

comment on column public.distribuidores.api_token is
  'Bearer token modo producción (/api/v1).';

comment on column public.distribuidores.api_token_test is
  'Bearer token modo pruebas (/api/v1/test).';

comment on column public.distribuidores.api_client_id is
  'Client ID para POST /api/v1/auth/token (client_credentials).';

comment on column public.distribuidores.api_client_secret is
  'Client secret para POST /api/v1/auth/token.';

create unique index if not exists idx_distribuidores_api_client_id
  on public.distribuidores (api_client_id)
  where api_client_id is not null;

create unique index if not exists idx_distribuidores_api_token_test
  on public.distribuidores (api_token_test)
  where api_token_test is not null;
