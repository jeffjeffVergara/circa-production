-- Pre-venta support on pedidos
alter table public.pedidos
    add column if not exists tipo_operacion text not null default 'venta';

alter table public.pedidos
    add column if not exists preventa_aceptada_at timestamptz null;

alter table public.pedidos
    add column if not exists preventa_aceptada_por text null;

do $$
begin
    if exists (
        select 1
        from pg_type t
        join pg_namespace n on n.oid = t.typnamespace
        where t.typname = 'pedido_estado'
          and n.nspname = 'public'
    ) then
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_borrador'
        ) then
            alter type public.pedido_estado add value 'preventa_borrador';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_confirmada'
        ) then
            alter type public.pedido_estado add value 'preventa_confirmada';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_aceptada'
        ) then
            alter type public.pedido_estado add value 'preventa_aceptada';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_en_preparacion'
        ) then
            alter type public.pedido_estado add value 'preventa_en_preparacion';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_despachada'
        ) then
            alter type public.pedido_estado add value 'preventa_despachada';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_entregada'
        ) then
            alter type public.pedido_estado add value 'preventa_entregada';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_cancelada'
        ) then
            alter type public.pedido_estado add value 'preventa_cancelada';
        end if;
        if not exists (
            select 1 from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where t.typname = 'pedido_estado'
              and n.nspname = 'public'
              and e.enumlabel = 'preventa_rechazada'
        ) then
            alter type public.pedido_estado add value 'preventa_rechazada';
        end if;
    end if;
end $$;

create index if not exists idx_pedidos_tipo_operacion
    on public.pedidos (tipo_operacion, created_at desc);
