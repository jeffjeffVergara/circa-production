create extension if not exists pgcrypto;

create table if not exists public.events (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    bodega_id uuid null references public.bodegas(id) on delete set null,
    pedido_id uuid null references public.pedidos(id) on delete set null,
    telefono text null,
    event_type text not null,
    source text not null default 'system',
    channel text not null default 'whatsapp',
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    bodega_id uuid null references public.bodegas(id) on delete set null,
    telefono text not null,
    direction text not null check (direction in ('inbound', 'outbound')),
    message_id text null,
    message_type text null,
    content text null default '',
    template_name text null default '',
    reply_to_message_id text null default '',
    response_time_ms integer null,
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists idx_events_bodega_created
    on public.events (bodega_id, created_at desc);
create index if not exists idx_events_event_type_created
    on public.events (event_type, created_at desc);
create index if not exists idx_events_pedido_created
    on public.events (pedido_id, created_at desc);

create index if not exists idx_messages_telefono_created
    on public.messages (telefono, created_at desc);
create index if not exists idx_messages_bodega_created
    on public.messages (bodega_id, created_at desc);
create index if not exists idx_messages_direction_created
    on public.messages (direction, created_at desc);

create or replace view public.bodega_features_v1 as
with compras as (
    select
        p.bodega_id,
        count(*) filter (where p.estado in ('confirmado', 'preventa_confirmada', 'entregado', 'pagado')) as compras_count,
        avg(coalesce(p.monto_productos, 0)) filter (where p.estado in ('confirmado', 'preventa_confirmada', 'entregado', 'pagado')) as ticket_promedio,
        max(p.created_at) filter (where p.estado in ('confirmado', 'preventa_confirmada', 'entregado', 'pagado')) as ultima_compra_at,
        max(case when coalesce(p.monto_financiado, 0) > 0 then 1 else 0 end) as usa_credito_int
    from public.pedidos p
    group by p.bodega_id
),
msg as (
    select
        m.bodega_id,
        count(*) filter (where m.direction = 'inbound') as inbound_count,
        count(*) filter (where m.direction = 'outbound') as outbound_count
    from public.messages m
    group by m.bodega_id
)
select
    b.id as bodega_id,
    b.nombre_comercial,
    b.telefono_whatsapp as telefono,
    coalesce(c.compras_count, 0) as frecuencia_compra,
    round(coalesce(c.ticket_promedio, 0)::numeric, 2) as ticket_promedio,
    case when c.ultima_compra_at is null then null else (current_date - c.ultima_compra_at::date) end as dias_desde_ultima_compra,
    (coalesce(c.usa_credito_int, 0) = 1) as usa_credito,
    coalesce(msg.inbound_count, 0) as mensajes_inbound,
    coalesce(msg.outbound_count, 0) as mensajes_outbound
from public.bodegas b
left join compras c on c.bodega_id = b.id
left join msg on msg.bodega_id = b.id;
