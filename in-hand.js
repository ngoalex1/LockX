/* Browser capture is evidence, not hardware attestation or product authentication. */
(() => {
  'use strict';
  const base = API_BASE + '/in-hand';
  const $ = (s, p = document) => p.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = t => t ? new Date(t * 1000).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'}) : 'Not recorded';
  const labels = {waiting:'Awaiting capture',capturing:'Capture started',processing:'Comparing evidence',confirmed:'In-hand confirmed',mismatch:'Mismatch found',inconclusive:'More evidence needed',expired:'Link expired'};
  const scope = 'This records a visual match at the capture time. It does not certify product authenticity, ownership, current possession, ticket validity, or delivery.';
  let photos = [], draft = {}, capabilities = null, routeNumber = 0, poll = null, reportURLs = [], capture = null, sellerData = null, sellerToken = null, isStandalone = false;
  let managementKey = '';
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
  function revokeReports() { reportURLs.forEach(URL.revokeObjectURL); reportURLs = []; }
  async function privateURL(id) { const url = URL.createObjectURL(await (await api('/media/' + id, {}, true)).blob()); reportURLs.push(url); return url; }
  function showHome() {
    page.innerHTML = `${heading()}<div class="ih-layout"><div><form id="ihRequestForm" class="ih-card"><div class="ih-card-top"><span class="ih-step-number">01</span><div><h2>Choose the photos to verify.</h2><p>Four views tell a good story. Select up to six.</p></div></div><label>Item name<input name="title" required maxlength="160" placeholder="e.g. Pokémon Charizard card · 1999" autocomplete="off"></label><div class="ih-fields"><label>Category<input name="category" maxlength="80" placeholder="Cards, electronics, appliances…" value="Other"></label><label>How can it be shown?<select name="capture_mode"><option value="handheld">Hold and turn the item</option><option value="flat">Card, paper, or flat item</option><option value="stationary">Move the phone around a large item</option><option value="digital">Digital ticket · visible details only</option></select></label></div><div id="ihDigitalNote" class="ih-note warning" hidden>A screen recording cannot establish ticket validity or exclusive transfer rights. Digital tickets receive a limited evidence report and cannot earn the physical-item marking.</div><label>Listing description <small>Optional</small><textarea name="description" maxlength="6000" placeholder="Paste what the listing says. LockX will also assess which claims the camera can support."></textarea></label><label>Distinguishing details <small>Optional</small><input name="details" maxlength="1200" placeholder="Wear, markings, identifiers, included accessories…"></label><div class="ih-upload"><button type="button" class="ih-button secondary" id="ihChoosePhotos">＋ Add listing photos</button><input id="ihPhotoInput" type="file" accept="image/*" multiple hidden><p>Up to 6 selected photos · Photos are resized before upload.</p></div><div id="ihPhotoGrid" class="ih-photo-grid"></div><div id="ihPhotoError" class="ih-note error" role="alert" hidden></div><label class="ih-check"><input type="checkbox" name="consent" required><span>I have permission to submit these photos and process the item recording. Photos remain private until I choose to publish a confirmed set.</span></label><div id="ihCreateError" class="ih-note error" role="alert" hidden></div><div class="ih-form-footer"><small>No login needed to create a check or view your results. The camera link lasts 24 hours.</small><button class="ih-button" type="submit" id="ihCreate">Create mobile link <span>→</span></button></div><div id="ihCreated"></div></form></div><aside class="ih-aside ih-card"><h3>From listing to confidence.</h3><ol><li><strong>Select the exact photos</strong>Keep a record of the images and description you want checked.</li><li><strong>Open the link on a phone</strong>Follow changing instructions to turn the item and show identifying details.</li><li><strong>Compare every selected view</strong>Each photo needs evidence from the capture. Unclear results stay unverified.</li><li><strong>Share a confirmed set</strong>Download QR-marked photos linked to a public LockX record.</li></ol><div class="ih-note">${esc(scope)}</div></aside></div><div class="ih-section-title"><h2>Your inspections on this browser</h2><button class="ih-button text" id="ihRefresh">Refresh ↻</button></div><div id="ihRequests" aria-live="polite"></div>`;
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
  async function showReport(id, route) {
    revokeReports();
    page.innerHTML = '<p class="ih-kicker">Private inspection record</p><p>Loading evidence…</p>';
    try {
      const r = await (await api('/requests/' + encodeURIComponent(id),{},true)).json();
      if (route !== routeNumber) return;
      const refs = r.media.filter(m=>m.role==='listing'), frames = r.media.filter(m=>m.role==='frame'), video = r.media.find(m=>m.role==='video'), visual = r.analysis?.visual;
      const findings = new Map((visual?.photos||[]).map(p=>[p.photo_index,p]));
      const canRetry = ['unavailable','failed'].includes(r.analysis_status);
      page.innerHTML = `<div class="ih-report-head"><div><a class="ih-button text" href="#in-hand">← All inspections</a><p class="ih-kicker">Private evidence record · ${esc(r.id.slice(0,8))}</p><h1>${esc(r.title)}</h1><span class="ih-status ${esc(r.status)}">${esc(labels[r.status]||r.status)}</span></div><button class="ih-button secondary" id="ihExport">Export evidence record ↓</button></div>${notice(r.analysis?.summary || (r.status==='expired'?'This link expired before a recording was submitted. Create a new inspection to capture fresh evidence.':'Send the mobile link to the person holding the item.'))}${canRetry?`<p>${notice('Automated comparison has not established a match. No verified marking is available for this capture.','warning')}</p><button class="ih-button secondary" id="ihRetryAnalysis">Try comparison again</button>`:''}${['waiting','capturing'].includes(r.status)?linkBox(r):''}<div id="ihReportError" class="ih-note error" hidden></div><div class="ih-section-title"><h2>Selected photos · ${refs.length}</h2></div><div class="ih-evidence-grid">${refs.map((p,i)=>{const f=findings.get(i);return `<figure><img data-private="${p.id}" alt="Reference photo ${i+1}"><figcaption><strong>Photo ${i+1} · ${f?esc({supported:'Match supported',contradicted:'Mismatch',not_established:'Not established'}[f.finding]):'Awaiting comparison'}</strong>${f?esc(f.evidence):esc(r.photo_notes[i]||'Exact selected reference photo.')}${f?.frame_indices.length?`<br>Capture frames: ${f.frame_indices.map(n=>n+1).join(', ')}`:''}</figcaption></figure>`;}).join('')}</div>${video?`<div class="ih-section-title"><h2>Camera evidence</h2></div><button class="ih-button secondary" id="ihLoadVideo">Load recording ▶</button><div id="ihVideo"></div><div class="ih-frame-row">${frames.map((f,i)=>`<figure><img data-private="${f.id}" loading="lazy" alt="Capture frame ${i+1}"><figcaption>Frame ${i+1} · ${f.seconds}s<br>${esc(f.label)}</figcaption></figure>`).join('')}</div>`:''}${visual?.claims.length?`<div class="ih-section-title"><h2>Written claims</h2></div><ul class="ih-findings">${visual.claims.map(c=>`<li><strong>${esc(c.subject)} · ${esc({supported:'Supported',contradicted:'Contradicted',not_established:'Not established'}[c.finding])}</strong>${esc(c.evidence)}</li>`).join('')}</ul>`:''}${visual?.concerns.length?notice(visual.concerns.join(' '),'warning'):''}${r.status==='confirmed'?publicationBox(r):''}<p class="ih-note" style="margin-top:25px">${esc(scope)} Browser camera evidence is not hardware-attested.</p>`;
      $('.ih-report-head').insertAdjacentHTML('afterend',managementBox(r));
      bindLinkButtons(page);
      $('#ihExport').onclick = async()=>{try{download(await (await api('/requests/'+r.id+'/evidence',{},true)).blob(),'lockx-'+r.id.slice(0,8)+'-evidence.json');}catch(error){errorAt('#ihReportError',error);}};
      if (canRetry) $('#ihRetryAnalysis').onclick = async e=>{e.target.disabled=true;try{await json('/requests/'+r.id+'/analyze',{},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if (video) $('#ihLoadVideo').onclick = async e=>{e.target.disabled=true;try{const url=await privateURL(video.id);if(route!==routeNumber)return;$('#ihVideo').innerHTML=`<video class="ih-report-video" controls playsinline preload="metadata" src="${url}"></video>`;e.target.hidden=true;}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if ($('#ihPublishForm')) $('#ihPublishForm').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await json('/requests/'+r.id+'/publish',{publish_selected_photos:true},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);b.disabled=false;}};
      if ($('#ihWithdraw')) $('#ihWithdraw').onclick=async e=>{e.target.disabled=true;try{await api('/requests/'+r.id+'/publication',{method:'DELETE'},true);showReport(id,route);}catch(error){errorAt('#ihReportError',error);e.target.disabled=false;}};
      if ($('#ihDownloadMarked')) $('#ihDownloadMarked').onclick=async e=>{e.target.disabled=true;try{download(await(await api('/requests/'+r.id+'/marked-photos',{},true)).blob(),'lockx-'+r.publication.id+'-verified-photos.zip');}catch(error){errorAt('#ihReportError',error);}finally{e.target.disabled=false;}};
      // Sequential decoding bounds memory use on older phones.
      for (const img of page.querySelectorAll('[data-private]')) {
        try { const url = await privateURL(img.dataset.private); if(route!==routeNumber)return; img.src = url; } catch { img.alt += ' · unavailable'; }
      }
      if (r.status==='processing' && route===routeNumber) poll=setTimeout(()=>{revokeReports();showReport(id,route);},6000);
    } catch (error) { if (route===routeNumber) page.innerHTML = `<a class="ih-button text" href="#in-hand">← All inspections</a>${notice(error.message,'error')}`; }
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
      shell(`<div class="ih-standalone-content"><span class="ih-kicker">Private camera check · No app needed</span><h1>Let’s see the item<br>in your hands.</h1><p>Show <strong>${esc(r.title)}</strong> from the angles below. You’ll follow one instruction at a time in a continuous recording.</p><div class="ih-seller-refs">${r.media.map((m,i)=>`<figure><img src="${base}/seller/${token}/photos/${m.id}" alt="Reference photo ${i+1}"><figcaption>Reference ${i+1}</figcaption></figure>`).join('')}</div>${notice(r.capture_mode==='stationary'?'Move your phone around the item. Do not lift or move a heavy appliance.':r.capture_mode==='digital'?'Use a second screen and hide usable barcodes. This check cannot establish ticket validity or transfer rights.':'Use good light, clear a little space, and keep the same item in view. No microphone is used.')}<label class="ih-seller-consent"><input type="checkbox" id="ihSellerConsent"><span>I have permission to show this item and consent to recording and comparison with these reference photos. I will keep faces and private information out of view.</span></label><div id="ihCaptureError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihStartCapture">Start camera check →</button><p style="text-align:center;font-size:11px">Usually 1–2 minutes · Rear camera · One continuous take</p></div>`);
      $('#ihStartCapture').onclick=startCapture;
      if(window.LOCKX_LOCAL_PREVIEW)$('#ihCaptureError').insertAdjacentHTML('beforebegin',notice('Local preview: automated comparison is disabled. Captures made here cannot earn a verified marking.','warning'));
    }catch(error){if(route===routeNumber)shell(`<div class="ih-standalone-content"><h1>Link unavailable.</h1>${notice(error.message,'error')}<p>Ask the inspection owner for a new mobile link.</p></div>`);}
  }
  function stopCapture(discard = true) {
    const current=capture;if(!current)return;
    clearInterval(current.timer);clearTimeout(current.limit);
    current.intentionalStop=true;
    if(current.recorder?.state!=='inactive'){try{current.recorder?.stop();}catch{}}
    current.stream?.getTracks().forEach(t=>t.stop());
    if(discard){current.cancelled=true;capture=null;}
  }
  async function startCapture() {
    if(!$('#ihSellerConsent')?.checked){errorAt('#ihCaptureError',Error('Please agree to the recording before starting.'));return;}
    const button=$('#ihStartCapture');button.disabled=true;button.textContent='Opening camera…';
    let current=null;const route=routeNumber;
    try {
      if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)throw Error('Open this link over HTTPS in Safari or Chrome to use the camera.');
      if(!window.MediaRecorder)throw Error('This browser cannot record the inspection. Open the link in Safari or Chrome.');
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720},frameRate:{ideal:20,max:24}},audio:false});
      if(route!==routeNumber || !isStandalone || !location.hash.includes('/capture/')){stream.getTracks().forEach(t=>t.stop());return;}
      const mime=['video/mp4','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
      current={stream,chunks:[],cancelled:false,intentionalStop:false,stage:null,qualityRetries:0,route:routeNumber};capture=current;
      const recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:1_200_000});current.recorder=recorder;
      recorder.ondataavailable=e=>{if(e.data.size)current.chunks.push(e.data);};
      recorder.onerror=()=>captureFailed('The camera recording was interrupted. Please start a fresh check.');
      stream.getVideoTracks().forEach(t=>t.onended=()=>{if(!current.intentionalStop)captureFailed('Camera access ended. Please start a fresh check.');});
      recorder.start(1000);
      const stage=await json('/seller/'+sellerToken+'/start',{});
      if(current.cancelled)return;
      shell(`<div class="ih-camera-screen"><div class="ih-camera-view"><video id="ihLiveVideo" autoplay playsinline muted></video><span class="ih-live"><i></i> RECORDING <span id="ihElapsed">0:00</span></span><div class="ih-target" id="ihTarget" hidden><img id="ihTargetPhoto" alt="Reference view to match"><small id="ihTargetLabel"></small></div></div><div class="ih-camera-controls"><div class="ih-camera-step"><span id="ihStepNumber"></span><span>ONE CONTINUOUS TAKE</span></div><div class="ih-progress-line"><span id="ihStepProgress"></span></div><h2 id="ihInstructionTitle"></h2><p id="ihInstruction"></p><div id="ihQualityFeedback" class="ih-note warning" hidden></div><button class="ih-button ih-wide" id="ihNextView">Hold steady…</button><button class="ih-button text ih-wide" id="ihQualityOverride" hidden>Continue with a quality warning</button><button class="ih-camera-cancel" id="ihCancelCapture">Cancel and restart</button></div></div>`);
      const video=$('#ihLiveVideo');video.srcObject=stream;await video.play();
      current.clientStarted=Date.now();
      $('#ihNextView').onclick=()=>advanceCapture(false);$('#ihQualityOverride').onclick=()=>advanceCapture(true);
      $('#ihCancelCapture').onclick=()=>{stopCapture();showSeller(sellerToken,routeNumber);};
      updateStage(stage);
      current.timer=setInterval(()=>{
        if(capture!==current)return;
        const seconds=Math.floor((Date.now()-current.clientStarted)/1000);$('#ihElapsed').textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
        const remaining=Math.max(0,Math.ceil((current.readyAt-Date.now())/1000));const b=$('#ihNextView');if(!current.busy){b.disabled=remaining>0;b.textContent=remaining?`Hold this view · ${remaining}s`:current.stage.position+1===current.stage.total?'Finish recording →':'Check this view →';}
      },250);
      current.limit=setTimeout(()=>captureFailed('This check reached two minutes. Please start again and follow each prompt without long pauses.'),118000);
    }catch(error){
      if(current?.cancelled)return;
      stopCapture();
      const message=error.name==='NotAllowedError'?'Allow camera access in your browser settings, then try again.':error.name==='NotFoundError'?'No camera was found. Open this link on your phone.':error.name==='NotReadableError'?'The camera is busy. Close other camera apps and try again.':error.message;
      if($('#ihCaptureError')){errorAt('#ihCaptureError',Error(message));button.disabled=false;button.textContent='Try camera again →';}else captureFailed(message);
    }
  }
  function updateStage(stage) {
    const current=capture;if(!current)return;current.stage=stage;current.qualityRetries=0;current.readyAt=Date.now()+stage.minimum_seconds*1000;
    $('#ihStepNumber').textContent=`VIEW ${stage.position+1} OF ${stage.total}`;
    $('#ihStepProgress').style.width=(stage.position/stage.total*100)+'%';
    $('#ihInstructionTitle').textContent=stage.stage.label;$('#ihInstruction').textContent=stage.stage.instruction;
    $('#ihQualityFeedback').hidden=true;$('#ihQualityOverride').hidden=true;
    const i=stage.stage.photo_index, target=$('#ihTarget');target.hidden=i===null;
    if(i!==null){$('#ihTargetPhoto').src=base+'/seller/'+sellerToken+'/photos/'+sellerData.media[i].id;$('#ihTargetLabel').textContent='PHOTO '+(i+1);}
  }
  function cameraFrame() {
    const video=$('#ihLiveVideo');if(!video?.videoWidth)throw Error('The camera is still opening. Wait a moment, then try again.');
    const canvas=document.createElement('canvas'),ratio=Math.min(1,720/video.videoWidth);canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);const image=canvas.toDataURL('image/jpeg',.8);canvas.width=canvas.height=1;return image;
  }
  async function advanceCapture(override) {
    const current=capture;if(!current||current.busy)return;current.busy=true;$('#ihNextView').disabled=true;$('#ihNextView').textContent='Checking camera view…';$('#ihQualityOverride').hidden=true;
    try {
      const next=await json('/seller/'+sellerToken+'/progress',{session_id:current.stage.session_id,stage_id:current.stage.stage.id,image:cameraFrame(),continue_with_quality_issue:override});
      if(current.cancelled)return;
      if(next.retry){current.qualityRetries++;$('#ihQualityFeedback').textContent=next.feedback;$('#ihQualityFeedback').hidden=false;$('#ihQualityOverride').hidden=current.qualityRetries<2;}
      else if(next.complete){current.stage=next;await finishCapture(current);return;}
      else updateStage(next);
    }catch(error){if(!current.cancelled){if(current.stage.complete||[409,410].includes(error.status)){captureFailed(error.message);return;}$('#ihQualityFeedback').textContent=error.message;$('#ihQualityFeedback').hidden=false;}}
    finally{current.busy=false;}
  }
  async function finishCapture(current) {
    clearInterval(current.timer);clearTimeout(current.limit);current.intentionalStop=true;
    const stopped=new Promise((resolve,reject)=>{current.recorder.onstop=resolve;current.recorder.onerror=()=>reject(Error('The recording could not be saved. Please record again.'));});
    current.recorder.stop();await stopped;current.stream.getTracks().forEach(t=>t.stop());
    current.blob=new Blob(current.chunks,{type:current.recorder.mimeType});current.chunks=[];
    if(current.blob.size>60*1024*1024){captureFailed('This recording is too large. Try a shorter capture.');return;}
    shell(`<div class="ih-standalone-content"><span class="ih-kicker">Capture complete</span><h1>Sending your<br>item evidence.</h1><p>Keep this page open while the recording uploads. Your private recording will be compared with each selected photo and the listing description.</p><progress id="ihUploadProgress" class="ih-upload-progress" max="100" value="0"></progress><p id="ihUploadLabel">Preparing upload…</p><div id="ihUploadError" class="ih-note error" hidden></div><button class="ih-button ih-wide" id="ihRetryUpload" hidden>Retry upload</button></div>`);
    $('#ihRetryUpload').onclick=()=>uploadCapture(current);await uploadCapture(current);
  }
  async function uploadCapture(current) {
    if(current.cancelled)return;$('#ihRetryUpload').hidden=true;$('#ihUploadError').hidden=true;
    const body=new FormData();body.append('payload',JSON.stringify({session_id:current.stage.session_id,consent:true,source:'browser_camera'}));body.append('video',current.blob,current.blob.type.includes('webm')?'capture.webm':'capture.mp4');
    try {
      await new Promise((resolve,reject)=>{
        const xhr=new XMLHttpRequest();current.upload=xhr;xhr.open('POST',base+'/seller/'+sellerToken+'/submit');xhr.timeout=180000;
        xhr.upload.onprogress=e=>{if(current.cancelled)return;if(e.lengthComputable){const pct=Math.round(e.loaded/e.total*100);$('#ihUploadProgress').value=pct;$('#ihUploadLabel').textContent=pct===100?'Upload complete. Processing the recording…':`Uploading · ${pct}%`;}};
        xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300)resolve();else{let message='Upload failed. Your recording is still here; try again.';try{const d=JSON.parse(xhr.responseText);if(typeof d.detail==='string')message=d.detail;}catch{}reject(Error(message));}};
        xhr.onerror=()=>reject(Error('Connection interrupted. Reconnect and retry; your recording is still on this page.'));xhr.ontimeout=()=>reject(Error('The upload timed out. Check your connection and retry.'));xhr.onabort=()=>reject(Error('Upload cancelled.'));xhr.send(body);
      });
      if(current.cancelled)return;current.blob=null;capture=null;
      shell(`<div class="ih-standalone-content ih-seller-result"><span class="ih-seal">✓</span><span class="ih-kicker">Recording received</span><h1>Your part is complete.</h1><p>The selected photos and recording are ready for comparison. Use the private management link to view the findings in LockX. No login is needed.</p>${notice('The capture is submitted. A verified marking is only issued after all selected photos pass comparison.')}<p>You can close this page.</p></div>`);
    }catch(error){if(!current.cancelled){errorAt('#ihUploadError',error);$('#ihRetryUpload').hidden=false;}}
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
  window.addEventListener('pagehide',()=>{if(capture?.upload)capture.upload.abort();stopCapture();});
  window.addEventListener('beforeunload',e=>{if(capture?.recorder?.state==='recording'||capture?.blob){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden && capture?.recorder?.state==='recording')captureFailed('The recording paused when this page left the screen. Keep the camera page open for the next attempt.');});
  api('/capabilities').then(r=>r.json()).then(r=>{capabilities=r;serviceState();}).catch(()=>{});
  route();
})();
