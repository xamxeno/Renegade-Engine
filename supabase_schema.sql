-- Run this SQL in your Supabase SQL editor
-- Go to: supabase.com → your project → SQL Editor → New Query → paste this → Run

create table if not exists artists (
  id uuid default gen_random_uuid() primary key,
  name text not null,
  platform text not null,
  platform_id text,
  followers integer default 0,
  genres text,
  profile_url text,
  image_url text,
  instagram text,
  facebook text,
  phone text,
  email text,
  ig_followers integer,
  contact_quality text default 'none',
  score integer,
  score_reason text,
  needs text,
  pitch_draft text,
  notes text,
  status text default 'new',
  contacted_at timestamptz,
  discovered_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(platform, platform_id)
);

-- Run these if the table already exists (add new columns):
alter table artists add column if not exists facebook text;
alter table artists add column if not exists phone text;
alter table artists add column if not exists ig_followers integer;
alter table artists add column if not exists contact_quality text default 'none';
-- v2: separate listeners (Last.fm monthly) from followers (social following)
alter table artists add column if not exists listeners integer default 0;
-- v2: production-need signals detected from artist bio
alter table artists add column if not exists needs text;
-- v3: discovery session tracking (groups all artists from one run)
alter table artists add column if not exists session_id text;

-- Index for fast filtering and sorting
create index if not exists artists_score_idx    on artists(score desc);
create index if not exists artists_listeners_idx on artists(listeners desc);
create index if not exists artists_status_idx   on artists(status);
create index if not exists artists_platform_idx  on artists(platform);
create index if not exists artists_session_idx   on artists(session_id);

-- Enable Row Level Security (open for now, lock down later)
alter table artists enable row level security;
create policy "Allow all" on artists for all using (true);
