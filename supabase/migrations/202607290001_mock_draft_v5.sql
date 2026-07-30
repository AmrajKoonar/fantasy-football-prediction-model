-- Fantasy Analytics Mock Draft V5
-- Apply in a Supabase project with Anonymous Sign-Ins enabled.

create extension if not exists pgcrypto;

create type public.draft_status as enum ('lobby', 'active', 'paused', 'completed', 'cancelled');
create type public.draft_format as enum ('snake', 'linear', 'auction');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 2 and 30),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.drafts (
  id uuid primary key default gen_random_uuid(),
  public_slug text not null unique default encode(gen_random_bytes(8), 'hex'),
  name text not null check (char_length(name) between 3 and 80),
  host_user_id uuid not null references auth.users(id),
  status public.draft_status not null default 'lobby',
  format public.draft_format not null,
  scoring_preset text not null,
  team_count integer not null check (team_count between 4 and 22 and team_count % 2 = 0),
  rounds integer not null check (rounds between 1 and 30),
  pick_timer_seconds integer check (
    pick_timer_seconds is null or pick_timer_seconds in
      (10,15,30,45,60,120,300,600,1800,3600,7200,14400,28800,43200,86400)
  ),
  settings jsonb not null,
  seed integer not null,
  current_pick_number integer not null default 1,
  current_round integer not null default 1,
  current_nomination_slot integer not null default 1,
  pick_deadline_at timestamptz,
  paused_seconds_remaining integer,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.draft_slots (
  id uuid primary key default gen_random_uuid(),
  draft_id uuid not null references public.drafts(id) on delete cascade,
  slot_number integer not null check (slot_number > 0),
  user_id uuid references auth.users(id) on delete set null,
  display_name text not null default 'Open',
  team_name text not null default '',
  is_cpu boolean not null default false,
  budget_remaining integer not null default 200 check (budget_remaining >= 0),
  created_at timestamptz not null default now(),
  unique (draft_id, slot_number),
  unique (draft_id, user_id)
);

create table public.draft_player_snapshots (
  id uuid primary key default gen_random_uuid(),
  draft_id uuid not null references public.drafts(id) on delete cascade,
  player_id text not null,
  name text not null,
  team text not null,
  primary_position text not null,
  eligible_positions text[] not null,
  rookie boolean not null,
  age numeric,
  overall_rank integer not null,
  position_rank integer not null,
  tier integer not null,
  projected_points numeric not null,
  points_per_game numeric not null,
  adp numeric not null,
  source text not null,
  unique (draft_id, player_id)
);

create table public.draft_picks (
  id uuid primary key default gen_random_uuid(),
  draft_id uuid not null references public.drafts(id) on delete cascade,
  player_id text not null,
  slot_number integer not null,
  round integer not null,
  pick_number integer not null,
  price integer,
  made_by uuid references auth.users(id),
  is_cpu boolean not null default false,
  created_at timestamptz not null default now(),
  unique (draft_id, player_id),
  unique (draft_id, pick_number),
  foreign key (draft_id, player_id)
    references public.draft_player_snapshots(draft_id, player_id)
);

create table public.draft_queues (
  draft_id uuid not null references public.drafts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  player_id text not null,
  priority integer not null check (priority >= 0),
  created_at timestamptz not null default now(),
  primary key (draft_id, user_id, player_id),
  unique (draft_id, user_id, priority)
);

create table public.draft_messages (
  id bigint generated always as identity primary key,
  draft_id uuid not null references public.drafts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  display_name text not null,
  body text not null check (char_length(body) between 1 and 500),
  created_at timestamptz not null default now()
);

create table public.draft_auctions (
  id uuid primary key default gen_random_uuid(),
  draft_id uuid not null references public.drafts(id) on delete cascade,
  nomination_number integer not null,
  nominating_slot integer not null,
  player_id text not null,
  current_bid integer not null,
  highest_bidder_slot integer,
  deadline_at timestamptz not null,
  status text not null default 'open' check (status in ('open', 'sold', 'cancelled')),
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  unique (draft_id, nomination_number),
  foreign key (draft_id, player_id)
    references public.draft_player_snapshots(draft_id, player_id)
);

create table public.draft_bids (
  id bigint generated always as identity primary key,
  auction_id uuid not null references public.draft_auctions(id) on delete cascade,
  draft_id uuid not null references public.drafts(id) on delete cascade,
  slot_number integer not null,
  user_id uuid references auth.users(id),
  amount integer not null check (amount > 0),
  created_at timestamptz not null default now()
);

create index drafts_history_idx on public.drafts (status, completed_at desc);
create index slots_draft_idx on public.draft_slots (draft_id, slot_number);
create index picks_draft_idx on public.draft_picks (draft_id, pick_number);
create index snapshots_draft_rank_idx on public.draft_player_snapshots (draft_id, overall_rank);
create index messages_draft_idx on public.draft_messages (draft_id, created_at desc);
create index auctions_draft_idx on public.draft_auctions (draft_id, nomination_number desc);

create or replace function public.is_draft_participant(target_draft uuid, target_user uuid default auth.uid())
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (
    select 1 from public.draft_slots
    where draft_id = target_draft and user_id = target_user
  ) or exists (
    select 1 from public.drafts
    where id = target_draft and host_user_id = target_user
  );
$$;

create or replace function public.handle_new_anonymous_user()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, 'Guest ' || upper(substr(new.id::text, 1, 4)))
  on conflict (id) do nothing;
  return new;
