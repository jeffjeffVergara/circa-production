-- Shared inbox / human takeover on WhatsApp (Circa support console backend).
-- Backend uses Supabase service role; RLS denies direct anon/authenticated API access.

create extension if not exists pgcrypto;

-- ── Queues (routing / priority groups; default queue seeded) ───────────────
create table if not exists public.support_queues (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    name text not null,
    slug text not null unique,
    priority_weight int not null default 0,
    metadata jsonb not null default '{}'::jsonb
);

insert into public.support_queues (name, slug, priority_weight)
values ('General', 'general', 0)
on conflict (slug) do nothing;

-- ── Agents (humans + supervisors in console) ──────────────────────────────
create table if not exists public.support_agents (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    email text unique,
    display_name text not null,
    role text not null default 'agent'
        check (role in ('agent', 'supervisor')),
    accept_assignments boolean not null default true,
    status text not null default 'offline'
        check (status in ('offline', 'online', 'busy')),
    api_token_sha256 text not null unique,
    api_token_hash text not null,
    last_seen_at timestamptz,
    last_assignment_at timestamptz,
    assignments_total int not null default 0,
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists idx_support_agents_status_accept
    on public.support_agents (status, accept_assignments)
    where accept_assignments = true;

-- ── Conversations (one non-CLOSED row per WhatsApp phone) ───────────────────
create table if not exists public.support_conversations (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    telefono_e164 text not null,
    contact_name text,
    bodega_id uuid references public.bodegas (id) on delete set null,
    queue_id uuid references public.support_queues (id) on delete set null,
    state text not null default 'BOT'
        check (state in ('BOT', 'WAITING_AGENT', 'HUMAN', 'PAUSED', 'CLOSED')),
    assigned_agent_id uuid references public.support_agents (id) on delete set null,
    priority int not null default 0,
    tags text[] not null default '{}',
    unread_for_agents int not null default 0,
    unread_for_contact int not null default 0,
    first_customer_message_at timestamptz,
    first_human_response_at timestamptz,
    escalated_at timestamptz,
    resolved_at timestamptz,
    closed_at timestamptz,
    sla_due_at timestamptz,
    last_customer_activity_at timestamptz,
    last_agent_activity_at timestamptz,
    abandon_notice_sent boolean not null default false,
    metadata jsonb not null default '{}'::jsonb
);

create unique index if not exists support_conversations_one_open_per_phone
    on public.support_conversations (telefono_e164)
    where state <> 'CLOSED';

create index if not exists idx_support_conv_state_updated
    on public.support_conversations (state, updated_at desc);

create index if not exists idx_support_conv_assigned
    on public.support_conversations (assigned_agent_id, state);

create index if not exists idx_support_conv_queue_state
    on public.support_conversations (queue_id, state, priority desc, updated_at desc);

-- ── Messages inside a support thread (distinct from public.messages analytics)
create table if not exists public.support_messages (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    conversation_id uuid not null references public.support_conversations (id) on delete cascade,
    direction text not null check (direction in ('inbound', 'outbound')),
    sender_kind text not null check (sender_kind in ('contact', 'agent', 'bot', 'system')),
    agent_id uuid references public.support_agents (id) on delete set null,
    wa_message_id text,
    wa_status text,
    message_type text not null default 'text',
    body text,
    media jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists idx_support_msg_conv_created
    on public.support_messages (conversation_id, created_at asc);

create unique index if not exists idx_support_msg_wa_id_unique
    on public.support_messages (wa_message_id)
    where wa_message_id is not null;

-- ── Audit trail ─────────────────────────────────────────────────────────────
create table if not exists public.support_audit_logs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    actor_kind text not null check (actor_kind in ('agent', 'system', 'webhook')),
    actor_agent_id uuid references public.support_agents (id) on delete set null,
    conversation_id uuid references public.support_conversations (id) on delete set null,
    action text not null,
    ip text,
    payload jsonb not null default '{}'::jsonb
);

create index if not exists idx_support_audit_conv_created
    on public.support_audit_logs (conversation_id, created_at desc);

create index if not exists idx_support_audit_actor_created
    on public.support_audit_logs (actor_agent_id, created_at desc);

-- ── RLS: block PostgREST anon/auth; service_role bypasses ────────────────────
alter table public.support_queues enable row level security;
alter table public.support_agents enable row level security;
alter table public.support_conversations enable row level security;
alter table public.support_messages enable row level security;
alter table public.support_audit_logs enable row level security;

create policy support_queues_deny_public on public.support_queues
    for all using (false);
create policy support_agents_deny_public on public.support_agents
    for all using (false);
create policy support_conversations_deny_public on public.support_conversations
    for all using (false);
create policy support_messages_deny_public on public.support_messages
    for all using (false);
create policy support_audit_logs_deny_public on public.support_audit_logs
    for all using (false);
