-- Vistas de lectura para métricas de soporte (BI / SQL manual / futuros RPC).
-- El backend puede seguir usando agregados en Python; estas vistas facilitan reporting.

create or replace view public.support_v_daily_closed as
select
    ((closed_at at time zone 'UTC'))::date as day_utc,
    count(*)::bigint as conversations_closed,
    count(*) filter (where first_human_response_at is null)::bigint as closed_without_agent_reply,
    avg(
        extract(
            epoch from (
                first_human_response_at - coalesce(escalated_at, created_at)
            )
        )
    ) filter (
        where first_human_response_at is not null
    )::double precision as avg_first_response_seconds,
    avg(
        extract(epoch from (closed_at - coalesce(first_human_response_at, escalated_at, created_at)))
    ) filter (where closed_at is not null)::double precision as avg_time_to_close_seconds
from public.support_conversations
where state = 'CLOSED'
  and closed_at is not null
group by 1;

comment on view public.support_v_daily_closed is
    'Agregados diarios (UTC) de conversaciones cerradas: primera respuesta y tiempo hasta cierre.';

revoke all on public.support_v_daily_closed from anon;
revoke all on public.support_v_daily_closed from authenticated;

create or replace view public.support_v_open_backlog as
select
    state,
    count(*)::bigint as cnt,
    sum(unread_for_agents)::bigint as unread_sum
from public.support_conversations
where state in ('WAITING_AGENT', 'HUMAN', 'PAUSED')
group by 1;

comment on view public.support_v_open_backlog is 'Snapshot colas abiertas por estado.';

revoke all on public.support_v_open_backlog from anon;
revoke all on public.support_v_open_backlog from authenticated;