end;
$$;
create trigger on_auth_user_created
  after insert on auth.users for each row execute procedure public.handle_new_anonymous_user();

alter table public.profiles enable row level security;
alter table public.drafts enable row level security;
alter table public.draft_slots enable row level security;
alter table public.draft_player_snapshots enable row level security;
alter table public.draft_picks enable row level security;
alter table public.draft_queues enable row level security;
alter table public.draft_messages enable row level security;
alter table public.draft_auctions enable row level security;
alter table public.draft_bids enable row level security;

create policy profiles_read_self on public.profiles for select to authenticated using (id = auth.uid());
create policy profiles_update_self on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
create policy drafts_read on public.drafts for select to authenticated
  using (status = 'completed' or public.is_draft_participant(id));
create policy slots_read on public.draft_slots for select to authenticated
  using (public.is_draft_participant(draft_id) or exists (
    select 1 from public.drafts where id = draft_id and status = 'completed'
  ));
create policy snapshots_read on public.draft_player_snapshots for select to authenticated
  using (public.is_draft_participant(draft_id) or exists (
    select 1 from public.drafts where id = draft_id and status = 'completed'
  ));
create policy picks_read on public.draft_picks for select to authenticated
  using (public.is_draft_participant(draft_id) or exists (
    select 1 from public.drafts where id = draft_id and status = 'completed'
  ));
create policy queues_owner_all on public.draft_queues for all to authenticated
  using (user_id = auth.uid() and public.is_draft_participant(draft_id))
  with check (user_id = auth.uid() and public.is_draft_participant(draft_id));
create policy messages_participant_read on public.draft_messages for select to authenticated
  using (public.is_draft_participant(draft_id));
create policy messages_participant_insert on public.draft_messages for insert to authenticated
  with check (user_id = auth.uid() and public.is_draft_participant(draft_id));
create policy auctions_read on public.draft_auctions for select to authenticated
  using (public.is_draft_participant(draft_id) or exists (
    select 1 from public.drafts where id = draft_id and status = 'completed'
  ));
create policy bids_read on public.draft_bids for select to authenticated
  using (public.is_draft_participant(draft_id));

create or replace function public.slot_for_pick(
  pick_no integer, teams integer, draft_kind public.draft_format, use_3rr boolean
) returns integer language plpgsql immutable as $$
declare round_no integer := ((pick_no - 1) / teams) + 1;
declare in_round integer := ((pick_no - 1) % teams) + 1;
declare reverse_round boolean;
begin
  if draft_kind = 'linear' then return in_round; end if;
  if use_3rr then
    reverse_round := round_no in (2, 3) or (round_no >= 4 and round_no % 2 = 1);
  else
    reverse_round := round_no % 2 = 0;
  end if;
  return case when reverse_round then teams - in_round + 1 else in_round end;
end;
$$;

create or replace function public.get_draft_by_slug(target_slug text)
returns jsonb language sql security definer set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'draft', to_jsonb(d),
    'slots', coalesce((select jsonb_agg(s order by s.slot_number) from public.draft_slots s where s.draft_id=d.id), '[]'::jsonb)
  )
  from public.drafts d where d.public_slug = target_slug or d.id::text = target_slug;
$$;

