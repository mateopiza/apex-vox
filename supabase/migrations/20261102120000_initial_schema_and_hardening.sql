-- =============================================================================
-- Apex Vox — initial schema + security hardening
-- Project: apex-vox (phavrymydailzprdevhf). The database was empty on 2026-11-02.
-- Apply once: Supabase dashboard → SQL Editor → paste → Run (or `supabase db push`).
--
-- Model: the browser never talks to these tables. Only the FastAPI server uses the
-- service_role key (bypasses RLS). RLS is forced on every table and client roles
-- get no privileges, so a leaked anon key exposes nothing.
-- =============================================================================

create extension if not exists "uuid-ossp" with schema extensions;

create table if not exists public.profiles (
    id uuid primary key default extensions.uuid_generate_v4(),
    email text unique not null,
    full_name text not null default '',
    plan text not null default 'free' check (plan in ('free', 'trial', 'pro')),
    preferred_language text not null default 'es' check (preferred_language in ('es', 'en')),
    trial_started_at timestamptz,
    trial_ends_at timestamptz,
    auto_billing_enabled boolean not null default false,
    bold_customer_id text,
    bold_subscription_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.daily_usage (
    id uuid primary key default extensions.uuid_generate_v4(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    usage_date date not null default current_date,
    used_seconds numeric(12, 3) not null default 0.0,
    audios_count integer not null default 0,
    updated_at timestamptz not null default now(),
    unique (user_id, usage_date)
);

create table if not exists public.subscriptions (
    id uuid primary key default extensions.uuid_generate_v4(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    order_id text unique not null,
    plan text not null default 'pro',
    status text not null default 'active' check (status in ('trial_active', 'active', 'past_due', 'cancelled')),
    amount integer not null default 30000,
    currency text not null default 'COP' check (currency in ('COP', 'USD')),
    trial_days integer not null default 3,
    trial_ends_at timestamptz,
    next_billing_at timestamptz,
    auto_billing boolean not null default false,
    bold_reference text,
    integrity_signature text,
    created_at timestamptz not null default now()
);

-- Columns match what app/services/job_manager.py sends (PostgREST rejects unknown columns).
create table if not exists public.transcriptions (
    job_id text primary key,
    user_id uuid references public.profiles(id) on delete set null,
    session_id text,
    engine_brand text not null default 'Mc-Lewis',
    total_duration_sec numeric(12, 3) not null default 0.0,
    total_duration_formatted text,
    detected_speakers_count integer not null default 1,
    storage_provider text not null default 'mega_s4',
    s4_audio_key text,
    s4_result_key text,
    retention_policy text not null default '24h' check (retention_policy in ('24h', 'unlimited')),
    expires_at timestamptz,
    plan text,
    file_order jsonb,
    dominant_speaker text,
    result_json jsonb,
    summa_json jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_transcriptions_user_id on public.transcriptions(user_id);
create index if not exists idx_transcriptions_expires_at on public.transcriptions(expires_at);
create index if not exists idx_daily_usage_user_date on public.daily_usage(user_id, usage_date);
create index if not exists idx_subscriptions_user_id on public.subscriptions(user_id);

-- Deny-by-default for client roles (RLS + no GRANTs).
alter table public.profiles       enable row level security;
alter table public.daily_usage    enable row level security;
alter table public.subscriptions  enable row level security;
alter table public.transcriptions enable row level security;
alter table public.profiles       force row level security;
alter table public.daily_usage    force row level security;
alter table public.subscriptions  force row level security;
alter table public.transcriptions force row level security;

revoke all on table public.profiles, public.daily_usage, public.subscriptions, public.transcriptions
  from anon, authenticated;
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;

-- Signed-in Supabase users (Google/GitHub) may read only their own profile row.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select to authenticated
  using (lower(email) = lower(coalesce((select auth.jwt()) ->> 'email', '')));
grant select on table public.profiles to authenticated;

comment on table public.profiles is 'Apex Vox accounts mirror. Server-only writes; RLS: users read their own row.';
comment on table public.transcriptions is 'Transcription metadata. Server-only (service_role).';

-- Security advisor fix: the auto-RLS event-trigger function must not be callable via /rest/v1/rpc.
do $$
begin
  if exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'rls_auto_enable') then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end $$;
