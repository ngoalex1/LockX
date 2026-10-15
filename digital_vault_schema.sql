-- LockX Digital Vault. Run once in the Supabase SQL Editor after marketplace_schema.sql.
-- All client access goes through the authenticated LockX API; the Storage bucket is private.

create table if not exists public.vault_items (
  id uuid primary key,
  owner_id uuid not null,
  category text not null check (category in ('watch', 'jewellery', 'handbag')),
  item_name text not null,
  brand text,
  model text,
  reference_number text,
  serial_number text,
  description text,
  distinctive_details text,
  purchase_date date,
  estimated_value numeric,
  currency text default 'USD',
  status text not null default 'protected' check (status in ('protected', 'missing', 'stolen', 'recovered', 'archived', 'pending_transfer')),
  recovery_case_id uuid references public.watch_cases(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists vault_items_owner_updated_idx on public.vault_items(owner_id, updated_at desc);

create table if not exists public.vault_item_photos (
  id uuid primary key,
  item_id uuid not null references public.vault_items(id) on delete cascade,
  storage_path text not null unique,
  sha256 text not null,
  created_at timestamptz not null default now()
);

create index if not exists vault_item_photos_item_idx on public.vault_item_photos(item_id, created_at asc);

create table if not exists public.vault_documents (
  id uuid primary key,
  item_id uuid not null references public.vault_items(id) on delete cascade,
  uploaded_by uuid not null,
  storage_path text not null unique,
  file_name text not null,
  content_type text not null,
  document_type text not null default 'ownership_record',
  transferable boolean not null default true,
  sha256 text not null,
  created_at timestamptz not null default now()
);

create index if not exists vault_documents_item_idx on public.vault_documents(item_id, created_at asc);

create table if not exists public.vault_transfers (
  id uuid primary key,
  item_id uuid not null references public.vault_items(id) on delete cascade,
  from_owner_id uuid not null,
  recipient_email text not null,
  recipient_id uuid,
  sharing_level text not null check (sharing_level in ('full', 'standard', 'minimal')),
  handover_note text,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'cancelled', 'expired', 'disputed')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  accepted_at timestamptz
);

create index if not exists vault_transfers_sender_idx on public.vault_transfers(from_owner_id, created_at desc);
create index if not exists vault_transfers_recipient_idx on public.vault_transfers(recipient_email, status, created_at desc);

create table if not exists public.vault_events (
  id uuid primary key,
  item_id uuid not null references public.vault_items(id) on delete cascade,
  event_type text not null,
  event_data jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists vault_events_item_idx on public.vault_events(item_id, occurred_at desc);

insert into storage.buckets (id, name, public)
values ('vault-files', 'vault-files', false)
on conflict (id) do nothing;

-- The browser never receives service credentials. No direct REST access is allowed.
alter table public.vault_items enable row level security;
alter table public.vault_item_photos enable row level security;
alter table public.vault_documents enable row level security;
alter table public.vault_transfers enable row level security;
alter table public.vault_events enable row level security;
revoke all on public.vault_items, public.vault_item_photos, public.vault_documents,
  public.vault_transfers, public.vault_events from public, anon, authenticated;

alter table public.vault_transfers add column if not exists previous_status text not null default 'protected';
alter table public.vault_transfers add column if not exists item_snapshot jsonb not null default '{}'::jsonb;
create unique index if not exists vault_one_pending_transfer on public.vault_transfers(item_id) where status = 'pending';

-- A recovery record keeps an immutable photo snapshot, not access to future uploads.
create table if not exists public.vault_recovery_photos (
  id uuid primary key,
  case_id uuid not null references public.watch_cases(id) on delete cascade,
  storage_path text not null,
  sha256 text not null,
  created_at timestamptz not null default now(),
  unique(case_id, storage_path)
);
alter table public.vault_recovery_photos enable row level security;
revoke all on public.vault_recovery_photos from public, anon, authenticated;
grant select, insert, update, delete on public.vault_recovery_photos to service_role;

-- Every mutation locks the same item row, preventing accept/cancel/edit races.
-- Only the trusted API can call this function; p_actor comes from verified auth.
create or replace function public.vault_mutate(
  p_action text, p_actor uuid, p_item uuid, p_payload jsonb default '{}'::jsonb,
  p_email text default null, p_transfer uuid default null
) returns jsonb language plpgsql security invoker set search_path = public as $$
declare
  i public.vault_items;
  t public.vault_transfers;
  edited public.vault_items;
  cid uuid;
  cnumber text;
  event_name text;
  event_payload jsonb := '{}'::jsonb;
  result jsonb;
  file_path text;
begin
  if p_action = 'create' then
    edited := jsonb_populate_record(null::public.vault_items, p_payload || jsonb_build_object(
      'id',p_item,'owner_id',p_actor,'status','protected','created_at',now(),'updated_at',now()));
    insert into public.vault_items select edited.* returning * into i;
    insert into public.vault_events values (gen_random_uuid(),i.id,'item_created',jsonb_build_object('category',i.category),now());
    return to_jsonb(i);
  end if;

  select * into i from public.vault_items where id=p_item for update;
  if not found then return jsonb_build_object('error',404,'message','Vault item not found'); end if;
  if p_action in ('accept','cancel') then
    select * into t from public.vault_transfers where id=p_transfer and item_id=i.id for update;
    if not found or (p_action='accept' and (p_email is null or t.recipient_email<>lower(p_email)))
      or (p_action='cancel' and t.from_owner_id<>p_actor) then
      return jsonb_build_object('error',404,'message','Transfer invitation not found');
    end if;
  elsif i.owner_id<>p_actor then
    return jsonb_build_object('error',404,'message','Vault item not found');
  end if;

  -- Expiry and unlocking commit together, even when acceptance returns a conflict.
  for t in select * from public.vault_transfers where item_id=i.id and status='pending' and expires_at<=now() for update loop
    update public.vault_transfers set status='expired' where id=t.id;
    update public.vault_items set status=t.previous_status,updated_at=now()
      where id=i.id and owner_id=t.from_owner_id and status='pending_transfer' returning * into i;
    insert into public.vault_events values(gen_random_uuid(),p_item,'transfer_expired','{}',now());
  end loop;
  select * into i from public.vault_items where id=p_item;
  if p_action='expire' then return to_jsonb(i); end if;

  if p_action in ('accept','cancel') then
    select * into t from public.vault_transfers where id=p_transfer for update;
    if t.status<>'pending' or i.owner_id<>t.from_owner_id or i.status<>'pending_transfer' then
      return jsonb_build_object('error',409,'message','This transfer is no longer available');
    end if;
    if p_action='accept' then
      if p_actor=t.from_owner_id then return jsonb_build_object('error',422,'message','Choose a different recipient'); end if;
      update public.vault_items set owner_id=p_actor,status='protected',recovery_case_id=null,updated_at=now() where id=i.id returning * into i;
      update public.vault_transfers set status='accepted',recipient_id=p_actor,accepted_at=now() where id=t.id;
      event_name := 'ownership_transferred';
      event_payload := jsonb_build_object('sharing_level','full','handover_note',t.handover_note);
    else
      update public.vault_items set status=t.previous_status,updated_at=now() where id=i.id returning * into i;
      update public.vault_transfers set status='cancelled' where id=t.id;
      event_name := 'transfer_cancelled';
    end if;
    result := jsonb_build_object('item',to_jsonb(i),'status',case when p_action='accept' then 'accepted' else 'cancelled' end);
  else
    if i.status='pending_transfer' then return jsonb_build_object('error',409,'message','Cancel the pending transfer before changing this item'); end if;
    case p_action
    when 'update' then
      edited := jsonb_populate_record(i,p_payload);
      update public.vault_items set category=edited.category,item_name=edited.item_name,brand=edited.brand,
        model=edited.model,reference_number=edited.reference_number,serial_number=edited.serial_number,
        description=edited.description,distinctive_details=edited.distinctive_details,purchase_date=edited.purchase_date,
        estimated_value=edited.estimated_value,currency=edited.currency,status=edited.status,updated_at=now()
        where id=i.id returning * into i;
      if i.status in ('recovered','archived') and i.recovery_case_id is not null then
        update public.watch_cases set status='paused' where id=i.recovery_case_id and owner_id=p_actor;
      end if;
      event_name := 'item_updated'; result := to_jsonb(i);
    when 'photo_add' then
      if (select count(*) from public.vault_item_photos where item_id=i.id)>=20 then
        return jsonb_build_object('error',409,'message','Each vault item can have up to 20 photos');
      end if;
      insert into public.vault_item_photos(id,item_id,storage_path,sha256) values
        ((p_payload->>'id')::uuid,i.id,p_payload->>'storage_path',p_payload->>'sha256');
      event_name := 'photo_added'; result := jsonb_build_object('id',p_payload->>'id');
    when 'photo_delete' then
      delete from public.vault_item_photos where id=(p_payload->>'id')::uuid and item_id=i.id returning storage_path into file_path;
      if not found then return jsonb_build_object('error',404,'message','Vault photo not found'); end if;
      event_name := 'photo_removed'; result := jsonb_build_object('storage_path',file_path);
    when 'document_add' then
      insert into public.vault_documents(id,item_id,uploaded_by,storage_path,file_name,content_type,sha256) values
        ((p_payload->>'id')::uuid,i.id,p_actor,p_payload->>'storage_path',p_payload->>'file_name',p_payload->>'content_type',p_payload->>'sha256');
      event_name := 'document_added'; result := jsonb_build_object('id',p_payload->>'id');
    when 'transfer' then
      if i.status not in ('protected','recovered') then return jsonb_build_object('error',409,'message','Resolve recovery before transferring this item'); end if;
      insert into public.vault_transfers(id,item_id,from_owner_id,recipient_email,sharing_level,handover_note,expires_at,previous_status,item_snapshot)
        values(gen_random_uuid(),i.id,p_actor,lower(p_payload->>'recipient_email'),'full',p_payload->>'handover_note',now()+interval '7 days',i.status,
          jsonb_build_object('id',i.id,'item_name',i.item_name,'brand',i.brand,'category',i.category)) returning * into t;
      update public.vault_items set status='pending_transfer',updated_at=now() where id=i.id;
      event_name := 'transfer_started'; result := to_jsonb(t);
    when 'recovery' then
      if p_payload->>'status' not in ('missing','stolen') then return jsonb_build_object('error',422,'message','Choose missing or stolen'); end if;
      select id,case_number into cid,cnumber from public.watch_cases where id=i.recovery_case_id and owner_id=p_actor;
      if cid is null then
        cid:=gen_random_uuid(); cnumber:='LX-'||upper(right(replace(cid::text,'-',''),8));
        insert into public.watch_cases(id,owner_id,case_number,brand,model,reference_number,serial_number,distinctive_marks,status)
          values(cid,p_actor,cnumber,coalesce(nullif(i.brand,''),i.category),coalesce(nullif(i.model,''),i.item_name),i.reference_number,i.serial_number,
          concat_ws(E'\n',i.description,i.distinctive_details,p_payload->>'note'),'open');
      end if;
      update public.watch_cases set status='open' where id=cid and owner_id=p_actor;
      insert into public.vault_recovery_photos(id,case_id,storage_path,sha256)
        select gen_random_uuid(),cid,storage_path,sha256 from public.vault_item_photos where item_id=i.id
        on conflict(case_id,storage_path) do nothing;
      update public.vault_items set status=p_payload->>'status',recovery_case_id=cid,updated_at=now() where id=i.id returning * into i;
      event_name:='recovery_started'; event_payload:=jsonb_build_object('status',i.status);
      result:=jsonb_build_object('item',to_jsonb(i),'case_id',cid,'case_number',cnumber,'search_status','ready_for_approved_sources');
    else
      return jsonb_build_object('error',422,'message','Unknown vault action');
    end case;
  end if;
  insert into public.vault_events values(gen_random_uuid(),i.id,event_name,event_payload,now());
  return result;
end;
$$;
revoke all on function public.vault_mutate(text,uuid,uuid,jsonb,text,uuid) from public,anon,authenticated;
grant execute on function public.vault_mutate(text,uuid,uuid,jsonb,text,uuid) to service_role;

grant select, insert, update, delete on public.vault_items to service_role;
grant select, insert, update, delete on public.vault_item_photos to service_role;
grant select, insert, update, delete on public.vault_documents to service_role;
grant select, insert, update, delete on public.vault_transfers to service_role;
grant select, insert, update, delete on public.vault_events to service_role;