create or replace function public.list_completed_drafts(
  page_no integer default 1, page_size integer default 20,
  format_filter text default null, scoring_filter text default null
) returns table (draft jsonb, total_count bigint)
language sql security definer set search_path = public, pg_temp as $$
  with filtered as (
    select * from public.drafts
    where status = 'completed'
      and (format_filter is null or format::text = format_filter)
      and (scoring_filter is null or scoring_preset = scoring_filter)
  )
  select to_jsonb(filtered), count(*) over()
  from filtered order by completed_at desc
  limit least(greatest(page_size, 1), 50)
  offset (greatest(page_no, 1) - 1) * least(greatest(page_size, 1), 50);
$$;

create or replace function public.create_mock_draft(
  draft_settings jsonb, player_snapshot jsonb, display_name text
) returns uuid language plpgsql security definer set search_path = public, pg_temp as $$
declare new_id uuid; teams integer; roster_size integer; selected_rounds integer;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  teams := (draft_settings->>'teamCount')::integer;
  selected_rounds := (draft_settings->>'rounds')::integer;
  roster_size := jsonb_array_length(draft_settings->'roster');
  if teams < 4 or teams > 22 or teams % 2 <> 0 then raise exception 'Invalid team count'; end if;
  if selected_rounds < 1 or selected_rounds > 30 or selected_rounds <> roster_size
    then raise exception 'Rounds must match roster size'; end if;
  if jsonb_array_length(player_snapshot) < 450 then raise exception 'Player snapshot is incomplete'; end if;

  insert into public.profiles (id, display_name) values (auth.uid(), left(display_name, 30))
    on conflict (id) do update set display_name=excluded.display_name, updated_at=now();
  insert into public.drafts (
    name, host_user_id, format, scoring_preset, team_count, rounds,
    pick_timer_seconds, settings, seed
  ) values (
    draft_settings->>'name', auth.uid(), (draft_settings->>'format')::public.draft_format,
    draft_settings->>'scoringPreset', teams, selected_rounds,
    nullif(draft_settings->>'pickTimerSeconds','')::integer,
    draft_settings, floor(random() * 2147483647)::integer
  ) returning id into new_id;

  insert into public.draft_slots (draft_id, slot_number, budget_remaining)
    select new_id, value, coalesce((draft_settings->>'auctionBudget')::integer, 200)
    from generate_series(1, teams) value;
  update public.draft_slots set user_id=auth.uid(), display_name=left(display_name,30),
    team_name=left(display_name,30) where draft_id=new_id and slot_number=1;

  insert into public.draft_player_snapshots (
    draft_id, player_id, name, team, primary_position, eligible_positions, rookie,
    age, overall_rank, position_rank, tier, projected_points, points_per_game, adp, source
  )
  select new_id, x."playerId", x.name, x.team, x."primaryPosition",
    x."eligiblePositions", x.rookie, x.age, x."overallRank", x."positionRank",
    x.tier, x."projectedPoints", x."pointsPerGame", x.adp, x.source
  from jsonb_to_recordset(player_snapshot) as x(
    "playerId" text, name text, team text, "primaryPosition" text,
    "eligiblePositions" text[], rookie boolean, age numeric, "overallRank" integer,
    "positionRank" integer, tier integer, "projectedPoints" numeric,
    "pointsPerGame" numeric, adp numeric, source text
  );
  return new_id;
end;
$$;

create or replace function public.claim_draft_slot(
  target_draft uuid, target_slot integer, display_name text, team_name text default ''
) returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare current_status public.draft_status;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  select status into current_status from public.drafts where id=target_draft for update;
  if current_status <> 'lobby' then raise exception 'Slots can only be claimed in the lobby'; end if;
  if exists(select 1 from public.draft_slots where draft_id=target_draft and user_id=auth.uid())
    then raise exception 'You already have a slot'; end if;
  update public.draft_slots set user_id=auth.uid(), is_cpu=false,
    display_name=left(display_name,30), team_name=left(coalesce(nullif(team_name,''),display_name),30)
  where draft_id=target_draft and slot_number=target_slot and user_id is null;
  if not found then raise exception 'That slot is no longer available'; end if;
end;
$$;

