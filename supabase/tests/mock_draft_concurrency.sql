-- Run with `supabase test db` after linking a local project.
begin;
select plan(6);

select has_table('public', 'drafts', 'drafts table exists');
select has_table('public', 'draft_picks', 'picks table exists');
select has_function('public', 'claim_draft_slot', array['uuid','integer','text','text'], 'atomic claim RPC exists');
select has_function('public', 'make_mock_pick', array['uuid','text'], 'atomic pick RPC exists');
select col_is_unique('public', 'draft_picks', array['draft_id','player_id'], 'a player is unique per draft');
select col_is_unique('public', 'draft_picks', array['draft_id','pick_number'], 'a pick number is unique per draft');

select * from finish();
rollback;

