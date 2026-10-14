const API_BASE='https://lockx-production.up.railway.app/api/v1';
const SUPABASE_URL='https://vlxrryhfaaxjqyzhzhxg.supabase.co';
const SUPABASE_KEY='sb_publishable_7J4GYdd-XvtT0SJ-gOG0VQ_Py1qXP1o';
let cases=[], session=null, supabaseClient, authMode='signin';
function toast(t,m){const e=document.querySelector('#toast');if(!e)return;document.querySelector('#toastTitle').textContent=t;document.querySelector('#toastText').textContent=m;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3600)}
function caseNumber(c){return c.case_number||'LX-'+c.id.replace(/-/g,'').slice(-6).toUpperCase()}
function display(c){return {...c,name:c.brand+' '+(c.model||''),ref:c.reference||'REFERENCE PENDING',serial:c.serial_number||'NOT PROVIDED',status:c.status==='paused'?'Paused':'Monitoring'}}
function render(){const empty='<div class="empty-state"><strong>No recovery cases yet.</strong><p>Report a stolen watch to begin protected monitoring.</p></div>';const count=document.querySelector('#caseCount');if(count)count.textContent=String(cases.length).padStart(2,'0');const dash=document.querySelector('#dashCases'),cards=document.querySelector('#caseCards');if(dash)dash.innerHTML=cases.length?cases.slice(0,3).map(c=>'<div class="case-row"><span class="watch-thumb"></span><div class="case-copy"><strong>'+c.name+'</strong><p>'+c.ref+' · CASE '+caseNumber(c)+'</p></div><span class="state">'+c.status+'</span></div>').join(''):empty;if(cards)cards.innerHTML=cases.length?cases.map(c=>'<article class="case-card" data-edit-case="'+c.id+'" role="button" tabindex="0" aria-label="Edit '+c.name+'"><div class="card-img"></div><div class="card-body"><div class="case-meta"><span class="state">'+c.status+'</span></div><h2>'+c.name+'</h2><p>'+c.ref+' · CASE '+caseNumber(c)+'</p><div class="case-data"><span>Serial <strong>'+c.serial+'</strong></span></div></div><div class="case-footer"><span>Edit details or add photos</span><b>Edit →</b></div></article>').join(''):empty}
function go(page){document.querySelectorAll('.page,.nav-item').forEach(e=>e.classList.remove('active'));document.getElementById(page)?.classList.add('active');document.querySelector('.nav-item[data-page="'+page+'"]')?.classList.add('active');const name=document.querySelector('#pageName');if(name)name.textContent=({dashboard:'Overview',cases:'My cases',matches:'Potential matches',alerts:'Alerts',monitoring:'Monitoring',sources:'Sources'})[page]||'Overview'}
function authModal(){if(document.querySelector('#authModal'))return;document.body.insertAdjacentHTML('beforeend','<div class="modal-backdrop open" id="authModal"><form class="modal" id="authForm"><p class="eyebrow">LOCKX ACCOUNT</p><h2 id="authTitle">Secure your recovery workspace.</h2><p>Sign in to manage private recovery cases and alerts.</p><label>Email<input required type="email" name="email" placeholder="you@example.com" /></label><label>Password<input required minlength="8" type="password" name="password" placeholder="At least 8 characters" /></label><div class="modal-footer"><span>🔒 Your cases are visible only to you.</span><button class="primary-button" type="submit" id="authSubmit">Sign in <span>→</span></button></div><button type="button" class="text-button" id="authSwitch">Create an account instead</button></form></div>');document.querySelector('#authSwitch').onclick=()=>{authMode=authMode==='signin'?'signup':'signin';document.querySelector('#authTitle').textContent=authMode==='signin'?'Secure your recovery workspace.':'Create your LockX account.';document.querySelector('#authSubmit').innerHTML=authMode==='signin'?'Sign in <span>→</span>':'Create account <span>→</span>';document.querySelector('#authSwitch').textContent=authMode==='signin'?'Create an account instead':'Sign in instead'};document.querySelector('#authForm').onsubmit=signIn}
async function signIn(e){e.preventDefault();const d=new FormData(e.target),b=document.querySelector('#authSubmit');b.disabled=true;try{const r=authMode==='signin'?await supabaseClient.auth.signInWithPassword({email:d.get('email'),password:d.get('password')}):await supabaseClient.auth.signUp({email:d.get('email'),password:d.get('password'),options:{emailRedirectTo:location.origin}});if(r.error)throw r.error;if(!r.data.session){toast('Check your email','Confirm your email, then sign in.');return}session=r.data.session;document.querySelector('#authModal').classList.remove('open');await loadCases();toast('Welcome to LockX','Your private workspace is ready.')}catch(err){toast('Could not sign in',err.message||'Please try again.')}finally{b.disabled=false}}
async function resetExpiredSession(){session=null;try{await supabaseClient.auth.signOut()}catch{}authModal();toast('Sign in again','Your session expired. Please sign in to access your cases.')}
async function loadCases(){if(!session){cases=[];render();return}try{const r=await fetch(API_BASE+'/cases',{headers:{Authorization:'Bearer '+session.access_token}});if(r.status===401){await resetExpiredSession();return}if(!r.ok)throw Error();cases=(await r.json()).map(display)}catch{toast('Case service unavailable','Please try again shortly.')}render()}
async function init(){await new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';s.onload=ok;s.onerror=no;document.head.append(s)});supabaseClient=window.supabase.createClient(SUPABASE_URL,SUPABASE_KEY);session=(await supabaseClient.auth.getSession()).data.session;authModal();if(session){document.querySelector('#authModal').classList.remove('open');await loadCases()}else render();supabaseClient.auth.onAuthStateChange((_e,next)=>session=next)}
document.addEventListener('click',e=>{const p=e.target.closest('[data-page]');if(p)go(p.dataset.page);if(e.target.matches('#newCaseBtn,#newCaseBtn2'))session?document.querySelector('#caseModal').classList.add('open'):document.querySelector('#authModal').classList.add('open');if(e.target.dataset.close)document.getElementById(e.target.dataset.close)?.classList.remove('open');if(e.target.closest('.mobile-menu'))document.querySelector('.sidebar')?.classList.toggle('open')});
document.querySelector('#caseForm')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.target,d=new FormData(f),b=f.querySelector('[type="submit"]');b.disabled=true;try{const r=await fetch(API_BASE+'/cases',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.access_token},body:JSON.stringify({brand:d.get('brand'),model:d.get('model'),reference:d.get('reference')||null,serial_number:d.get('serial')||null,distinctive_details:d.get('details')||null})});if(!r.ok)throw Error();cases.unshift(display(await r.json()));render();f.reset();document.querySelector('#caseModal').classList.remove('open');go('cases');toast('Case created','Protected monitoring is ready.')}catch{toast('Unable to save case','Please try again.')}finally{b.disabled=false}});
init();

