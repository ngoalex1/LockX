import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Run the actual browser helpers with controlled browser boundaries. No server,
// external packages, camera, paid model, or DOM implementation is required.
const source=fs.readFileSync(new URL('./in-hand.js',import.meta.url),'utf8');
function between(first,next){
  const start=source.indexOf(first),end=source.indexOf(next,start);
  assert.ok(start>=0&&end>start,`Browser helper boundaries exist: ${first}`);
  return source.slice(start,end);
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function clock(){
  let sequence=0;const timers=new Map();
  return {timers,setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);}};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('photo preparation uses at most two decoders and preserves selected order',async()=>{
  const button={disabled:false,textContent:''},create={disabled:false},error={hidden:true};
  let active=0,peak=0;const pending=[],errors=[];
  const context=vm.createContext({Promise,Array,Error,URL:{revokeObjectURL(){}},
    $:id=>({'#ihChoosePhotos':button,'#ihCreate':create,'#ihPhotoError':error}[id]),
    compressPhoto:file=>{active++;peak=Math.max(peak,active);return new Promise(resolve=>pending.push({file,resolve:()=>{active--;resolve({id:file,url:'blob:'+file});}}));},
    renderPhotos(){},errorAt:(id,error)=>errors.push(error.message)});
  vm.runInContext('let photos=[],photoPreparation=null,routeNumber=1;'+between('  async function addPhotos(e) {','  function renderPhotos()')+'globalThis.run=addPhotos;globalThis.state=()=>photos;',context);
  const task=context.run({target:{files:['one','two','three','four'],value:'selected'}});
  assert.equal(pending.length,2);assert.equal(create.disabled,true);
  pending[1].resolve();await flush();assert.equal(pending.length,3);
  pending[2].resolve();await flush();assert.equal(pending.length,4);
  pending[3].resolve();pending[0].resolve();await task;
  assert.equal(peak,2);assert.equal(context.state().map(photo=>photo.id).join(','),'one,two,three,four');
  assert.equal(create.disabled,false);assert.deepEqual(errors,[]);
});

test('navigating away cancels the remaining photo queue and revokes finished blobs',async()=>{
  const pending=[],revoked=[],button={},create={};
  const context=vm.createContext({Promise,Array,Error,URL:{revokeObjectURL:url=>revoked.push(url)},
    $:id=>({'#ihChoosePhotos':button,'#ihCreate':create,'#ihPhotoError':{}}[id]),
    compressPhoto:file=>new Promise(resolve=>pending.push(()=>resolve({id:file,url:'blob:'+file}))),
    renderPhotos:()=>assert.fail('Cancelled photos must not render'),errorAt:()=>assert.fail('Cancelled batch must not replace new-page errors')});
  vm.runInContext('let photos=[],photoPreparation=null,routeNumber=1;'+between('  async function addPhotos(e) {','  function renderPhotos()')+'globalThis.run=addPhotos;globalThis.navigate=()=>routeNumber++;globalThis.state=()=>photos;',context);
  const task=context.run({target:{files:['one','two','three'],value:''}});assert.equal(pending.length,2);
  context.navigate();pending.forEach(resolve=>resolve());await task;
  assert.equal(context.state().length,0);assert.equal(pending.length,2);assert.equal(revoked.sort().join(','),'blob:one,blob:two');
});

