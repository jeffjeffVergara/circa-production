-- Agente fijo para la consola cuando el acceso es por SUPPORT_BOOTSTRAP_SECRET (una palabra en env).
-- UUID estable: coincide con default SUPPORT_CONSOLE_AGENT_ID en app/support/security.py
-- api_token_* son placeholders (no usar para login); el login real es la palabra del env.
-- accept_assignments = false: no entra en round-robin automático.

insert into public.support_agents (
    id,
    display_name,
    role,
    accept_assignments,
    status,
    api_token_sha256,
    api_token_hash,
    metadata
)
values (
    'a0000000-0000-4000-8000-000000000001',
    'Circa · Consola (bootstrap)',
    'supervisor',
    false,
    'offline',
    '77f1238f423322b001f3c6d675620d70c9adaec2473c01123751a2c8f0cb2860',
    '$2b$12$G3e0pOX2e9tHSw0YdTlX4enTxrmQ6gcfIeV9qp85Ud7y1gt/rA5sC',
    '{"auth":"bootstrap_secret_env_only"}'::jsonb
)
on conflict (id) do update set
    display_name = excluded.display_name,
    role = excluded.role,
    accept_assignments = excluded.accept_assignments,
    metadata = excluded.metadata;
