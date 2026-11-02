-- =============================================================================
-- Apex Vox — security hardening (2026-11-02)
-- Apply in the Supabase project used by the app (SQL editor or `supabase db push`).
--
-- Model: the browser never talks to these tables. Only the FastAPI server uses the
-- service_role key (which bypasses RLS). RLS stays ON with no permissive policies,
-- so anon/authenticated keys get nothing even if they leak.
-- =============================================================================

-- 1. Password hashes never leave the app server.
alter table public.profiles drop column if exists password_hash;

-- 2. Deny-by-default for client roles, also at the GRANT level (defence in depth).
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

-- 3. Explicit, documented policies: signed-in Supabase users may read only their own
--    profile row (matched by verified e-mail). Writes stay server-only.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select to authenticated
  using (lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')));
grant select on table public.profiles to authenticated;

-- 4. Plans no longer auto-renew (Bold payment links are one-off).
alter table public.profiles alter column auto_billing_enabled set default false;
alter table public.subscriptions alter column auto_billing set default false;

comment on table public.profiles is 'Apex Vox accounts mirror. Server-only writes; RLS: users read their own row.';
comment on table public.transcriptions is 'Transcription metadata. Server-only (service_role).';
