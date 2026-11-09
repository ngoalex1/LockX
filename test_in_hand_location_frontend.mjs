import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('./in-hand.js',import.meta.url),'utf8');
const start=source.indexOf('  async function prepareCaptureLocation(route){');
const end=source.indexOf('  function stopCapture(discard = true) {',start);
assert.ok(start>=0&&end>start,'Location helper source exists');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const fresh=()=>({coords:{latitude:37.77492951,longitude:-122.41941551,accuracy:17.25},timestamp:1794240123456});
function harness({unsupported=false,throws=false,network}={}){
  let serial=0;const timers=new Map(),calls=[],requests=[],storage=[];
  const geolocation=unsupported?undefined:{getCurrentPosition(success,error,options){
    calls.push({success,error,options});if(throws)throw Error('Blocked browser permission');
  }};
  const current={route:1,token:'original-private-token',sessionID:'original-session',locationAllowed:true};
  const context=vm.createContext({AbortController,Number,JSON,encodeURIComponent,document:{hidden:false},navigator:{geolocation},
    localStorage:{setItem(...args){storage.push(args);}},sessionStorage:{setItem(...args){storage.push(args);}},
    setTimeout(fn,ms){const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
    api(path,options){requests.push({path,options});return network?network(path,options):Promise.resolve({json:async()=>({})});}});
  context.initial=current;
  vm.runInContext('let capture=initial,routeNumber=1,captureStartNumber=0;function activeCapture(current){return !!current&&capture===current&&!current.cancelled&&current.route===routeNumber;}'+
    source.slice(start,end)+'globalThis.prepare=prepareCaptureLocation;globalThis.request=requestCaptureLocation;globalThis.stop=stopCaptureLocation;globalThis.leave=()=>routeNumber++;globalThis.replace=()=>capture={route:1,sessionID:"new-session",token:"new-token"};',context);
  return {context,current,calls,requests,storage,timers,runTimer(ms){for(const [id,timer] of [...timers])if(timer.ms===ms){timers.delete(id);timer.fn();}}};
}

test('permission acquisition is nonblocking, fresh and bound to the active recording',async()=>{
  const h=harness();assert.equal(h.context.request(h.current),undefined);
  assert.equal(h.calls.length,1);assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0].options)),{enableHighAccuracy:true,maximumAge:0,timeout:4500});
  assert.equal(h.requests.length,0,'A permission prompt cannot delay recorder startup');
  h.context.request(h.current);assert.equal(h.calls.length,1,'The same recording requests permission only once');
  h.calls[0].success(fresh());await flush();
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].path,'/seller/original-private-token/location');
  const payload=JSON.parse(h.requests[0].options.body);
  assert.deepEqual(payload,{session_id:'original-session',latitude:37.77492951,longitude:-122.41941551,accuracy:17.25,timestamp:1794240123456});
  assert.equal(h.requests[0].options.method,'POST');assert.equal(h.timers.size,0);assert.deepEqual(h.storage,[],'Coordinates are never put in local or session storage');
});

test('unavailable permission and unsupported browsers leave ordinary recording alone',()=>{
  for(const mode of ['unsupported','throws','denied']){
    const h=harness({unsupported:mode==='unsupported',throws:mode==='throws'});
    assert.doesNotThrow(()=>h.context.request(h.current));
    if(mode==='denied')h.calls[0].error({code:1,message:'Permission denied'});
    assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);assert.deepEqual(h.storage,[]);
    assert.equal(h.current.cancelled,undefined);assert.equal(h.current.finishing,undefined);
  }
});

test('finishing, route navigation, replacement and cancellation suppress late fixes',()=>{
  for(const action of [h=>h.current.finishing=true,h=>h.context.leave(),h=>h.context.replace(),h=>h.current.cancelled=true,h=>h.context.stop(h.current)]){
    const h=harness();h.context.request(h.current);action(h);h.calls[0].success(fresh());
    assert.equal(h.requests.length,0);assert.deepEqual(h.storage,[]);
  }
});

test('closing capture aborts an outstanding lookup and cannot add data to the next take',async()=>{
  const h=harness({network:()=>new Promise(()=>{})});h.context.request(h.current);h.calls[0].success(fresh());
  assert.equal(h.requests.length,1);const signal=h.requests[0].options.signal;assert.equal(signal.aborted,false);
  h.context.stop(h.current);assert.equal(signal.aborted,true);assert.equal(h.timers.size,0);
  h.context.replace();h.calls[0].success(fresh());await flush();assert.equal(h.requests.length,1);
});

