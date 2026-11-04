-- =============================================================================
-- Apex Vox — replica of the account state (only used with STATE_BACKEND=postgres)
-- Apply once: Supabase dashboard → SQL Editor → paste → Run (or `supabase db push`).
-- Steps for the cutover and rollback: docs/deployment.md.
--
-- One row per record of the state file. Only the server reaches these tables, with
-- the service_role key: RLS has no policies and client roles get no privileges.
-- =============================================================================

create table if not exists public.app_state (
    section text not null,
    key text not null,
    value jsonb not null,
    updated_at timestamptz not null default now(),
    primary key (section, key)
);

create table if not exists public.app_state_meta (
    id smallint primary key default 1 check (id = 1),
    generation bigint not null default 0,
    importing boolean not null default false,
    updated_at timestamptz not null default now()
);

insert into public.app_state_meta (id) values (1) on conflict (id) do nothing;

alter table public.app_state      enable row level security;
alter table public.app_state_meta enable row level security;
alter table public.app_state      force row level security;
alter table public.app_state_meta force row level security;

revoke all on table public.app_state, public.app_state_meta from anon, authenticated;

-- Applies one batch in a single transaction. The generation is what detects a second
-- writer: during an overlapping deploy, the older copy gets an error instead of overwriting.
create or replace function public.app_state_apply(
    expected_generation bigint,
    new_generation bigint,
    upserts jsonb,
    deletes jsonb
) returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
    current_generation bigint;
begin
    select generation into current_generation
    from public.app_state_meta where id = 1 for update;

    if current_generation is distinct from expected_generation then
        raise exception 'app_state generation conflict: expected %, found %',
            expected_generation, current_generation;
    end if;

    insert into public.app_state (section, key, value, updated_at)
    select item ->> 'section', item ->> 'key', item -> 'value', now()
    from jsonb_array_elements(upserts) as item
    on conflict (section, key) do update
        set value = excluded.value, updated_at = excluded.updated_at;

    delete from public.app_state as state
    using jsonb_array_elements(deletes) as item
    where state.section = item ->> 'section' and state.key = item ->> 'key';

    update public.app_state_meta
    set generation = new_generation, updated_at = now()
    where id = 1;

    return new_generation;
end;
$$;

revoke all on function public.app_state_apply(bigint, bigint, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.app_state_apply(bigint, bigint, jsonb, jsonb) to service_role;
