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
  let photos = [], capabilities = null, routeNumber = 0, poll = null, reportURLs = [], capture = null, sellerData = null, sellerToken = null, isStandalone = false;
  let managementKey = '', reportRenderNumber = 0;
  const reportMedia = new Map();
  let markedFiles=null;
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
    return `<div class="ih-hero"><div><span class="ih-kicker">Service 03 · Photo-to-item verification</span><h1>The photos. The item.<br>The same story.</h1><p class="ih-lead">Connect listing photos to the item on hand. A 10-second video, a photo-by-photo result, and a record buyers can open.</p><div class="ih-pills"><span>No login or app needed</span><span>10-second video</span><span>Shareable verified photos</span></div></div><div class="ih-flow-preview" aria-hidden="true"><div class="ih-preview-photos">${[1,2,3,4].map(i=>`<span class="ih-preview-photo">PHOTO ${i}</span>`).join('')}</div><span class="ih-preview-arrow">→</span><div class="ih-preview-record"><span class="ih-seal">✓</span><strong>One item.<br>A verified photo set.</strong><small>Every marking links back<br>to its LockX record.</small></div></div></div>`;
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
  function revokeReports() { reportURLs.forEach(URL.revokeObjectURL); reportURLs = []; reportMedia.clear();clearMarkedFiles(); }
  async function privateURL(id) {
    if(reportMedia.has(id))return reportMedia.get(id);
    const route=routeNumber,pending=(async()=>{const blob=await(await api('/media/'+id,{},true)).blob();if(route!==routeNumber)throw Error('Inspection changed.');const url=URL.createObjectURL(blob);reportURLs.push(url);return url;})();
    reportMedia.set(id,pending);
    try{return await pending;}catch(error){if(reportMedia.get(id)===pending)reportMedia.delete(id);throw error;}
  }
  function reportFingerprint(record){return JSON.stringify([record.status,record.analysis_status,record.submitted,record.media.map(m=>[m.id,m.role,m.sha256]),record.publication,record.publication_status]);}
  function pollReport(id,route,record,delay=1800){
    clearTimeout(poll);if((record.status!=='processing'&&record.publication_status!=='pending')||route!==routeNumber)return;const render=reportRenderNumber;
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
    page.innerHTML = `${heading()}<div class="ih-layout"><div><form id="ihRequestForm" class="ih-card"><div class="ih-card-top"><span class="ih-step-number">01</span><div><h2>Choose the photos to verify.</h2><p>Four views tell a good story. Select up to six.</p></div></div><div class="ih-upload"><button type="button" class="ih-button secondary" id="ihChoosePhotos">＋ Add photos</button><input id="ihPhotoInput" type="file" accept="image/*" multiple hidden><p>Up to 6 selected photos · Photos are resized before upload.</p></div><div id="ihPhotoGrid" class="ih-photo-grid"></div><div id="ihPhotoError" class="ih-note error" role="alert" hidden></div><label class="ih-check"><input type="checkbox" name="consent" required><span>I have permission to submit these photos and record the item. If every photo matches, automatically create QR-marked copies and a public verification record showing these photos. The camera recording stays private.</span></label><div id="ihCreateError" class="ih-note error" role="alert" hidden></div><div class="ih-form-footer"><small>No login needed to create a check or view your results. The camera link lasts 24 hours.</small><button class="ih-button" type="submit" id="ihCreate">Continue to verification <span>→</span></button></div><div id="ihCreated"></div></form></div><aside class="ih-aside ih-card"><h3>From listing to confidence.</h3><ol><li><strong>Select the exact photos</strong>Choose the images you want matched to the recorded item.</li><li><strong>Open the link on a phone</strong>Record a 10-second video showing the views and identifying details in your photos. Recording stops automatically.</li><li><strong>Compare every selected view</strong>Each photo needs evidence from the capture. Unclear results stay unverified.</li><li><strong>Save your verified photos</strong>When every photo matches, QR-marked images appear automatically on the same page.</li></ol><div class="ih-note">${esc(scope)}</div></aside></div><div class="ih-section-title"><h2>Your inspections on this browser</h2><button class="ih-button text" id="ihRefresh">Refresh ↻</button></div><div id="ihRequests" aria-live="polite"></div>`;
    $('.ih-hero').insertAdjacentHTML('afterend','<div id="ihServiceState" class="ih-note warning" style="margin-bottom:22px" hidden></div>');
    serviceState();
    $('#ihChoosePhotos').onclick = () => $('#ihPhotoInput').click();
    $('#ihPhotoInput').onchange = addPhotos;
    $('#ihRequestForm').onsubmit = createRequest;
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
      return {blob, url:URL.createObjectURL(blob), selected:true};
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
    finally { button.disabled = false; button.textContent = '＋ Add photos'; }
  }
  function renderPhotos() {
    const grid = $('#ihPhotoGrid'); if (!grid) return;
    grid.innerHTML = photos.map((p,i)=>`<div class="ih-photo-tile"><img src="${p.url}" alt="Selected reference photo ${i+1}"><button type="button" class="ih-remove" data-remove="${i}" aria-label="Remove photo ${i+1}">×</button><div class="ih-photo-meta"><label><input type="checkbox" data-select="${i}" ${p.selected?'checked':''}>Photo ${i+1}</label></div></div>`).join('');
    grid.onclick = e => { const remove = e.target.closest('[data-remove]'); if (remove) { const p = photos.splice(Number(remove.dataset.remove),1)[0]; URL.revokeObjectURL(p.url); renderPhotos(); } };
    grid.oninput = e => { if (e.target.dataset.select !== undefined) photos[Number(e.target.dataset.select)].selected = e.target.checked; };
  }
  async function createRequest(e) {
    e.preventDefault();
    const selected = photos.filter(p=>p.selected), button = $('#ihCreate');
    if (!selected.length) { errorAt('#ihCreateError',Error('Select at least one photo to verify.')); return; }
    button.disabled = true; button.textContent = 'Creating your link…'; $('#ihCreateError').hidden = true;
    try {
      const payload = {title:'Photo verification', consent:true, auto_publish:true};
      const body = new FormData(); body.append('payload',JSON.stringify(payload)); selected.forEach((p,i)=>body.append('photos',p.blob,`reference-${i+1}.jpg`));
      const record = await (await api('/requests',{method:'POST',body},true)).json();
      remember(record.id,record.manage_key);
      if(window.matchMedia('(max-width:720px)').matches||/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)){location.hash='in-hand/capture/'+record.token;return;}
      $('#ihCreated').innerHTML = linkBox(record)+`<details class="ih-result-details"><summary>Keep your private management link</summary>${managementBox(record)}</details>`;
      bindLinkButtons($('#ihCreated')); loadRequests();
      $('#ihCreated').scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch (error) { errorAt('#ihCreateError',error); }
    finally { button.disabled = false; button.innerHTML = 'Continue to verification <span>→</span>'; }
  }
  function linkBox(record) {
    const link = appLink('capture/' + record.token);
    return `<div class="ih-link-box"><label>Private mobile capture link<input readonly value="${esc(link)}" aria-label="Private capture link"></label><div class="ih-link-actions"><button type="button" class="ih-button secondary" data-copy="${esc(link)}">Copy link</button>${navigator.share?`<button type="button" class="ih-button secondary" data-share="${esc(link)}">Share to phone</button>`:''}<a class="ih-button" href="#in-hand/capture/${esc(record.token)}">Record on this device →</a></div><p style="font-size:11px;color:#819073;margin-bottom:0">Expires ${esc(date(record.expires))}. Anyone with this link can submit the capture. Share it only with the person holding the item.</p></div>`;
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
      page.innerHTML = `<div class="ih-report-head"><div><a class="ih-button text" href="#in-hand">← All inspections</a><p class="ih-kicker">Private evidence record · ${esc(r.id.slice(0,8))}</p><h1>${esc(r.title)}</h1><span class="ih-status ${esc(r.status)}">${esc(labels[r.status]||r.status)}</span></div><button class="ih-button secondary" id="ihExport">Export evidence record ↓</button></div>${notice(r.analysis?.summary || (r.status==='expired'?'This link expired before a recording was submitted. Create a new inspection to capture fresh evidence.':'Send the mobile link to the person holding the item.'))}${canRetry?`<p>${notice('Automated comparison has not established a match. No verified marking is available for this capture.','warning')}</p><button class="ih-button secondary" id="ihRetryAnalysis">Try comparison again</button>`:''}${['waiting','capturing'].includes(r.status)?linkBox(r):''}${r.status==='confirmed'?publicationBox(r):''}<div id="ihReportError" class="ih-note error" hidden></div><div class="ih-section-title"><h2>Selected photos · ${refs.length}</h2></div><div class="ih-evidence-grid">${refs.map((p,i)=>{const f=findings.get(i);return `<figure><img data-private="${p.id}" alt="Reference photo ${i+1}"><figcaption><strong>Photo ${i+1} · ${f?esc({supported:'Match supported',contradicted:'Mismatch',not_established:'Not established'}[f.finding]):'Awaiting comparison'}</strong>${f?esc(f.evidence):esc(r.photo_notes[i]||'Exact selected reference photo.')}${f?.frame_indices.length?`<br>Capture frames: ${f.frame_indices.map(n=>n+1).join(', ')}`:''}</figcaption></figure>`;}).join('')}</div>${video?`<div class="ih-section-title"><h2>Camera evidence</h2></div><button class="ih-button secondary" id="ihLoadVideo">Load recording ▶</button><div id="ihVideo"></div><div class="ih-frame-row">${frames.map((f,i)=>`<figure><img data-private="${f.id}" loading="lazy" alt="Capture frame ${i+1}"><figcaption>Frame ${i+1} · ${f.seconds}s<br>${esc(f.label)}</figcaption></figure>`).join('')}</div>`:''}${visual?.claims.length?`<div class="ih-section-title"><h2>Written claims</h2></div><ul class="ih-findings">${visual.claims.map(c=>`<li><strong>${esc(c.subject)} · ${esc({supported:'Supported',contradicted:'Contradicted',not_established:'Not established'}[c.finding])}</strong>${esc(c.evidence)}</li>`).join('')}</ul>`:''}${visual?.concerns.length?notice(visual.concerns.join(' '),'warning'):''}<p class="ih-note" style="margin-top:25px">${esc(scope)} Browser camera evidence is not hardware-attested.</p>`;
      $('.ih-report-head').insertAdjacentHTML('afterend',`<details class="ih-result-details"><summary>Private management link</summary>${managementBox(r)}</details>`);
      bindLinkButtons(page);bindMarkedDownloads(page);
      $('#ihExport').onclick = async()=>{try{download(await (await api('/requests/'+r.id+'/evidence',{},true)).blob(),'lockx-'+r.id.slice(0,8)+'-evidence.json');}catch(error){errorAt('#ihReportError',error);}};
      if (canRetry) $('#ihRetryAnalysis').onclick = async e=>{e.target.disabled=true;try{await json('/requests/'+r.id+'/analyze',{},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if (video) $('#ihLoadVideo').onclick = async e=>{e.target.disabled=true;try{const url=await privateURL(video.id);if(route!==routeNumber)return;$('#ihVideo').innerHTML=`<video class="ih-report-video" data-media-id="${video.id}" controls playsinline preload="metadata" src="${url}"></video>`;e.target.hidden=true;}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if ($('#ihPublishForm')) $('#ihPublishForm').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await json('/requests/'+r.id+'/publish',{publish_selected_photos:true},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);b.disabled=false;}};
      if ($('#ihWithdraw')) $('#ihWithdraw').onclick=async e=>{e.target.disabled=true;try{await api('/requests/'+r.id+'/publication',{method:'DELETE'},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if(loadedVideo&&video?.id===loadedVideo.dataset.mediaId){$('#ihVideo').append(loadedVideo);$('#ihLoadVideo').hidden=true;}
      // Poll only metadata; immutable media URLs survive processing-state changes.
      pollReport(id,route,r);
      // Sequential decoding bounds memory use on older phones.
      for (const img of page.querySelectorAll('[data-private]')) {
        try { const url = await privateURL(img.dataset.private); if(route!==routeNumber||render!==reportRenderNumber)return; img.src = url; } catch { img.alt += ' · unavailable'; }
      }
    } catch (error) { if (route===routeNumber&&render===reportRenderNumber) page.innerHTML = `<a class="ih-button text" href="#in-hand">← All inspections</a>${notice(error.message,'error')}`; }
  }
  function verifiedPhotoSet(publication) {
    const link=appLink('verify/'+publication.id);
    return `<section class="ih-verified-set" data-marked-publication="${esc(publication.id)}" aria-label="Your QR-marked verified photos"><div class="ih-verified-actions"><button type="button" class="ih-button ih-wide" data-save-all-photos disabled>Save all to Photos</button><button type="button" class="ih-button secondary ih-wide" data-copy="${esc(link)}">Copy verification link</button></div><p class="ih-save-photos-hint" data-save-photos-hint aria-live="polite">Preparing your verified JPEG images…</p><div id="ihMarkedError" class="ih-note error" role="alert" hidden></div><button type="button" class="ih-button secondary" data-marked-retry hidden>Prepare photos again</button><div class="ih-marked-gallery">${(publication.photos||[]).map((photo,i)=>`<figure><img src="${base}/public/${encodeURIComponent(publication.id)}/photos/${encodeURIComponent(photo.id)}" alt="Verified photo ${i+1} with LockX marking and QR code"><figcaption><strong>Photo ${i+1} · Verified</strong><button type="button" class="ih-button secondary" data-save-marked-photo="/public/${encodeURIComponent(publication.id)}/photos/${encodeURIComponent(photo.id)}" data-photo-index="${i}" data-download-name="lockx-${esc(publication.id)}-photo-${i+1}.jpg" disabled>Save photo ${i+1}</button></figcaption></figure>`).join('')}</div><a class="ih-button text" href="#in-hand/verify/${esc(publication.id)}">View public verification record ↗</a></section>`;
  }
  function clearMarkedFiles(){if(markedFiles){markedFiles.controller.abort();markedFiles.files=[];markedFiles.entries=[];markedFiles.listener=null;markedFiles=null;}}
  function canSharePhotos(files){try{return !!files.length&&typeof navigator.share==='function'&&typeof navigator.canShare==='function'&&navigator.canShare({files});}catch{return false;}}
  function bindMarkedDownloads(element) {
    const section=$('[data-marked-publication]',element);
    if(!section){clearMarkedFiles();return;}
    const buttons=$$('[data-save-marked-photo]',section),publication=section.dataset.markedPublication;
    const key=routeNumber+':'+publication+':'+buttons.map(button=>button.dataset.saveMarkedPhoto).join(',');
    if(markedFiles?.key!==key){
      clearMarkedFiles();
      const state={key,publication,route:routeNumber,controller:new AbortController(),entries:buttons.map(()=>({file:null,error:null})),files:[],pending:true,listener:null};markedFiles=state;
      // Prepare actual JPEG Files before a tap: Safari requires the native share call
      // itself to run synchronously within that tap's transient user activation.
      const timeout=setTimeout(()=>state.controller.abort(),20000);
      Promise.allSettled(buttons.map(async(button,index)=>{
        try{
          const blob=await(await api(button.dataset.saveMarkedPhoto,{signal:state.controller.signal})).blob();
          if(markedFiles!==state||state.route!==routeNumber||state.controller.signal.aborted)return;
          if(!blob.size||!/^image\/jpeg(?:;|$)/i.test(blob.type))throw Error('A verified photo could not be prepared.');
          state.entries[index].file=new File([blob],button.dataset.downloadName,{type:'image/jpeg'});
        }catch(error){if(markedFiles===state&&state.entries[index])state.entries[index].error=error;}
        if(markedFiles===state)state.listener?.();
      })).then(()=>{
        clearTimeout(timeout);if(markedFiles!==state)return;
        state.pending=false;state.files=state.entries.map(entry=>entry.file).filter(Boolean);state.listener?.();
      });
    }
    const state=markedFiles,allButton=$('[data-save-all-photos]',section),hint=$('[data-save-photos-hint]',section),errorBox=$('#ihMarkedError',section),retry=$('[data-marked-retry]',section);
    const current=()=>markedFiles===state&&state.route===routeNumber&&section.isConnected;
    function message(text,error=false){if(!current())return;if(error){errorBox.textContent=text;errorBox.hidden=false;}else{hint.textContent=text;errorBox.hidden=true;}}
    function update(){
      if(!current())return;
      const loaded=state.entries.filter(entry=>entry.file).length,failed=state.entries.some(entry=>entry.error);
      const complete=!state.pending&&loaded===buttons.length&&buttons.length>0,multiple=complete&&canSharePhotos(state.files),single=state.entries.some(entry=>entry.file&&canSharePhotos([entry.file]));
      allButton.disabled=!multiple;allButton.hidden=!state.pending&&!multiple;
      retry.hidden=state.pending||!failed;
      buttons.forEach((button,index)=>{const file=state.entries[index]?.file;button.disabled=!file;button.textContent=(file&&canSharePhotos([file])?'Save photo ':'Download JPEG ')+(index+1);});
      hint.textContent=state.pending?'Preparing your verified JPEG images…':multiple?'Select Save Images (iPhone), or a Photos/Gallery save option if available.':failed?'Some images could not be prepared. Try again, or press and hold each photo to use your phone’s save option.':single?'This browser shares one photo at a time. Use Save photo below, then choose your phone’s save option.':'This browser saves individual JPEGs to Downloads. To save to Photos, press and hold each image and choose its save option.';
    }
    state.listener=update;update();
    async function shareFiles(files,button){
      if(!current()||!canSharePhotos(files))return;
      const old=button.textContent;button.disabled=true;
      try{
        // No fetch or await before share; pass only image Files so iOS offers Save Images.
        const sharing=navigator.share({files});
        await sharing;
        message('Share menu closed. Photos are saved only if you chose its save option.');
      }catch(error){if(error.name!=='AbortError')message('The share menu could not save these photos. Press and hold an image to use your phone’s save option.',true);}
      finally{if(current()){button.disabled=false;button.textContent=old;}}
    }
    allButton.onclick=()=>{if(current()&&!state.pending&&state.files.length===buttons.length)shareFiles(state.files,allButton);};
    buttons.forEach((button,index)=>button.onclick=()=>{
      const file=state.entries[index]?.file;if(!current()||!file)return;
      if(canSharePhotos([file]))shareFiles([file],button);
      else{download(file,file.name);message('JPEG downloaded. This browser saves downloads separately from Photos. You can also press and hold the image to use your phone’s save option.');}
    });
    retry.onclick=()=>{clearMarkedFiles();bindMarkedDownloads(element);};
  }
  function publicationBox(r) {
    const p = r.publication;
    if (p?.revoked) return '<div class="ih-card" style="margin-top:25px"><h2>Public record withdrawn.</h2><p>The QR link now shows that this record was withdrawn. A new capture is needed to publish another set.</p></div>';
    if (p) return `<div class="ih-card ih-ready-card"><span class="ih-kicker">Ready to use in your listing</span><h2>Your verified photos are ready.</h2>${verifiedPhotoSet({...p,photos:r.media.filter(m=>m.role==='marked')})}<details class="ih-result-details"><summary>Publication controls</summary><button class="ih-button text" id="ihWithdraw">Withdraw public record</button></details></div>`;
    if(r.auto_publish)return `<div class="ih-card ih-ready-card"><h2>Your photos matched.</h2>${notice(r.publication_status==='failed'?'The QR images could not be prepared. Your comparison and recording are saved.':'Preparing the QR-marked photos automatically. This page updates when they are ready.')}</div>`;
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
  function hasLocalCaptureConsent(record=sellerData){return !!record?.auto_publish&&secretPattern.test(browserAccess.records[record.id]||'');}
  async function showSeller(token, route) {
    sellerToken=token;sellerData=null;
    shell('<div class="ih-standalone-content"><p>Opening your camera check…</p></div>');
    try {
      const r=await(await api('/seller/'+encodeURIComponent(token))).json();if(route!==routeNumber)return;sellerData=r;
      if(!['waiting','capturing'].includes(r.status)){showSellerResult(token,route);return;}
      const localConsent=hasLocalCaptureConsent(r);
      shell(`<div class="ih-standalone-content ih-camera-intro"><span class="ih-kicker">10-second video · No app or login</span><h1>Show the item.<br>Get verified photos.</h1><p>In one 10-second video, slowly show the views in your photos. Bring printed numbers and markings close enough to read.</p><div class="ih-seller-refs">${r.media.map((m,i)=>`<figure><img src="${base}/seller/${token}/photos/${m.id}" alt="Reference photo ${i+1}"><figcaption>Photo ${i+1}</figcaption></figure>`).join('')}</div>${notice(r.capture_mode==='stationary'?'Move your phone around the item. Do not lift or move a heavy appliance.':r.capture_mode==='digital'?'Use a second screen and hide usable barcodes. This check cannot establish ticket validity or transfer rights.':'Keep the same item in view, in good light. Show its front, back, sides, and photographed details. No microphone is used.')}<details class="ih-result-details ih-capture-options"><summary>Voice instructions</summary><label class="ih-voice-option"><input type="checkbox" id="ihVoiceConsent" ${voiceEnabled()?'checked':''}><span>Read instructions aloud <small>Optional · instructions are always shown on screen</small></span></label></details>${localConsent?'<p class="ih-capture-consent-note">Your permission is saved. Keep faces and private information out of the recording.</p>':'<label class="ih-seller-consent"><input type="checkbox" id="ihSellerConsent"><span>I have permission to show this item and consent to recording and comparison with these photos. I will keep faces and private information out of view.</span></label>'}<div id="ihCaptureError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihStartCapture">Record 10-second video →</button><p class="ih-scan-target">Recording stops automatically. ${r.auto_publish?'If every photo matches, your QR-marked photos appear here automatically.':'Results appear here when comparison finishes.'} Unclear photos stay unverified.</p></div>`);
      $('#ihStartCapture').onclick=startCapture;
      if(!('speechSynthesis' in window))$('#ihVoiceConsent').closest('details').hidden=true;
      if(window.LOCKX_LOCAL_PREVIEW)$('#ihCaptureError').insertAdjacentHTML('beforebegin',notice('Local preview: automated comparison is disabled. Captures made here cannot earn a verified marking.','warning'));
    }catch(error){if(route===routeNumber)shell(`<div class="ih-standalone-content"><h1>Link unavailable.</h1>${notice(error.message,'error')}<p>Ask the inspection owner for a new mobile link.</p></div>`);}
  }
  async function showSellerResult(token,route,started=Date.now()) {
    clearTimeout(poll);
    if(route!==routeNumber)return;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{
      const result=await(await api('/seller/'+encodeURIComponent(token)+'/result',{signal:controller.signal})).json();
      if(route!==routeNumber)return;
      const waitingForMarks=result.status==='confirmed'&&result.auto_publish&&result.publication_status==='pending';
      const pending=result.status==='processing'||waitingForMarks,count=sellerData?.media.length||result.photos.length;
      const ready=result.status==='confirmed'&&result.publication_status==='ready'&&result.publication?.photos?.length===count;
      const title=ready?'Your verified photos are ready.':waitingForMarks?'Creating your QR-marked photos.':pending?`Comparing your ${count} photos.`:result.status==='confirmed'?'Your photo match is confirmed.':result.status==='mismatch'?'Some photos did not match.':'More evidence is needed.';
      const findings=new Map(result.photos.map(photo=>[photo.photo_index,photo]));
      const identifiers=sellerData?.capture_mode==='digital'?[]:(result.identifier_checks||[]);
      const numberChecks=identifiers.length?`<section class="ih-number-checks"><h2>Numbers & markings</h2>${identifiers.map(item=>`<article><header><strong>${esc(item.label)} · Photo ${item.photo_index+1}</strong><span>${esc({supported:'Matches',contradicted:'Different',not_established:'Unclear'}[item.finding]||'Unclear')}</span></header><div><p><small>IN PHOTO</small><code>${esc(item.reference_text||'Not readable')}</code></p><p><small>IN VIDEO</small><code>${esc(item.video_text||'Not readable')}</code></p></div><p>${esc(item.evidence)}</p></article>`).join('')}</section>`:'';
      const knownKey=browserAccess.records[result.id],ownerLink=secretPattern.test(knownKey||'')?appLink('report/'+result.id+'/'+knownKey):'';
      const comparison=`<div class="ih-phone-photo-results">${(sellerData?.media||[]).map((photo,i)=>{const finding=findings.get(i);return `<figure><img src="${base}/seller/${encodeURIComponent(token)}/photos/${photo.id}" alt="Selected photo ${i+1}"><figcaption><strong>Photo ${i+1} · ${result.status==='processing'?'Comparing…':esc({supported:'Match supported',contradicted:'Mismatch',not_established:'Not established'}[finding?.finding]||'Not established')}</strong><span>${result.status==='processing'?'Checking against frames from your recording.':esc(finding?.evidence||'The recording did not establish this photo match.')}</span></figcaption></figure>`;}).join('')}</div>${numberChecks}${ownerLink?`<a class="ih-button text" href="${esc(ownerLink)}">Private evidence & record controls →</a>`:''}`;
      const publicationNote=result.publication_status==='withdrawn'?notice('The public verification record was withdrawn. Its photos no longer carry an active verification record.','warning'):result.publication_status==='failed'?notice('Your photo match is confirmed, but the QR images could not be prepared. Your recording is saved.','warning'):'';
      shell(`<div class="ih-standalone-content ih-phone-results"><span class="ih-kicker">${ready?'✓ All photos matched':`Camera off · ${waitingForMarks?'Preparing verified photos':pending?'AI comparison in progress':'Photo-by-photo result'}`}</span><h1>${esc(title)}</h1><p>${ready?'Your QR-marked images are ready to save and use in your listing. Each QR code opens this photo set’s LockX verification record.':esc(result.summary)}</p>${pending?notice(Date.now()-started>90000?'This is taking longer than usual. Your camera is off and the recording is saved. This page will update automatically.':waitingForMarks?'Every photo matched. Adding its verified marking and QR code now…':result.auto_publish?'LockX is checking every photo against the recording. Your verified images will appear here automatically if they all match.':'LockX is checking every photo against the recording. This page updates automatically.'):''}${publicationNote}${ready?verifiedPhotoSet(result.publication)+`<details class="ih-result-details"><summary>Comparison details</summary>${comparison}</details>`:comparison}${result.publication_status==='failed'&&ownerLink?`<p><a class="ih-button secondary ih-wide" href="${esc(ownerLink)}">Open saved record</a></p>`:''}<p class="ih-note">${esc(result.scope||scope)}</p></div>`);
      bindLinkButtons(standalone);bindMarkedDownloads(standalone);
      if(pending)poll=setTimeout(()=>showSellerResult(token,route,started),Date.now()-started>30000?5000:1500);
    }catch(error){
      if(route!==routeNumber)return;
      shell(`<div class="ih-standalone-content"><span class="ih-kicker">Camera off · recording received</span><h1>Checking your result.</h1>${notice(error.message,'warning')}<p>Your recording has been sent. Keep this private camera link to return to the comparison.</p><button class="ih-button ih-wide" id="ihRefreshSellerResult">Check again</button></div>`);
      $('#ihRefreshSellerResult').onclick=()=>showSellerResult(token,route,started);
      poll=setTimeout(()=>showSellerResult(token,route,started),5000);
    }finally{clearTimeout(timeout);}
  }
  function voiceEnabled(){try{return localStorage.getItem('lockx-scan-voice')==='on';}catch{return false;}}
  function speak(current,text){if(!current?.voice||!window.speechSynthesis||current.cancelled)return;try{speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.rate=.95;speechSynthesis.speak(utterance);}catch{}}
  function activeCapture(current){return !!current&&capture===current&&!current.cancelled&&current.route===routeNumber;}
  function stopQualityLoop(current){clearTimeout(current.frameTimer);if(current.frameCallback!==undefined)try{current.video?.cancelVideoFrameCallback(current.frameCallback);}catch{}current.frameCallback=undefined;}
  function stopCapture(discard = true) {
    const current=capture;if(!current)return;
    if(discard)current.cancelled=true;
    clearInterval(current.timer);clearTimeout(current.limit);clearTimeout(current.retryTimer);clearTimeout(current.progressTimer);clearTimeout(current.startTimer);clearTimeout(current.finalizeTimer);clearTimeout(current.playTimer);stopQualityLoop(current);
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
    if(!hasLocalCaptureConsent()&&!$('#ihSellerConsent')?.checked){errorAt('#ihCaptureError',Error('Please agree to the recording before starting.'));return;}
    const button=$('#ihStartCapture');button.disabled=true;button.textContent='Opening camera…';
    const voice=!!$('#ihVoiceConsent')?.checked;try{localStorage.setItem('lockx-scan-voice',voice?'on':'off');}catch{}
    let current=null;const route=routeNumber;
    try {
      if(typeof window.LockXCapture?.stopRecorder!=='function')throw Error('The camera update has not loaded. Reload this page, then try again.');
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('Open this link over HTTPS in Safari or Chrome to use the camera.');
      if(!window.MediaRecorder)throw Error('This browser cannot record the item. Open the link in Safari or Chrome.');
      const portrait=window.innerHeight>=window.innerWidth;
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:portrait?720:1280,max:1280},height:{ideal:portrait?960:720,max:1280},aspectRatio:{ideal:portrait ? .75 : 16/9},frameRate:{ideal:20,max:24}},audio:false});
      if(route!==routeNumber||!isStandalone||!location.hash.includes('/capture/')){stream.getTracks().forEach(t=>t.stop());return;}
      current={stream,queue:[],nextSequence:0,uploadedCount:0,bytesTotal:0,uploadedBytes:0,cancelled:false,intentionalStop:false,route,voice};capture=current;
      const mime=['video/mp4','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
      const recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:1_200_000});current.recorder=recorder;
      recorder.ondataavailable=e=>enqueueChunks(current,e.data);
      recorder.onerror=()=>{if(activeCapture(current)&&!current.finishing)captureFailed('The browser interrupted the recording. Please record a fresh 10-second video.');};
      stream.getVideoTracks().forEach(t=>t.onended=()=>{if(activeCapture(current)&&!current.intentionalStop)captureFailed('Camera access ended. Please record a fresh 10-second video.');});
      renderCamera(current);current.video=$('#ihLiveVideo');current.video.srcObject=stream;
      const play=current.video.play();await Promise.race([play,new Promise((_,reject)=>{current.playTimer=setTimeout(()=>reject(Error('The camera preview did not open. Please reopen this link in Safari or Chrome.')),8000);})]);clearTimeout(current.playTimer);
      if(!activeCapture(current))return;
      current.layoutHandler=()=>positionReticle(current);window.addEventListener('resize',current.layoutHandler);window.visualViewport?.addEventListener('resize',current.layoutHandler);
      if(window.ResizeObserver){current.layoutObserver=new ResizeObserver(current.layoutHandler);current.layoutObserver.observe(current.video);current.layoutObserver.observe($('.ih-scan-bottom'));}
      current.startRequest=new AbortController();const controller=current.startRequest;current.startTimer=setTimeout(()=>controller.abort(),15000);
      const session=await(await api('/seller/'+sellerToken+'/video/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:controller.signal})).json();
      clearTimeout(current.startTimer);if(!activeCapture(current))return;
      current.sessionID=session.session_id;current.seconds=10;
      current.recordingStarted=performance.now();current.wallStarted=Date.now();recorder.start(1000);
      $('#ihRecorderState').textContent='REC';$('#ihInstructionTitle').textContent='Show the views in your photos.';$('#ihInstruction').textContent=session.stage.instruction;
      $('.ih-auto-camera').dataset.kind='motion';positionReticle(current);
      speak(current,'Recording for ten seconds. Slowly show the item from the views in your photos.');
      const pulse=()=>{
        if(!activeCapture(current)||current.finishing)return;
        const elapsed=Math.max(performance.now()-current.recordingStarted,Date.now()-current.wallStarted)/1000;
        $('#ihElapsed').textContent='0:'+String(Math.min(10,Math.floor(elapsed))).padStart(2,'0');$('#ihRemaining').textContent=Math.max(0,10-Math.floor(elapsed))+'s left';
        $('#ihStepProgress').style.width=Math.min(100,elapsed*10)+'%';
        renderUploadStatus(current);
        if(elapsed>=10){finishCapture(current);return;}
        if(!current.lastSample||performance.now()-current.lastSample>=450){current.lastSample=performance.now();updateCameraFeedback(current);}
      };
      current.timer=setInterval(pulse,250);
      // Independent of camera-frame callbacks and quality heuristics: recording always ends.
      current.limit=setTimeout(()=>{if(activeCapture(current)&&!current.finishing)finishCapture(current);},10000);
      pulse();pumpChunks(current);
    }catch(error){
      clearTimeout(current?.playTimer);clearTimeout(current?.startTimer);
      if(current?.cancelled||route!==routeNumber)return;
      const message=error.name==='NotAllowedError'?'Allow camera access in your browser settings, then try again.':error.name==='NotFoundError'?'No camera was found. Open this link on your phone.':error.name==='NotReadableError'?'The camera is busy. Close other camera apps and try again.':error.name==='AbortError'?'The connection could not start recording. Reconnect and try again.':error.message;
      if($('#ihCaptureError')){stopCapture();errorAt('#ihCaptureError',Error(message));button.disabled=false;button.textContent='Try camera again →';}else captureFailed(message);
    }
  }
  function renderCamera(current){
    document.body.classList.add('ih-scanning');
    standalone.innerHTML=`<div class="ih-auto-camera"><video id="ihLiveVideo" autoplay playsinline muted aria-label="Live item camera"></video><div class="ih-scan-shade"></div><header class="ih-scan-head"><span class="ih-scan-brand">lock<span>x</span></span><span class="ih-live"><i></i> <span id="ihRecorderState">READY</span> <span id="ihElapsed">0:00</span></span><button id="ihCancelCapture" class="ih-scan-close" aria-label="Cancel recording">×</button></header><div class="ih-scan-reticle" aria-hidden="true"><i></i><i></i><i></i><i></i></div><div class="ih-scan-bottom"><div class="ih-scan-instruction"><span class="ih-scan-caption">10-SECOND VIDEO · STOPS AUTOMATICALLY</span><div class="ih-video-countdown" id="ihRemaining" role="timer">10s left</div><h2 id="ihInstructionTitle">Getting the camera ready.</h2><p id="ihInstruction">Show the front, sides, back, and details in your selected photos.</p></div><div class="ih-scan-feedback" id="ihQualityFeedback" role="status">The timer starts when recording begins.</div><div class="ih-scan-progress"><span id="ihStepProgress"></span></div><div class="ih-reference-chips" aria-label="Photos to compare after recording">${sellerData.media.map((m,i)=>`<div class="ih-reference-chip"><img src="${base}/seller/${sellerToken}/photos/${m.id}" alt="Selected photo ${i+1}"><span>${i+1}</span><small>To compare</small></div>`).join('')}</div><footer class="ih-scan-footer"><button type="button" id="ihVoiceToggle" aria-pressed="${current.voice}">${current.voice?'◖ Voice on':'◖ Voice off'}</button><span id="ihStreamingStatus">Preparing recording upload</span></footer><p class="ih-capture-scope">AI compares every photo after the 10-second video.</p></div></div>`;
    $('#ihCancelCapture').onclick=()=>{stopCapture();showSeller(sellerToken,routeNumber);};
    $('#ihVoiceToggle').hidden=!('speechSynthesis' in window);
    $('#ihVoiceToggle').onclick=e=>{current.voice=!current.voice;e.currentTarget.setAttribute('aria-pressed',String(current.voice));e.currentTarget.textContent=current.voice?'◖ Voice on':'◖ Voice off';try{localStorage.setItem('lockx-scan-voice',current.voice?'on':'off');}catch{}if(!current.voice)try{speechSynthesis.cancel();}catch{}};
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
  function updateCameraFeedback(current){
    // Advisory only. Exposure changes, hand motion and missing frame callbacks cannot extend recording.
    try{
      const metrics=sampleQuality(current),feedback=$('#ihQualityFeedback');if(!metrics||!feedback)return;
      feedback.textContent=metrics.brightness<24?'Add light while you slowly show the item.':metrics.brightness>240?'Reduce glare while you show the item.':metrics.sharpness<18?'Move closer so identifying details are visible.':'Show the views, markings, and readable numbers.';
    }catch{}
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
    if(!activeCapture(current)||current.finishing)return;
    current.finishing=true;current.intentionalStop=true;current.recordingSeconds=(performance.now()-current.recordingStarted)/1000;
    clearInterval(current.timer);clearTimeout(current.limit);stopQualityLoop(current);
    try{speechSynthesis.cancel();}catch{}
    // The stop helper shuts camera tracks immediately and bounds Safari's final stop event.
    let saved;
    try{saved=LockXCapture.stopRecorder(current.recorder,current.stream,{timeoutMs:4000});}
    catch(error){try{current.recorder.stop();}catch{}current.stream.getTracks().forEach(track=>{try{track.stop();}catch{}});captureFailed('The camera is off, but the recording could not be saved. Reload this page and record again.');return;}
    current.layoutObserver?.disconnect();window.removeEventListener('resize',current.layoutHandler);window.visualViewport?.removeEventListener('resize',current.layoutHandler);
    document.body.classList.remove('ih-scanning');
    shell(`<div class="ih-standalone-content"><span class="ih-kicker">Camera off · saving your 10-second video</span><h1>Recording finished.</h1><p>Sending the recording, then comparing it with all ${sellerData.media.length} selected photos. Keep this page open to see each result.</p><progress id="ihUploadProgress" class="ih-upload-progress" max="100" value="0"></progress><p id="ihUploadLabel">Saving the last video frame…</p><div id="ihUploadError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihRetryUpload" hidden>Retry upload · no new recording needed</button><p class="ih-scan-target">Recording has stopped. Upload and AI comparison can take longer on a slow connection.</p></div>`);
    try{await saved;}catch(error){if(activeCapture(current))captureFailed(error.message);return;}
    if(!activeCapture(current))return;current.sampleCanvas=null;current.previousFrame=null;
    $('#ihRetryUpload').onclick=()=>uploadCapture(current);await uploadCapture(current);
  }
  async function uploadCapture(current) {
    if(!activeCapture(current)||current.finalizing)return;current.finalizing=true;$('#ihRetryUpload').hidden=true;$('#ihUploadError').hidden=true;
    try{
      current.uploadPaused=false;await pumpChunks(current);if(!activeCapture(current))return;
      if(current.queue.length||current.uploadPaused)throw current.uploadError||Error('The connection paused. Keep this page open and retry.');
      if(!current.uploadedCount)throw Error('The browser did not save any video. Please start a fresh scan.');
      renderUploadStatus(current);current.progressRequest=new AbortController();current.finalizeTimer=setTimeout(()=>current.progressRequest?.abort(),30000);
      try{await api('/seller/'+sellerToken+'/scan/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:current.sessionID,consent:true,source:'browser_camera',chunk_count:current.uploadedCount,recording_seconds:current.recordingSeconds}),signal:current.progressRequest.signal});}
      catch(error){if(error.status!==409)throw error;const state=await(await api('/seller/'+sellerToken)).json();if(['waiting','capturing'].includes(state.status))throw error;}
      if(!activeCapture(current))return;current.queue=[];capture=null;
      await showSellerResult(sellerToken,current.route);
    }catch(error){if(activeCapture(current)){errorAt('#ihUploadError',error);$('#ihRetryUpload').hidden=false;renderUploadStatus(current);}}
    finally{clearTimeout(current.finalizeTimer);current.finalizing=false;}
  }
  function captureFailed(message) {
    stopCapture();shell(`<div class="ih-standalone-content"><span class="ih-kicker">A fresh capture is needed</span><h1>Let’s try that again.</h1>${notice(message,'warning')}<p>The camera is off. Use one uninterrupted 10-second recording with the same item throughout.</p><button class="ih-button ih-wide" id="ihRestart">Start again</button></div>`);$('#ihRestart').onclick=()=>showSeller(sellerToken,routeNumber);
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
