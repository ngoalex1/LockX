/* Actual account module in a VM: no identity provider, message, payment or live API. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','verification-account.js'),'utf8'),attemptId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const response=(data,{ok=true,status=200}={})=>({ok,status,json:async()=>data,blob:async()=>new Blob(['photo'],{type:'image/jpeg'})});
const session=(name='one')=>({access_token:'owner-token-'+name,user:{id:name==='one'?'11111111-1111-4111-8111-111111111111':'22222222-2222-4222-8222-222222222222',email:name+'@example.test'}});
const item=(extra={})=>({id:'root-check',kind:'buyer',title:'Actual listing item',listing_url:'https://market.example/item/1',created:1700000000,updated:1700000010,outcome:'partial',verified_count:1,total_count:1,root_total_count:4,preview_media_id:null,unread_count:1,latest_attempt:{id:'attempt-two',outcome:'verified',verified_count:1,total_count:1},attempts:[{id:'root-check',outcome:'inconclusive'},{id:'attempt-two',outcome:'verified'}],...extra});
function harness(options={}){
  const controls=new Map(),events=new Map(),documentEvents=new Map(),authListeners=[],requests=[],timers=new Map(),revoked=[],sent=[];let currentSession=options.session===undefined?session():options.session,serial=0,boots=0;
  class Element{
    constructor(){this._html='';this.isConnected=true;this.dataset={};this.hidden=false;this.textContent='';this.value='';this.disabled=false;this.style={};this.handlers={};}
    set innerHTML(value){this._html=value;for(const match of value.matchAll(/id="([^"]+)"/g)){const key='#'+match[1];if(!controls.has(key))controls.set(key,new Element());}}
    get innerHTML(){return this._html;}
    querySelector(selector){if(selector==='button'){if(!this.button)this.button=new Element();return this.button;}return controls.get(selector)||null;}
    querySelectorAll(selector){if(selector.includes('[data-verification-media]'))return [...this._html.matchAll(/data-verification-(media|preview)="([^"]+)"/g)].map(match=>{const image=new Element();image.dataset[match[1]==='media'?'verificationMedia':'verificationPreview']=match[2];return image;});return [];}
    addEventListener(name,fn){this.handlers[name]=fn;}
    append(){}
  }
  const container=new Element(),doc={hidden:false,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(name,fn){documentEvents.set(name,fn);}};
  const auth={getSession:async()=>({data:{session:currentSession}}),onAuthStateChange(fn){authListeners.push(fn);},signInWithOtp:async args=>{sent.push(args);return {error:null};}};
  const win={ensureLockXAuthClient:async()=>{boots++;return {auth};},LockXCredits:{authorization:async()=>currentSession?'Bearer '+currentSession.access_token:''},addEventListener(name,fn){if(!events.has(name))events.set(name,[]);events.get(name).push(fn);},dispatchEvent(event){for(const fn of events.get(event.type)||[])fn(event);}};
  const context={window:win,document:doc,API_BASE:'https://api.example/v1',location:{hash:options.hash||'#in-hand/account',origin:'https://lockx.example',pathname:'/',search:options.search||''},URL:{...URL,createObjectURL:()=> 'blob:actual-photo',revokeObjectURL:url=>revoked.push(url)},URLSearchParams,AbortController,Blob,Number,Date,JSON,Set,Promise,Error,encodeURIComponent,Event:class Event{constructor(type){this.type=type;}},setTimeout(fn,ms){timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id),fetch:async(url,init)=>{requests.push({url,init});return options.fetch?options.fetch(url,init):response({items:[item()],next_cursor:null,unread_count:1});}};
  context.history={replaceState(_a,_b,value){const url=new URL(value,context.location.origin);context.location.hash=url.hash;context.location.search=url.search;context.location.pathname=url.pathname;}};
  // A real URL constructor is needed for redirect and listing validation.
  context.URL=class AccountURL extends URL{};context.URL.createObjectURL=()=> 'blob:actual-photo';context.URL.revokeObjectURL=url=>revoked.push(url);
  vm.createContext(context);vm.runInContext(source.replace(/\}\)\(\);\s*$/, 'window.testAccount={card,counts,status,action,reportLink,listingLink,identity,returnRoute};})();'),context);
  return {api:win.LockXAccount,helpers:win.testAccount,context,container,controls,requests,timers,revoked,sent,get boots(){return boots;},switchOwner(next){currentSession=next;for(const fn of authListeners)fn('SIGNED_IN',next);},hidden(value){doc.hidden=value;documentEvents.get('visibilitychange')?.();},navigate(hash){context.location.hash=hash;win.dispatchEvent({type:'hashchange'});}};
}
test('dashboard is Bearer-only, shows buyer and seller tabs, and links exact latest attempt behind account sign-in',async()=>{
  const h=harness();h.api.mount(h.container);await flush();await flush();
  assert.equal(h.requests.length,1);assert.match(h.requests[0].url,/\/account\/verifications\?kind=all&limit=20$/);assert.deepEqual(Object.keys(h.requests[0].init.headers),['Authorization']);assert.equal(h.requests[0].init.headers.Authorization,'Bearer owner-token-one');
  const html=h.container.innerHTML;assert.match(html,/Your verifications/);assert.match(html,/>All<\/a>/);assert.match(html,/>Buying<\/a>/);assert.match(html,/>Selling<\/a>/);assert.match(html,/#in-hand\/report\/attempt-two\?account=1/);assert.match(html,/1 of 1 photos verified in this recording · 4 original photos/);assert.match(html,/1 new result/);assert.doesNotMatch(html,/4 of 4|manage_key|capture-token|owner-token/);assert.equal(h.boots,1);
});
test('Buying and Selling tabs request only the selected server filter',async()=>{
  for(const kind of ['buyer','seller']){const h=harness({hash:'#in-hand/account?kind='+kind});h.api.mount(h.container);await flush();await flush();assert.ok(h.requests[0].url.includes('kind='+kind));assert.match(h.container.innerHTML,new RegExp('kind='+kind+'" aria-current="page"'));}
});
test('unsigned dashboard does not call account APIs and email sign-in resumes the same dashboard filter',async()=>{
  const h=harness({session:null,hash:'#in-hand/account?kind=buyer'});h.api.mount(h.container);await flush();await flush();assert.equal(h.requests.length,0);assert.match(h.container.innerHTML,/Your results, on any device/);
  h.controls.get('#vaEmail').value='buyer@example.test';await h.controls.get('#vaSignIn').onsubmit({preventDefault(){}});
  assert.equal(h.sent.length,1);assert.equal(new URL(h.sent[0].options.emailRedirectTo).searchParams.get('verification_return'),'#in-hand/account?kind=buyer');assert.equal(new URL(h.sent[0].options.emailRedirectTo).hash,'');assert.match(h.controls.get('#vaSignInStatus').textContent,/bring you back here/);
});
test('email result sign-in preserves exact attempt and account marker without trusting a private device key',async()=>{
  const h=harness({session:null,hash:'#in-hand/report/'+attemptId+'?account=1'});let opened=0;await h.api.guardReport(h.container,attemptId,()=>opened++);assert.equal(opened,0);assert.equal(h.requests.length,0);assert.match(h.container.innerHTML,/Sign in to open your result/);
  h.controls.get('#vaEmail').value='owner@example.test';await h.controls.get('#vaSignIn').onsubmit({preventDefault(){}});assert.equal(new URL(h.sent[0].options.emailRedirectTo).searchParams.get('verification_return'),'#in-hand/report/'+attemptId+'?account=1');
  h.switchOwner(session());await h.api.guardReport(h.container,attemptId,owner=>{opened++;assert.equal(owner,session().user.id);});assert.equal(opened,1);
});
test('account changes synchronously clear verdicts and abort the old owner request; a late response cannot restore them',async()=>{
  let resolve;const h=harness({fetch:()=>new Promise(done=>resolve=done)});h.api.mount(h.container);await flush();assert.equal(h.requests.length,1);
  h.switchOwner(session('two'));assert.equal(h.requests[0].init.signal.aborted,true);assert.doesNotMatch(h.container.innerHTML,/Actual listing item|Verified photos ready/);
  resolve(response({items:[item({title:'OLD OWNER VERDICT'})],unread_count:1}));await flush();await flush();assert.doesNotMatch(h.container.innerHTML,/OLD OWNER VERDICT|Actual listing item/);
});
test('sign-out clears loaded results immediately and the same device cannot reuse them unsigned',async()=>{
  const h=harness();h.api.mount(h.container);await flush();await flush();assert.match(h.container.innerHTML,/Actual listing item/);h.switchOwner(null);assert.doesNotMatch(h.container.innerHTML,/Actual listing item|1 new result/);h.api.mount(h.container);await flush();await flush();assert.match(h.container.innerHTML,/Your results, on any device/);assert.equal(h.requests.length,1);
});
test('dashboard starts no read-marker mutation; opening a signed-in report can mark its root read once',async()=>{
  const h=harness({fetch:async(url,init)=>response(init.method==='POST'?{updated:1,unread_count:0}:{items:[item()],unread_count:1})});h.api.mount(h.container);await flush();await flush();assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  h.navigate('#in-hand/report/attempt-two?account=1');await h.api.guardReport(h.container,'attempt-two',()=>{});await h.api.markViewed('root-check');const post=h.requests.find(request=>request.init.method==='POST');assert.match(post.url,/\/account\/verifications\/root-check\/read$/);assert.deepEqual(JSON.parse(post.init.body),{});assert.equal(post.init.headers.Authorization,'Bearer owner-token-one');
});
test('empty, error and retry states show actual server outcomes without fabricated totals',async()=>{
  const empty=harness({fetch:async()=>response({items:[],unread_count:0})});empty.api.mount(empty.container);await flush();await flush();assert.match(empty.container.innerHTML,/No verifications yet/);assert.doesNotMatch(empty.container.innerHTML,/new results|4 photos|100%/);
  let fails=true;const error=harness({fetch:async()=>fails?response({detail:'Temporarily unavailable'},{ok:false,status:503}):response({items:[],unread_count:0})});error.api.mount(error.container);await flush();await flush();assert.match(error.container.innerHTML,/couldn’t load/);assert.match(error.container.innerHTML,/Temporarily unavailable/);fails=false;await error.controls.get('#vaRetry').handlers.click();await flush();assert.match(error.container.innerHTML,/No verifications yet/);
});
test('polling runs only while visible, hidden pending responses are ignored, and navigation aborts outstanding requests',async()=>{
  const h=harness();h.api.mount(h.container);await flush();await flush();assert.ok([...h.timers.values()].some(timer=>timer.ms===30000));h.hidden(true);assert.equal([...h.timers.values()].some(timer=>timer.ms===30000),false);const calls=h.requests.length;h.hidden(false);await flush();await flush();assert.equal(h.requests.length,calls+1);
  let finish;const pending=harness({fetch:()=>new Promise(resolve=>finish=resolve)});pending.api.mount(pending.container);await flush();pending.navigate('#landing');assert.equal(pending.requests[0].init.signal.aborted,true);finish(response({items:[item()],unread_count:1}));await flush();assert.doesNotMatch(pending.container.innerHTML,/Actual listing item/);
});
test('pagination uses an opaque encoded cursor and appends without duplicate root checks',async()=>{
  let calls=0;const h=harness({fetch:async()=>response(++calls===1?{items:[item()],next_cursor:'opaque+/=cursor',unread_count:1}:{items:[item(),item({id:'second-root',title:'Second actual item',latest_attempt:{id:'second-root'}})],next_cursor:null,unread_count:1})});h.api.mount(h.container);await flush();await flush();await h.controls.get('#vaMore').handlers.click();await flush();assert.ok(h.requests[1].url.includes('cursor=opaque%2B%2F%3Dcursor'));assert.equal((h.container.innerHTML.match(/Actual listing item/g)||[]).length,1);assert.match(h.container.innerHTML,/Second actual item/);
});
test('dashboard text is escaped, listing links are public HTTP only, and each attempt retains its own account result link',()=>{
  const h=harness(),html=h.helpers.card(item({title:'<script>bad</script>',listing_url:'javascript:alert(1)'}));assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>|javascript:|View listing/);assert.match(html,/#in-hand\/report\/root-check\?account=1/);assert.match(html,/#in-hand\/report\/attempt-two\?account=1/);assert.match(html,/Photos are not combined into one recording/);assert.equal(h.helpers.listingLink('https://user:pass@market.example/item'),'');assert.equal(h.helpers.reportLink('bad/secret'),'#in-hand/account');
});
test('private thumbnails use authenticated media blobs and URLs are revoked when leaving the dashboard',async()=>{
  const h=harness({fetch:async(url)=>url.includes('/in-hand/media/')?response({}):response({items:[item({preview_media_id:'actual-media-id'})],unread_count:1})});h.api.mount(h.container);await flush();await flush();await flush();const image=h.requests.find(request=>request.url.includes('/in-hand/media/actual-media-id'));assert.ok(image);assert.equal(image.init.headers.Authorization,'Bearer owner-token-one');assert.doesNotMatch(h.container.innerHTML,/https:\/\/api\.example\/v1\/in-hand\/media/);h.navigate('#landing');assert.deepEqual(h.revoked,['blob:actual-photo']);
});

test('256px account thumbnails take precedence over original media and reject noncanonical or cross-origin preview URLs',async()=>{
  const h=harness({fetch:async(url)=>url.endsWith('/thumbnail')?response({}):response({items:[item({preview_url:'/account/verifications/root-check/thumbnail',preview_media_id:'full-size-original'})],unread_count:1})});h.api.mount(h.container);await flush();await flush();await flush();
  assert.ok(h.requests.some(request=>request.url==='https://api.example/v1/account/verifications/root-check/thumbnail'));assert.equal(h.requests.some(request=>request.url.includes('/in-hand/media/')),false);
  for(const preview_url of ['https://other.example/track','/account/verifications/unrelated-root/thumbnail','/account/verifications/root-check/thumbnail?key=bad']){const html=h.helpers.card(item({preview_url}));assert.doesNotMatch(html,/data-verification-preview=/);}
});

test('unchanged visible polling keeps current DOM and prepared thumbnail blobs instead of fetching images again',async()=>{
  const h=harness({fetch:async(url)=>url.endsWith('/thumbnail')?response({}):response({items:[item({preview_url:'/account/verifications/root-check/thumbnail'})],unread_count:1})});h.api.mount(h.container);await flush();await flush();await flush();const before=h.container.innerHTML;
  const timer=[...h.timers.values()].find(timer=>timer.ms===30000);assert.ok(timer);await timer.fn();await flush();
  assert.equal(h.container.innerHTML,before);assert.equal(h.requests.filter(request=>request.url.endsWith('/thumbnail')).length,1);assert.deepEqual(h.revoked,[]);
});

test('proof preparation, manual publishing, and withdrawn outcomes do not claim verified photos are ready',()=>{
  const h=harness();for(const outcome of ['preparing_proof','ready_to_publish','withdrawn']){const html=h.helpers.card(item({outcome,attempts:[]}));assert.doesNotMatch(html,/Verified photos ready/);assert.match(html,new RegExp('data-outcome="'+outcome+'"'));}
});

test('pending or unfinished requests hide result counts and pending buyer requests say Awaiting seller',()=>{
  const h=harness();for(const outcome of ['pending','processing','failed','cancelled','declined','expired']){const row=item({outcome});assert.equal(h.helpers.counts(row),'');assert.doesNotMatch(h.helpers.card(row),/photos verified in this recording|photos matched in this recording/);}
  assert.match(h.helpers.card(item({outcome:'pending',kind:'buyer'})),/Awaiting seller/);assert.match(h.helpers.card(item({outcome:'pending',kind:'seller'})),/Awaiting recording/);
});

test('proof preparation, manual publishing, proof failure and withdrawal label counts matched rather than verified',()=>{
  const h=harness();for(const outcome of ['preparing_proof','ready_to_publish','proof_preparation_failed','withdrawn']){const count=h.helpers.counts(item({outcome}));assert.match(count,/1 of 1 photos matched in this recording/);assert.doesNotMatch(count,/verified/);}
  for(const outcome of ['verified','partial','mismatch'])assert.match(h.helpers.counts(item({outcome})),/photos verified in this recording/);
});

test('magic-link query restores the exact account report after the SDK replaces its hash and strips the return query',async()=>{
  const target='#in-hand/report/'+attemptId+'?account=1',h=harness({hash:'#access_token=private-auth-token&refresh_token=private-refresh-token',search:'?verification_return='+encodeURIComponent(target)});await flush();await flush();
  assert.equal(h.context.location.hash,target);assert.equal(h.context.location.search,'');assert.equal(h.boots,1);assert.equal(h.requests.length,0,'Session restoration alone never fetches or marks a private result');assert.doesNotMatch(JSON.stringify(h.sent),/private-auth-token/);
});

test('return-route whitelist rejects external URLs, management capabilities, admin paths and arbitrary query strings without booting auth',async()=>{
  const invalid=['https://evil.example/','#admin','#in-hand/report/'+attemptId+'/SECRET_KEY','#in-hand/report/'+attemptId+'?account=0','#in-hand/report/'+attemptId+'?account=1&extra=yes','#in-hand/account?admin=1','javascript:alert(1)','#in-hand/report/not-a-uuid?account=1'];
  for(const value of invalid){const h=harness({hash:'#landing',search:'?verification_return='+encodeURIComponent(value)});await flush();assert.equal(h.helpers.returnRoute(value),'');assert.equal(h.context.location.hash,'#landing');assert.equal(h.context.location.search,'');assert.equal(h.boots,0);assert.equal(h.requests.length,0);}
  const h=harness();assert.equal(h.helpers.returnRoute('#in-hand/account?kind=seller'),'#in-hand/account?kind=seller');
});

test('compact dashboard puts only its heading and tabs above the list, with account metadata disclosed below',async()=>{
  const h=harness();h.api.mount(h.container);await flush();await flush();const html=h.container.innerHTML,above=html.split('<div class="va-records">')[0];
  assert.match(above,/class="va-account va-compact-account"/);assert.match(above,/<header class="va-heading"><h1 id="vaTitle">Your verifications<\/h1><\/header>/);assert.match(above,/class="va-tabs"/);
  assert.doesNotMatch(above,/va-eyebrow|Keep track|one@example|new result|va-account-bar|Refresh|Verify photos/);
  assert.match(html,/<details class="va-account-details"><summary>Account details<\/summary><div class="va-details-body">/);assert.ok(html.indexOf('one@example.test')>html.indexOf('va-account-details'));assert.ok(html.indexOf('id="vaRefresh"')>html.indexOf('va-account-details'));
});

test('compact item has one main action and hides dates, listing and independent attempt history in Details',()=>{
  const h=harness(),html=h.helpers.card(item()),main=html.split('<details class="va-details">')[0],details=html.slice(html.indexOf('<details class="va-details">'));
  assert.match(html,/<article class="va-record va-compact-record">/);assert.match(main,/Actual listing item/);assert.match(main,/>Buying<\/span>/);assert.match(main,/aria-label="1 new result">New<\/span>/);assert.ok(main.indexOf('va-record-meta')<main.indexOf('<h2>'));assert.match(main,/1\/1 verified · latest recording/);
  assert.equal((main.match(/class="va-button"/g)||[]).length,1);assert.doesNotMatch(main,/va-date|va-counts|View listing|Recording attempts|original photos|Each recording/);
  assert.match(details,/<summary>Details<\/summary><div class="va-details-body">/);assert.match(details,/va-date/);assert.match(details,/View listing/);assert.match(details,/1 of 1 photos verified in this recording · 4 original photos/);assert.match(details,/Photos are not combined into one recording/);assert.match(details,/#in-hand\/report\/attempt-two\?account=1/);
});

test('every outcome has a contextual navigation action without promising retry, publication or a new recording',()=>{
  const h=harness();for(const [outcome,kind,label] of [['verified','seller','View proof'],['partial','buyer','Review result'],['pending','buyer','View request'],['pending','seller','Continue'],['processing','buyer','View progress'],['preparing_proof','seller','View progress'],['ready_to_publish','seller','Review & publish'],['failed','buyer','Open check'],['proof_preparation_failed','seller','Open check'],['withdrawn','seller','View result'],['inconclusive','seller','Review result'],['mismatch','buyer','Review result'],['cancelled','buyer','View request'],['declined','buyer','View request'],['expired','buyer','View request']]){
    const row=item({outcome,kind}),html=h.helpers.card(row);assert.equal(h.helpers.action(row),label);assert.match(html,new RegExp('class="va-button" href="#in-hand/report/attempt-two\\?account=1">'+label.replace('&','&amp;')+'<\\/a>'));assert.equal((html.match(/class="va-button"/g)||[]).length,1);assert.doesNotMatch(html,/>(?:Retry|Publish|Record again|New check)<\/a>/);
  }
});

test('compact statuses show only supported completed ratios and preserve independent latest-recording scope',()=>{
  const h=harness();assert.equal(h.helpers.status(item({outcome:'verified',root_total_count:4,latest_attempt:{id:'root-check',verified_count:4,total_count:4}})),'Verified · 4/4 photos');assert.equal(h.helpers.status(item({outcome:'partial',latest_attempt:{verified_count:2,total_count:4}})),'2/4 photos verified');assert.equal(h.helpers.status(item({outcome:'verified'})),'1/1 verified · latest recording');
  for(const outcome of ['pending','processing','preparing_proof','ready_to_publish','failed','proof_preparation_failed','withdrawn','cancelled','declined','expired','inconclusive','mismatch'])assert.doesNotMatch(h.helpers.status(item({outcome})),/\d+\/\d+/);
  assert.equal(h.helpers.status(item({outcome:'partial',latest_attempt:{verified_count:null,total_count:4}})),'Some photos verified');
  for(const latest_attempt of [{verified_count:null,total_count:4},{verified_count:5,total_count:4},{verified_count:1.5,total_count:4},{verified_count:0,total_count:0}])assert.equal(h.helpers.status(item({outcome:'verified',latest_attempt})),'Verified');
});
