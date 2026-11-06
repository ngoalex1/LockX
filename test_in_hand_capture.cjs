const test = require('node:test');
const assert = require('node:assert/strict');
const {measureFrame, inspectFrame, stopRecorder} = require('./in-hand-capture.js');
function rgba(width, height, sample) {
  const pixels=new Uint8ClampedArray(width*height*4);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const i=(y*width+x)*4;const value=sample(x,y);pixels.set([value,value,value,255],i);
  }
  return pixels;
}
const clear={brightness:128,sharpness:100,motion:0};
test('frame measurements distinguish texture, blank light, and image movement',()=>{
  const first=measureFrame(rgba(32,24,(x,y)=>(x+y)%2?60:190),32,24);
  assert.ok(first.sharpness>18);assert.equal(first.motion,null);
  const same=measureFrame(rgba(32,24,(x,y)=>(x+y)%2?60:190),32,24,first.gray);
  assert.equal(same.motion,0);
  const moved=measureFrame(rgba(32,24,(x,y)=>(x+y)%2?190:60),32,24,first.gray);
  assert.ok(moved.motion>100);
  const blank=measureFrame(rgba(32,24,()=>128),32,24);
  assert.equal(blank.sharpness,0);
  assert.throws(()=>measureFrame(new Uint8Array(8),32,24),/Invalid/);
});
test('stable views require sustained clear frames; poor quality resets the hold',()=>{
  let d=inspectFrame({},clear,0,'stable');assert.equal(d.ready,false);
  d=inspectFrame(d.state,clear,700,'stable');assert.equal(d.ready,true);
  d=inspectFrame(d.state,{...clear,brightness:10},750,'stable');assert.ok(d.issue);assert.equal(d.ready,false);
  d=inspectFrame(d.state,clear,800,'stable');assert.equal(d.ready,false);
  d=inspectFrame(d.state,clear,1500,'stable');assert.equal(d.ready,true);
  assert.match(inspectFrame({}, {...clear,sharpness:0},1000,'stable').feedback,/focus/);
  assert.match(inspectFrame({}, {...clear,brightness:250},1000,'stable').feedback,/glare/);
});
test('movement stage requires observed movement followed by a clear pause',()=>{
  let d=inspectFrame({},clear,0,'motion');
  d=inspectFrame(d.state,clear,1000,'motion');assert.equal(d.ready,false);
  d=inspectFrame(d.state,{...clear,motion:4},1250,'motion');assert.equal(d.ready,false);
  d=inspectFrame(d.state,{...clear,motion:4},1500,'motion');assert.equal(d.ready,false);
  d=inspectFrame(d.state,clear,1750,'motion');assert.equal(d.ready,false);
  d=inspectFrame(d.state,clear,2500,'motion');assert.equal(d.ready,true);
  assert.equal(inspectFrame({},clear,3000,'motion').ready,false,'a new stage does not inherit the previous movement');
});
test('minor exposure flicker cannot keep a clear handheld view waiting indefinitely',()=>{
  let previous=null,state={},firstReady=null;
  for(let elapsed=0;elapsed<=5000;elapsed+=250){
    const exposure=(elapsed/250%2)*2;
    const frame=measureFrame(rgba(32,24,(x,y)=>((x+y)%2?60:190)+exposure),32,24,previous);
    previous=frame.gray;
    const decision=inspectFrame(state,frame,10000+elapsed,'stable',elapsed);state=decision.state;
    assert.equal(decision.issue,null);
    if(elapsed>0)assert.equal(frame.motion,2,'two luminance levels can be normal camera exposure variation');
    if(decision.ready){firstReady=elapsed;assert.equal(decision.timedFallback,true);break;}
  }
  assert.equal(firstReady,3500,'a clear frame is submitted for server checks at the bounded deadline');
  assert.equal(state.stableSince,null,'the old pixel stability threshold would never have passed');
});
test('persistent nonzero hand motion advances at the deadline without claiming a pause or identity',()=>{
  for(const kind of ['stable','motion']){
    let state={},decision;
    for(let elapsed=0;elapsed<=3500;elapsed+=250){
      decision=inspectFrame(state,{...clear,motion:4.5+(elapsed%1000)/1000},elapsed,kind,elapsed);state=decision.state;
      assert.equal(decision.ready,elapsed>=3500);
    }
    assert.equal(decision.timedFallback,true);
    assert.equal(decision.issue,null);
    assert.equal(state.stableSince,null);
    assert.equal('verified' in decision,false);
    assert.equal('quality_override' in decision,false,'local fallback cannot override server evidence checks');
  }
});
test('a movement cue cannot block forever when the local detector sees no motion',()=>{
  const before=inspectFrame({},clear,3499,'motion',3499);
  assert.equal(before.ready,false);
  const deadline=inspectFrame(before.state,clear,3500,'motion',3500);
  assert.equal(deadline.ready,true);
  assert.equal(deadline.timedFallback,true);
  assert.equal(deadline.state.motionSamples,0,'the final recording must establish the challenge, not this local cue');
});
test('persistent poor quality triggers a bounded server attempt while keeping the issue visible',()=>{
  for(const metrics of [{...clear,brightness:10},{...clear,brightness:250},{...clear,sharpness:0}]){
    const early=inspectFrame({},metrics,4499,'stable',4499);
    assert.equal(early.ready,false);assert.ok(early.issue);
    const deadline=inspectFrame(early.state,metrics,4500,'stable',4500);
    assert.equal(deadline.ready,true);assert.equal(deadline.timedFallback,true);
    assert.equal(deadline.feedback,deadline.issue);
    assert.equal('quality_override' in deadline,false);
  }
});

