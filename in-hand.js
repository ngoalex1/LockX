/* Browser capture is evidence, not hardware attestation or product authentication. */
(() => {
  'use strict';
  const base = API_BASE + '/in-hand';
  const $ = (s, p = document) => p.querySelector(s);
  const $$ = (s, p = document) => [...p.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = t => t ? new Date(t * 1000).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'}) : 'Not recorded';
  const labels = {waiting:'Awaiting capture',capturing:'Capture started',processing:'Comparing evidence',confirmed:'In-hand confirmed',mismatch:'Mismatch found',inconclusive:'More evidence needed',expired:'Link expired'};
  const scope = 'This records a visual match at the capture time. It does not certify product authenticity, ownership, current possession, ticket validity, or delivery.';
  let photos = [], draft = {}, capabilities = null, routeNumber = 0, poll = null, reportURLs = [], capture = null, sellerData = null, sellerToken = null, isStandalone = false;
  let managementKey = '', reportRenderNumber = 0;
  const reportMedia = new Map();
  const secretPattern = /^[A-Za-z0-9_-]{43}$/;
  let browserAccess;
  try { browserAccess = JSON.parse(localStorage.getItem('lockx-in-hand-access') || 'null'); } catch {}
  if(!secretPattern.test(browserAccess?.key||''))browserAccess={key:btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''),records:{}};
  if(!browserAccess.records||typeof browserAccess.records!=='object'||Array.isArray(browserAccess.records))browserAccess.records={};
  function saveAccess(){try{localStorage.setItem('lockx-in-hand-access',JSON.stringify(browserAccess));}catch{}}
  saveAccess();
  function remember(id,key){if(secretPattern.test(key||'')){browserAccess.records[id]=key;saveAccess();}}
  const page = document.createElement('section');
  page.id = 'in-hand'; page.className = 'page ih-page';
  $('main').append(page);
  document.body.insertAdjacentHTML('beforeend', '<section id="ihStandalone" aria-label="LockX mobile verification"></section>');
  const standalone = $('#ihStandalone');
  function heading() {
    return `<div class="ih-hero"><div><span class="ih-kicker">Service 03 · Photo-to-item verification</span><h1>The photos. The item.<br>The same story.</h1><p class="ih-lead">Connect listing photos to the item on hand. A guided camera check, a photo-by-photo result, and a record buyers can open.</p><div class="ih-pills"><span>No login or app needed</span><span>Guided camera capture</span><span>Shareable verified photos</span></div></div><div class="ih-flow-preview" aria-hidden="true"><div class="ih-preview-photos">${[1,2,3,4].map(i=>`<span class="ih-preview-photo">PHOTO ${i}</span>`).join('')}</div><span class="ih-preview-arrow">→</span><div class="ih-preview-record"><span class="ih-seal">✓</span><strong>One item.<br>A verified photo set.</strong><small>Every marking links back<br>to its LockX record.</small></div></div></div>`;
  }
  const notice = (text, type = '') => `<div class="ih-note ${type}" role="status">${esc(text)}</div>`;
  function shell(content) {
    standalone.innerHTML = `<header class="ih-standalone-head"><a class="ih-wordmark" href="#in-hand" aria-label="LockX home">lock<span>x</span></a><small>In-hand verification</small></header>${content}`;
  }
  async function api(path, options = {}, auth = false) {
    const headers = new Headers(options.headers || {});
    if (auth) {
      if(managementKey)headers.set('X-LockX-Manage-Key',managementKey);
      else headers.set('X-LockX-Guest-Key',browserAccess.key);
    }
    const r = await fetch(base + path, {...options, headers});
    if (!r.ok) {
      let message = 'The request could not be completed. Please try again.';
      try { const body = await r.json(); if (typeof body.detail === 'string') message = body.detail; } catch {}
      const error = Error(message); error.status = r.status; throw error;
    }
    return r;
  }
  async function json(path, data, auth = false, method = 'POST') {
    return (await api(path, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}, auth)).json();
  }
  function errorAt(id, error) { const e = $(id); if (e) { e.hidden = false; e.className = 'ih-note error'; e.textContent = error.message || String(error); } }
  async function copy(text, button) {
    try { await navigator.clipboard.writeText(text); const old = button.textContent; button.textContent = 'Copied'; setTimeout(()=>button.textContent=old,2000); }
    catch { toast('Copy the link', 'Select the link above and copy it using your phone’s controls.'); }
  }
  function appLink(path) { return location.origin + location.pathname + '#in-hand/' + path; }
  function reportPath(record){const key=managementKey||browserAccess.records[record.id];return 'report/'+record.id+(secretPattern.test(key||'')?'/'+key:'');}
  function managementBox(record){const key=managementKey||browserAccess.records[record.id];if(!secretPattern.test(key||''))return '';const link=appLink(reportPath(record));return `<div class="ih-link-box"><label>Private management link<input readonly value="${esc(link)}" aria-label="Private management link"></label><button type="button" class="ih-button secondary" data-copy="${esc(link)}">Copy private results link</button><p style="font-size:11px;color:#819073;margin-bottom:0">Keep this link to view your results, download approved photos, and control publication without an account. Anyone with it can manage this photo set. Keep it private.</p></div>`;}
  function revokeReports() { reportURLs.forEach(URL.revokeObjectURL); reportURLs = []; reportMedia.clear(); }
  async function privateURL(id) {
    if(reportMedia.has(id))return reportMedia.get(id);
    const route=routeNumber,pending=(async()=>{const blob=await(await api('/media/'+id,{},true)).blob();if(route!==routeNumber)throw Error('Inspection changed.');const url=URL.createObjectURL(blob);reportURLs.push(url);return url;})();
    reportMedia.set(id,pending);
    try{return await pending;}catch(error){if(reportMedia.get(id)===pending)reportMedia.delete(id);throw error;}
  }
  function reportFingerprint(record){return JSON.stringify([record.status,record.analysis_status,record.submitted,record.media.map(m=>[m.id,m.role,m.sha256]),record.publication]);}
  function pollReport(id,route,record,delay=1800){
    clearTimeout(poll);if(record.status!=='processing'||route!==routeNumber)return;const render=reportRenderNumber;
    poll=setTimeout(async()=>{
      if(route!==routeNumber||render!==reportRenderNumber)return;
      if(document.hidden){pollReport(id,route,record);return;}
      try{
        const next=await(await api('/requests/'+encodeURIComponent(id),{},true)).json();if(route!==routeNumber||render!==reportRenderNumber)return;
        if(reportFingerprint(next)!==reportFingerprint(record))await showReport(id,route,next);
        else pollReport(id,route,next);
      }catch{if(route===routeNumber&&render===reportRenderNumber)pollReport(id,route,record,5000);}
    },delay);
  }
  function showHome() {
    page.innerHTML = `${heading()}<div class="ih-layout"><div><form id="ihRequestForm" class="ih-card"><div class="ih-card-top"><span class="ih-step-number">01</span><div><h2>Choose the photos to verify.</h2><p>Four views tell a good story. Select up to six.</p></div></div><label>Item name<input name="title" required maxlength="160" placeholder="e.g. Pokémon Charizard card · 1999" autocomplete="off"></label><div class="ih-fields"><label>Category<input name="category" maxlength="80" placeholder="Cards, electronics, appliances…" value="Other"></label><label>How can it be shown?<select name="capture_mode"><option value="handheld">Hold and turn the item</option><option value="flat">Card, paper, or flat item</option><option value="stationary">Move the phone around a large item</option><option value="digital">Digital ticket · visible details only</option></select></label></div><div id="ihDigitalNote" class="ih-note warning" hidden>A screen recording cannot establish ticket validity or exclusive transfer rights. Digital tickets receive a limited evidence report and cannot earn the physical-item marking.</div><label>Listing description <small>Optional</small><textarea name="description" maxlength="6000" placeholder="Paste what the listing says. LockX will also assess which claims the camera can support."></textarea></label><label>Distinguishing details <small>Optional</small><input name="details" maxlength="1200" placeholder="Wear, markings, identifiers, included accessories…"></label><div class="ih-upload"><button type="button" class="ih-button secondary" id="ihChoosePhotos">＋ Add listing photos</button><input id="ihPhotoInput" type="file" accept="image/*" multiple hidden><p>Up to 6 selected photos · Photos are resized before upload.</p></div><div id="ihPhotoGrid" class="ih-photo-grid"></div><div id="ihPhotoError" class="ih-note error" role="alert" hidden></div><label class="ih-check"><input type="checkbox" name="consent" required><span>I have permission to submit these photos and process the item recording. Photos remain private until I choose to publish a confirmed set.</span></label><div id="ihCreateError" class="ih-note error" role="alert" hidden></div><div class="ih-form-footer"><small>No login needed to create a check or view your results. The camera link lasts 24 hours.</small><button class="ih-button" type="submit" id="ihCreate">Create mobile link <span>→</span></button></div><div id="ihCreated"></div></form></div><aside class="ih-aside ih-card"><h3>From listing to confidence.</h3><ol><li><strong>Select the exact photos</strong>Keep a record of the images and description you want checked.</li><li><strong>Open the link on a phone</strong>Follow a short automatic scan. Clear views are collected as you turn the item and show identifying details.</li><li><strong>Compare every selected view</strong>Each photo needs evidence from the capture. Unclear results stay unverified.</li><li><strong>Share a confirmed set</strong>Download QR-marked photos linked to a public LockX record.</li></ol><div class="ih-note">${esc(scope)}</div></aside></div><div class="ih-section-title"><h2>Your inspections on this browser</h2><button class="ih-button text" id="ihRefresh">Refresh ↻</button></div><div id="ihRequests" aria-live="polite"></div>`;
    $('.ih-hero').insertAdjacentHTML('afterend','<div id="ihServiceState" class="ih-note warning" style="margin-bottom:22px" hidden></div>');
    serviceState();
    $('#ihChoosePhotos').onclick = () => $('#ihPhotoInput').click();
    $('#ihPhotoInput').onchange = addPhotos;
    $('#ihRequestForm [name=capture_mode]').onchange = e => $('#ihDigitalNote').hidden = e.target.value !== 'digital';
    $('#ihRequestForm').onsubmit = createRequest;
    for(const [key,value] of Object.entries(draft)){const input=$(`#ihRequestForm [name="${key}"]`);if(input&&input.type!=='checkbox')input.value=value;}
    $('#ihRequestForm').addEventListener('input',e=>{if(e.target.name&&e.target.type!=='checkbox')draft[e.target.name]=e.target.value;});
    $('#ihDigitalNote').hidden=$('#ihRequestForm [name=capture_mode]').value!=='digital';
    $('#ihRefresh').onclick = loadRequests;
    renderPhotos(); loadRequests();
  }
  function serviceState() {
    const el=$('#ihServiceState');if(!el)return;
    if(window.LOCKX_LOCAL_PREVIEW){el.hidden=false;el.textContent='Local preview: links work on this computer. A deployed HTTPS site is needed for another phone. Automated comparison is disabled here, so preview captures cannot earn verified markings.';}
    else if(capabilities&&!capabilities.visual_comparison_ready){el.hidden=false;el.textContent='Automated comparison is currently unavailable. You can collect camera evidence, but a verified marking cannot be issued until comparison is available.';}
  }
  async function compressPhoto(file) {
    if (file.size > 25 * 1024 * 1024) throw Error('Choose an image under 25 MB.');
    const sourceURL = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = sourceURL;
      await image.decode();
      if (!image.naturalWidth || image.naturalWidth * image.naturalHeight > 80_000_000) throw Error('This image is too large. Export a smaller copy.');
      const ratio = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio)); canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0,0,canvas.width,canvas.height); ctx.drawImage(image,0,0,canvas.width,canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/jpeg',.86));
      if (!blob || blob.size > 5 * 1024 * 1024) throw Error('This image could not be resized. Try a JPEG or PNG copy.');
      canvas.width = canvas.height = 1;
      return {blob, url:URL.createObjectURL(blob), selected:true, note:''};
    } catch (error) { throw Error(error.message?.includes('image') ? error.message : 'This photo format cannot be opened here. Try a JPEG or PNG copy.'); }
    finally { URL.revokeObjectURL(sourceURL); }
  }
  async function addPhotos(e) {
    const files = [...e.target.files]; e.target.value = '';
    const button = $('#ihChoosePhotos'); button.disabled = true; button.textContent = 'Preparing photos…';
    $('#ihPhotoError').hidden = true;
    try {
      if (photos.length + files.length > 6) throw Error('Keep up to six photos. Remove a photo before adding another.');
      for (const file of files) { photos.push(await compressPhoto(file)); renderPhotos(); }
    } catch (error) { errorAt('#ihPhotoError',error); }
    finally { button.disabled = false; button.textContent = '＋ Add listing photos'; }
  }
  function renderPhotos() {
    const grid = $('#ihPhotoGrid'); if (!grid) return;
    grid.innerHTML = photos.map((p,i)=>`<div class="ih-photo-tile"><img src="${p.url}" alt="Selected reference photo ${i+1}"><button type="button" class="ih-remove" data-remove="${i}" aria-label="Remove photo ${i+1}">×</button><div class="ih-photo-meta"><label><input type="checkbox" data-select="${i}" ${p.selected?'checked':''}>Photo ${i+1}</label><input data-note="${i}" maxlength="350" value="${esc(p.note)}" aria-label="Detail to check in photo ${i+1}" placeholder="Detail to check (optional)"></div></div>`).join('');
    grid.onclick = e => { const remove = e.target.closest('[data-remove]'); if (remove) { const p = photos.splice(Number(remove.dataset.remove),1)[0]; URL.revokeObjectURL(p.url); renderPhotos(); } };
    grid.oninput = e => { if (e.target.dataset.select !== undefined) photos[Number(e.target.dataset.select)].selected = e.target.checked; if (e.target.dataset.note !== undefined) photos[Number(e.target.dataset.note)].note = e.target.value; };
  }
  async function createRequest(e) {
    e.preventDefault();
    const selected = photos.filter(p=>p.selected), button = $('#ihCreate');
    if (!selected.length) { errorAt('#ihCreateError',Error('Select at least one photo to verify.')); return; }
    button.disabled = true; button.textContent = 'Creating your link…'; $('#ihCreateError').hidden = true;
    try {
      const fields = new FormData(e.target), payload = Object.fromEntries(['title','category','capture_mode','description','details'].map(k=>[k,fields.get(k)]));
      payload.consent = true; payload.photo_notes = selected.map(p=>p.note);
      const body = new FormData(); body.append('payload',JSON.stringify(payload)); selected.forEach((p,i)=>body.append('photos',p.blob,`reference-${i+1}.jpg`));
      const record = await (await api('/requests',{method:'POST',body},true)).json();
      remember(record.id,record.manage_key);
      $('#ihCreated').innerHTML = linkBox(record)+managementBox(record);
      bindLinkButtons($('#ihCreated')); loadRequests();
      $('#ihCreated').scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch (error) { errorAt('#ihCreateError',error); }
    finally { button.disabled = false; button.innerHTML = 'Create mobile link <span>→</span>'; }
  }
  function linkBox(record) {
    const link = appLink('capture/' + record.token);
    return `<div class="ih-link-box"><label>Private mobile capture link<input readonly value="${esc(link)}" aria-label="Private capture link"></label><div class="ih-link-actions"><button type="button" class="ih-button secondary" data-copy="${esc(link)}">Copy link</button>${navigator.share?`<button type="button" class="ih-button secondary" data-share="${esc(link)}">Share to phone</button>`:''}<a class="ih-button" href="#in-hand/capture/${esc(record.token)}">Open camera check →</a></div><p style="font-size:11px;color:#819073;margin-bottom:0">Expires ${esc(date(record.expires))}. Anyone with this link can submit the capture. Share it only with the person holding the item.</p></div>`;
  }
  function bindLinkButtons(element) {
    element.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>copy(b.dataset.copy,b));
    element.querySelectorAll('[data-share]').forEach(b=>b.onclick=async()=>{try{await navigator.share({title:'LockX camera check',url:b.dataset.share});}catch(error){if(error.name!=='AbortError')toast('Share unavailable','Copy the link instead.');}});
  }
  async function loadRequests() {
    const container = $('#ihRequests'); if (!container) return;
    container.textContent = 'Loading your inspections…';
    try {
      const records = await (await api('/requests',{},true)).json();
      if (!container.isConnected) return;
      container.innerHTML = records.length ? records.map(r=>`<article class="ih-request"><div><strong>${esc(r.title)}</strong><small>${r.media.filter(m=>m.role==='listing').length} selected photos · ${esc(date(r.created))}</small></div><div class="ih-request-actions"><span class="ih-status ${esc(r.status)}">${esc(labels[r.status]||r.status)}</span><a class="ih-button text" href="#in-hand/${esc(reportPath(r))}">View record →</a></div></article>`).join('') : '<div class="ih-empty">Your first photo-to-item inspection starts above.<br>Completed captures and their findings will appear here.</div>';
    } catch (error) { container.innerHTML = notice(error.message,'error'); }
  }
  async function showReport(id, route,record=null) {
    clearTimeout(poll);const render=++reportRenderNumber,loadedVideo=record?$('#ihVideo video'):null;
    if(!record)page.innerHTML = '<p class="ih-kicker">Private inspection record</p><p>Loading evidence…</p>';
    try {
      const r = record||await (await api('/requests/' + encodeURIComponent(id),{},true)).json();
      if (route !== routeNumber||render!==reportRenderNumber) return;
      const refs = r.media.filter(m=>m.role==='listing'), frames = r.media.filter(m=>m.role==='frame'), video = r.media.find(m=>m.role==='video'), visual = r.analysis?.visual;
      const findings = new Map((visual?.photos||[]).map(p=>[p.photo_index,p]));
      const canRetry = ['unavailable','failed'].includes(r.analysis_status);
      page.innerHTML = `<div class="ih-report-head"><div><a class="ih-button text" href="#in-hand">← All inspections</a><p class="ih-kicker">Private evidence record · ${esc(r.id.slice(0,8))}</p><h1>${esc(r.title)}</h1><span class="ih-status ${esc(r.status)}">${esc(labels[r.status]||r.status)}</span></div><button class="ih-button secondary" id="ihExport">Export evidence record ↓</button></div>${notice(r.analysis?.summary || (r.status==='expired'?'This link expired before a recording was submitted. Create a new inspection to capture fresh evidence.':'Send the mobile link to the person holding the item.'))}${canRetry?`<p>${notice('Automated comparison has not established a match. No verified marking is available for this capture.','warning')}</p><button class="ih-button secondary" id="ihRetryAnalysis">Try comparison again</button>`:''}${['waiting','capturing'].includes(r.status)?linkBox(r):''}<div id="ihReportError" class="ih-note error" hidden></div><div class="ih-section-title"><h2>Selected photos · ${refs.length}</h2></div><div class="ih-evidence-grid">${refs.map((p,i)=>{const f=findings.get(i);return `<figure><img data-private="${p.id}" alt="Reference photo ${i+1}"><figcaption><strong>Photo ${i+1} · ${f?esc({supported:'Match supported',contradicted:'Mismatch',not_established:'Not established'}[f.finding]):'Awaiting comparison'}</strong>${f?esc(f.evidence):esc(r.photo_notes[i]||'Exact selected reference photo.')}${f?.frame_indices.length?`<br>Capture frames: ${f.frame_indices.map(n=>n+1).join(', ')}`:''}</figcaption></figure>`;}).join('')}</div>${video?`<div class="ih-section-title"><h2>Camera evidence</h2></div><button class="ih-button secondary" id="ihLoadVideo">Load recording ▶</button><div id="ihVideo"></div><div class="ih-frame-row">${frames.map((f,i)=>`<figure><img data-private="${f.id}" loading="lazy" alt="Capture frame ${i+1}"><figcaption>Frame ${i+1} · ${f.seconds}s<br>${esc(f.label)}</figcaption></figure>`).join('')}</div>`:''}${visual?.claims.length?`<div class="ih-section-title"><h2>Written claims</h2></div><ul class="ih-findings">${visual.claims.map(c=>`<li><strong>${esc(c.subject)} · ${esc({supported:'Supported',contradicted:'Contradicted',not_established:'Not established'}[c.finding])}</strong>${esc(c.evidence)}</li>`).join('')}</ul>`:''}${visual?.concerns.length?notice(visual.concerns.join(' '),'warning'):''}${r.status==='confirmed'?publicationBox(r):''}<p class="ih-note" style="margin-top:25px">${esc(scope)} Browser camera evidence is not hardware-attested.</p>`;
      $('.ih-report-head').insertAdjacentHTML('afterend',managementBox(r));
      bindLinkButtons(page);
      $('#ihExport').onclick = async()=>{try{download(await (await api('/requests/'+r.id+'/evidence',{},true)).blob(),'lockx-'+r.id.slice(0,8)+'-evidence.json');}catch(error){errorAt('#ihReportError',error);}};
      if (canRetry) $('#ihRetryAnalysis').onclick = async e=>{e.target.disabled=true;try{await json('/requests/'+r.id+'/analyze',{},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if (video) $('#ihLoadVideo').onclick = async e=>{e.target.disabled=true;try{const url=await privateURL(video.id);if(route!==routeNumber)return;$('#ihVideo').innerHTML=`<video class="ih-report-video" data-media-id="${video.id}" controls playsinline preload="metadata" src="${url}"></video>`;e.target.hidden=true;}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if ($('#ihPublishForm')) $('#ihPublishForm').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await json('/requests/'+r.id+'/publish',{publish_selected_photos:true},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);b.disabled=false;}};
      if ($('#ihWithdraw')) $('#ihWithdraw').onclick=async e=>{e.target.disabled=true;try{await api('/requests/'+r.id+'/publication',{method:'DELETE'},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if ($('#ihDownloadMarked')) $('#ihDownloadMarked').onclick=async e=>{e.target.disabled=true;try{download(await(await api('/requests/'+r.id+'/marked-photos',{},true)).blob(),'lockx-'+r.publication.id+'-verified-photos.zip');}catch(error){errorAt('#ihReportError',error);}finally{e.target.disabled=false;}};
      if(loadedVideo&&video?.id===loadedVideo.dataset.mediaId){$('#ihVideo').append(loadedVideo);$('#ihLoadVideo').hidden=true;}
      // Poll only metadata; immutable media URLs survive processing-state changes.
      pollReport(id,route,r);
      // Sequential decoding bounds memory use on older phones.
      for (const img of page.querySelectorAll('[data-private]')) {
        try { const url = await privateURL(img.dataset.private); if(route!==routeNumber||render!==reportRenderNumber)return; img.src = url; } catch { img.alt += ' · unavailable'; }
      }
    } catch (error) { if (route===routeNumber&&render===reportRenderNumber) page.innerHTML = `<a class="ih-button text" href="#in-hand">← All inspections</a>${notice(error.message,'error')}`; }
  }
  function publicationBox(r) {
    const p = r.publication;
    if (p?.revoked) return '<div class="ih-card" style="margin-top:25px"><h2>Public record withdrawn.</h2><p>The QR link now shows that this record was withdrawn. A new capture is needed to publish another set.</p></div>';
    if (p) {
      const link=appLink('verify/'+p.id);
      return `<div class="ih-card" style="margin-top:25px"><span class="ih-kicker">A portable record</span><h2>Your verified photo set is ready.</h2><div class="ih-link-box"><label>Public verification record<input readonly value="${esc(link)}"></label><div class="ih-link-actions"><button class="ih-button secondary" data-copy="${esc(link)}">Copy public link</button><a class="ih-button secondary" href="#in-hand/verify/${p.id}">View public record</a><button class="ih-button" id="ihDownloadMarked">Download marked photos ↓</button></div></div><button class="ih-button text" id="ihWithdraw">Withdraw public record</button></div>`;
    }
    return `<form id="ihPublishForm" class="ih-card" style="margin-top:25px"><span class="ih-kicker">Ready to share</span><h2>Make these photos verifiable.</h2><p>Publish this approved photo set and download copies marked “LockX In-hand verified,” with a QR link to its record.</p><label class="ih-check"><input type="checkbox" required><span>I want these selected photos and the item title to be publicly visible. I have checked for faces, addresses, usable ticket barcodes, and other private information.</span></label><button class="ih-button">Publish verified photo set →</button></form>`;
  }
  function download(blob, name) { const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000); }
  async function showPublic(id, route) {
    shell('<div class="ih-standalone-content"><p>Opening verification record…</p></div>');
    try {
      const r=await(await api('/public/'+encodeURIComponent(id))).json();if(route!==routeNumber)return;
      if(r.status!=='verified'){shell(`<div class="ih-standalone-content"><span class="ih-kicker">Record ${esc(id)}</span><h1>This record was withdrawn.</h1>${notice('These photos no longer carry an active public LockX record.','warning')}<p>Withdrawn ${esc(date(r.withdrawn))}.</p></div>`);return;}
      shell(`<article class="ih-standalone-content"><span class="ih-public-status">✓ LockX verification record</span><h1>${esc(r.title)}</h1><p>These exact ${r.photo_count} photos were compared with a guided item capture. Check that the listing shows the same photos and identifying details.</p><div class="ih-public-facts"><div><span>CAPTURED</span><strong>${esc(date(r.captured))}</strong></div><div><span>RECORD ID</span><strong>${esc(r.id)}</strong></div><div><span>PHOTO MATCH</span><strong>${r.photo_count} of ${r.photo_count} selected photos supported</strong></div><div><span>VERIFICATION SCOPE</span><strong>Visual photo-to-item correspondence</strong></div></div><div class="ih-public-gallery">${r.photos.map((p,i)=>`<figure><a href="${base}/public/${id}/photos/${p.id}" target="_blank" rel="noopener"><img src="${base}/public/${id}/photos/${p.id}" alt="LockX verified photo ${i+1}" loading="lazy"></a><figcaption>Verified photo ${i+1}</figcaption></figure>`).join('')}</div>${notice(r.scope)}<p>A marking alone is not proof. Confirm that you are viewing the genuine LockX website. This is a historical capture record; it does not track who holds the item today.</p></article>`);
    }catch(error){if(route===routeNumber)shell(`<div class="ih-standalone-content"><h1>Record not confirmed.</h1>${notice(error.message,'error')}<p>Do not rely on a photo marking without a matching LockX record.</p></div>`);}
  }
  async function showSeller(token, route) {
    sellerToken=token;sellerData=null;
    shell('<div class="ih-standalone-content"><p>Opening your camera check…</p></div>');
    try {
      const r=await(await api('/seller/'+encodeURIComponent(token))).json();if(route!==routeNumber)return;sellerData=r;
      if(!['waiting','capturing'].includes(r.status)){shell(`<div class="ih-standalone-content ih-seller-result"><span class="ih-seal">✓</span><h1>Capture received.</h1><p>Your recording was submitted. Open the separate private management link to view the result. No login is needed.</p>${notice('Submission does not itself mean the item or photos passed verification.')}</div>`);return;}
      shell(`<div class="ih-standalone-content ih-camera-intro"><span class="ih-kicker">Private camera check · No app needed</span><h1>Show it.<br>Slowly turn it.<br>You’re done.</h1><p>Show <strong>${esc(r.title)}</strong> in one continuous scan. LockX collects clear views automatically and asks for a detail only when needed.</p><div class="ih-seller-refs">${r.media.map((m,i)=>`<figure><img src="${base}/seller/${token}/photos/${m.id}" alt="Reference photo ${i+1}"><figcaption>Reference ${i+1}</figcaption></figure>`).join('')}</div><div class="ih-scan-explainer"><span>01 <strong>Show the item</strong></span><span>02 <strong>Follow the movement</strong></span><span>03 <strong>Capture ends automatically</strong></span></div>${notice(r.capture_mode==='stationary'?'Move your phone around the item. Do not lift or move a heavy appliance.':r.capture_mode==='digital'?'Use a second screen and hide usable barcodes. This check cannot establish ticket validity or transfer rights.':'Use good light, clear a little space, and keep the same item in view. No microphone is used.')}<label class="ih-voice-option"><input type="checkbox" id="ihVoiceConsent" ${voiceEnabled()?'checked':''}><span>Read instructions aloud <small>Optional · visual instructions are always shown</small></span></label><label class="ih-seller-consent"><input type="checkbox" id="ihSellerConsent"><span>I have permission to show this item and consent to recording and comparison with these reference photos. I will keep faces and private information out of view.</span></label><div id="ihCaptureError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihStartCapture">Start automatic camera check →</button><p class="ih-scan-target">Designed for a 15–25 second scan of a straightforward item. More views or a slow connection can take longer. Comparison follows capture.</p></div>`);
      $('#ihStartCapture').onclick=startCapture;
      if(!('speechSynthesis' in window))$('#ihVoiceConsent').closest('label').hidden=true;
      if(window.LOCKX_LOCAL_PREVIEW)$('#ihCaptureError').insertAdjacentHTML('beforebegin',notice('Local preview: automated comparison is disabled. Captures made here cannot earn a verified marking.','warning'));
    }catch(error){if(route===routeNumber)shell(`<div class="ih-standalone-content"><h1>Link unavailable.</h1>${notice(error.message,'error')}<p>Ask the inspection owner for a new mobile link.</p></div>`);}
  }
  function voiceEnabled(){try{return localStorage.getItem('lockx-scan-voice')==='on';}catch{return false;}}
  function speak(current,text){if(!current?.voice||!window.speechSynthesis||current.cancelled)return;try{speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.rate=.95;speechSynthesis.speak(utterance);}catch{}}
  function activeCapture(current){return !!current&&capture===current&&!current.cancelled&&current.route===routeNumber;}
  function stopQualityLoop(current){clearTimeout(current.frameTimer);if(current.frameCallback!==undefined)try{current.video?.cancelVideoFrameCallback(current.frameCallback);}catch{}current.frameCallback=undefined;}
  function stopCapture(discard = true) {
    const current=capture;if(!current)return;
    if(discard)current.cancelled=true;
    clearInterval(current.timer);clearTimeout(current.limit);clearTimeout(current.retryTimer);clearTimeout(current.progressTimer);clearTimeout(current.startTimer);clearTimeout(current.finalizeTimer);stopQualityLoop(current);
    current.startRequest?.abort();current.progressRequest?.abort();current.upload?.abort();
    current.intentionalStop=true;
    if(current.recorder?.state!=='inactive'){try{current.recorder?.stop();}catch{}}
    current.stream?.getTracks().forEach(t=>t.stop());
    current.layoutObserver?.disconnect();window.removeEventListener('resize',current.layoutHandler);window.visualViewport?.removeEventListener('resize',current.layoutHandler);
    try{speechSynthesis.cancel();}catch{}
    document.body.classList.remove('ih-scanning');
    if(discard){current.queue=[];current.sampleCanvas=null;current.previousFrame=null;capture=null;}
  }
  async function startCapture() {
    if(!$('#ihSellerConsent')?.checked){errorAt('#ihCaptureError',Error('Please agree to the recording before starting.'));return;}
    const button=$('#ihStartCapture');button.disabled=true;button.textContent='Opening camera…';
    const voice=!!$('#ihVoiceConsent')?.checked;try{localStorage.setItem('lockx-scan-voice',voice?'on':'off');}catch{}
    let current=null;const route=routeNumber;
    try {
      if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)throw Error('Open this link over HTTPS in Safari or Chrome to use the camera.');
      if(!window.MediaRecorder)throw Error('This browser cannot record the inspection. Open the link in Safari or Chrome.');
      if(voice)speak({voice:true},'Camera check starting. Follow the instructions on your screen.');
      const portrait=window.innerHeight>=window.innerWidth;
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:portrait?720:1280,max:1280},height:{ideal:portrait?960:720,max:1280},aspectRatio:{ideal:portrait ? .75 : 16/9},frameRate:{ideal:20,max:24}},audio:false});
      if(route!==routeNumber || !isStandalone || !location.hash.includes('/capture/')){stream.getTracks().forEach(t=>t.stop());return;}
      const mime=['video/mp4','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
      current={stream,queue:[],nextSequence:0,uploadedCount:0,bytesTotal:0,uploadedBytes:0,cancelled:false,intentionalStop:false,stage:null,route,voice,captured:new Set(),nextAttemptAt:0};capture=current;
      const recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:1_200_000});current.recorder=recorder;
      recorder.ondataavailable=e=>enqueueChunks(current,e.data);
      recorder.onerror=()=>{if(activeCapture(current))captureFailed('The camera recording was interrupted. Please start a fresh check.');};
      stream.getVideoTracks().forEach(t=>t.onended=()=>{if(activeCapture(current)&&!current.intentionalStop)captureFailed('Camera access ended. Please start a fresh check.');});
      renderCamera(current);current.video=$('#ihLiveVideo');current.video.srcObject=stream;await current.video.play();if(!activeCapture(current))return;
      current.layoutHandler=()=>positionReticle(current);window.addEventListener('resize',current.layoutHandler);window.visualViewport?.addEventListener('resize',current.layoutHandler);
      if(window.ResizeObserver){current.layoutObserver=new ResizeObserver(current.layoutHandler);current.layoutObserver.observe(current.video);current.layoutObserver.observe($('.ih-scan-bottom'));}positionReticle(current);
      if(!activeCapture(current))return;
      current.recordingStarted=performance.now();recorder.start(1000);
      current.limit=setTimeout(()=>{if(activeCapture(current))captureFailed('The connection could not start this scan in time. Please reconnect and start again.');},88000);
      current.startRequest=new AbortController();current.startTimer=setTimeout(()=>current.startRequest?.abort(),25000);
      const stage=await(await api('/seller/'+sellerToken+'/scan/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:current.startRequest.signal})).json();
      clearTimeout(current.startTimer);if(!activeCapture(current))return;
      current.sessionID=stage.session_id;current.maxSeconds=stage.max_capture_seconds||90;
      updateStage(stage);pumpChunks(current);
      current.timer=setInterval(()=>{
        if(!activeCapture(current))return;
        const seconds=Math.floor((performance.now()-current.recordingStarted)/1000);const elapsed=$('#ihElapsed');if(elapsed)elapsed.textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
        renderUploadStatus(current);
      },500);
      const remaining=current.maxSeconds*1000-(performance.now()-current.recordingStarted);clearTimeout(current.limit);
      current.limit=setTimeout(()=>{if(activeCapture(current))captureFailed('This scan reached its time limit. Please start again in good light and follow each movement.');},Math.max(1000,remaining));
      scheduleQuality(current);
    }catch(error){
      if(current?.cancelled||route!==routeNumber)return;
      const message=error.name==='NotAllowedError'?'Allow camera access in your browser settings, then try again.':error.name==='NotFoundError'?'No camera was found. Open this link on your phone.':error.name==='NotReadableError'?'The camera is busy. Close other camera apps and try again.':error.name==='AbortError'?'The connection could not start the scan. Reconnect and try again.':error.message;
      if($('#ihCaptureError')){stopCapture();errorAt('#ihCaptureError',Error(message));button.disabled=false;button.textContent='Try camera again →';}else captureFailed(message);
    }
  }
  function renderCamera(current){
    document.body.classList.add('ih-scanning');
    standalone.innerHTML=`<div class="ih-auto-camera"><video id="ihLiveVideo" autoplay playsinline muted aria-label="Live item camera"></video><div class="ih-scan-shade"></div><header class="ih-scan-head"><span class="ih-scan-brand">lock<span>x</span></span><span class="ih-live"><i></i> REC <span id="ihElapsed">0:00</span></span><button id="ihCancelCapture" class="ih-scan-close" aria-label="Cancel recording">×</button></header><div class="ih-scan-reticle" aria-hidden="true"><i></i><i></i><i></i><i></i></div><div class="ih-scan-target-photo" id="ihTarget" hidden><img id="ihTargetPhoto" alt="Selected reference view"><small id="ihTargetLabel"></small></div><div class="ih-scan-bottom"><div class="ih-scan-instruction" aria-live="polite" aria-atomic="true"><span class="ih-scan-caption" id="ihStepNumber">OPENING YOUR SCAN</span><div class="ih-movement-cue" id="ihMovementCue" aria-hidden="true"><span>↔</span></div><h2 id="ihInstructionTitle">Get the item ready</h2><p id="ihInstruction">Keep it in view. The scan will advance automatically.</p></div><div class="ih-scan-feedback" id="ihQualityFeedback" role="status">Opening the camera…</div><button class="ih-scan-quality-override" id="ihQualityOverride" hidden>Capture this view with a quality warning</button><div class="ih-scan-progress"><span id="ihStepProgress"></span></div><div class="ih-reference-chips" aria-label="Reference views collected">${sellerData.media.map((m,i)=>`<div class="ih-reference-chip" data-reference="${i}" aria-label="Photo ${i+1}: view needed"><img src="${base}/seller/${sellerToken}/photos/${m.id}" alt=""><span>${i+1}</span><small>View needed</small></div>`).join('')}</div><footer class="ih-scan-footer"><button type="button" id="ihVoiceToggle" aria-pressed="${current.voice}">${current.voice?'◖ Voice on':'◖ Voice off'}</button><span id="ihStreamingStatus">Preparing recording upload</span></footer><p class="ih-capture-scope">Views captured here are compared after the scan. They are not yet verified.</p></div></div>`;
    $('#ihCancelCapture').onclick=()=>{stopCapture();showSeller(sellerToken,routeNumber);};
    $('#ihQualityOverride').onclick=()=>advanceCapture(current,true);
    $('#ihVoiceToggle').hidden=!('speechSynthesis' in window);
    $('#ihVoiceToggle').onclick=e=>{current.voice=!current.voice;e.currentTarget.setAttribute('aria-pressed',String(current.voice));e.currentTarget.textContent=current.voice?'◖ Voice on':'◖ Voice off';try{localStorage.setItem('lockx-scan-voice',current.voice?'on':'off');}catch{}if(current.voice)speak(current,current.stage?.stage?.instruction||'Follow the instructions on screen.');else try{speechSynthesis.cancel();}catch{}};
  }
  function updateStage(stage) {
    const current=capture;if(!activeCapture(current))return;current.stage=stage;current.stageStarted=performance.now();current.motionState={};current.previousFrame=null;current.nextAttemptAt=0;current.qualityRetries=0;
    $('.ih-auto-camera').dataset.kind=stage.stage.kind;
    $('#ihStepNumber').textContent=`VIEW ${stage.position+1} OF ${stage.total} · AUTOMATIC`;
    $('#ihStepProgress').style.width=(stage.position/stage.total*100)+'%';
    $('#ihInstructionTitle').textContent=stage.stage.label;$('#ihInstruction').textContent=stage.stage.instruction;
    $('#ihQualityOverride').hidden=true;$('#ihQualityFeedback').textContent=stage.stage.kind==='motion'?'Move slowly, then pause briefly.':'Hold the item steady.';
    const cue=$('#ihMovementCue');cue.classList.toggle('is-stable',stage.stage.kind!=='motion');cue.querySelector('span').textContent=stage.stage.kind==='motion'?'↔':'◎';
    const indices=stage.stage.photo_indices||[],i=indices[0],target=$('#ihTarget');target.hidden=!Number.isInteger(i)||!sellerData.media[i];
    if(!target.hidden){$('#ihTargetPhoto').src=base+'/seller/'+sellerToken+'/photos/'+sellerData.media[i].id;$('#ihTargetLabel').textContent=indices.length>1?'REFERENCE VIEWS':'PHOTO '+(i+1);}
    $$('.ih-reference-chip',standalone).forEach(chip=>chip.classList.toggle('is-current',indices.includes(Number(chip.dataset.reference))));
    positionReticle(current);speak(current,stage.stage.instruction);
  }
  function positionReticle(current){
    if(!activeCapture(current)||!current.video?.videoWidth)return;
    const root=$('.ih-auto-camera'),reticle=$('.ih-scan-reticle'),panel=$('.ih-scan-bottom'),header=$('.ih-scan-head');if(!root||!reticle||!panel||!header)return;
    const bounds=current.video.getBoundingClientRect(),outer=root.getBoundingClientRect(),scale=Math.min(bounds.width/current.video.videoWidth,bounds.height/current.video.videoHeight);
    const width=current.video.videoWidth*scale,height=current.video.videoHeight*scale;
    // Matches object-position: center 12%; no cropping or black bars inside the guide.
    const imageLeft=bounds.left+(bounds.width-width)/2,imageTop=bounds.top+(bounds.height-height)*.12;
    const panelBounds=panel.getBoundingClientRect(),sidePanel=panelBounds.width<outer.width*.75&&panelBounds.left>outer.left+outer.width*.3;
    const left=Math.max(imageLeft+10,outer.left+18),right=Math.min(imageLeft+width-10,sidePanel?panelBounds.left-12:outer.right-18);
    const top=Math.max(imageTop+10,header.getBoundingClientRect().bottom+10),bottom=Math.min(imageTop+height-10,sidePanel?outer.bottom-12:panelBounds.top-12);
    if(right-left<45||bottom-top<45){reticle.hidden=true;return;}reticle.hidden=false;
    const guideWidth=(right-left)*.85,guideHeight=(bottom-top)*.88;
    Object.assign(reticle.style,{left:(left+(right-left-guideWidth)/2-outer.left)+'px',right:'auto',top:(top+(bottom-top-guideHeight)/2-outer.top)+'px',width:guideWidth+'px',height:guideHeight+'px'});
  }
  function sampleQuality(current){
    const video=current.video;if(!video?.videoWidth||video.readyState<2)return null;
    if(!current.sampleCanvas){current.sampleCanvas=document.createElement('canvas');current.sampleCanvas.width=128;current.sampleCanvas.height=96;current.sampleContext=current.sampleCanvas.getContext('2d',{willReadFrequently:true});}
    const context=current.sampleContext;context.drawImage(video,0,0,128,96);const measured=LockXCapture.measureFrame(context.getImageData(0,0,128,96).data,128,96,current.previousFrame);current.previousFrame=measured.gray;return measured;
  }
  function scheduleQuality(current){
    if(!activeCapture(current)||current.finishing)return;
    const next=()=>{if(!activeCapture(current)||current.finishing)return;const now=performance.now();if(!current.lastSample||now-current.lastSample>=240){current.lastSample=now;checkQuality(current,now);}scheduleQuality(current);};
    if(typeof current.video?.requestVideoFrameCallback==='function')current.frameCallback=current.video.requestVideoFrameCallback(next);else current.frameTimer=setTimeout(next,250);
  }
  function checkQuality(current,now){
    if(!current.stage?.stage||current.busy||current.finishing)return;
    let quality;try{quality=sampleQuality(current);}catch{captureFailed('The camera could not provide a usable frame. Please reopen this link in Safari or Chrome.');return;}if(!quality)return;
    const feedback=$('#ihQualityFeedback'),elapsed=(now-current.stageStarted)/1000,stage=current.stage.stage;
    const decision=LockXCapture.inspectFrame(current.motionState,quality,now,stage.kind);current.motionState=decision.state;
    if(now>=current.nextAttemptAt||decision.issue)feedback.textContent=decision.feedback;
    $('#ihQualityOverride').hidden=!(decision.issue&&elapsed>=10)&&current.qualityRetries<2;
    if(!decision.ready||now<current.nextAttemptAt)return;
    if(elapsed<(stage.minimum_seconds??current.stage.minimum_seconds??1))return;
    advanceCapture(current,false);
  }
  function cameraFrame(current) {
    const video=current.video;if(!video?.videoWidth)throw Error('The camera is still opening. Wait a moment, then try again.');
    const canvas=document.createElement('canvas'),ratio=Math.min(1,720/video.videoWidth);canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);const image=canvas.toDataURL('image/jpeg',.8);canvas.width=canvas.height=1;return image;
  }
  async function advanceCapture(current,override) {
    if(!activeCapture(current)||current.busy||current.finishing||!current.stage?.stage)return;current.busy=true;$('#ihQualityFeedback').textContent='Clear view captured. Keep the item in frame…';$('#ihQualityOverride').hidden=true;
    const previous=current.stage.stage;
    try {
      const controller=new AbortController();current.progressRequest=controller;current.progressTimer=setTimeout(()=>controller.abort(),12000);
      const next=await(await api('/seller/'+sellerToken+'/scan/progress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:current.sessionID,stage_id:previous.id,image:cameraFrame(current),continue_with_quality_issue:override,recording_seconds:(performance.now()-current.recordingStarted)/1000}),signal:current.progressRequest.signal})).json();
      clearTimeout(current.progressTimer);if(!activeCapture(current))return;
      if(next.retry){if(!next.remaining_seconds)current.qualityRetries++;current.nextAttemptAt=performance.now()+Math.max(700,(next.remaining_seconds||0)*1000);$('#ihQualityFeedback').textContent=next.feedback||'Keep this clear view for a moment longer.';$('#ihQualityOverride').hidden=current.qualityRetries<2;}
      else{
        (previous.photo_indices||[]).forEach(i=>current.captured.add(i));
        $$('.ih-reference-chip',standalone).forEach(chip=>{if(current.captured.has(Number(chip.dataset.reference))){chip.classList.add('is-captured');chip.querySelector('small').textContent='View captured';chip.setAttribute('aria-label','Photo '+(Number(chip.dataset.reference)+1)+': view captured, comparison pending');}});
        if(next.complete){current.stage=next;await finishCapture(current);return;}
        updateStage(next);
      }
    }catch(error){if(activeCapture(current)){if([409,410].includes(error.status)){captureFailed(error.message);return;}current.nextAttemptAt=performance.now()+1800;$('#ihQualityFeedback').textContent=error.status===425?'Keep this view a moment longer.':'Connection slow. Keep the item in frame; retrying automatically.';}}
    finally{clearTimeout(current.progressTimer);current.busy=false;}
  }
  function enqueueChunks(current,blob){
    if(!blob?.size||!activeCapture(current))return;
    current.bytesTotal+=blob.size;if(current.bytesTotal>60*1024*1024){captureFailed('This recording exceeded the upload limit. Please start a shorter scan.');return;}
    const partSize=4*1024*1024;for(let offset=0;offset<blob.size;offset+=partSize)current.queue.push({sequence:current.nextSequence++,blob:blob.slice(offset,Math.min(blob.size,offset+partSize))});
    pumpChunks(current);
  }
  function sendChunk(current,part){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();current.upload=xhr;xhr.open('POST',base+'/seller/'+sellerToken+'/scan/'+encodeURIComponent(current.sessionID)+'/chunks/'+part.sequence);xhr.timeout=45000;xhr.setRequestHeader('Content-Type','application/octet-stream');
      xhr.upload.onprogress=e=>{current.inflightBytes=e.loaded;renderUploadStatus(current);};
      xhr.onload=()=>{current.inflightBytes=0;if(xhr.status>=200&&xhr.status<300)resolve();else{let message='Upload interrupted. Your remaining recording is still on this page.';try{const body=JSON.parse(xhr.responseText);if(typeof body.detail==='string')message=body.detail;}catch{}const error=Error(message);error.status=xhr.status;reject(error);}};
      xhr.onerror=()=>reject(Error('Connection interrupted. Reconnect and retry; your remaining recording is still on this page.'));xhr.ontimeout=()=>reject(Error('The connection is taking too long. Reconnect and retry.'));xhr.onabort=()=>reject(Error('Upload cancelled.'));xhr.send(part.blob);
    });
  }
  async function pumpChunks(current){
    if(!activeCapture(current)||!current.sessionID||current.uploadPaused)return;
    if(current.pumping)return current.pumping;
    current.pumping=(async()=>{
      while(activeCapture(current)&&current.queue.length){
        const part=current.queue[0];let sent=false;
        for(let attempt=0;attempt<3&&!sent;attempt++){
          try{await sendChunk(current,part);sent=true;}
          catch(error){if(!activeCapture(current))return;current.uploadError=error;if([409,410,413].includes(error.status)||attempt===2){current.uploadPaused=true;renderUploadStatus(current);return;}await new Promise(resolve=>{current.retryTimer=setTimeout(resolve,700*(attempt+1));});}
        }
        if(!activeCapture(current))return;
        current.queue.shift();current.uploadedCount++;current.uploadedBytes+=part.blob.size;current.inflightBytes=0;current.uploadError=null;renderUploadStatus(current);
      }
    })();
    try{await current.pumping;}finally{current.pumping=null;}
  }
  function renderUploadStatus(current){
    if(!activeCapture(current))return;
    const status=$('#ihStreamingStatus');if(status)status.textContent=current.uploadPaused?'Connection paused · recording saved on this page':current.uploadedCount?'Sending while you scan':!current.bytesTotal&&performance.now()-current.recordingStarted>5000?'This browser sends the recording when capture ends':'Preparing recording upload';
    const progress=$('#ihUploadProgress');if(progress){const pct=current.bytesTotal?Math.min(100,Math.floor((current.uploadedBytes+(current.inflightBytes||0))/current.bytesTotal*100)):0;progress.value=pct;$('#ihUploadLabel').textContent=current.queue.length?`Sending recording · ${pct}%`:'Recording uploaded. Preparing comparison…';}
  }
  async function finishCapture(current) {
    if(!activeCapture(current)||current.finishing)return;current.finishing=true;stopQualityLoop(current);clearInterval(current.timer);clearTimeout(current.limit);current.intentionalStop=true;
    try{speechSynthesis.cancel();}catch{}
    const stopped=new Promise((resolve,reject)=>{current.recorder.onstop=resolve;current.recorder.onerror=()=>reject(Error('The recording could not be saved. Please record again.'));});
    try{current.recorder.stop();await stopped;}catch(error){if(activeCapture(current))captureFailed(error.message);return;}if(!activeCapture(current))return;current.stream.getTracks().forEach(t=>t.stop());current.layoutObserver?.disconnect();window.removeEventListener('resize',current.layoutHandler);window.visualViewport?.removeEventListener('resize',current.layoutHandler);current.sampleCanvas=null;current.previousFrame=null;
    document.body.classList.remove('ih-scanning');
    shell(`<div class="ih-standalone-content"><span class="ih-kicker">Camera scan complete</span><h1>Your views<br>are captured.</h1><p>Keep this page open while the remaining recording is sent. LockX will compare every selected photo and the listing description in the background.</p><progress id="ihUploadProgress" class="ih-upload-progress" max="100" value="0"></progress><p id="ihUploadLabel">Sending the last part…</p><div id="ihUploadError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihRetryUpload" hidden>Retry sending · no new scan needed</button><p class="ih-scan-target">If the connection drops, keep this page open. Already received parts are preserved and retries resume the remaining upload.</p></div>`);
    $('#ihRetryUpload').onclick=()=>uploadCapture(current);await uploadCapture(current);
  }
  async function uploadCapture(current) {
    if(!activeCapture(current)||current.finalizing)return;current.finalizing=true;$('#ihRetryUpload').hidden=true;$('#ihUploadError').hidden=true;
    try{
      current.uploadPaused=false;await pumpChunks(current);if(!activeCapture(current))return;
      if(current.queue.length||current.uploadPaused)throw current.uploadError||Error('The connection paused. Keep this page open and retry.');
      if(!current.uploadedCount)throw Error('The browser did not save any video. Please start a fresh scan.');
      renderUploadStatus(current);current.progressRequest=new AbortController();current.finalizeTimer=setTimeout(()=>current.progressRequest?.abort(),30000);
      try{await api('/seller/'+sellerToken+'/scan/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:current.sessionID,consent:true,source:'browser_camera',chunk_count:current.uploadedCount}),signal:current.progressRequest.signal});}
      catch(error){if(error.status!==409)throw error;const state=await(await api('/seller/'+sellerToken)).json();if(['waiting','capturing'].includes(state.status))throw error;}
      if(!activeCapture(current))return;current.queue=[];capture=null;
      shell(`<div class="ih-standalone-content ih-seller-result"><span class="ih-seal">✓</span><span class="ih-kicker">Recording received</span><h1>Your part is complete.</h1><p>LockX is comparing the selected photos, written claims, and continuous recording. Use the separate private management link to view the findings. No login is needed.</p>${notice('Views captured does not mean verified. A verified marking is only issued after all selected photos pass comparison.')}<p>You can close this page.</p></div>`);
    }catch(error){if(activeCapture(current)){errorAt('#ihUploadError',error);$('#ihRetryUpload').hidden=false;renderUploadStatus(current);}}
    finally{clearTimeout(current.finalizeTimer);current.finalizing=false;}
  }
  function captureFailed(message) {
    stopCapture();shell(`<div class="ih-standalone-content"><span class="ih-kicker">A fresh capture is needed</span><h1>Let’s try that again.</h1>${notice(message,'warning')}<p>Use one uninterrupted recording with the same item throughout.</p><button class="ih-button ih-wide" id="ihRestart">Start again</button></div>`);$('#ihRestart').onclick=()=>showSeller(sellerToken,routeNumber);
  }
  function route() {
    routeNumber++;clearTimeout(poll);poll=null;stopCapture();revokeReports();
    const match=location.hash.match(/^#in-hand\/(capture|report|verify)\/([A-Za-z0-9_-]+)(?:\/([A-Za-z0-9_-]{43}))?$/), active=location.hash==='#in-hand'||!!match;
    if(!active){if(isStandalone){document.body.classList.remove('ih-capture-mode');isStandalone=false;go(location.hash.slice(1)||'dashboard');}return;}
    const kind=match?.[1], id=match?.[2];isStandalone=kind==='capture'||kind==='verify';document.body.classList.toggle('ih-capture-mode',isStandalone);$('#authModal')?.classList.remove('open');
    managementKey=kind==='report'?(match?.[3]||browserAccess.records[id]||''):'';
    if(kind==='report'&&managementKey)remember(id,managementKey);
    if(isStandalone){window.scrollTo(0,0);if(kind==='capture')showSeller(id,routeNumber);else showPublic(id,routeNumber);}
    else{go('in-hand');if(kind==='report')showReport(id,routeNumber);else showHome();}
  }
  document.addEventListener('click',e=>{const nav=e.target.closest('[data-page]');if(nav?.dataset.page==='in-hand'){if(location.hash==='#in-hand')route();else location.hash='in-hand';}else if(nav&&location.hash.startsWith('#in-hand'))location.hash=nav.dataset.page;});
  window.addEventListener('hashchange',route);
  window.addEventListener('pagehide',()=>stopCapture());
  window.addEventListener('beforeunload',e=>{if(capture?.recorder?.state==='recording'||capture?.finishing){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden && capture?.recorder?.state==='recording')captureFailed('The recording paused when this page left the screen. Keep the camera page open for the next attempt.');});
  api('/capabilities').then(r=>r.json()).then(r=>{capabilities=r;serviceState();}).catch(()=>{});
  route();
})();
