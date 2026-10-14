-- LockX compliant marketplace network. Run once in Supabase SQL Editor.
create table if not exists public.marketplace_scan_jobs (
  id uuid primary key, owner_id uuid not null,
  case_id uuid not null references public.watch_cases(id) on delete cascade,
  status text not null check (status in ('queued','running','completed','waiting_for_source_access','failed')),
  configured_sources jsonb not null default '[]'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  requested_at timestamptz not null default now(), started_at timestamptz, completed_at timestamptz
);
create index if not exists marketplace_scan_jobs_owner_requested_idx on public.marketplace_scan_jobs(owner_id, requested_at desc);
create table if not exists public.marketplace_candidates (
  id uuid primary key, owner_id uuid not null,
  case_id uuid not null references public.watch_cases(id) on delete cascade,
  scan_job_id uuid not null references public.marketplace_scan_jobs(id) on delete cascade,
  connector_key text not null, external_id text not null, listing_url text not null, title text not null,
  description text, price text, currency text, location text,
  listing_image_urls jsonb not null default '[]'::jsonb, raw_listing jsonb not null default '{}'::jsonb,
  text_score numeric, image_score numeric, confidence numeric not null, visual_status text not null,
  match_reasons jsonb not null default '[]'::jsonb,
  status text not null default 'new' check (status in ('new','reviewing','dismissed','escalated')),
  evidence_sha256 text not null, evidence_captured_at timestamptz not null default now(), created_at timestamptz not null default now(),
  unique(case_id, connector_key, external_id)
);
create index if not exists marketplace_candidates_owner_created_idx on public.marketplace_candidates(owner_id, created_at desc);
grant select, insert, update, delete on public.marketplace_scan_jobs to service_role;
grant select, insert, update, delete on public.marketplace_candidates to service_role;