test('acquisition and HTTP deadlines abandon optional location without extending recording',async()=>{
  const acquire=harness();acquire.context.request(acquire.current);acquire.runTimer(5500);acquire.calls[0].success(fresh());
  assert.equal(acquire.requests.length,0);assert.equal(acquire.timers.size,0);
  const http=harness({network:()=>new Promise(()=>{})});http.context.request(http.current);http.calls[0].success(fresh());
  const signal=http.requests[0].options.signal;http.runTimer(3500);assert.equal(signal.aborted,true);
  assert.equal(http.current.cancelled,undefined);assert.equal(http.current.finishing,undefined);
});

test('network rejections and malformed device readings never fail the camera flow',async()=>{
  const network=harness({network:()=>Promise.reject(Error('Offline'))});network.context.request(network.current);network.calls[0].success(fresh());await flush();
  assert.equal(network.timers.size,0);assert.equal(network.current.cancelled,undefined);
  for(const invalid of [{coords:{}},{...fresh(),timestamp:NaN},{...fresh(),coords:{...fresh().coords,latitude:Infinity}},
    {...fresh(),coords:{...fresh().coords,accuracy:-1}},{...fresh(),coords:{...fresh().coords,longitude:'-122'}}]){
    const h=harness();h.context.request(h.current);assert.doesNotThrow(()=>h.calls[0].success(invalid));assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);
  }
});

test('missing sessions and inactive captures cannot ask for location',()=>{
  for(const change of [h=>delete h.current.sessionID,h=>h.current.locationAllowed=false,h=>h.current.finishing=true,h=>h.current.cancelled=true,h=>h.context.leave()]){
    const h=harness();change(h);h.context.request(h.current);assert.equal(h.calls.length,0);assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);
  }
});

test('native permission decision precedes the timed recording and discards preflight coordinates',async()=>{
  const h=harness();const prepared=h.context.prepare(1);await flush();assert.equal(h.calls.length,1);
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0].options)),{enableHighAccuracy:false,maximumAge:0,timeout:2500});
  h.calls[0].success(fresh());assert.equal(await prepared,true);
  assert.equal(h.requests.length,0,'The pre-recording fix must never be attached to a recording');assert.deepEqual(h.storage,[]);
});

test('known geolocation grants or denials do not open an extra prompt',async()=>{
  for(const state of ['granted','denied']){
    const h=harness();h.context.navigator.permissions={query:async()=>({state})};
    assert.equal(await h.context.prepare(1),state==='granted');assert.equal(h.calls.length,0);assert.equal(h.requests.length,0);
  }
});

test('permission denial, browser error and navigation cannot start an unrelated permission lookup',async()=>{
  const denied=harness();const pending=denied.context.prepare(1);await flush();denied.calls[0].error({code:1});assert.equal(await pending,false);
  const unsupported=harness({unsupported:true});assert.equal(await unsupported.context.prepare(1),false);
  const broken=harness({throws:true});assert.equal(await broken.context.prepare(1),false);
  const late=harness();const old=late.context.prepare(1);await flush();late.context.leave();late.calls[0].success(fresh());assert.equal(await old,false);
  const navigated=harness();navigated.context.leave();assert.equal(await navigated.context.prepare(1),false);assert.equal(navigated.calls.length,0);
});

test('a position timeout after permission allows a fresh optional fix during recording',async()=>{
  for(const code of [2,3]){
    const h=harness();const prepared=h.context.prepare(1);await flush();h.calls[0].error({code});
    assert.equal(await prepared,true);assert.equal(h.requests.length,0);
  }
});

