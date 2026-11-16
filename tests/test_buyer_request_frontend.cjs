/* Real browser module in a VM. No account, payment, AI call, or seller message is sent. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '..', 'in-hand.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = (body, ok=true, status=200) => ({ok,status,json:async()=>body});
const managementKey = 'k'.repeat(43);
const record = (state='pending',extra={}) => ({id:'buyer-record',title:'Listing camera',status:state==='pending'?'waiting':'processing',token:'seller-capture-token',manage_key:managementKey,media:[],auto_publish:true,analysis_status:'pending',buyer_request:{state,listing_url:'https://market.example/items/123',buyer_funded:true,credit_reserved:true,expires:1795000000},...extra});
class FormDataFake {
  constructor(){this.entries=[];}
  append(...entry){this.entries.push(entry);}
  get(key){return this.entries.find(entry=>entry[0]===key)?.[1];}
}
function harness(options={}) {
  const nodes=new Map(),requests=[],timers=new Map(),events={},calls={ensure:0,refresh:0,camera:0,recording:0,clipboard:[],shares:[]};let timer=0;
  class Element {
    constructor(){this._html='';this.htmlWrites=0;this.textContent='';this.hidden=false;this.isConnected=true;this.dataset={};this.style={};this.checked=false;this.disabled=false;this.value='';this.classList={add(){},remove(){},toggle(){}};}
    get innerHTML(){return this._html;}
    set innerHTML(html){this._html=html;this.htmlWrites++;}
    append(node){if(node.id==='in-hand')nodes.set('#in-hand',node);}
    prepend(){}
    setAttribute(){}
    insertAdjacentHTML(){}
    addEventListener(){}
    scrollIntoView(){}
    closest(){return new Element();}
    focus(){this.focused=true;}
    select(){this.selected=true;}
    async play(){}
    querySelector(selector){return nodes.get(selector)||null;}
    querySelectorAll(selector){return selector==='input,select,[data-remove],[data-select],#ihChoosePhotos'?['#ihListingURL','#ihBuyerTitle','#ihBuyerCaptureMode','#ihChoosePhotos'].map(id=>nodes.get(id)):[];}
  }
  for(const id of ['main','#ihStandalone','#ihRequestForm','#ihChoosePhotos','#ihPhotoInput','#ihPhotoGrid','#ihPhotoError','#ihCreate','#ihCreateError','#ihCreated','#ihListingURL','#ihBuyerTitle','#ihBuyerCaptureMode','#ihServiceState','#ihExport','.ih-report-head','#ihCopyBuyerMessage','#ihShareBuyerMessage','#ihCancelBuyerRequest','#ihBuyerMessage','#ihBuyerActionError','#ihStartCapture','#ihSellerConsent','#ihShareEvidence','#ihVoiceConsent','#ihCaptureError','#ihDeclineBuyerRequest','#ihLiveVideo','#ihLightStatus','#ihRecorderState','#ihInstructionTitle','#ihInstruction','.ih-auto-camera','#ihElapsed','#ihRemaining','#ihStepProgress','#ihPublicEvidence'])nodes.set(id,new Element());
  nodes.get('#ihRequestForm').dataset.buyer='true';nodes.get('#ihBuyerCaptureMode').value='handheld';nodes.get('#ihBuyerTitle').value='Listing camera';nodes.get('#ihListingURL').value='https://market.example/items/123';
  const document={body:new Element(),hidden:false,readyState:'loading',querySelector:selector=>nodes.get(selector)||null,querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(){}};
  const stream={getTracks:()=>[{stop(){}}],getVideoTracks:()=>[{stop(){}}]};
  class Recorder {static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';calls.recording++;}}
  const window={isSecureContext:true,MediaRecorder:Recorder,LockXCapture:{stopRecorder(){}},innerHeight:800,innerWidth:400,speechSynthesis:{},matchMedia:()=>({matches:true}),scrollTo(){},addEventListener:(name,fn)=>events[name]=fn,LockXCredits:{authorization:async()=> 'Bearer fake-owner',ensureForVerification:async()=>{calls.ensure++;await options.ensure?.();},refresh:()=>{calls.refresh++;},decorate(){}}};
  const navigator={userAgent:'iPhone',clipboard:{writeText:async text=>{if(options.clipboardFail)throw Error('Clipboard unavailable');calls.clipboard.push(text);}},mediaDevices:{getUserMedia:async()=>{calls.camera++;return stream;}}};
  if(options.share)navigator.share=async data=>{calls.shares.push(data);if(options.shareFail)throw Error('Share unavailable');};
  const context={window,document,navigator,API_BASE:'https://api.example/v1',location:{hash:'#other',origin:'https://lockx.example',pathname:'/'},URL,URLSearchParams,Headers,FormData:FormDataFake,AbortController,Date,Intl,JSON,Promise,Map,Set,Number,Math,Error,crypto:webcrypto,MediaRecorder:Recorder,performance:{now:()=>100},btoa:value=>Buffer.from(value,'binary').toString('base64'),localStorage:{getItem:()=>null,setItem(){}},setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id),setInterval:()=>999,clearInterval(){},go(){},toast(){},fetch:async(url,init={})=>{requests.push({url,init});if(url.endsWith('/capabilities'))return response({visual_comparison_ready:true,buyer_requests:true});return options.fetch?options.fetch(url,init):response(record());}};
  let code=source.replace(/\}\)\(\);\s*$/,`window.testBuyer={page,showBuyer,createRequest,buyerMessage,buyerRequestBox,bindBuyerRequest,copyBuyerMessage,safeListingURL,sourceLink,reportFingerprint,pollReport,showReport,showSeller,showPublic,startCapture,route,setCapabilities(value){capabilities=value;},setPhotos(value){photos=value;},getAttempt(){return buyerAttempt;},setRoute(value){routeNumber=value;},setupCapture(record){document.querySelector('#ihSellerConsent').checked=true;sellerData=record;sellerToken='capture-token';routeNumber=1;isStandalone=true;location.hash='#in-hand/capture/capture-token';browserAccess.records[record.id]='${managementKey}';prepareCaptureLocation=async()=>false;renderCamera=()=>{document.querySelector('#ihShareEvidence').checked=false;};positionReticle=()=>{};requestCaptureLocation=()=>{};renderUploadStatus=()=>{};updateCameraFeedback=()=>{};pumpChunks=()=>{};speak=()=>{};}};})();`);
  vm.createContext(context);vm.runInContext(code,context);
  return {api:window.testBuyer,nodes,requests,timers,calls,context,events};
}

test('buyer create waits for fresh credit preflight and never starts buyer phone capture',async()=>{
  let finish;const gate=new Promise(resolve=>finish=resolve);
  const h=harness({ensure:()=>gate,fetch:async()=>response(record())});await flush();h.api.setPhotos([{blob:{bytes:'same-photo'},selected:true}]);
  const creation=h.api.createRequest({preventDefault(){}});await flush();assert.equal(h.requests.filter(r=>r.init.method==='POST').length,0);assert.equal(h.calls.ensure,1);
  finish();await creation;
  const request=h.requests.find(r=>r.url.endsWith('/requests')&&r.init.method==='POST'),payload=JSON.parse(request.init.body.get('payload'));
  assert.equal(payload.request_kind,'buyer');assert.ok(['handheld','flat','stationary','digital'].includes(payload.capture_mode));assert.equal(payload.listing_url,'https://market.example/items/123');assert.equal(payload.auto_publish,true);assert.equal(payload.publish_matched_photos,true);assert.equal(payload.consent,true);assert.match(payload.request_key,/^[A-Za-z0-9_-]{16,80}$/);
  assert.equal(h.context.location.hash,'in-hand/report/buyer-record/'+managementKey);assert.doesNotMatch(h.context.location.hash,/capture/);assert.equal(h.calls.refresh,1);
});

test('ambiguous creation retry uses original nonce, title, listing, and photo bytes without a second preflight',async()=>{
  let count=0;const h=harness({fetch:async()=>{if(++count===1)throw Error('Connection lost');return response(record());}});await flush();const photo={blob:{bytes:'original'},selected:true};h.api.setPhotos([photo]);
  await h.api.createRequest({preventDefault(){}});assert.ok(h.api.getAttempt());assert.equal(h.nodes.get('#ihBuyerTitle').disabled,true);
  h.nodes.get('#ihBuyerTitle').value='A changed title';h.nodes.get('#ihListingURL').value='https://other.example/other';h.api.setPhotos([{blob:{bytes:'changed'},selected:true}]);
  await h.api.createRequest({preventDefault(){}});
  const requests=h.requests.filter(r=>r.url.endsWith('/requests')&&r.init.method==='POST');assert.equal(requests.length,2);assert.equal(requests[0].init.body.get('payload'),requests[1].init.body.get('payload'));assert.equal(requests[1].init.body.get('photos'),photo.blob);assert.equal(h.calls.ensure,1);assert.equal(h.api.getAttempt(),null);
});

test('old-server capability and unsafe listing URL fail before any credit reservation',async()=>{
  const h=harness();await flush();h.api.setPhotos([{blob:{},selected:true}]);h.api.setCapabilities({visual_comparison_ready:true});await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.match(h.nodes.get('#ihCreateError').textContent,/not available.*No credit/);
  h.api.setCapabilities({buyer_requests:true});h.nodes.get('#ihListingURL').value='javascript:alert(1)';await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.equal(h.api.safeListingURL('https://user:password@market.example/item'),'');assert.equal(h.api.sourceLink({listing_url:'javascript:alert(1)'}),'');
});

test('seller invitation contains only the capture and original listing links, with honest manual-share copy',()=>{
  const h=harness({share:true}),r=record();const message=h.api.buyerMessage(r),html=h.api.buyerRequestBox(r);
  assert.match(message,/#in-hand\/capture\/seller-capture-token/);assert.match(message,/https:\/\/market.example\/items\/123/);assert.doesNotMatch(message,/report\/|kkkkk|manage/i);assert.match(html,/You send it yourself; LockX does not contact/);assert.doesNotMatch(html,/request sent|message sent/i);assert.match(html,/Copy message/);assert.match(html,/Share message/);assert.match(html,/Cancel request/);assert.match(html,/noopener noreferrer/);
});

test('native sharing failure falls back to copying the same seller message',async()=>{
  const h=harness({share:true,shareFail:true});h.api.bindBuyerRequest(record(),0);await h.nodes.get('#ihShareBuyerMessage').onclick();assert.equal(h.calls.shares.length,1);assert.equal(h.calls.clipboard[0],h.api.buyerMessage(record()));assert.doesNotMatch(JSON.stringify(h.calls.shares[0]),/report\/|kkkkk/);
});

test('clipboard failure selects the visible message for manual copy',async()=>{
  const h=harness({clipboardFail:true});await h.api.copyBuyerMessage(record(),h.nodes.get('#ihCopyBuyerMessage'));assert.equal(h.nodes.get('#ihBuyerMessage').focused,true);assert.equal(h.nodes.get('#ihBuyerMessage').selected,true);
});

test('seller sharing consent always starts unchecked, including locally saved recording permission',async()=>{
  const h=harness({fetch:async()=>response(record())});await flush();h.api.setRoute(1);await h.api.showSeller('seller-capture-token',1);const html=h.nodes.get('#ihStandalone').innerHTML;
  assert.match(html,/id="ihShareEvidence"/);assert.doesNotMatch(html,/id="ihShareEvidence"[^>]*checked/);assert.match(html,/The requester can view the private recording/);assert.match(html,/Decline request/);assert.match(html,/free for you, with no account/);
});

test('buyer and buyer retry captures require a fresh sharing decision; saved permission never grants it',async()=>{
  for(const data of [record(),{id:'retry',request_kind:'buyer',media:[]}]){
    const h=harness();h.api.setupCapture(data);await h.api.startCapture();assert.equal(h.calls.camera,0);assert.match(h.nodes.get('#ihCaptureError').textContent,/Agree to sharing/);assert.equal(h.requests.filter(r=>r.url.endsWith('/video/start')).length,0);
  }
});

test('capture sends the explicit sharing choice saved before camera rendering clears the checkbox',async()=>{
  for(const share of [true,false]){
    const h=harness({fetch:async url=>response(url.endsWith('/video/start')?{session_id:'session',stage:{instruction:'Turn item'}}:{})});h.api.setupCapture({id:'self-seller',media:[]});h.nodes.get('#ihShareEvidence').checked=share;await h.api.startCapture();
    const request=h.requests.find(r=>r.url.endsWith('/video/start'));assert.ok(request);assert.deepEqual(JSON.parse(request.init.body),{share_evidence:share});assert.equal(h.nodes.get('#ihShareEvidence').checked,false);assert.equal(h.calls.recording,1);
  }
});

test('buyer waiting polls leave copy controls untouched until the server state changes',async()=>{
  const r=record();const h=harness({fetch:async()=>response(r)});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);const before=h.api.page.htmlWrites;
  const timer=[...h.timers.values()].find(t=>t.ms===1800);assert.ok(timer);await timer.fn();assert.equal(h.api.page.htmlWrites,before);assert.match(h.api.page.innerHTML,/Awaiting seller/);assert.doesNotMatch(h.api.page.innerHTML,/Checking against frames from your recording/);
  assert.notEqual(h.api.reportFingerprint(r),h.api.reportFingerprint({...r,buyer_request:{...r.buyer_request,state:'declined'}}));
});

test('owner cancellation and seller decline use their own scoped authorities and explicit consent',async()=>{
  const h=harness({fetch:async url=>response(url.endsWith('/decline')?{}:record('cancelled',{status:'expired'}))});await flush();h.api.bindBuyerRequest(record(),0);await h.nodes.get('#ihCancelBuyerRequest').onclick();const cancel=h.requests.find(r=>r.url.endsWith('/cancel'));assert.deepEqual(JSON.parse(cancel.init.body),{consent:true});assert.equal(cancel.init.headers.get('Authorization'),'Bearer fake-owner');
  const seller=harness({fetch:async url=>response(url.endsWith('/decline')?{}:record())});await flush();seller.api.setRoute(1);await seller.api.showSeller('seller-capture-token',1);await seller.nodes.get('#ihDeclineBuyerRequest').onclick();const decline=seller.requests.find(r=>r.url.endsWith('/decline'));assert.deepEqual(JSON.parse(decline.init.body),{consent:true});assert.equal(decline.init.headers.get('Authorization'),null);assert.match(decline.url,/\/seller\/seller-capture-token\/decline$/);
});

test('public proof mounts the optional evidence viewer before the existing photo gallery',async()=>{
  const mounts=[];const h=harness({fetch:async()=>response({id:'proof',status:'verified',title:'Camera',total_count:1,photo_count:1,photos:[{id:'photo'}],scope:'Visual correspondence'})});h.context.window.LockXEvidence={mount:async(container,options)=>mounts.push({container,options})};await flush();h.api.setRoute(1);await h.api.showPublic('proof',1);assert.equal(mounts.length,1);assert.equal(mounts[0].options.apiBase,'https://api.example/v1/in-hand');assert.equal(mounts[0].options.publicationId,'proof');const html=h.nodes.get('#ihStandalone').innerHTML;assert.ok(html.indexOf('ihPublicEvidence')<html.indexOf('ih-public-gallery'));assert.match(html,/\/public\/proof\/photos\/photo/);
});
