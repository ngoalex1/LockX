const test=require('node:test');
const assert=require('node:assert/strict');
const {createLightCycle}=require('./in-hand-capture.js');

function timerClock(){
  let now=0,id=0;const timers=new Map();
  return {setTimer(fn,ms){const key=++id;timers.set(key,{at:now+ms,fn});return key;},clearTimer(key){timers.delete(key);},advance(ms){now+=ms;for(const [key,timer] of [...timers])if(timer.at<=now){timers.delete(key);timer.fn();}},get count(){return timers.size;}};
}
function device(action=()=>Promise.resolve(),torch=true){
  const calls=[];return {calls,readyState:'live',getCapabilities(){return {torch};},applyConstraints(value){const on=value.advanced[0].torch;calls.push(on);return action(on);}};
}
const flushed=()=>new Promise(resolve=>setImmediate(resolve));

test('optional torch runs five seconds on then off without controlling recorder duration',async()=>{
  const clock=timerClock(),track=device(),states=[];
  const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});
  assert.equal(cycle.supported,true);assert.equal(cycle.start(),undefined);await flushed();
  assert.deepEqual(track.calls,[true]);assert.deepEqual(states,['on']);
  clock.advance(4999);assert.deepEqual(track.calls,[true]);
  clock.advance(1);await flushed();assert.deepEqual(track.calls,[true,false]);assert.deepEqual(states,['on','off']);
  clock.advance(5000);assert.equal(clock.count,0);cycle.finish();cycle.finish();assert.deepEqual(track.calls,[true,false,false]);
});

test('unsupported devices and fixed-on lights receive no constraints or timers',()=>{
  for(const torch of [undefined,false,[false],[true]]){
    const clock=timerClock(),track=device(),states=[];track.getCapabilities=()=>({torch});
    const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});
    assert.equal(cycle.supported,false);cycle.start();cycle.finish();
    assert.deepEqual(track.calls,[]);assert.equal(clock.count,0);assert.deepEqual(states,['unsupported']);
  }
});

test('capability exceptions fall back to ordinary camera recording',()=>{
  const track={getCapabilities(){throw Error('Unavailable');},applyConstraints(){assert.fail('unsupported light must not be requested');}};
  const cycle=createLightCycle(track);assert.equal(cycle.supported,false);cycle.start();cycle.finish();
});

test('a late ON completion after the five-second deadline is followed by OFF',async()=>{
  const clock=timerClock(),states=[];let resolveOn;
  const track=device(on=>on?new Promise(resolve=>{resolveOn=resolve;}):Promise.resolve(),[false,true]);
  const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});cycle.start();
  clock.advance(5000);assert.deepEqual(track.calls,[true,false]);resolveOn();await flushed();
  assert.deepEqual(track.calls,[true,false,false]);assert.deepEqual(states,['off']);
});

test('cancel while ON is pending clears timers and cannot re-enable light',async()=>{
  const clock=timerClock(),states=[];let resolveOn;
  const track=device(on=>on?new Promise(resolve=>{resolveOn=resolve;}):Promise.resolve());
  const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});cycle.start();cycle.finish();
  assert.equal(clock.count,0);assert.deepEqual(track.calls,[true,false]);resolveOn();await flushed();
  assert.deepEqual(track.calls,[true,false,false]);assert.deepEqual(states,['off']);
  cycle.start();clock.advance(10000);assert.deepEqual(track.calls,[true,false,false]);
});

test('Light off override cancels the automatic cycle permanently',async()=>{
  const clock=timerClock(),track=device(),states=[];
  const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});cycle.start();await flushed();
  cycle.disable();cycle.disable();cycle.start();clock.advance(20000);cycle.finish();
  assert.equal(clock.count,0);assert.deepEqual(track.calls,[true,false,false]);assert.deepEqual(states,['on','disabled']);
});

test('rejected or thrown torch requests fall back without rejecting recording',async()=>{
  for(const immediate of [true,false]){
    const clock=timerClock(),states=[];
    const track=device(on=>{if(on){if(immediate)throw Error('Unsupported driver');return Promise.reject(Error('Unsupported driver'));}return Promise.reject(Error('Off unavailable'));});
    const cycle=createLightCycle(track,{...clock,onState:state=>states.push(state)});
    assert.equal(cycle.start(),undefined);await flushed();
    assert.deepEqual(track.calls,[true,false]);assert.deepEqual(states,['failed']);assert.equal(clock.count,0);
    cycle.finish();await flushed();
  }
});

test('ending the camera track stops later light calls and UI callback failures are isolated',async()=>{
  const clock=timerClock(),track=device();
  const cycle=createLightCycle(track,{...clock,onState(){throw Error('Detached UI');}});cycle.start();await flushed();
  track.readyState='ended';clock.advance(5000);cycle.finish();assert.deepEqual(track.calls,[true]);
});