class FakeRecorder {
  constructor(stopAction){this.state='recording';this.listeners=new Map();this.stopAction=stopAction;}
  addEventListener(name,handler){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(handler);}
  removeEventListener(name,handler){this.listeners.get(name)?.delete(handler);}
  emit(name,event={}){this['on'+name]?.(event);for(const handler of [...(this.listeners.get(name)||[])])handler(event);}
  stop(){this.state='inactive';this.stopAction?.(this);}
}
function fakeStream(){const tracks=[{stops:0,stop(){this.stops++;}},{stops:0,stop(){this.stops++;}}];return {tracks,getTracks(){return tracks;}};}
test('stop recorder releases camera immediately and waits for final data followed by stop',async()=>{
  const stream=fakeStream(),events=[];
  const recorder=new FakeRecorder(r=>queueMicrotask(()=>{r.emit('dataavailable',{data:'last video bytes'});r.emit('stop');}));
  const ondata=event=>events.push(event.data);recorder.ondataavailable=ondata;
  const saved=stopRecorder(recorder,stream,{timeoutMs:50}).then(()=>events.push('saved'));
  assert.deepEqual(stream.tracks.map(track=>track.stops),[1,1]);
  assert.deepEqual(events,[],'camera shutdown does not pretend final bytes were already emitted');
  await saved;
  assert.deepEqual(events,['last video bytes','saved']);
  assert.equal(recorder.ondataavailable,ondata);
  assert.equal(recorder.listeners.get('stop').size,0);
  assert.equal(recorder.listeners.get('error').size,0);
});
test('missing stop event rejects promptly and the camera is already shut down',async()=>{
  const stream=fakeStream(),recorder=new FakeRecorder(),started=Date.now();
  const stopped=stopRecorder(recorder,stream,{timeoutMs:25});
  assert.deepEqual(stream.tracks.map(track=>track.stops),[1,1]);
  await assert.rejects(stopped,/did not finish saving/);
  assert.ok(Date.now()-started<500,'missing onstop cannot produce an unbounded wait');
  assert.equal(recorder.listeners.get('stop').size,0);
});
test('a thrown recorder stop still shuts down all camera tracks',async()=>{
  const stream=fakeStream(),recorder=new FakeRecorder(()=>{throw Error('Device stop failed');});
  await assert.rejects(stopRecorder(recorder,stream,{timeoutMs:25}),/Device stop failed/);
  assert.deepEqual(stream.tracks.map(track=>track.stops),[1,1]);
  assert.equal(recorder.listeners.get('stop').size,0);
});
test('a recorder error rejects saving while preserving the caller data handler',async()=>{
  const stream=fakeStream(),recorder=new FakeRecorder(r=>queueMicrotask(()=>r.emit('error')));
  const ondata=()=>{};recorder.ondataavailable=ondata;
  await assert.rejects(stopRecorder(recorder,stream,{timeoutMs:50}),/could not be saved/);
  assert.equal(recorder.ondataavailable,ondata);
  assert.deepEqual(stream.tracks.map(track=>track.stops),[1,1]);
});
test('legacy handler-only recorders retain their original stop and data callbacks',async()=>{
  const stream=fakeStream(),events=[];
  const originalStop=()=>events.push('original stop'),originalData=()=>events.push('final bytes');
  const recorder={state:'recording',onstop:originalStop,ondataavailable:originalData,stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable();this.onstop();});}};
  await stopRecorder(recorder,stream,{timeoutMs:50});
  assert.deepEqual(events,['final bytes','original stop']);
  assert.equal(recorder.ondataavailable,originalData);
  assert.equal(recorder.onstop,originalStop);
  assert.deepEqual(stream.tracks.map(track=>track.stops),[1,1]);
});
