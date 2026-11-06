const test = require('node:test');
const assert = require('node:assert/strict');
const {measureFrame, inspectFrame} = require('./in-hand-capture.js');
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
