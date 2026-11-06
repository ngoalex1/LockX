/* Lightweight camera feedback only. These checks do not establish item identity. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.LockXCapture=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function measureFrame(pixels,width,height,previous){
    if(width<3||height<3||pixels.length!==width*height*4)throw Error('Invalid camera frame.');
    const count=width*height,gray=new Uint8Array(count);let brightness=0,difference=0,edges=0;
    for(let i=0;i<count;i++){const p=i*4,g=Math.round(pixels[p]*.299+pixels[p+1]*.587+pixels[p+2]*.114);gray[i]=g;brightness+=g;if(previous)difference+=Math.abs(g-previous[i]);}
    for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++){const i=y*width+x,l=gray[i-1]+gray[i+1]+gray[i-width]+gray[i+width]-4*gray[i];edges+=l*l;}
    return {gray,brightness:brightness/count,sharpness:edges/((width-2)*(height-2)),motion:previous?difference/count:null};
  }
  function inspectFrame(previous,metrics,now,kind){
    const state={stableSince:null,motionSamples:0,motionEnergy:0,...previous};
    const issue=metrics.brightness<24?'Add some light to the item.':metrics.brightness>240?'Reduce glare or move away from the bright light.':metrics.sharpness<18?'Move a little closer and let the camera focus.':null;
    if(issue)return {state:{...state,stableSince:null},issue,ready:false,feedback:issue};
    if(metrics.motion!==null&&metrics.motion>1.8){state.motionSamples++;state.motionEnergy+=metrics.motion;state.stableSince=null;}
    else if(state.stableSince===null)state.stableSince=now;
    const moved=kind!=='motion'||(state.motionSamples>=2&&state.motionEnergy>=5);
    if(!moved)return {state,issue:null,ready:false,feedback:'Slowly turn the item or move around it.'};
    const ready=state.stableSince!==null&&now-state.stableSince>=650;
    return {state,issue:null,ready,feedback:ready?'Clear view. Keep it here a moment…':kind==='motion'?'Good. Pause briefly at this angle.':'Hold steady. Collecting a clear view…'};
  }
  return Object.freeze({measureFrame,inspectFrame});
});