test('approved JPEGs load once for gallery and synchronous native sharing; failed indices stay excluded',async()=>{
  const buttons=[0,2,3].map(index=>({dataset:{saveMarkedPhoto:'/public/set/photos/'+index,downloadName:'photo-'+index+'.jpg',photoIndex:String(index)},disabled:true,textContent:''}));
  const images=buttons.map(button=>({dataset:{markedPhoto:button.dataset.saveMarkedPhoto},src:'',getAttribute(name){return name==='src'?this.src:null;}}));
  const all={disabled:true,hidden:false,textContent:'Save photos matched'},hint={},error={},retry={},section={dataset:{markedPublication:'set'},isConnected:true};
  const calls=[],revoked=[],shared=[];let urlCounter=0;
  const context=vm.createContext({Promise,Map,Error,File,Blob,AbortController,setTimeout,clearTimeout,
    URL:{createObjectURL:()=>`blob:marked-${++urlCounter}`,revokeObjectURL:url=>revoked.push(url)},
    navigator:{canShare:({files})=>files.every(file=>file instanceof File),share:args=>{shared.push(args);return Promise.resolve();}},
    api:async(path,options)=>{calls.push({path,options});return{blob:async()=>new Blob([Uint8Array.from([255,216,255,217])],{type:'image/jpeg'})};},
    $:selector=>({'[data-marked-publication]':section,'[data-save-all-photos]':all,'[data-save-photos-hint]':hint,'#ihMarkedError':error,'[data-marked-retry]':retry}[selector]),
    $$:selector=>({'[data-save-marked-photo]':buttons,'[data-marked-photo]':images}[selector]),download:()=>assert.fail('Unexpected download')});
  vm.runInContext('let markedFiles=null,routeNumber=1;'+between('  function clearMarkedFiles(){','  function reportPublication(r)')+'globalThis.bind=bindMarkedDownloads;globalThis.clear=clearMarkedFiles;globalThis.state=()=>markedFiles;',context);
  context.bind({});await flush();await flush();
  assert.equal(calls.length,3);assert.equal(context.state().files.length,3);assert.equal(all.disabled,false);
  assert.equal(images.map(image=>image.src).join(','),'blob:marked-1,blob:marked-2,blob:marked-3');
  assert.ok(calls.every(call=>call.options.cache==='no-store'));
  all.onclick();assert.equal(shared.length,1,'Native share starts before the tap handler returns');
  assert.equal(shared[0].files.map(file=>file.name).join(','),'photo-0.jpg,photo-2.jpg,photo-3.jpg');
  assert.equal(Object.keys(shared[0]).join(','),'files');assert.equal(calls.length,3,'Tap never waits for another download');
  context.bind({});await flush();assert.equal(calls.length,3,'Rerender reuses the prepared files');
  context.clear();assert.equal(revoked.length,3);
});

class FakeEventSource{
  constructor(url){this.url=url;this.listeners=new Map();this.closed=false;FakeEventSource.instances.push(this);}
  addEventListener(name,listener){this.listeners.set(name,listener);}
  close(){this.closed=true;}
  emit(status){this.listeners.get('status')?.({data:JSON.stringify(status)});}
  static instances=[];
}
const processing={status:'processing',analysis_status:'running',publication_status:null};
function eventHarness({available=true}={}){
  const requests=[];FakeEventSource.instances=[];
  const context=vm.createContext({JSON,Error,encodeURIComponent,EventSource:FakeEventSource,window:{EventSource:available?FakeEventSource:undefined},base:'/api/v1/in-hand',
    showSellerResult:(...args)=>requests.push({args,closed:FakeEventSource.instances.at(-1)?.closed})});
  vm.runInContext('let sellerEvents=null,sellerEventsDisabled=false,routeNumber=1;'+between('  function closeSellerEvents(){','  async function showSellerResult(')+'globalThis.watch=watchSellerEvents;globalThis.close=closeSellerEvents;globalThis.navigate=()=>routeNumber++;globalThis.state=()=>({sellerEvents,sellerEventsDisabled});',context);
  return {context,requests,connect(){context.watch('private_token',1,1000,processing);return FakeEventSource.instances.at(-1);}};
}

test('SSE initial unchanged status is quiet and changed revisions fetch the scoped result once',()=>{
  const {connect,requests}=eventHarness(),stream=connect();
  assert.equal(stream.url,'/api/v1/in-hand/seller/private_token/events');
  stream.emit({...processing,revision:'first'});assert.equal(requests.length,0);
  stream.emit({...processing,analysis_status:'complete',publication_status:'pending',revision:'second'});
  assert.equal(requests.length,1);assert.equal(requests[0].args.join(','),'private_token,1,1000');
  stream.emit({...processing,analysis_status:'complete',publication_status:'pending',revision:'second'});assert.equal(requests.length,1);
});

test('terminal SSE closes before fetching the result so EOF cannot trigger a duplicate fetch',()=>{
  const {connect,requests,context}=eventHarness(),stream=connect();
  stream.emit({status:'mismatch',analysis_status:'complete',publication_status:'ready',revision:'terminal'});
  assert.equal(requests.length,1);assert.equal(requests[0].closed,true);assert.equal(context.state().sellerEvents,null);
  stream.onerror();assert.equal(requests.length,1);
});

test('SSE transport failure switches immediately to a scoped GET and disables reconnect loops',()=>{
  const {connect,requests,context}=eventHarness(),stream=connect();stream.onerror();
  assert.equal(requests.length,1);assert.equal(stream.closed,true);assert.equal(context.state().sellerEventsDisabled,true);
  stream.onerror();context.watch('private_token',1,1000,processing);assert.equal(requests.length,1);assert.equal(FakeEventSource.instances.length,1);
});

