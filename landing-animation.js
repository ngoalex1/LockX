/* Lightweight, on-demand illustration. It never accesses the camera. */
(()=>{
  'use strict';
  function install(){
      const root=document.getElementById('lockx-pokemon-demo');
      if(!root||root.dataset.initialized)return;
      root.dataset.initialized='true';
      const demo=root.querySelector('.lx-demo');
      const card='<span class="trading-card" aria-hidden="true"><span class="card-face card-front"><span class="card-title">Pikachu</span><span class="card-hp">HP 60 ⚡</span><span class="card-art"><span class="pika"><span class="pika-tail"></span><span class="pika-ear"></span><span class="pika-ear right"></span><span class="pika-body"></span><span class="pika-head"><span class="pika-eye"></span><span class="pika-cheek"></span><span class="pika-mouth"></span></span><span class="pika-foot"></span></span></span><span class="card-attack">Thunder Shock <b>20</b></span><span class="card-detail"></span></span><span class="card-face card-back"><span class="pokemon-word">Pokémon</span><span class="pokeball"></span><span class="pokemon-word bottom">Pokémon</span></span><span class="card-edge left"></span><span class="card-edge right"></span></span>';
      const hand='<span class="hand-part wrist"></span><span class="hand-part palm"></span><span class="hand-part index-finger"></span><span class="hand-part middle-finger"></span><span class="hand-part ring-finger"></span><span class="hand-part little-finger"></span>'+card+'<span class="hand-part thumb"></span><span class="cuff"></span>';
      root.querySelectorAll('.card-slot').forEach(slot=>{slot.innerHTML=card;});
      root.querySelectorAll('[data-grip]').forEach(slot=>{slot.innerHTML='<div class="grip-scale" aria-hidden="true"><div class="grip-rig">'+hand+'</div></div>';});
      const reducedMotion=matchMedia('(prefers-reduced-motion:reduce)');
      const config={motion:!reducedMotion.matches};
      let elapsed=0,playing=false,startedAt=0,frame=null,lastPhase='',lastSecond=-1;
      const total=12400;
      const steps=[...demo.querySelectorAll('[data-step]')];
      const camera=demo.querySelector('[data-camera]');
      const photos=demo.querySelector('[data-photos]');
      const countdown=demo.querySelector('[data-countdown]');
      const angleLabel=demo.querySelector('[data-angle]');
      const playLabel=demo.querySelector('[data-play-label]');
      const keyframes=[[0,0,-8,8,0,0],[.12,18,-2,-8,-4,-5],[.25,90,9,12,8,1],[.40,174,5,-9,2,-5],[.52,190,-7,12,-7,3],[.68,270,-12,-8,4,-4],[.84,350,4,-14,-4,-1],[1,360,-8,8,0,0]];
      function pose(progress){
        const index=Math.max(0,keyframes.findIndex((point,i)=>i<keyframes.length-1&&progress<=keyframes[i+1][0]));
        const a=keyframes[index],b=keyframes[index+1];
        const t=Math.min(1,Math.max(0,(progress-a[0])/(b[0]-a[0]))),ease=t*t*(3-2*t);
        return a.slice(1).map((value,i)=>value+(b[i+1]-value)*ease);
      }
      function render(){
        const phase=elapsed<1500?'photos':elapsed<total?'video':'verified',step=phase==='photos'?0:phase==='video'?1:2,comparing=phase==='video'&&elapsed>=11500;
        demo.dataset.phase=phase;demo.dataset.playing=String(playing);demo.dataset.ended=String(elapsed>=total);demo.dataset.motion=String(config.motion);
        const progress=Math.min(1,Math.max(0,(elapsed-1500)/10000));
        let [turn,roll,tilt,x,y]=pose(progress);
        if(!config.motion||reducedMotion.matches){turn=progress<.25||progress>.75?0:180;roll=-8;tilt=0;x=0;y=0;}
        demo.style.setProperty('--turn',turn.toFixed(2)+'deg');demo.style.setProperty('--roll',roll.toFixed(2)+'deg');demo.style.setProperty('--tilt',tilt.toFixed(2)+'deg');demo.style.setProperty('--sway-x',x.toFixed(2)+'px');demo.style.setProperty('--sway-y',y.toFixed(2)+'px');
        const angle=Math.round(turn/5)*5,view=turn<65||turn>305?'Front':turn>115&&turn<245?'Back':'Edge';
        angleLabel.textContent=comparing?'Turn complete · 360°':view+' · '+angle+'°';
        const seconds=Math.max(0,Math.min(10,Math.ceil((11500-elapsed)/1000)));
        if(seconds!==lastSecond){countdown.textContent='00:'+String(seconds).padStart(2,'0');lastSecond=seconds;}
        demo.querySelector('[data-camera-status]').textContent=comparing?'Comparing…':'Live view';
        playLabel.textContent=playing?'Pause':elapsed>=total?'Replay':elapsed>0?'Continue animation':'Play animation';
        if(lastPhase!==phase){
          steps.forEach((button,i)=>{if(i===step)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');button.classList.toggle('is-complete',i<step);});
          camera.setAttribute('aria-hidden',String(phase!=='video'));photos.setAttribute('aria-hidden',String(phase==='video'));
          demo.querySelectorAll('[data-photo-label]').forEach(el=>{el.textContent=phase==='verified'?'Verified':el.dataset.photoLabel;});
          demo.querySelector('[data-live-state]').textContent=['Step 1. Take photos of the Pokémon card.','Step 2. A phone records the hand turning the card through its front, edges, and back for 10 seconds.','Step 3. Photos verified.'][step];lastPhase=phase;
        }
      }
      function pause(){if(playing)elapsed=Math.min(total,performance.now()-startedAt);playing=false;cancelAnimationFrame(frame);render();}
      function tick(){elapsed=Math.min(total,performance.now()-startedAt);if(elapsed>=total)playing=false;render();if(playing)frame=requestAnimationFrame(tick);}
      demo.querySelector('[data-play]').addEventListener('click',()=>{if(playing){pause();return;}if(elapsed>=total)elapsed=0;playing=true;startedAt=performance.now()-elapsed;tick();});
      steps.forEach((button,i)=>button.addEventListener('click',()=>{pause();elapsed=[0,1500,total][i];render();}));
      render();
      document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
      new IntersectionObserver(entries=>{if(!entries[0].isIntersecting)pause();},{threshold:.05}).observe(demo);
      reducedMotion.addEventListener('change',render);
  }
  window.LockXAnimation={install};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();
