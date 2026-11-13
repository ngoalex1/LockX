const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'..','marketing.js'),'utf8');
const visit='00000000-0000-4000-8000-000000000001';
function harness(options={}) {
  const requests=[],listeners={},storage=options.storage||new Map();
  const location={pathname:options.path||'/',hash:'',search:options.search||'',hostname:'lockx.ai'};
  const document={referrer:options.referrer||'',addEventListener:(name,fn)=>listeners[name]=fn};
  const window={LOCKX_LOCAL_PREVIEW:options.preview||false,LockXCredits:{authorization:async()=> 'Bearer test-user'}};
  const context={window,document,location,navigator:{globalPrivacyControl:options.privacy||false,doNotTrack:options.dnt||'0'},
    API_BASE:'https://api.example/v1',URL,URLSearchParams,Date,JSON,Set,Promise,AbortController,
    requestIdleCallback:()=>{},setTimeout:()=>1,clearTimeout:()=>{},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    fetch:async(url,request)=>{requests.push({url,...request,body:JSON.parse(request.body)});return {ok:!options.fail,json:async()=>url.endsWith('/visits')?{visit_id:visit,created:Date.now()/1000}: {ok:true}};}};
  vm.createContext(context);vm.runInContext(source,context);
  return {api:window.LockXMarketing,requests,storage,listeners};
}
const tests=[];
function test(name,fn){tests.push([name,fn]);}
test('single-flight visits and one event per visit type',async()=>{
  const h=harness();assert.deepEqual(await Promise.all([h.api.getVisit(),h.api.getVisit()]),[visit,visit]);
  await h.api.track('verify_click');await h.api.track('verify_click');await h.api.track('wallet_open');
  assert.equal(h.requests.filter(r=>r.url.endsWith('/visits')).length,1);
  assert.equal(h.requests.filter(r=>r.url.endsWith('/events')).length,2);
});
test('campaign payload excludes private query fields and full referrer',async()=>{
  const h=harness({search:'?utm_source=instagram&utm_medium=social&utm_campaign=launch&utm_content=story&token=private-secret&email=private@example.com',referrer:'https://instagram.com/private/path?secret=hidden'});
  await h.api.getVisit();assert.deepEqual(JSON.parse(JSON.stringify(h.requests[0].body)),{source:'instagram',medium:'social',campaign:'launch',content:'story'});
  assert.ok(!h.requests[0].body.referrer);assert.ok(!JSON.stringify([...h.storage.values()]).includes('private-secret'));
});
test('known social referrers are normalized without sending URLs',async()=>{
  const h=harness({referrer:'https://l.instagram.com/outgoing?private=x'});await h.api.getVisit();
  assert.equal(h.requests[0].body.source,'instagram');assert.equal(h.requests[0].body.medium,'social');
});
test('privacy signals, local preview and admin pages perform no tracking',async()=>{
  for(const options of [{privacy:true},{dnt:'1'},{preview:true},{path:'/Ngoalex1'}]){
    const h=harness(options);assert.equal(await h.api.getVisit(),null);await h.api.track('wallet_open');assert.equal(h.requests.length,0);
  }
});
test('verification associations use authenticated request ID only',async()=>{
  const h=harness();await h.api.recordVerification('00000000-0000-4000-8000-000000000002');
  const mapping=h.requests.find(r=>r.url.endsWith('/verifications'));
  assert.equal(mapping.headers.Authorization,'Bearer test-user');assert.equal(mapping.body.request_id,'00000000-0000-4000-8000-000000000002');
});
test('same campaign survives navigation without creating another visit',async()=>{
  const one=harness();await one.api.getVisit();
  const two=harness({storage:one.storage});assert.equal(await two.api.getVisit(),visit);assert.equal(two.requests.length,0);
});
test('new explicit campaign starts a separate attribution visit',async()=>{
  const one=harness();await one.api.getVisit();
  const two=harness({storage:one.storage,search:'?utm_source=tiktok&utm_campaign=new'});await two.api.getVisit();
  assert.equal(two.requests.length,1);assert.equal(two.requests[0].body.source,'tiktok');
});
test('ingest failures and unknown event types do not disrupt product actions',async()=>{
  const h=harness({fail:true});assert.equal(await h.api.getVisit(),null);await h.api.track('payment_complete');
  assert.equal(h.requests.length,1);
});
module.exports=async()=>{const results=[];for(const[name,fn]of tests){try{await fn();results.push({name,status:'PASS'});}catch(error){results.push({name,status:'FAIL',error:error.stack});}}return results;};