test('malformed SSE events fall back; unsupported EventSource and old routes do not start streams',()=>{
  const unavailable=eventHarness({available:false});unavailable.connect();assert.equal(FakeEventSource.instances.length,0);
  const {connect,requests,context}=eventHarness(),stream=connect();stream.listeners.get('status')({data:'not json'});
  assert.equal(requests.length,1);assert.equal(stream.closed,true);
  const next=eventHarness(),old=next.connect();next.context.navigate();old.emit({...processing,revision:'old'});old.onerror();assert.equal(next.requests.length,0);
  next.context.close();assert.equal(old.closed,true);
});

function resultHarness(){
  const timers=clock(),requests=[],rendered=[];
  const context=vm.createContext({AbortController,JSON,Date,Map,Set,Error,encodeURIComponent,...timers,
    api:(path,options)=>{const request=deferred();requests.push({path,options,...request});return request.promise;},
    shell:html=>rendered.push(html),$:()=>null,eligiblePhotoIndices:()=>new Set(),publicationPhotoIndex:()=>0,
    photoResultCards:()=>'',qualityRetryReason:()=>null,esc:value=>String(value??''),notice:()=>'',scope:'scope',
    bindLinkButtons(){},bindMarkedDownloads(){},verifiedPhotoSet:()=>'',appLink:()=>'',watchSellerEvents(){},closeSellerEvents(){}});
  vm.runInContext('let routeNumber=1,poll=null,sellerResultNumber=0,sellerResultRequest=null,sellerData={media:[]},sellerEvents=null,browserAccess={records:{}},standalone={};const secretPattern=/^[A-Za-z0-9_-]{43}$/;'+between('  async function showSellerResult(','  function voiceEnabled()')+'globalThis.run=showSellerResult;globalThis.navigate=()=>routeNumber++;globalThis.setStream=()=>sellerEvents={};',context);
  return {context,timers,requests,rendered};
}
function processingResult(){return {...processing,id:'request',total_count:1,verified_count:0,photos:[{photo_index:0,finding:'not_established',evidence:''}],eligible_photo_indices:[],summary:'Checking'};}

test('a newer result fetch aborts the previous request and stale success cannot overwrite the page',async()=>{
  const {context,requests,rendered}=resultHarness();const old=context.run('token',1,Date.now()),current=context.run('token',1,Date.now());
  assert.equal(requests[0].options.signal.aborted,true);
  const stale=new Proxy({}, {get:()=>assert.fail('Stale result must be rejected before its fields are read')});
  requests[0].resolve({json:async()=>stale});await old;assert.equal(rendered.length,0);
  context.navigate();requests[1].resolve({json:async()=>stale});await current;assert.equal(rendered.length,0);
});

test('a stale result failure cannot overwrite the newer page or schedule retries',async()=>{
  const {context,requests,rendered,timers}=resultHarness();const old=context.run('token',1,Date.now()),current=context.run('token',1,Date.now());
  requests[0].reject(Error('Old disconnected request'));await old;assert.equal(rendered.length,0);
  context.navigate();requests[1].reject(Error('Navigated away'));await current;
  assert.equal(rendered.length,0);assert.equal(timers.timers.size,0);
});

test('healthy SSE keeps only a recovery watchdog; absent SSE retains fast polling',async()=>{
  for(const [stream,expected] of [[true,15000],[false,1500]]){
    const {context,requests,timers,rendered}=resultHarness();if(stream)context.setStream();
    const task=context.run('token',1,Date.now());requests[0].resolve({json:async()=>processingResult()});await task;
    assert.equal(rendered.length,1);assert.deepEqual([...timers.timers.values()].map(timer=>timer.ms),[expected]);
  }
});

const qualityContext=vm.createContext({});
vm.runInContext(between('  function qualityRetryReason(result){','  async function showSeller(')+'globalThis.reason=qualityRetryReason;',qualityContext);
const qualityResult=()=>({status:'inconclusive',analysis_status:'complete',verified_count:0,eligible_photo_indices:[],publication_status:'not_eligible',photos:[{finding:'not_established'}],capture_retry_reason:'low_light'});

test('only typed low-light and motion-blur failures offer a light-assisted retry',()=>{
  assert.equal(qualityContext.reason(qualityResult()),'low_light');
  assert.equal(qualityContext.reason({...qualityResult(),capture_retry_reason:'motion_blur'}),'motion_blur');
  for(const reason of [undefined,'shaky','missing_view','low light','item_mismatch','ordinary_inconclusive'])assert.equal(qualityContext.reason({...qualityResult(),capture_retry_reason:reason}),null);
});