function recordingHarness({cameraPending=false}={}){
  const elements=new Map(),windowEvents=new Map(),documentEvents=new Map(),positions=[],timers=new Map();
  const calls={camera:0,recordings:0,stops:0,errors:[],requests:[]};let serial=0,resolveCamera;
  const element=selector=>{if(!elements.has(selector))elements.set(selector,{checked:true,disabled:false,hidden:false,textContent:'',dataset:{},style:{},play:async()=>{}});return elements.get(selector);};
  const track={stop(){calls.stops++;}},stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
  class Recorder{static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';calls.recordings++;}stop(){this.state='inactive';}}
  const win={isSecureContext:true,MediaRecorder:Recorder,LockXCapture:{stopRecorder(){}},innerHeight:800,innerWidth:400,
    addEventListener(name,fn){windowEvents.set(name,fn);},removeEventListener(){},speechSynthesis:{}};
  const doc={hidden:false,body:{classList:{remove(){},add(){}}},addEventListener(name,fn){documentEvents.set(name,fn);}};
  const context=vm.createContext({AbortController,Number,JSON,Date,Promise,Error,encodeURIComponent,window:win,document:doc,MediaRecorder:Recorder,LockXCapture:win.LockXCapture,
    location:{hash:'#in-hand/capture/original-private-token'},performance:{now:()=>1000},localStorage:{setItem(){}},
    navigator:{permissions:{query:async()=>({state:'prompt'})},geolocation:{getCurrentPosition(success,error,options){positions.push({success,error,options});}},
      mediaDevices:{getUserMedia(){calls.camera++;return cameraPending?new Promise(resolve=>{resolveCamera=resolve;}):Promise.resolve(stream);}}},
    setTimeout(fn,ms){const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},setInterval(){return 99;},clearInterval(){},
    $:element,api:async(path)=>{calls.requests.push(path);return {json:async()=>({session_id:'original-session',stage:{instruction:'Turn the item'}})};},
    hasLocalCaptureConsent:()=>true,renderCamera(){},positionReticle(){},speak(){},pumpChunks(){},enqueueChunks(){},renderUploadStatus(){},updateCameraFeedback(){},finishCapture(){},
    errorAt:(selector,error)=>calls.errors.push(error.message),captureFailed:message=>calls.errors.push(message),
    closeSellerEvents(){},clearMarkedFiles(){},route(){}});
  // Use the real generation state, camera start/stop, optional-location helpers
  // and lifecycle handlers so this catches their interaction, not just a mock.
  const mainState=source.split('\n').find(line=>line.startsWith('  let photos ='));
  const auxiliaryState=source.split('\n').find(line=>line.startsWith('  let markedFiles='));
  const generation=source.includes('let captureStartNumber')?source.split('\n').find(line=>line.includes('let captureStartNumber')): 'let captureStartNumber=0;';
  const globals=mainState+'\n'+auxiliaryState+'\n'+(auxiliaryState.includes('captureStartNumber')?'':generation)+'\n';
  const helpers=source.slice(source.indexOf('  function activeCapture(current){'),source.indexOf('  function renderCamera(current)'));
  const handlers=source.slice(source.indexOf("  window.addEventListener('pagehide'"),source.indexOf("  api('/capabilities')"));
  vm.runInContext(globals+"routeNumber=1;isStandalone=true;sellerToken='original-private-token';sellerData={media:[]};"+helpers+handlers+'globalThis.start=startCapture;globalThis.stop=stopCapture;',context);
  return {context,calls,positions,button:element('#ihStartCapture'),hide(kind){doc.hidden=true;if(kind==='pagehide')windowEvents.get('pagehide')({});else documentEvents.get('visibilitychange')({});},
    show(){doc.hidden=false;},resolveCamera(){resolveCamera(stream);}};
}

test('pagehide or backgrounding during a permission prompt prevents late Allow from opening the camera',async()=>{
  for(const kind of ['pagehide','visibilitychange']){
    const h=recordingHarness(),pending=h.context.start();await flush();assert.equal(h.positions.length,1);assert.equal(h.button.disabled,true);assert.equal(h.calls.camera,0);
    h.hide(kind);assert.equal(h.button.disabled,false,'Returning to this page must offer a fresh button tap');
    h.show();h.positions[0].success(fresh());await pending;
    assert.equal(h.calls.camera,0);assert.equal(h.calls.recordings,0);assert.deepEqual(h.calls.requests,[]);assert.equal(h.button.disabled,false);
    const retry=h.context.start();await flush();assert.equal(h.positions.length,2);h.positions[1].success(fresh());await retry;
    assert.equal(h.calls.camera,1);assert.equal(h.calls.recordings,1);assert.deepEqual(h.calls.errors,[]);
  }
});

test('a camera request completed after hiding releases its stream without recording',async()=>{
  for(const kind of ['pagehide','visibilitychange']){
    const h=recordingHarness({cameraPending:true}),pending=h.context.start();await flush();h.positions[0].success(fresh());await flush();assert.equal(h.calls.camera,1);
    h.hide(kind);h.show();h.resolveCamera();await pending;
    assert.equal(h.calls.recordings,0);assert.equal(h.calls.stops,1);assert.equal(h.button.disabled,false);assert.deepEqual(h.calls.requests,[]);
  }
});

test('ordinary permission Allow and Deny still start the same fixed camera recording',async()=>{
  for(const allowed of [true,false]){
    const h=recordingHarness(),pending=h.context.start();await flush();
    if(allowed)h.positions[0].success(fresh());else h.positions[0].error({code:1});
    await pending;assert.equal(h.calls.camera,1);assert.equal(h.calls.recordings,1);assert.deepEqual(h.calls.errors,[]);
    assert.equal(h.calls.requests.filter(path=>path.endsWith('/video/start')).length,1);
    assert.equal(h.positions.length,allowed?2:1,'Only granted access requests a fresh fix during recording');
    h.context.stop();
  }
});
