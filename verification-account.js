/* Account verifications use the signed-in owner only. Capability links stay separate. */
(() => {
  'use strict';
  const base=API_BASE+'/account/verifications',mediaBase=API_BASE+'/in-hand/media/';
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const id=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)?value:null;
  const outcomes={pending:'Awaiting recording',processing:'Comparing your recording',preparing_proof:'Preparing verified photos',ready_to_publish:'Matched photos ready to publish',withdrawn:'Public proof withdrawn',verified:'Verified photos ready',partial:'Some photos verified',inconclusive:'More evidence needed',mismatch:'Photos did not all match',failed:'Comparison could not finish',proof_preparation_failed:'Proof images need attention',cancelled:'Request cancelled',declined:'Seller declined',expired:'Recording link expired'};
  let active=null,sequence=0,clientBoot=null,knownOwner=null,lastUnreadCount=null;
  const requests=new Set();
  function valid(state){return active===state&&state.container.isConnected&&state.hash===location.hash;}
  function stop(){sequence++;for(const controller of requests)controller.abort();requests.clear();if(active){clearTimeout(active.timer);active.urls.forEach(url=>URL.revokeObjectURL(url));active.urls.clear();}active=null;}
  function resetOwner(owner){
    if(owner===knownOwner)return;knownOwner=owner;lastUnreadCount=null;sequence++;
    for(const controller of requests)controller.abort();requests.clear();
    if(active){clearTimeout(active.timer);active.urls.forEach(url=>URL.revokeObjectURL(url));active.urls.clear();active.container.innerHTML='<div class="va-panel" role="status">Checking your sign-in…</div>';}
    document.querySelectorAll('[data-verification-unread]').forEach(node=>{node.hidden=true;node.textContent='';});
  }
  async function authClient(){
    if(!clientBoot)clientBoot=window.ensureLockXAuthClient().then(client=>{
      client.auth.onAuthStateChange?.((_event,session)=>resetOwner(session?.user?.id||null));return client;
    }).catch(error=>{clientBoot=null;throw error;});
    return clientBoot;
  }
  async function identity(){
    const client=await authClient();
    for(let attempt=0;attempt<2;attempt++){
      const authorization=await window.LockXCredits.authorization(true),{data,error}=await client.auth.getSession();if(error)throw error;
      const session=data?.session;resetOwner(session?.user?.id||null);
      if(!session?.access_token||!session.user?.id)return null;
      if(authorization==='Bearer '+session.access_token)return {authorization,owner:session.user.id,email:session.user.email||''};
    }
    throw Error('Your sign-in changed. Please try again.');
  }
  function badge(count){return Number.isSafeInteger(count)&&count>0?`<span class="va-badge">${count} new ${count===1?'result':'results'}</span>`:'';}
  function updateBadges(count){lastUnreadCount=Number.isSafeInteger(count)&&count>=0?count:null;document.querySelectorAll('[data-verification-unread]').forEach(node=>{node.hidden=!Number.isSafeInteger(lastUnreadCount)||lastUnreadCount<1;node.textContent=node.hidden?'':String(lastUnreadCount);});}
  function reportLink(value){return id(value)?'#in-hand/report/'+encodeURIComponent(value)+'?account=1':'#in-hand/account';}
  function returnRoute(value){
    if(typeof value!=='string')return '';
    if(/^#in-hand\/account(?:\?kind=(?:all|buyer|seller))?$/.test(value))return value;
    return /^#in-hand\/report\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\?account=1$/i.test(value)?value:'';
  }
  function listingLink(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:'';}catch{return '';}}
  function time(value){return Number.isFinite(value)&&value>0?new Date(value*1000).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'';}
  function counts(item){
    const latest=item.latest_attempt||item,verified=latest.verified_count,total=latest.total_count,outcome=item.outcome||latest.outcome;
    if(!['verified','partial','mismatch','inconclusive','preparing_proof','ready_to_publish','proof_preparation_failed','withdrawn'].includes(outcome))return '';
    if(!Number.isInteger(verified)||!Number.isInteger(total)||verified<0||total<1||verified>total)return '';
    const rootTotal=Number.isInteger(item.root_total_count)&&item.root_total_count>total?` · ${item.root_total_count} original photos`:'';
    const label=['preparing_proof','ready_to_publish','proof_preparation_failed','withdrawn'].includes(outcome)?'matched':'verified';
    return `${verified} of ${total} photos ${label} in this recording${rootTotal}`;
  }
  function card(item){
    if(!id(item?.id))return '';
    const latest=item.latest_attempt||item,target=id(latest.id)||item.id,kind=item.kind==='buyer'?'Buying':'Selling',outcome=item.kind==='buyer'&&item.outcome==='pending'?'Awaiting seller':outcomes[item.outcome]||'Status unavailable',listing=listingLink(item.listing_url);
    const attempts=Array.isArray(item.attempts)?item.attempts.slice(0,3).filter(attempt=>id(attempt?.id)):[];
    const preview=item.preview_url==='/account/verifications/'+item.id+'/thumbnail'?`data-verification-preview="${esc(item.preview_url)}"`:id(item.preview_media_id)?`data-verification-media="${esc(item.preview_media_id)}"`:'';
    return `<article class="va-record"><div class="va-record-main"><div class="va-thumb">${preview?`<img ${preview} alt="Listing photo for ${esc(item.title||'your item')}" loading="lazy">`:'<span>No photo</span>'}</div><div class="va-record-copy"><div class="va-record-meta"><span>${kind}</span>${badge(item.unread_count)}</div><h2>${esc(item.title||'Item verification')}</h2><p class="va-status" data-outcome="${esc(item.outcome||'unknown')}">${outcome}</p>${counts(item)?`<p class="va-counts">${esc(counts(item))}</p>`:''}<p class="va-date">${esc(time(item.created))}${latest.id!==item.id?' · Latest recording shown':''}</p></div></div><div class="va-record-actions"><a class="va-button" href="${reportLink(target)}">View result</a>${listing?`<a class="va-text" href="${esc(listing)}" target="_blank" rel="noopener noreferrer">View listing</a>`:''}</div>${attempts.length>1?`<details class="va-attempts"><summary>${attempts.length} recording attempts</summary><p>Each recording has its own evidence and proof. Photos are not combined into one recording.</p><ol>${attempts.map((attempt,index)=>`<li><a href="${reportLink(attempt.id)}">Attempt ${index+1}</a><span>${outcomes[attempt.outcome]||'Status unavailable'}${attempt.id===target?' · Latest':''}</span></li>`).join('')}</ol></details>`:''}</article>`;
  }
  function shell(state,content){
    state.container.innerHTML=`<section class="va-account" aria-labelledby="vaTitle"><header class="va-heading"><div><p class="va-eyebrow">Your LockX account</p><h1 id="vaTitle">Your verifications</h1><p>Keep track of the items you’re buying and selling.</p></div><a class="va-text" href="#in-hand">Verify photos</a></header>${content}</section>`;
  }
  function signIn(state,report=false){
    const content=`<div class="va-panel va-sign-in"><h2>${report?'Sign in to open your result.':'Your results, on any device.'}</h2><p>Use the email that ${report?'owns this verification':'you used for your credits and verifications'}. No password needed.</p><form id="vaSignIn"><label for="vaEmail">Email address</label><input id="vaEmail" type="email" autocomplete="email" inputmode="email" maxlength="254" required><button class="va-button" type="submit">Send sign-in link</button></form><p id="vaSignInStatus" role="status" hidden></p></div>`;
    if(report)state.container.innerHTML=`<section class="va-account"><a class="va-text" href="#in-hand/account">Your verifications</a>${content}</section>`;else shell(state,content);
    const form=state.container.querySelector('#vaSignIn');if(!form)return;
    form.onsubmit=async event=>{
      event.preventDefault();const button=form.querySelector('button'),message=state.container.querySelector('#vaSignInStatus'),email=state.container.querySelector('#vaEmail').value.trim();button.disabled=true;message.hidden=false;message.textContent='Sending your sign-in link…';
      try{
        const target=returnRoute(state.hash);if(!target)throw Error('Open Your verifications and sign in again.');
        const client=await authClient(),redirect=new URL(location.origin+'/');redirect.searchParams.set('verification_return',target);
        const {error}=await client.auth.signInWithOtp({email,options:{emailRedirectTo:redirect.href}});if(error)throw error;
        if(valid(state))message.textContent='Check your email. The link will bring you back here.';
      }catch(error){if(valid(state))message.textContent=error.message||'The sign-in link could not be sent. Try again.';}
      finally{if(valid(state))button.disabled=false;}
    };
  }
  function tabs(state){return `<nav class="va-tabs" aria-label="Verification type">${[['all','All'],['buyer','Buying'],['seller','Selling']].map(([kind,label])=>`<a href="#in-hand/account${kind==='all'?'':'?kind='+kind}" ${state.kind===kind?'aria-current="page"':''}>${label}</a>`).join('')}</nav>`;}
  async function ownerFetch(url,owner,options={}){
    const identityNow=await identity();if(!identityNow||identityNow.owner!==owner)throw Error('Sign in to the account that owns these verifications.');if(document.hidden)throw Error('Open this page to continue.');
    const controller=new AbortController();requests.add(controller);const deadline=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch(url,{...options,cache:'no-store',signal:controller.signal,headers:{Authorization:identityNow.authorization,...(options.body?{'Content-Type':'application/json'}:{})}});
      if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(typeof data.detail==='string'?data.detail:response.status===401?'Your sign-in expired. Sign in again.':'Your verifications could not load. Please try again.');}
      return response;
    }finally{clearTimeout(deadline);requests.delete(controller);}
  }
  async function thumbnails(state){
    const images=[...state.container.querySelectorAll('[data-verification-media],[data-verification-preview]')];let next=0;
    await Promise.all([0,1].map(async()=>{while(next<images.length){const image=images[next++];if(!valid(state)||document.hidden||knownOwner!==state.owner)return;try{
      const path=image.dataset.verificationPreview?API_BASE+image.dataset.verificationPreview:mediaBase+encodeURIComponent(image.dataset.verificationMedia);
      const blob=await(await ownerFetch(path,state.owner)).blob();if(!valid(state)||document.hidden||knownOwner!==state.owner)return;
      if(!/^image\//i.test(blob.type)||!blob.size)throw Error('Photo unavailable');const url=URL.createObjectURL(blob);state.urls.add(url);image.src=url;
    }catch{if(valid(state))image.alt='Listing photo unavailable';}}}));
  }
  function schedule(state){clearTimeout(state.timer);if(valid(state)&&!document.hidden)state.timer=setTimeout(()=>load(state),30000);}
  async function load(state,append=false){
    if(!valid(state)||document.hidden||state.loading)return;state.loading=true;const run=++state.run;
    try{
      const owner=await identity();if(!valid(state)||run!==state.run)return;
      if(!owner){state.owner=null;signIn(state);return;}state.owner=owner.owner;const generation=sequence;
      const query=new URLSearchParams({kind:state.kind,limit:'20'});if(append&&state.cursor)query.set('cursor',state.cursor);
      const data=await(await ownerFetch(base+'?'+query,state.owner)).json();if(!valid(state)||run!==state.run||generation!==sequence||knownOwner!==state.owner)return;
      if(!Array.isArray(data.items))throw Error('Your verifications could not load. Please try again.');
      state.items=append?[...state.items,...data.items.slice(0,20).filter(item=>!state.items.some(old=>old.id===item.id))]:data.items.slice(0,20);state.cursor=typeof data.next_cursor==='string'&&data.next_cursor.length<=2048?data.next_cursor:null;
      const fingerprint=JSON.stringify([state.items,state.cursor,data.unread_count]);if(fingerprint===state.fingerprint){schedule(state);return;}state.fingerprint=fingerprint;
      state.urls.forEach(url=>URL.revokeObjectURL(url));state.urls.clear();updateBadges(data.unread_count);
      shell(state,`<div class="va-account-bar"><span>${esc(owner.email)}</span>${badge(data.unread_count)}<button type="button" class="va-text" id="vaRefresh">Refresh</button></div>${tabs(state)}<div class="va-records">${state.items.length?state.items.map(card).join(''):`<div class="va-panel va-empty"><h2>No ${state.kind==='buyer'?'buyer requests':state.kind==='seller'?'seller verifications':'verifications'} yet.</h2><p>New checks created with this email will appear here.</p><div class="va-empty-actions"><a class="va-button" href="#in-hand${state.kind==='buyer'?'/buy':''}">${state.kind==='buyer'?'Request seller verification':'Verify your photos'}</a>${state.kind==='all'?'<a class="va-text" href="#in-hand/buy">Ask a seller for proof</a>':''}</div></div>`}</div>${state.cursor?'<button type="button" class="va-button va-secondary" id="vaMore">Load more</button>':''}<p class="va-note">Results belong to the signed-in email. Earlier checks created without an account stay on their original private links.</p>`);
      state.container.querySelector('#vaRefresh')?.addEventListener('click',()=>load(state));state.container.querySelector('#vaMore')?.addEventListener('click',()=>load(state,true));
      thumbnails(state);schedule(state);
    }catch(error){if(valid(state)&&run===state.run){shell(state,`${tabs(state)}<div class="va-panel" role="alert"><h2>Your verifications couldn’t load.</h2><p>${esc(error.name==='AbortError'?'The connection took too long. Try again.':error.message)}</p><button type="button" class="va-button" id="vaRetry">Try again</button></div>`);state.container.querySelector('#vaRetry')?.addEventListener('click',()=>load(state));}}
    finally{state.loading=false;}
  }
  function mount(container){
    stop();const kind=new URLSearchParams(location.hash.split('?')[1]||'').get('kind'),state={container,mode:'dashboard',hash:location.hash,kind:['buyer','seller'].includes(kind)?kind:'all',run:0,urls:new Set(),items:[],cursor:null,loading:false};active=state;
    shell(state,'<div class="va-panel" role="status">Loading your verifications…</div>');load(state);
  }
  async function guardReport(container,requestId,onReady){
    stop();const state={container,mode:'report',hash:location.hash,urls:new Set(),requestId};active=state;container.innerHTML='<div class="va-panel" role="status">Opening your private result…</div>';
    try{const owner=await identity();if(!valid(state))return;if(!owner){signIn(state,true);return;}state.owner=owner.owner;onReady(owner.owner);}
    catch(error){if(valid(state)){container.innerHTML=`<section class="va-account"><div class="va-panel" role="alert"><p>${esc(error.message)}</p><button class="va-button" id="vaReportRetry">Try again</button></div></section>`;container.querySelector('#vaReportRetry')?.addEventListener('click',()=>guardReport(container,requestId,onReady));}}
  }
  async function markViewed(rootId){
    const state=active;if(!state?.owner||!id(rootId))return;
    try{const data=await(await ownerFetch(base+'/'+encodeURIComponent(rootId)+'/read',state.owner,{method:'POST',body:'{}'})).json();if(valid(state)&&knownOwner===state.owner)updateBadges(data.unread_count);}catch{} // A read marker never blocks opening the result.
  }
  function decorate(){
    const links=document.querySelector('#lockxPublicHeader .lx-header-links');
    if(links&&!links.querySelector('[data-verification-account]')){const link=document.createElement('a');link.href='#in-hand/account';link.dataset.verificationAccount='';link.className='va-header-link';link.innerHTML='Your verifications <span data-verification-unread hidden></span>';links.append(link);}
    document.querySelectorAll('.lx-chapter-buyer .lx-chapter-inner,.lx-chapter-seller .lx-chapter-inner').forEach(chapter=>{if(chapter.querySelector('[data-verification-account]'))return;const link=document.createElement('a');link.href='#in-hand/account';link.dataset.verificationAccount='';link.className='va-text va-chapter-entry';link.textContent='Your verifications';chapter.append(link);});
    updateBadges(lastUnreadCount);
  }
  async function resumeReturn(){
    const query=new URLSearchParams(location.search||'');if(!query.has('verification_return'))return;
    const target=returnRoute(query.get('verification_return')),initialHash=location.hash;
    if(target){try{await identity();}catch{}} // Let the shared SDK consume an implicit auth fragment first.
    query.delete('verification_return');const search=query.toString();
    const authFragment=/^#(?:access_token=|error=|refresh_token=|token_type=)/.test(location.hash||'');
    const unchanged=location.hash===initialHash||authFragment||!location.hash;
    const next=target&&unchanged?target:authFragment?'':location.hash;
    history.replaceState(null,'',(location.pathname||'/')+(search?'?'+search:'')+next);
    if(target&&next===target)window.dispatchEvent(new Event('hashchange'));
  }
  window.addEventListener('hashchange',()=>{if(active&&active.hash!==location.hash)stop();});
  window.addEventListener('pagehide',stop);
  document.addEventListener('visibilitychange',()=>{if(!active)return;if(document.hidden){clearTimeout(active.timer);if(active.mode==='dashboard'){active.run++;active.loading=false;}for(const controller of requests)controller.abort();requests.clear();}else if(active.mode==='dashboard')load(active);});
  window.addEventListener('lockx-page',decorate);document.addEventListener('DOMContentLoaded',decorate,{once:true});
  window.LockXAccount={mount,guardReport,markViewed,isOwner:owner=>!!owner&&knownOwner===owner,decorate,stop};decorate();
  window.dispatchEvent(new Event('lockx-account-ready'));
  resumeReturn();
})();
