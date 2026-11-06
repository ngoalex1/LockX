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
  function inspectFrame(previous,metrics,now,kind,elapsedMs=0){
    const state={stableSince:null,motionSamples:0,motionEnergy:0,...previous};
    const issue=metrics.brightness<24?'Add some light to the item.':metrics.brightness>240?'Reduce glare or move away from the bright light.':metrics.sharpness<18?'Move a little closer and let the camera focus.':null;
    // These checks help choose a frame. Hand jitter and auto-exposure must never
    // prevent the server from receiving evidence for its own quality/comparison checks.
    const elapsed=Number.isFinite(elapsedMs)?Math.max(0,elapsedMs):0;
    const timedFallback=elapsed>=(issue?4500:3500);
    if(issue)return {state:{...state,stableSince:null},issue,ready:timedFallback,timedFallback,feedback:issue};
    if(metrics.motion!==null&&metrics.motion>1.8){state.motionSamples++;state.motionEnergy+=metrics.motion;state.stableSince=null;}
    else if(state.stableSince===null)state.stableSince=now;
    const moved=kind!=='motion'||(state.motionSamples>=2&&state.motionEnergy>=5);
    if(!moved&&!timedFallback)return {state,issue:null,ready:false,timedFallback:false,feedback:'Slowly turn the item or move around it.'};
    const ready=timedFallback||(state.stableSince!==null&&now-state.stableSince>=650);
    return {state,issue:null,ready,timedFallback,feedback:timedFallback?'Collecting this view for comparison…':ready?'Clear view. Keep it here a moment…':kind==='motion'?'Good. Pause briefly at this angle.':'Hold steady. Collecting a clear view…'};
  }
  function stopRecorder(recorder,stream,{timeoutMs=4000}={}){
    return new Promise((resolve,reject)=>{
      let settled=false,timer;
      const removers=[];
      function settle(error){
        if(settled)return;settled=true;clearTimeout(timer);removers.forEach(remove=>remove());
        if(error)reject(error);else resolve();
      }
      function listen(name,handler){
        if(typeof recorder.addEventListener==='function'){
          recorder.addEventListener(name,handler);removers.push(()=>recorder.removeEventListener(name,handler));
        }else{
          const property='on'+name,previous=recorder[property];
          const wrapper=function(event){try{if(typeof previous==='function')previous.call(this,event);}finally{handler(event);}};
          recorder[property]=wrapper;removers.push(()=>{if(recorder[property]===wrapper)recorder[property]=previous;});
        }
      }
      try{
        if(!recorder||recorder.state==='inactive')throw Error('The recording ended before it could be saved. Please record again.');
        listen('stop',()=>settle());
        listen('error',()=>settle(Error('The recording could not be saved. Please record again.')));
        timer=setTimeout(()=>settle(Error('The camera did not finish saving the recording. Please record again.')),Math.max(1,Number.isFinite(timeoutMs)?timeoutMs:4000));
        // MediaRecorder emits its final dataavailable before stop. Keep the caller's
        // data handler intact; only that stop event confirms the final blob arrived.
        recorder.stop();
      }catch(error){settle(error);}
      finally{
        // Release the physical camera even if stop throws or its event never arrives.
        try{stream?.getTracks().forEach(track=>{try{track.stop();}catch{}});}catch{}
      }
    });
  }
  return Object.freeze({measureFrame,inspectFrame,stopRecorder});
});