test('number or photo contradictions, approved subsets, unfinished checks, and withdrawal block the retry CTA',()=>{
  const changes=[{status:'mismatch'},{status:'confirmed'},{status:'processing'},{analysis_status:'running'},
    {verified_count:1},{eligible_photo_indices:[2]},{publication_status:'ready'},{publication_status:'pending'},{publication_status:'withdrawn'},
    {photos:[{finding:'contradicted'}]},{identifier_checks:[{finding:'contradicted',reference_text:'001027',video_text:'001072'}]}];
  changes.forEach(change=>assert.equal(qualityContext.reason({...qualityResult(),...change}),null));
});

function captureHarness({serverReason,query=''}={}){
  const timers=clock(),elements=new Map(),calls={cycles:0,starts:0,recordings:0,errors:[]};
  const element=selector=>{if(!elements.has(selector))elements.set(selector,{checked:true,dataset:{},style:{},textContent:'',hidden:false,closest:()=>({}),play:async()=>{}});return elements.get(selector);};
  const track={stop(){}};const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
  class Recorder{static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';calls.recordings++;}stop(){this.state='inactive';}}
  const captureAPI={stopRecorder(){},createLightCycle(){calls.cycles++;return {supported:true,start(){calls.starts++;},finish(){},disable(){}};}};
  const win={isSecureContext:true,MediaRecorder:Recorder,LockXCapture:captureAPI,innerHeight:800,innerWidth:400,addEventListener(){},speechSynthesis:{}};
  const detail={id:'inspection',status:'waiting',capture_mode:'handheld',media:[],auto_publish:true,...(serverReason?{capture_retry_reason:serverReason}:{})};
  const context=vm.createContext({AbortController,JSON,Date,Promise,Error,encodeURIComponent,...timers,setInterval:()=>99,clearInterval(){},
    performance:{now:()=>1000},window:win,MediaRecorder:Recorder,LockXCapture:captureAPI,
    navigator:{mediaDevices:{getUserMedia:async()=>stream}},location:{hash:'#in-hand/capture/token',search:query},
    localStorage:{setItem(){}},$:element,api:async path=>({json:async()=>path.endsWith('/video/start')?{session_id:'session',stage:{instruction:'Turn item'}}:detail}),
    shell(){},notice:()=>'',esc:value=>String(value),voiceEnabled:()=>false,renderCamera(){},positionReticle(){},speak(){},pumpChunks(){},enqueueChunks(){},renderUploadStatus(){},updateCameraFeedback(){},
    errorAt:(selector,error)=>calls.errors.push(error.message),stopCapture(){},captureFailed:message=>calls.errors.push(message),showSellerResult(){},finishCapture(){}});
  vm.runInContext("let routeNumber=1,isStandalone=true,capture=null,sellerToken=null,sellerData=null,retryLightToken=null,retryConsentToken=null,autoStartRetryToken=null,browserAccess={records:{}};const secretPattern=/^[A-Za-z0-9_-]{43}$/,base='/api/v1/in-hand';"+
    between('  function hasLocalCaptureConsent(','  function closeSellerEvents(){')+
    between('  function activeCapture(current){','  function stopQualityLoop(')+
    between('  async function startCapture() {','  function renderCamera(current)')+
    'globalThis.load=showSeller;globalThis.start=startCapture;',context);
  return {context,calls};
}

test('ordinary first capture never creates or starts a light cycle, including URL light hints',async()=>{
  for(const query of ['', '?light=true&retry=1&capture_retry_reason=low_light']){
    const {context,calls}=captureHarness({query});await context.load('token',1);await context.start();
    assert.deepEqual(calls.errors,[]);assert.equal(calls.recordings,1);assert.equal(calls.cycles,0);assert.equal(calls.starts,0);
  }
});

test('server-approved quality child capture enables the retry light cycle; unrelated reasons do not',async()=>{
  for(const reason of ['low_light','motion_blur','ordinary_inconclusive','missing_view']){
    const {context,calls}=captureHarness({serverReason:reason});await context.load('token',1);await context.start();
    assert.deepEqual(calls.errors,[]);assert.equal(calls.recordings,1);
    const expected=['low_light','motion_blur'].includes(reason)?1:0;assert.equal(calls.cycles,expected);assert.equal(calls.starts,expected);
  }
});
