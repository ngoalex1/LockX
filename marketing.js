/* First-party campaign attribution. No pixels, fingerprinting, email or full URLs. */
(() => {
  'use strict';
  const base=API_BASE+'/credits/traffic',key='lockx.campaignVisit.v1',lifetime=24*60*60*1000;
  const admin=()=>location.pathname.replace(/\/+$/,'').toLowerCase()==='/ngoalex1'||location.hash==='#admin';
  const clean=(value,max)=>String(value||'').replace(/[^a-zA-Z0-9 _.\-]/g,'').trim().slice(0,max);
  const platforms=['instagram','tiktok','facebook','youtube','x','linkedin','pinterest','threads'];
  function campaign() {
    const query=new URLSearchParams(location.search);
    let source=clean(query.get('utm_source'),40).toLowerCase(),medium=clean(query.get('utm_medium'),40).toLowerCase();
    if(!source){
      let host='';try{host=new URL(document.referrer).hostname.toLowerCase();}catch{}
      const domains={instagram:'instagram.com',tiktok:'tiktok.com',facebook:'facebook.com',youtube:'youtube.com',x:'x.com',linkedin:'linkedin.com',pinterest:'pinterest.com',threads:'threads.net'};
      source=platforms.find(name=>host===domains[name]||host.endsWith('.'+domains[name]))||
        (host==='t.co'?'x':host==='youtu.be'?'youtube':host&&host!==location.hostname?'referral':'direct');
      medium=platforms.includes(source)?'social':source==='direct'?'none':'referral';
    }
    return {source,medium:medium||'social',campaign:clean(query.get('utm_campaign'),80),content:clean(query.get('utm_content'),120)};
  }
  let visit=null,flight=null;
  try{visit=JSON.parse(sessionStorage.getItem(key)||'null');}catch{}
  if(!visit||!/^[-a-f0-9]{36}$/i.test(visit.visit_id||'')||!Number.isFinite(visit.saved)||Date.now()-visit.saved>=lifetime)visit=null;
  const incoming=campaign(),explicit=new URLSearchParams(location.search).has('utm_source');
  if(visit&&explicit&&JSON.stringify(visit.campaign)!==JSON.stringify(incoming))visit=null;
  async function send(path,body,authorization) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),1800);
    try{
      const response=await fetch(base+path,{method:'POST',cache:'no-store',credentials:'omit',signal:controller.signal,
        headers:{'Content-Type':'application/json',...(authorization?{Authorization:authorization}:{})},body:JSON.stringify(body)});
      if(!response.ok)return null;
      return await response.json();
    }catch{return null;}finally{clearTimeout(timer);}
  }
  function getVisit() {
    if(admin()||window.LOCKX_LOCAL_PREVIEW||navigator.globalPrivacyControl===true||navigator.doNotTrack==='1')return Promise.resolve(null);
    if(visit&&Date.now()-visit.saved<lifetime)return Promise.resolve(visit.visit_id);
    if(flight)return flight;
    flight=(async()=>{
      const result=await send('/visits',incoming);
      if(!result?.visit_id)return null;
      visit={visit_id:result.visit_id,saved:Date.now(),campaign:incoming};
      try{sessionStorage.setItem(key,JSON.stringify(visit));}catch{}
      return visit.visit_id;
    })().finally(()=>{flight=null;});
    return flight;
  }
  const recorded=new Set();
  async function track(event) {
    if(!['verify_click','wallet_open'].includes(event)||recorded.has(event))return;
    const id=await getVisit();if(!id)return;
    recorded.add(event);await send('/events',{visit_id:id,event});
  }
  async function recordVerification(requestId,authorization) {
    try{
      const id=await getVisit(),token=authorization||await window.LockXCredits?.authorization?.();
      if(!id||!token)return;
      await send('/verifications',{visit_id:id,request_id:requestId},token);
    }catch{}
  }
  window.LockXMarketing={getVisit,track,recordVerification};
  document.addEventListener('click',event=>{
    if(event.target.closest?.('a[href="#in-hand"]'))track('verify_click');
  },{passive:true});
  // Attribution is asynchronous and never blocks the page's first render.
  if(!admin()){
    if(typeof requestIdleCallback==='function')requestIdleCallback(()=>getVisit(),{timeout:1500});
    else setTimeout(()=>getVisit(),0);
  }
})();