// PHOTO-UPLOAD-READY
const pz=document.querySelector('.upload-zone'),pi=document.createElement('input');pi.type='file';pi.accept='image/jpeg,image/png,image/heic,.heic';pi.multiple=true;pi.hidden=true;pz.append(pi);const pn=pz.querySelector('small');pz.querySelector('button').onclick=()=>pi.click();pi.onchange=()=>{let n=pi.files.length;pn.textContent=n?n+' photo'+(n>1?'s':'')+' selected · Private evidence upload':'JPG, PNG or HEIC · Up to 10 photos'};

let editingCaseId=null;function openCaseEditor(id){const c=cases.find(x=>x.id===id);if(!c)return;editingCaseId=id;const f=document.querySelector('#caseForm');f.brand.value=c.brand||'';f.model.value=c.model||'';f.reference.value=c.reference||'';f.serial.value=c.serial_number||'';f.details.value=c.distinctive_details||'';pi.value='';pn.textContent='JPG, PNG or HEIC · Up to 10 photos';document.querySelector('#caseEyebrow').textContent='EDIT RECOVERY CASE';document.querySelector('#modalTitle').textContent='Update this watch record.';document.querySelector('#caseModalDescription').textContent='Add details or more reference photos whenever you have them.';f.querySelector('[type="submit"]').innerHTML='Save changes <span>→</span>';document.querySelector('#caseModal').classList.add('open')}function openNewCase(){editingCaseId=null;const f=document.querySelector('#caseForm');f.reset();pi.value='';pn.textContent='JPG, PNG or HEIC · Up to 10 photos';document.querySelector('#caseEyebrow').textContent='NEW RECOVERY CASE';document.querySelector('#modalTitle').textContent='Tell us about the watch.';document.querySelector('#caseModalDescription').textContent='We’ll use these details to create its unique search profile.';f.querySelector('[type="submit"]').innerHTML='Create case <span>→</span>'}document.addEventListener('click',e=>{const card=e.target.closest('[data-edit-case]');if(card)openCaseEditor(card.dataset.editCase);if(e.target.matches('#newCaseBtn,#newCaseBtn2'))openNewCase()});document.querySelector('#caseForm').addEventListener('submit',async e=>{e.preventDefault();e.stopImmediatePropagation();let f=e.target,d=new FormData(f),b=f.querySelector('[type="submit"]'),a=[...pi.files];if(!session){authModal();toast('Sign in required','Create or sign in to your LockX account before saving a case.');return}if(a.length>10)return toast('Too many photos','Choose no more than 10 photos.');b.disabled=true;try{const payload={brand:d.get('brand'),model:d.get('model'),reference:d.get('reference')||null,serial_number:d.get('serial')||null,distinctive_details:d.get('details')||null};let r=await fetch(API_BASE+'/cases'+(editingCaseId?'/'+editingCaseId:''),{method:editingCaseId?'PATCH':'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.access_token},body:JSON.stringify(payload)});if(!r.ok)throw Error();let c=await r.json();for(let x of a){let q=new FormData();q.append('photo',x);b.textContent='Uploading reference photos…';let u=await fetch(API_BASE+'/cases/'+c.id+'/photos',{method:'POST',headers:{Authorization:'Bearer '+session.access_token},body:q});if(!u.ok)throw Error()}c=display(c);cases=[c,...cases.filter(x=>x.id!==c.id)];render();document.querySelector('#caseModal').classList.remove('open');go('cases');toast(editingCaseId?'Case updated':'Case created',a.length?'Reference photos were stored privately.':'Protected monitoring is ready.');editingCaseId=null;openNewCase()}catch{toast('Unable to save case','Your case details or photo could not be saved.')}finally{b.disabled=false;b.innerHTML=editingCaseId?'Save changes <span>→</span>':'Create case <span>→</span>'}},true);

const caseFormEyebrow=document.querySelector('#caseForm .eyebrow'),caseFormDescription=document.querySelector('#modalTitle').nextElementSibling;if(caseFormEyebrow)caseFormEyebrow.id='caseEyebrow';if(caseFormDescription)caseFormDescription.id='caseModalDescription';


function addDeleteControls(){document.querySelectorAll('#caseCards [data-edit-case]').forEach(card=>{if(card.querySelector('[data-delete-case]'))return;const c=cases.find(x=>x.id===card.dataset.editCase),footer=card.querySelector('.case-footer');if(!c||!footer)return;const button=document.createElement('button');button.type='button';button.dataset.deleteCase=c.id;button.textContent='Delete';button.setAttribute('aria-label','Delete '+c.name);button.style.cssText='margin-left:auto;margin-right:14px;border:0;background:transparent;padding:3px 0;color:#a74e3b;font:500 10px DM Sans,sans-serif;cursor:pointer';button.onclick=async event=>{event.preventDefault();event.stopPropagation();if(!confirm('Delete '+c.name+'? This permanently removes the case and its private reference photos.'))return;button.disabled=true;button.textContent='Deleting…';try{const response=await fetch(API_BASE+'/cases/'+c.id+'/delete',{method:'POST',headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)throw Error();cases=cases.filter(x=>x.id!==c.id);render();toast('Case deleted','The case and its private reference photos were removed.')}catch{button.disabled=false;button.textContent='Delete';toast('Unable to delete case','Please try again shortly.')}};footer.insertBefore(button,footer.querySelector('b'))})}
new MutationObserver(addDeleteControls).observe(document.querySelector('#caseCards'),{childList:true});addDeleteControls();


const renderCaseCards=render;const referencePhotoCache=new Map();
async function showReferencePhotos(){if(!session)return;await Promise.all(cases.map(async c=>{try{let response=await fetch(API_BASE+'/cases/'+c.id+'/photos',{headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)return;let photos=await response.json();referencePhotoCache.set(c.id,photos);let card=document.querySelector('#caseCards [data-edit-case="'+c.id+'"]');if(!card)return;let image=card.querySelector('.card-img');if(photos[0]?.url){image.style.backgroundImage='linear-gradient(#14252a22,#14252a22),url("'+photos[0].url+'")';image.style.backgroundSize='cover';image.style.backgroundPosition='center';image.style.backgroundColor='#243630'}let footer=card.querySelector('.case-footer span');if(footer)footer.textContent=photos.length+' reference photo'+(photos.length===1?'':'s')+' secured'}catch{}}))}
render=function(){renderCaseCards();showReferencePhotos()};showReferencePhotos();


async function refreshReferencePhotoPreviews(){if(!session)return;await Promise.all(cases.map(async c=>{try{const response=await fetch(API_BASE+'/cases/'+c.id+'/photos',{headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)return;const photos=await response.json(),card=document.querySelector('#caseCards [data-edit-case="'+c.id+'"]');if(!card)return;const image=card.querySelector('.card-img');if(photos[0]?.url){let preview=image.querySelector('img[data-reference-preview]');if(!preview){preview=document.createElement('img');preview.dataset.referencePreview='true';preview.alt='Reference photo for '+c.name;preview.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:2;display:block;background:#243630';image.append(preview)}preview.src=photos[0].url}const footer=card.querySelector('.case-footer span');if(footer)footer.textContent=photos.length+' reference photo'+(photos.length===1?'':'s')+' secured'}catch{}}))}
const renderWithReferencePhotoPreviews=render;render=function(){renderWithReferencePhotoPreviews();refreshReferencePhotoPreviews()};refreshReferencePhotoPreviews();


let editingPhotoCount=0;
function ensureReferenceGallery(){let gallery=document.querySelector('#referenceGallery');if(gallery)return gallery;gallery=document.createElement('div');gallery.id='referenceGallery';gallery.setAttribute('aria-live','polite');gallery.style.cssText='display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 2px';pz.insertAdjacentElement('afterend',gallery);return gallery}
function renderReferenceGallery(photos){const gallery=ensureReferenceGallery();gallery.replaceChildren();editingPhotoCount=photos.length;pn.textContent=editingCaseId?photos.length+'/10 saved · Select more to add':'JPG, PNG or HEIC · Up to 10 photos';photos.forEach(photo=>{const tile=document.createElement('figure');tile.style.cssText='position:relative;width:104px;height:82px;margin:0;border:1px solid #d7ddd8;border-radius:6px;overflow:hidden;background:#f4f6f4';const image=document.createElement('img');image.src=photo.url;image.alt='Saved reference photo';image.style.cssText='width:100%;height:100%;display:block;object-fit:cover';const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove reference photo');remove.style.cssText='position:absolute;top:4px;right:4px;width:24px;height:24px;border:0;border-radius:50%;background:#351b18e8;color:#fff;font:20px/20px sans-serif;cursor:pointer';remove.onclick=async event=>{event.preventDefault();event.stopPropagation();if(!confirm('Remove this reference photo? This permanently deletes it from this recovery case.'))return;remove.disabled=true;try{const response=await fetch(API_BASE+'/cases/'+editingCaseId+'/photos/'+photo.id+'/delete',{method:'POST',headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)throw Error();await loadReferenceGallery(editingCaseId);refreshReferencePhotoPreviews();toast('Reference photo removed','The photo was permanently removed from this case.')}catch{remove.disabled=false;toast('Unable to remove photo','Please try again shortly.')}};tile.append(image,remove);gallery.append(tile)});if(editingCaseId&&photos.length<10){const note=document.createElement('div');note.textContent=(10-photos.length)+' more photo'+(photos.length===9?'':'s')+' can be added';note.style.cssText='align-self:center;color:#758078;font:11px DM Sans,sans-serif';gallery.append(note)}}
async function loadReferenceGallery(caseId){if(!session||!caseId)return;const gallery=ensureReferenceGallery();gallery.textContent='Loading saved reference photos…';gallery.style.cssText='display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 2px;color:#758078;font:11px DM Sans,sans-serif';try{const response=await fetch(API_BASE+'/cases/'+caseId+'/photos',{headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)throw Error();renderReferenceGallery(await response.json())}catch{gallery.textContent='Saved reference photos are temporarily unavailable.'}}
const openCaseEditorWithGallery=openCaseEditor;openCaseEditor=function(id){openCaseEditorWithGallery(id);loadReferenceGallery(id)};
const openNewCaseWithGallery=openNewCase;openNewCase=function(){openNewCaseWithGallery();editingPhotoCount=0;const gallery=ensureReferenceGallery();gallery.replaceChildren();gallery.style.cssText='display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 2px'};
pi.onchange=()=>{const selected=[...pi.files];if(selected.length+editingPhotoCount>10){pi.value='';toast('Too many photos','A recovery case can contain up to 10 reference photos.');return}pn.textContent=selected.length?editingPhotoCount+' saved · '+selected.length+' photo'+(selected.length===1?'':'s')+' ready to add':(editingCaseId?editingPhotoCount+'/10 saved · Select more to add':'JPG, PNG or HEIC · Up to 10 photos')};


function removeExternalCaseDeleteControls(){document.querySelectorAll('#caseCards [data-delete-case]').forEach(button=>button.remove())}
const renderWithoutExternalCaseDelete=render;render=function(){renderWithoutExternalCaseDelete();removeExternalCaseDeleteControls()};removeExternalCaseDeleteControls();new MutationObserver(removeExternalCaseDeleteControls).observe(document.querySelector('#caseCards'),{childList:true,subtree:true});
function ensureCaseDeleteInEditor(){let button=document.querySelector('#deleteCaseInEditor');if(button)return button;button=document.createElement('button');button.id='deleteCaseInEditor';button.type='button';button.textContent='Delete this case';button.style.cssText='display:block;margin-top:14px;border:0;background:transparent;padding:4px 0;color:#a74e3b;font:600 12px DM Sans,sans-serif;cursor:pointer';button.onclick=async()=>{const currentCase=cases.find(item=>item.id===editingCaseId);if(!currentCase)return;if(!confirm('Delete '+currentCase.name+'? This permanently removes the case and its private reference photos.'))return;button.disabled=true;button.textContent='Deleting…';try{const response=await fetch(API_BASE+'/cases/'+currentCase.id+'/delete',{method:'POST',headers:{Authorization:'Bearer '+session.access_token}});if(!response.ok)throw Error();cases=cases.filter(item=>item.id!==currentCase.id);render();document.querySelector('#caseModal').classList.remove('open');editingCaseId=null;openNewCase();go('cases');toast('Case deleted','The case and its private reference photos were removed.')}catch{button.disabled=false;button.textContent='Delete this case';toast('Unable to delete case','Please try again shortly.')}};document.querySelector('#caseForm .modal-footer').insertAdjacentElement('afterend',button);return button}
const openCaseEditorWithDeleteInEditor=openCaseEditor;openCaseEditor=function(id){openCaseEditorWithDeleteInEditor(id);const button=ensureCaseDeleteInEditor();button.hidden=false;button.disabled=false;button.textContent='Delete this case'};
const openNewCaseWithDeleteInEditor=openNewCase;openNewCase=function(){openNewCaseWithDeleteInEditor();const button=ensureCaseDeleteInEditor();button.hidden=true;button.disabled=false;button.textContent='Delete this case'};


// OVERVIEW-CASE-PHOTOS: use signed, private reference-photo previews on the
// dashboard and make each active-case row open its editable recovery record.
const renderWithCaseEditorDelete=render;
function wireOverviewCaseRows(){
 const rows=[...document.querySelectorAll('#dashCases .case-row')];
 rows.forEach((row,index)=>{
  const recoveryCase=cases[index];
  if(!recoveryCase)return;
  row.dataset.editCase=recoveryCase.id;
  row.setAttribute('role','button');
  row.setAttribute('tabindex','0');
  row.setAttribute('aria-label','Open '+recoveryCase.name);
  row.style.cursor='pointer';
  if(!row.querySelector('.case-arrow'))row.insertAdjacentHTML('beforeend','<span class="case-arrow" aria-hidden="true">→</span>');
 });
}
async function refreshOverviewReferencePhotos(){
 if(!session)return;
 await Promise.all(cases.slice(0,3).map(async recoveryCase=>{
  try{
   let photos=referencePhotoCache.get(recoveryCase.id);
   if(!photos){
    const response=await fetch(API_BASE+'/cases/'+recoveryCase.id+'/photos',{headers:{Authorization:'Bearer '+session.access_token}});
    if(!response.ok)return;
    photos=await response.json();
    referencePhotoCache.set(recoveryCase.id,photos);
   }
   const thumbnail=document.querySelector('#dashCases [data-edit-case="'+recoveryCase.id+'"] .watch-thumb');
   if(!thumbnail||!photos[0]?.url)return;
   let image=thumbnail.querySelector('img[data-overview-reference-preview]');
   if(!image){
    image=document.createElement('img');
    image.dataset.overviewReferencePreview='true';
    image.alt='Reference photo for '+recoveryCase.name;
    image.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:2;display:block';
    thumbnail.append(image);
   }
   image.src=photos[0].url;
   thumbnail.classList.add('has-reference');
  }catch{}
 }));
}
render=function(){renderWithCaseEditorDelete();wireOverviewCaseRows();refreshOverviewReferencePhotos()};
document.addEventListener('keydown',event=>{
 const row=event.target.closest('#dashCases [data-edit-case]');
 if(row&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openCaseEditor(row.dataset.editCase)}
});
wireOverviewCaseRows();refreshOverviewReferencePhotos();

// MARKETPLACE-NETWORK: approved-source status, scan jobs, and reviewable
// candidates. No marketplace is queried unless its official credentials exist.
const marketplaceEscape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const marketplaceHeaders=()=>({Authorization:'Bearer '+session.access_token});
let marketplaceSources=[];
function sourceState(source){return source.configured?'Connected':source.status.replaceAll('_',' ')}
function renderSources(sources){
 const grid=document.querySelector('#sourceGrid');if(!grid)return;
 grid.innerHTML=sources.map(source=>'<article class="source"><div class="source-top"><span class="source-logo">'+marketplaceEscape(source.name.slice(0,2).toUpperCase())+'</span><span class="state '+(source.configured?'':'paused')+'">'+marketplaceEscape(sourceState(source))+'</span></div><h2>'+marketplaceEscape(source.name)+'</h2><p>'+marketplaceEscape(source.description)+'</p><div class="source-footer"><small>'+marketplaceEscape(source.access.replaceAll('_',' '))+'</small><small class="'+(source.configured?'':'wait')+'">'+(source.configured?'Scanning':'Access required')+'</small></div></article>').join('');
}
function renderMarketplaceMatches(matches){
 const table=document.querySelector('#matchTable'),preview=document.querySelector('#dashMatches');
 const empty='<div class="empty-state"><strong>No approved-source candidates yet.</strong><p>New candidates will appear after a configured marketplace scan.</p></div>';
 if(table)table.innerHTML=matches.length?'<div class="match-head"><span>Candidate</span><span>Source</span><span>Confidence</span><span>Evidence</span><span></span></div>'+matches.map(match=>'<article class="match-row"><div class="match-item"><div class="listing-image"></div><div class="match-title"><strong>'+marketplaceEscape(match.title)+'</strong><p>'+marketplaceEscape(match.location||'Location unavailable')+(match.price?' · '+marketplaceEscape(match.price)+' '+marketplaceEscape(match.currency||''):'')+'</p></div></div><div class="source-label">'+marketplaceEscape(match.connector_key.replaceAll('_',' '))+'<small>'+marketplaceEscape(match.visual_status.replaceAll('_',' '))+'</small></div><strong class="confidence '+(match.confidence>=.8?'high':'')+'">'+Math.round(Number(match.confidence)*100)+'%</strong><small title="SHA-256 evidence digest">SHA-256 ✓</small><a class="text-button" href="'+marketplaceEscape(match.listing_url)+'" target="_blank" rel="noreferrer">Review →</a></article>').join(''):empty;
 if(preview)preview.innerHTML=matches.slice(0,2).map(match=>'<div class="mini-match"><div class="listing-image"></div><div><strong>'+marketplaceEscape(match.title)+'</strong><p>'+marketplaceEscape(match.connector_key.replaceAll('_',' '))+' · '+Math.round(Number(match.confidence)*100)+'% confidence</p></div><a class="confidence" href="'+marketplaceEscape(match.listing_url)+'" target="_blank" rel="noreferrer">Review →</a></div>').join('')||empty;
}
function renderScanTimeline(scans){const timeline=document.querySelector('#timeline');if(!timeline)return;timeline.innerHTML=scans.length?scans.slice(0,5).map(scan=>'<div class="timeline-event"><p><strong>'+marketplaceEscape(scan.status.replaceAll('_',' '))+'</strong><br />'+marketplaceEscape((scan.configured_sources||[]).join(', ')||'No approved connector configured')+'</p><small>'+marketplaceEscape(scan.requested_at||'just now')+'</small></div>').join(''):'<div class="timeline-event"><p><strong>Ready for approved sources</strong><br />Add marketplace credentials or an authorized feed to begin monitoring.</p></div>'}
async function loadMarketplaceNetwork(){
 try{const sourceResponse=await fetch(API_BASE+'/sources');if(sourceResponse.ok){marketplaceSources=await sourceResponse.json();renderSources(marketplaceSources)}
  if(!session)return;
  const matchResponse=await fetch(API_BASE+'/matches',{headers:marketplaceHeaders()});if(matchResponse.ok)renderMarketplaceMatches(await matchResponse.json());
  const scanResponses=await Promise.all(cases.slice(0,3).map(recoveryCase=>fetch(API_BASE+'/cases/'+recoveryCase.id+'/scans',{headers:marketplaceHeaders()})));
  const scans=(await Promise.all(scanResponses.filter(response=>response.ok).map(response=>response.json()))).flat().sort((a,b)=>String(b.requested_at).localeCompare(String(a.requested_at)));renderScanTimeline(scans);
 }catch{}
}
const loadCasesWithMarketplaceNetwork=loadCases;loadCases=async function(){await loadCasesWithMarketplaceNetwork();loadMarketplaceNetwork()};
const goWithMarketplaceNetwork=go;go=function(page){goWithMarketplaceNetwork(page);if(['sources','matches','monitoring'].includes(page))loadMarketplaceNetwork()};
document.querySelector('#runScan')?.addEventListener('click',async()=>{
 if(!session){authModal();toast('Sign in required','Sign in before starting a compliant marketplace scan.');return}
 if(!cases.length){toast('No recovery cases','Create a recovery case before starting a scan.');return}
 const button=document.querySelector('#runScan');button.disabled=true;
 try{const responses=await Promise.all(cases.filter(recoveryCase=>recoveryCase.status!=='Paused').map(recoveryCase=>fetch(API_BASE+'/cases/'+recoveryCase.id+'/scan',{method:'POST',headers:marketplaceHeaders()})));
 const jobs=await Promise.all(responses.map(response=>response.ok?response.json():Promise.reject()));
 const queued=jobs.filter(job=>job.status==='queued').length;
 toast(queued?'Approved scan queued':'Source access required',queued?'LockX is checking configured official connectors.':'No marketplace credentials are connected yet. Your case data was not sent to any marketplace.');loadMarketplaceNetwork();
 }catch{toast('Unable to start scan','Please try again shortly.')}finally{button.disabled=false}
});
loadMarketplaceNetwork();
