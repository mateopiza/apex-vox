-- =============================================================================
-- Apex Vox, Apex Summa & Apex Box — Supabase Cloud PostgreSQL Schema
-- =============================================================================
-- Run this migration in the Supabase Cloud SQL Editor to initialize tables,
-- indexes, and Row Level Security (RLS) policies for:
--   1. User Profiles & Plans (Free: 2h/day + 24h retention | Pro: Unlimited)
--   2. Subscriptions & Bold API Recurring Billing ($30.000 COP / $10 USD, 3-day trial)
--   3. Daily Audio Quota Tracking (1 or multiple audios per day up to 7,200s)
--   4. Transcriptions, Mega S4 Object Keys & Apex Summa AI Reports
-- =============================================================================

create extension if not exists "uuid-ossp";

-- 1. User Profiles Table
create table if not exists public.profiles (
    id uuid primary key default uuid_generate_v4(),
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

-- 2. Daily Audio Usage Table (2 hours = 7200s free per day across 1 or multiple audios)
create table if not exists public.daily_usage (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    usage_date date not null default current_date,
    used_seconds numeric(12, 3) not null default 0.0,
    audios_count integer not null default 0,
    updated_at timestamptz not null default now(),
    unique (user_id, usage_date)
);

-- 3. Subscriptions & Bold API Transactions Table
create table if not exists public.subscriptions (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    order_id text unique not null,
    plan text not null default 'pro',
    status text not null default 'trial_active' check (status in ('trial_active', 'active', 'past_due', 'cancelled')),
    amount integer not null default 30000,
    currency text not null default 'COP' check (currency in ('COP', 'USD')),
    trial_days integer not null default 3,
    trial_ends_at timestamptz,
    next_billing_at timestamptz,
    auto_billing boolean not null default true,
    bold_reference text,
    integrity_signature text,
    created_at timestamptz not null default now()
);

-- 4. Transcriptions & Mega S4 Storage Metadata Table
create table if not exists public.transcriptions (
    job_id text primary key,
    user_id uuid references public.profiles(id) on delete set null,
    session_id text,
    engine_brand text not null default 'Mc-Lewis',
    total_duration_sec numeric(12, 3) not null default 0.0,
    detected_speakers_count integer not null default 1,
    storage_provider text not null default 'mega_s4',
    s4_audio_key text,
    s4_result_key text,
    retention_policy text not null default '24h' check (retention_policy in ('24h', 'unlimited')),
    expires_at timestamptz,
    result_json jsonb,
    summa_json jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_transcriptions_user_id on public.transcriptions(user_id);
create index if not exists idx_transcriptions_expires_at on public.transcriptions(expires_at);
create index if not exists idx_daily_usage_user_date on public.daily_usage(user_id, usage_date);

-- Enable Row Level Security (RLS)
alter table public.profiles enable row level security;
alter table public.daily_usage enable row level security;
alter table public.subscriptions enable row level security;
alter table public.transcriptions enable row level security;