create or replace function public.release_draft_slot(target_draft uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if exists(select 1 from public.drafts where id=target_draft and host_user_id=auth.uid())
    then raise exception 'The host cannot leave their own draft'; end if;
  update public.draft_slots set user_id=null, is_cpu=false, display_name='Open', team_name=''
  where draft_id=target_draft and user_id=auth.uid()
    and exists(select 1 from public.drafts where id=target_draft and status='lobby');
end;
$$;

create or replace function public.start_mock_draft(target_draft uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare d public.drafts%rowtype;
begin
  select * into d from public.drafts where id=target_draft for update;
  if d.host_user_id <> auth.uid() or d.status <> 'lobby' then raise exception 'Host lobby required'; end if;
  update public.draft_slots set is_cpu=true, display_name='CPU '||slot_number,
    team_name='CPU '||slot_number where draft_id=target_draft and user_id is null;
  update public.drafts set status='active', started_at=now(), updated_at=now(),
    pick_deadline_at=case when pick_timer_seconds is null then null else now()+make_interval(secs=>pick_timer_seconds) end
  where id=target_draft;
end;
$$;

create or replace function public.pause_mock_draft(target_draft uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  update public.drafts set status='paused',
    paused_seconds_remaining=case when pick_deadline_at is null then null else greatest(0,extract(epoch from pick_deadline_at-now())::integer) end,
    pick_deadline_at=null, updated_at=now()
  where id=target_draft and host_user_id=auth.uid() and status='active';
  if not found then raise exception 'Active host draft required'; end if;
end;
$$;

create or replace function public.resume_mock_draft(target_draft uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  update public.drafts set status='active',
    pick_deadline_at=case when pick_timer_seconds is null then null
      else now()+make_interval(secs=>coalesce(paused_seconds_remaining,pick_timer_seconds)) end,
    paused_seconds_remaining=null, updated_at=now()
  where id=target_draft and host_user_id=auth.uid() and status='paused';
  if not found then raise exception 'Paused host draft required'; end if;
end;
$$;

create or replace function public.draft_player_fits(
  target_draft uuid, target_slot integer, target_player text
) returns boolean language plpgsql stable security definer set search_path = public, pg_temp as $$
declare roster_json jsonb; player_position text; drafted_total integer;
declare drafted_at_position integer; capacity integer; player_rookie boolean; pool_filter text;
begin
  select settings->'roster', rounds, settings->>'playerPool'
    into roster_json, capacity, pool_filter
    from public.drafts where id=target_draft;
  select primary_position, rookie into player_position, player_rookie from public.draft_player_snapshots
    where draft_id=target_draft and player_id=target_player;
  select count(*) into drafted_total from public.draft_picks
    where draft_id=target_draft and slot_number=target_slot;
  if player_position is null or drafted_total >= capacity then return false; end if;
  if pool_filter='rookies' and not player_rookie then return false; end if;
  if pool_filter='veterans' and player_rookie then return false; end if;
  select count(*) into drafted_at_position from public.draft_picks p
    join public.draft_player_snapshots s on s.draft_id=p.draft_id and s.player_id=p.player_id
    where p.draft_id=target_draft and p.slot_number=target_slot
      and s.primary_position=player_position;
  select count(*) into capacity from jsonb_array_elements(roster_json) item
    where item->>'position'=player_position
      or item->>'position'='BENCH'
      or (item->>'position'='FLEX' and player_position in ('RB','WR','TE'))
      or (item->>'position'='SUPERFLEX' and player_position in ('QB','RB','WR','TE'))
      or (item->>'position'='IDP_FLEX' and player_position in ('DL','LB','DB'));
  return drafted_at_position < capacity;
end;
$$;

create or replace function public.make_mock_pick(
  target_draft uuid, target_player text
) returns uuid language plpgsql security definer set search_path = public, pg_temp as $$
declare d public.drafts%rowtype; slot_no integer; new_pick uuid; is_cpu_slot boolean;
begin
  select * into d from public.drafts where id=target_draft for update;
  if d.status <> 'active' or d.format='auction' then raise exception 'Draft is not in pick mode'; end if;
  slot_no := public.slot_for_pick(d.current_pick_number,d.team_count,d.format,
    coalesce((d.settings->>'thirdRoundReversal')::boolean,false));
  select is_cpu into is_cpu_slot from public.draft_slots
    where draft_id=target_draft and slot_number=slot_no;
  if is_cpu_slot or not exists(
    select 1 from public.draft_slots where draft_id=target_draft and slot_number=slot_no and user_id=auth.uid()
  ) then raise exception 'It is not your turn'; end if;
  if not exists(select 1 from public.draft_player_snapshots
    where draft_id=target_draft and player_id=target_player) then raise exception 'Unknown player'; end if;
  if not public.draft_player_fits(target_draft,slot_no,target_player)
    then raise exception 'Player does not fit the remaining roster'; end if;
  insert into public.draft_picks(draft_id,player_id,slot_number,round,pick_number,made_by)
    values(target_draft,target_player,slot_no,((d.current_pick_number-1)/d.team_count)+1,d.current_pick_number,auth.uid())
    returning id into new_pick;
  update public.drafts set current_pick_number=current_pick_number+1,
    current_round=((current_pick_number)/team_count)+1, updated_at=now(),
    status=case when current_pick_number >= team_count*rounds then 'completed' else status end,
    completed_at=case when current_pick_number >= team_count*rounds then now() else completed_at end,
    pick_deadline_at=case when current_pick_number >= team_count*rounds or pick_timer_seconds is null then null
      else now()+make_interval(secs=>pick_timer_seconds) end where id=target_draft;
  return new_pick;
end;
$$;

create or replace function public.advance_mock_draft(target_draft uuid)
returns text language plpgsql security definer set search_path = public, pg_temp as $$
declare d public.drafts%rowtype; slot_no integer; chosen text; cpu_slot boolean; queue_pick text;
declare open_auction public.draft_auctions%rowtype; min_bid integer;
begin
  select * into d from public.drafts where id=target_draft for update;
  if d.status <> 'active' then return null; end if;
  if d.format='auction' then
    select * into open_auction from public.draft_auctions
      where draft_id=target_draft and status='open' order by nomination_number desc limit 1 for update;
    if open_auction.id is not null then
      if open_auction.deadline_at <= now() then
        perform public.settle_auction(open_auction.id);
        return open_auction.player_id;
      end if;
      return null;
    end if;
    select is_cpu into cpu_slot from public.draft_slots
      where draft_id=target_draft and slot_number=d.current_nomination_slot;
    if not cpu_slot then return null; end if;
    select p.player_id into chosen from public.draft_player_snapshots p
      where p.draft_id=target_draft
        and not exists(select 1 from public.draft_picks x where x.draft_id=target_draft and x.player_id=p.player_id)
        and public.draft_player_fits(target_draft,d.current_nomination_slot,p.player_id)
      order by p.projected_points-p.overall_rank*.2
        +(abs(hashtextextended(p.player_id,d.seed+d.current_pick_number))%1000)/100.0 desc limit 1;
    min_bid := coalesce((d.settings->>'minimumBid')::integer,1);
    insert into public.draft_auctions(
      draft_id,nomination_number,nominating_slot,player_id,current_bid,highest_bidder_slot,deadline_at
    ) values(target_draft,d.current_pick_number,d.current_nomination_slot,chosen,min_bid,
      d.current_nomination_slot,now()+make_interval(secs=>coalesce(d.pick_timer_seconds,30)))
      returning id into open_auction.id;
    insert into public.draft_bids(auction_id,draft_id,slot_number,amount)
      values(open_auction.id,target_draft,d.current_nomination_slot,min_bid);
    return chosen;
  end if;
  slot_no := public.slot_for_pick(d.current_pick_number,d.team_count,d.format,
    coalesce((d.settings->>'thirdRoundReversal')::boolean,false));
  select is_cpu into cpu_slot from public.draft_slots where draft_id=target_draft and slot_number=slot_no;
  if not cpu_slot and (d.pick_deadline_at is null or d.pick_deadline_at > now()) then return null; end if;
  if not cpu_slot then
    select q.player_id into queue_pick from public.draft_queues q
    join public.draft_slots s on s.draft_id=q.draft_id and s.user_id=q.user_id
    where q.draft_id=target_draft and s.slot_number=slot_no
      and not exists(select 1 from public.draft_picks p where p.draft_id=q.draft_id and p.player_id=q.player_id)
    order by q.priority limit 1;
  end if;
  chosen := queue_pick;
  if chosen is null then
    select p.player_id into chosen from public.draft_player_snapshots p
    where p.draft_id=target_draft
      and not exists(select 1 from public.draft_picks x where x.draft_id=target_draft and x.player_id=p.player_id)
      and public.draft_player_fits(target_draft,slot_no,p.player_id)
      and (not (p.primary_position in ('K','DEF')) or d.current_round >= greatest(1,d.rounds-2))
    order by
      p.projected_points - p.overall_rank*.2
      + (abs(hashtextextended(p.player_id,d.seed+d.current_pick_number)) % 1000)/100.0 desc,
      p.overall_rank limit 1;
  end if;
  if chosen is null then raise exception 'No eligible players remain'; end if;
  insert into public.draft_picks(draft_id,player_id,slot_number,round,pick_number,is_cpu)
    values(target_draft,chosen,slot_no,((d.current_pick_number-1)/d.team_count)+1,d.current_pick_number,cpu_slot);
  update public.drafts set current_pick_number=current_pick_number+1,
    current_round=((current_pick_number)/team_count)+1, updated_at=now(),
    status=case when current_pick_number >= team_count*rounds then 'completed' else status end,
    completed_at=case when current_pick_number >= team_count*rounds then now() else completed_at end,
    pick_deadline_at=case when current_pick_number >= team_count*rounds or pick_timer_seconds is null then null
      else now()+make_interval(secs=>pick_timer_seconds) end where id=target_draft;
  return chosen;
end;
$$;

create or replace function public.undo_last_mock_pick(target_draft uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare d public.drafts%rowtype;
begin
  select * into d from public.drafts where id=target_draft for update;
  if d.host_user_id <> auth.uid() or d.current_pick_number <= 1 then raise exception 'Host pick required'; end if;
  delete from public.draft_picks where draft_id=target_draft and pick_number=d.current_pick_number-1;
  update public.drafts set status='active', completed_at=null,
    current_pick_number=current_pick_number-1,
    current_round=((current_pick_number-2)/team_count)+1,
    pick_deadline_at=case when pick_timer_seconds is null then null else now()+make_interval(secs=>pick_timer_seconds) end,
    updated_at=now() where id=target_draft;
end;
$$;

create or replace function public.nominate_auction_player(target_draft uuid, target_player text)
returns uuid language plpgsql security definer set search_path = public, pg_temp as $$
declare d public.drafts%rowtype; new_auction uuid; min_bid integer;
begin
  select * into d from public.drafts where id=target_draft for update;
  if d.status <> 'active' or d.format <> 'auction' then raise exception 'Auction is not active'; end if;
  if exists(select 1 from public.draft_auctions where draft_id=target_draft and status='open')
    then raise exception 'A nomination is already open'; end if;
  if not exists(select 1 from public.draft_slots where draft_id=target_draft
    and slot_number=d.current_nomination_slot and user_id=auth.uid()) then raise exception 'Not your nomination'; end if;
  if exists(select 1 from public.draft_picks where draft_id=target_draft and player_id=target_player)
    then raise exception 'Player already sold'; end if;
  if not public.draft_player_fits(target_draft,d.current_nomination_slot,target_player)
    then raise exception 'Player does not fit the nominator roster'; end if;
  min_bid := coalesce((d.settings->>'minimumBid')::integer,1);
  insert into public.draft_auctions(
    draft_id,nomination_number,nominating_slot,player_id,current_bid,highest_bidder_slot,deadline_at
  ) values(target_draft,d.current_pick_number,d.current_nomination_slot,target_player,min_bid,
    d.current_nomination_slot,now()+make_interval(secs=>coalesce(d.pick_timer_seconds,30)))
    returning id into new_auction;
  insert into public.draft_bids(auction_id,draft_id,slot_number,user_id,amount)
    values(new_auction,target_draft,d.current_nomination_slot,auth.uid(),min_bid);
  return new_auction;
end;
$$;

create or replace function public.place_auction_bid(target_auction uuid, bid_amount integer)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare a public.draft_auctions%rowtype; d public.drafts%rowtype; bidder public.draft_slots%rowtype;
declare min_bid integer; roster_size integer; filled integer; max_bid integer;
begin
  select * into a from public.draft_auctions where id=target_auction for update;
  select * into d from public.drafts where id=a.draft_id for update;
  select * into bidder from public.draft_slots where draft_id=a.draft_id and user_id=auth.uid();
  if a.status <> 'open' or a.deadline_at <= now() then raise exception 'Auction is closed'; end if;
  if bidder.id is null then raise exception 'Participant required'; end if;
  if not public.draft_player_fits(a.draft_id,bidder.slot_number,a.player_id)
    then raise exception 'Player does not fit the bidder roster'; end if;
  min_bid := coalesce((d.settings->>'minimumBid')::integer,1);
  select count(*) into filled from public.draft_picks where draft_id=a.draft_id and slot_number=bidder.slot_number;
  roster_size := d.rounds;
  max_bid := bidder.budget_remaining - greatest(0,roster_size-filled-1)*min_bid;
  if bid_amount < a.current_bid+min_bid or bid_amount > max_bid then raise exception 'Invalid bid'; end if;
  update public.draft_auctions set current_bid=bid_amount, highest_bidder_slot=bidder.slot_number,
    deadline_at=case when deadline_at-now() < interval '10 seconds' then now()+interval '10 seconds' else deadline_at end
    where id=target_auction;
  insert into public.draft_bids(auction_id,draft_id,slot_number,user_id,amount)
    values(target_auction,a.draft_id,bidder.slot_number,auth.uid(),bid_amount);
end;
$$;

create or replace function public.settle_auction(target_auction uuid)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare a public.draft_auctions%rowtype; d public.drafts%rowtype;
begin
  select * into a from public.draft_auctions where id=target_auction for update;
  select * into d from public.drafts where id=a.draft_id for update;
  if a.status <> 'open' or a.deadline_at > now() then return; end if;
  insert into public.draft_picks(draft_id,player_id,slot_number,round,pick_number,price,is_cpu)
    select a.draft_id,a.player_id,a.highest_bidder_slot,
      (select count(*)+1 from public.draft_picks where draft_id=a.draft_id and slot_number=a.highest_bidder_slot),
      d.current_pick_number,a.current_bid,s.is_cpu
    from public.draft_slots s where s.draft_id=a.draft_id and s.slot_number=a.highest_bidder_slot;
  update public.draft_slots set budget_remaining=budget_remaining-a.current_bid
    where draft_id=a.draft_id and slot_number=a.highest_bidder_slot;
  update public.draft_auctions set status='sold',settled_at=now() where id=target_auction;
  update public.drafts set current_pick_number=current_pick_number+1,
    current_nomination_slot=(current_nomination_slot % team_count)+1,
    status=case when current_pick_number >= team_count*rounds then 'completed' else status end,
    completed_at=case when current_pick_number >= team_count*rounds then now() else completed_at end,
    updated_at=now() where id=a.draft_id;
end;
$$;

revoke execute on all functions in schema public from public, anon;
grant execute on function public.is_draft_participant(uuid,uuid) to authenticated;
grant execute on function public.get_draft_by_slug(text) to authenticated;
grant execute on function public.list_completed_drafts(integer,integer,text,text) to authenticated;
grant execute on function public.create_mock_draft(jsonb,jsonb,text) to authenticated;
grant execute on function public.claim_draft_slot(uuid,integer,text,text) to authenticated;
grant execute on function public.release_draft_slot(uuid) to authenticated;
grant execute on function public.start_mock_draft(uuid) to authenticated;
grant execute on function public.pause_mock_draft(uuid) to authenticated;
grant execute on function public.resume_mock_draft(uuid) to authenticated;
grant execute on function public.make_mock_pick(uuid,text) to authenticated;
grant execute on function public.advance_mock_draft(uuid) to authenticated;
grant execute on function public.undo_last_mock_pick(uuid) to authenticated;
grant execute on function public.nominate_auction_player(uuid,text) to authenticated;
grant execute on function public.place_auction_bid(uuid,integer) to authenticated;
grant execute on function public.settle_auction(uuid) to authenticated;

grant select on public.drafts, public.draft_slots, public.draft_player_snapshots,
  public.draft_picks, public.draft_messages, public.draft_queues,
  public.draft_auctions, public.draft_bids, public.profiles to authenticated;
grant insert on public.draft_messages, public.draft_queues to authenticated;
grant update, delete on public.draft_queues to authenticated;
grant usage, select on all sequences in schema public to authenticated;

alter publication supabase_realtime add table public.drafts;
alter publication supabase_realtime add table public.draft_slots;
alter publication supabase_realtime add table public.draft_picks;
alter publication supabase_realtime add table public.draft_messages;
alter publication supabase_realtime add table public.draft_auctions;
alter publication supabase_realtime add table public.draft_bids;
