// PostgreSQL lifecycle tests; never connects to production.
// Run with PGLITE_MODULE=/absolute/path/to/@electric-sql/pglite/dist/index.js node test_vault_database.mjs
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const {PGlite}=await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
  create schema storage; create table storage.buckets(id text primary key,name text,public boolean);
  create table public.watch_cases(id uuid primary key,owner_id uuid,case_number text,brand text,model text,
    reference_number text,serial_number text,distinctive_marks text,status text,created_at timestamptz default now());
  grant usage on schema public to service_role; grant all on watch_cases to service_role;`);
await db.exec(await readFile(new URL('./digital_vault_schema.sql',import.meta.url),'utf8'));
// Migration is safe to rerun.
await db.exec(await readFile(new URL('./digital_vault_schema.sql',import.meta.url),'utf8'));
const seller='00000000-0000-4000-8000-000000000001', buyer='00000000-0000-4000-8000-000000000002';
const item='00000000-0000-4000-8000-000000000003';
const mutate=async(action,actor=seller,payload={},transfer=null,email=null)=>
  (await db.query('select vault_mutate($1,$2,$3,$4,$5,$6) result',[action,actor,item,JSON.stringify(payload),email,transfer])).rows[0].result;
await db.exec('set role service_role');
assert.equal((await mutate('create',seller,{category:'watch',item_name:'Test watch',currency:'USD'})).owner_id,seller);
assert.equal((await mutate('update',buyer,{item_name:'intruder'})).error,404);
await mutate('update',seller,{serial_number:'123'});
assert.equal((await mutate('update',seller,{serial_number:null})).serial_number,null);
for(let n=0;n<20;n++) assert.ok((await mutate('photo_add',seller,{id:crypto.randomUUID(),storage_path:`test/${n}.jpg`,sha256:'test'})).id);
assert.equal((await mutate('photo_add',seller,{id:crypto.randomUUID(),storage_path:'overflow',sha256:'test'})).error,409);
await mutate('document_add',seller,{id:crypto.randomUUID(),storage_path:'paper.pdf',file_name:'Receipt.pdf',content_type:'application/pdf',sha256:'test'});
const recovery=await mutate('recovery',seller,{status:'stolen',note:'Test note'});
assert.equal((await db.query('select count(*)::int n from vault_recovery_photos')).rows[0].n,20);
assert.equal((await mutate('recovery',seller,{status:'stolen'})).case_id,recovery.case_id);
assert.equal((await db.query('select count(*)::int n from vault_recovery_photos')).rows[0].n,20);
assert.equal((await mutate('transfer',seller,{recipient_email:'buyer@example.com'})).error,409);
await mutate('update',seller,{status:'recovered'});
let t=await mutate('transfer',seller,{recipient_email:'buyer@example.com',handover_note:'Service history travels.'});
assert.equal((await mutate('update',seller,{item_name:'locked'})).error,409);
assert.equal((await mutate('photo_add',seller,{})).error,409);
assert.equal((await mutate('recovery',seller,{status:'missing'})).error,409);
assert.equal((await mutate('accept',buyer,{},t.id,'wrong@example.com')).error,404);
assert.equal((await mutate('cancel',seller,{},t.id)).item.status,'recovered');
assert.equal((await mutate('accept',buyer,{},t.id,'buyer@example.com')).error,409);
t=await mutate('transfer',seller,{recipient_email:'buyer@example.com'});
await db.query("update vault_transfers set expires_at=now()-interval '1 minute' where id=$1",[t.id]);
assert.equal((await mutate('accept',buyer,{},t.id,'buyer@example.com')).error,409);
assert.equal((await db.query('select status from vault_items where id=$1',[item])).rows[0].status,'recovered');
assert.equal((await db.query('select status from vault_transfers where id=$1',[t.id])).rows[0].status,'expired');
t=await mutate('transfer',seller,{recipient_email:'buyer@example.com',handover_note:'Service history travels.'});
const accepted=await mutate('accept',buyer,{},t.id,'buyer@example.com');
assert.equal(accepted.item.owner_id,buyer);
assert.equal(accepted.item.recovery_case_id,null);
assert.equal((await mutate('cancel',seller,{},t.id)).error,409);
assert.equal((await mutate('accept',buyer,{},t.id,'buyer@example.com')).error,409);
assert.equal((await mutate('update',seller,{item_name:'old owner'})).error,404);
assert.equal((await db.query('select count(*)::int n from vault_item_photos where item_id=$1',[item])).rows[0].n,20);
assert.equal((await db.query('select count(*)::int n from vault_documents where item_id=$1',[item])).rows[0].n,1);
assert.equal((await db.query("select event_data->>'handover_note' note from vault_events where event_type='ownership_transferred'")).rows[0].note,'Service history travels.');
await mutate('update',buyer,{item_name:'New owner private name'});
assert.equal((await db.query('select item_snapshot from vault_transfers where id=$1',[t.id])).rows[0].item_snapshot.item_name,'Test watch');
assert.notEqual((await mutate('recovery',buyer,{status:'missing'})).case_id,recovery.case_id);
await db.exec('reset role');
for(const role of ['anon','authenticated']) {
  await db.exec(`set role ${role}`);
  for(const table of ['vault_items','vault_item_photos','vault_documents','vault_events','vault_transfers','vault_recovery_photos'])
    await assert.rejects(db.query(`select * from ${table}`),/permission denied/);
  await assert.rejects(mutate('update',buyer,{item_name:'forged'}),/permission denied/);
  await db.exec('reset role');
}
console.log('PASS: migration rerun, ownership, null edits, 20-photo cap, recovery snapshots/idempotency, transfer locks, wrong recipient, cancel, expiry/unlock, acceptance/replay, documents/history, new-owner recovery, direct REST roles denied.');
await db.close();
