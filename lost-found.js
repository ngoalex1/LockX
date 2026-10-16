/* LockX Lost & Found: uses the existing session; finder intake needs no account. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0}).format(cents / 100);
  const categories = ['Watch', 'Jewelry', 'Electronics', 'Camera', 'Bicycle', 'Bag', 'Other'];
  const icons = {
    search:'<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4 4"/>',
    arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
    pin:'<path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    photo:'<rect x="3" y="5" width="18" height="15" rx="3"/><circle cx="9" cy="10" r="1.5"/><path d="m4 18 5-5 4 3 3-4 5 5"/>',
    phone:'<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 18h4M10 5h4"/>',
    shield:'<path d="m12 2 8 4v6c0 5-8 9-8 9s-8-4-8-9V6l8-4Z"/><path d="m8 12 3 3 5-6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    link:'<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 10a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-2 2"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
  };
  const icon = name => `<svg class="lf-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.search}</svg>`;
  const state = {tab:'discover', reports:[], mine:[], matches:[], capabilities:null, category:'', query:'', loading:true, error:'', detail:null, recoveryAlerts:[], monitorHealth:null};
  const urls = new Map();
  let lastFocus, activeLoad = 0, currentUser = null;
  function headers() { return typeof session !== 'undefined' && session ? {Authorization:'Bearer ' + session.access_token} : {}; }
  function signedIn() { return Boolean(headers().Authorization); }
  async function api(path, options = {}) {
    const response = await fetch(API_BASE + '/lost-found' + path, {...options, headers:{...headers(), ...options.headers}});
    if (!response.ok) {
      let detail;
      try {detail = (await response.json()).detail;} catch {}
      if (response.status === 401) throw Error('Please sign in again to access your reports.');
      throw Error(typeof detail === 'string' ? detail : 'Lost & Found is unavailable. Check the API connection and try again.');
    }
    return response.status === 204 ? null : response.json();
  }
  $('main').insertAdjacentHTML('beforeend', `
    <section id="lost-found" class="page lf-page">
      <div class="lf-heading"><div><p class="eyebrow">THE LOCKX RECOVERY NETWORK</p><h1>Lost. Found. <em>Reunited.</em></h1><p class="intro">A small lead can bring something irreplaceable home.</p></div>
      <button class="primary-button" data-lf="report">${icon('plus')} Report a missing item</button></div>
      <div id="lfPreview"></div>
      <div class="lf-hero">
        <div class="lf-hero-copy"><span class="lf-kicker">GOOD PEOPLE. BETTER CONNECTIONS.</span><h2>Found something?<br/>A photo is all it takes.</h2><p>Send a photo. We’ll look for a missing-item report<br class="lf-desktop"/> and help connect the dots.</p><div class="lf-hero-actions"><button class="lf-white-button" data-lf="finder">${icon('photo')} Send a finder photo ${icon('arrow')}</button><button class="lf-hero-link" data-lf="sms">Or send us a text ↗</button></div><div class="lf-hero-foot">${icon('shield')} No account needed · Your contact details stay private</div></div>
        <div class="lf-hero-art" aria-hidden="true"><div class="lf-orbit lf-orbit-one"></div><div class="lf-orbit lf-orbit-two"></div><div class="lf-photo-card"><div class="lf-photo-top"><span class="lf-live-dot"></span> A LITTLE CLOSER TO HOME <span>✦</span></div><div class="lf-watch-art">${watchArt()}</div><div class="lf-photo-caption"><span>${icon('photo')} One photo. A new possibility.</span><b>↗</b></div></div><div class="lf-floating-tag">${icon('check')} Help it find its person.</div></div>
      </div>
      <div class="lf-stats" id="lfStats"></div>
      <div class="lf-workspace"><div class="lf-tabs" role="tablist" aria-label="Lost and Found views"><button role="tab" data-lf-tab="discover" class="active">Missing items</button><button role="tab" data-lf-tab="mine">My reports <span id="lfMineCount">0</span></button><button role="tab" data-lf-tab="inbox">Match inbox <span id="lfMatchCount">0</span></button></div><button class="lf-refresh" data-lf="refresh" aria-label="Refresh Lost and Found">↻ <span>Refresh</span></button></div>
      <div class="lf-toolbar"><label class="lf-search">${icon('search')}<input id="lfSearch" type="search" placeholder="Search item, brand, or city…" aria-label="Search missing items"/></label><div class="lf-category-wrap"><select id="lfCategory" aria-label="Filter category"><option value="">All categories</option>${categories.map(c=>`<option>${c}</option>`).join('')}</select></div><span class="lf-view-label">${icon('grid')} <span id="lfResultCount">0 items</span></span></div>
      <div id="lfContent" aria-live="polite"></div>
      <div class="lf-bottom-note">${icon('shield')} Every lead deserves a careful look. Matches require ownership verification before a return.</div>
    </section>
    <div class="modal-backdrop lf-dialog" id="lfModal" role="dialog" aria-modal="true" aria-labelledby="lfModalTitle"><div class="modal lf-modal" id="lfModalBody"></div></div>
  `);

  function watchArt() {
    return '<svg viewBox="0 0 240 190" fill="none"><defs><linearGradient id="lfSteel" x1="60" y1="0" x2="160" y2="190" gradientUnits="userSpaceOnUse"><stop stop-color="#a3a59c"/><stop offset=".27" stop-color="#eeeeDF"/><stop offset=".52" stop-color="#8c9187"/><stop offset=".72" stop-color="#e5e8da"/><stop offset="1" stop-color="#7d857b"/></linearGradient></defs><g transform="rotate(28 120 95)"><rect x="96" y="1" width="48" height="188" rx="12" fill="url(#lfSteel)"/><path d="M97 14h46M97 24h46M97 35h46M97 155h46M97 166h46M97 177h46M108 1v188M132 1v188" stroke="#6d776a" stroke-opacity=".45"/><rect x="157" y="88" width="10" height="14" rx="2" fill="#b7baa9"/><circle cx="120" cy="95" r="49" fill="url(#lfSteel)" stroke="#667264" stroke-width="2"/><circle cx="120" cy="95" r="42" fill="#203a30" stroke="#c2c7ac" stroke-width="2"/><circle cx="120" cy="95" r="34" stroke="#94a38c" stroke-width=".5"/><g stroke="#e5e1c8" stroke-width="3"><path d="M120 60v6M120 124v6M85 95h6M149 95h6M95 70l4 4M141 116l4 4M95 120l4-4M141 74l4-4"/></g><path d="m119 76 1 19 16 9" stroke="#e7e1c5" stroke-width="3" stroke-linecap="round"/><path d="m120 95-13 23" stroke="#c6a76b"/><circle cx="120" cy="95" r="3" fill="#ddd8bc"/><text x="120" y="85" text-anchor="middle" fill="#bbbfa9" font-size="5" font-family="serif" letter-spacing="2">LOCKX</text></g></svg>';
  }
  function itemArt(category) {
    if (category === 'Watch') return watchArt();
    const drawings = {
      Jewelry:'<path d="M54 55 80 27h80l26 28-66 88-66-88Z"/><path d="M54 55h132M80 27l20 28 20-28 20 28 20-28M100 55l20 88 20-88"/>',
      Electronics:'<rect x="78" y="20" width="84" height="146" rx="14"/><rect x="85" y="28" width="70" height="128" rx="8"/><path d="M107 35h26M113 146h14"/>',
      Camera:'<rect x="38" y="53" width="164" height="100" rx="12"/><circle cx="126" cy="102" r="35"/><circle cx="126" cy="102" r="25"/><path d="m85 53 12-20h52l12 20M49 73h27M168 65h17"/>',
      Bicycle:'<circle cx="57" cy="126" r="34"/><circle cx="184" cy="126" r="34"/><path d="m57 126 37-69 37 69H57l26-48h82l19 48-27-84h-17M81 57h27"/>',
      Bag:'<rect x="55" y="60" width="130" height="104" rx="12"/><path d="M91 60V43a29 29 0 0 1 58 0v17M88 63v22M152 63v22M57 103h126"/>',
      Other:'<rect x="59" y="46" width="122" height="116" rx="15"/><path d="m59 68 61 25 61-25M120 93v69M90 35h60"/>'
    };
    return `<svg viewBox="0 0 240 190" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${drawings[category] || drawings.Other}</svg>`;
  }
  function openModal(markup) {
    lastFocus = document.activeElement;
    $('#lfModalBody').innerHTML = `<button type="button" class="close" data-lf="close" aria-label="Close dialog">×</button>${markup}`;
    $('#lfModal').classList.add('open');
    document.body.classList.add('lf-modal-open');
    setTimeout(()=>$('#lfModalBody').querySelector('input, button, select, textarea')?.focus(), 0);
  }
  function closeModal() {
    $('#lfModal').classList.remove('open');
    document.body.classList.remove('lf-modal-open');
    lastFocus?.focus();
  }
  function needAccount() {
    if (signedIn()) return false;
    closeModal();
    openAuth();
    $('#authModal').classList.add('open');
    return true;
  }
  async function load() {
    if(location.protocol==='file:'){state.loading=false;state.error='file-preview';render();return;}
    const loadId = ++activeLoad;
    const user = typeof session!=='undefined'&&session ? (session.user?.id||headers().Authorization) : null;
    if (currentUser !== user) {
      if(currentUser&&$('#lfModal').classList.contains('open'))closeModal();
      state.detail=null;
      state.mine = [];state.matches = [];state.recoveryAlerts = [];
      for (const url of urls.values()) URL.revokeObjectURL(url);
      urls.clear();currentUser = user;
    }
    state.loading = true;state.error = '';render();
    try {
      const requests = [api('/public'), api('/capabilities')];
      if (signedIn()) requests.push(api('/reports'), api('/matches'), api('/recovery-alerts'), api('/monitoring-health'));
      const values = await Promise.all(requests);
      if (loadId !== activeLoad) return;
      [state.reports, state.capabilities] = values;
      state.mine = values[2] || [];state.matches = values[3] || [];state.recoveryAlerts=values[4]||[];state.monitorHealth=values[5]||null;
    } catch (error) {
      if (loadId !== activeLoad) return;
      state.error = error.message;
    } finally {
      if (loadId === activeLoad) {state.loading = false;render();}
    }
  }
  function workProof(h) {
    const a=h?.activity,t=a?.totals||{},fmt=v=>v===undefined?'—':Number(v).toLocaleString();
    const recent=a?.recent_runs||[],last=recent[0],stamp=v=>v?new Date(v*1000).toLocaleString():null;
    const metrics=[['listings_checked','Listing checks','Across recorded scans; repeat checks included'],['photo_comparisons','Photo comparisons','Completed comparisons against owner photos'],['unchanged_skipped','Unchanged listings skipped','Previously reviewed details retained'],['new_flags','Close-match flags','Distinctive features sent for owner review']];
    return `<div class="lf-work-proof"><div class="lf-proof-heading"><h3>The work behind your recovery.</h3><span>YOUR RECORDED ACTIVITY</span></div><div class="lf-proof-metrics">${metrics.map(([key,label,hint])=>`<div><strong>${fmt(t[key])}</strong><span>${label}</span><small>${hint}</small></div>`).join('')}</div><div class="lf-proof-sources">${Object.entries(last?.sources||h?.sources||{}).filter(([k])=>k!=='comparison_limit').map(([key,value])=>`<span><b>${esc(key==='facebook_marketplace'?'Facebook Marketplace':key==='ebay_browse'?'eBay':'Craigslist')}</b> ${esc(typeof value==='object'?(value.status==='completed'?fmt(value.count)+' cards retrieved':value.status.replaceAll('_',' ')):value.replaceAll('_',' '))}</span>`).join('')}</div><details class="lf-proof-receipts"><summary>Scan receipts ${recent.length?'· '+recent.length+' recent':''}</summary>${recent.length?recent.map(run=>`<div class="lf-scan-receipt"><time>${esc(stamp(run.started))}</time><span>${esc(run.status.replaceAll('_',' '))}</span><span>${fmt(run.summary.listings_checked||0)} listing checks · ${fmt(run.summary.photo_comparisons||0)} photo comparisons · ${fmt(run.summary.new_flags||0)} new flags</span></div>`).join(''):'<p>No scans recorded yet. Enable monitoring on a report with reference photos to begin.</p>'}</details><div class="lf-proof-timing"><span>Worker check-in: ${esc(stamp(h?.last_tick)||'awaiting confirmation')}</span><span>Next search due: ${esc(stamp(a?.next_due)||'enable a report to schedule')}</span></div></div>`;
  }
  function recoveryActivity() {
    const h=state.monitorHealth, online=Boolean(h?.worker_healthy), watches=Number(h?.your_active_watches)||0;
    return `<section class="lf-activity ${online?'is-online':''}" aria-label="LockX recovery monitoring workflow"><div class="lf-activity-head"><div><p class="eyebrow">YOUR RECOVERY NETWORK</p><h2>Always ready for the next lead.</h2></div><span class="lf-worker-state"><i></i>${online?'Worker online':h?'Worker awaiting confirmation':'Recovery workflow'}</span>${h?.browser_status==='browser_unavailable'?'<span class="lf-intake-blocked">Source intake blocked</span>':''}<button type="button" class="lf-motion-toggle" data-lf-motion aria-pressed="false" aria-label="Pause recovery animation">Pause animation</button></div><div class="lf-bot-flow"><div class="lf-flow-wire" aria-hidden="true"><span></span><span></span><span></span></div><div class="lf-flow-source"><span class="lf-flow-label">01 / DISCOVER</span><div class="lf-web-window"><div class="lf-web-bar"><i></i><i></i><i></i><span>Marketplace listings</span></div><div class="lf-web-photos"><span>${icon('photo')}</span><span>${icon('clock')}</span><span>${icon('photo')}</span><span>${icon('search')}</span></div><div class="lf-web-lines"><i></i><i></i></div><div class="lf-scan-beam"></div></div><p>Websites &amp; listing photos</p></div><div class="lf-flow-bot"><span class="lf-flow-label">02 / COMPARE</span><div class="lf-robot-stage" aria-hidden="true"><div class="lf-orbit"></div><div class="lf-robot"><div class="lf-robot-antenna"></div><div class="lf-robot-head"><div class="lf-robot-eyes"><i></i><i></i></div><div class="lf-robot-mouth"></div></div><div class="lf-robot-body"><span>X</span></div><div class="lf-robot-arm left"></div><div class="lf-robot-arm right"></div></div><span class="lf-robot-spark">✦</span></div><p>Compare distinctive details</p></div><div class="lf-flow-destination"><span class="lf-flow-label">03 / CONNECT</span><div class="lf-owner-row"><span class="lf-owner-avatar">A</span><div><strong>Lost item report</strong><small>Owner reference photos</small></div><i></i></div><div class="lf-owner-row"><span class="lf-owner-avatar">B</span><div><strong>Found item report</strong><small>Item details &amp; photos</small></div><i></i></div><div class="lf-owner-row"><span class="lf-owner-avatar">✓</span><div><strong>Owner’s match inbox</strong><small>Possible match for review</small></div><i></i></div><p>Route leads to the right account</p></div></div><div class="lf-activity-footer"><span>${icon('clock')} Searches scheduled every 6 hours</span><span>${online?watches+' active '+(watches===1?'watch':'watches'):'Status checked when signed in'}</span><small>Workflow illustration · movement does not represent live scans</small></div>${workProof(h)}${online&&!watches?`<div class="lf-activity-start">${h?.browser_status==='browser_unavailable'?'Marketplace intake needs connection. You can prepare your report now.':'Add an item with reference photos and enable monitoring to begin.'} <button type="button" data-lf="report">Add your missing item →</button></div>`:''}</section>`;
  }
  function render() {
    const caps = state.capabilities;
    $('#lfPreview').innerHTML = window.LOCKX_LOCAL_PREVIEW ? '<div class="lf-preview-note"><b>LOCAL PREVIEW</b> Sample reports in a separate local database. No texts or payments are sent.</div>' : '';
    $('#lfStats').innerHTML = [
      [icon('search'), state.reports.length.toString().padStart(2,'0'), 'Open public reports', 'Help someone find what matters'],
      [icon('shield'), state.mine.filter(r=>r.status==='recovered').length.toString().padStart(2,'0'), 'Your items returned', 'Every reunion starts with a lead'],
      [icon('photo'), caps?.vision_ready ? 'Configured' : 'Manual review', 'Photo identification', caps?.vision_ready ? 'Image analysis is configured' : 'Add details to help match photos'],
      [icon('phone'), caps?.sms_ready ? 'Configured' : 'Web intake ready', 'Text-to-find', caps?.sms_ready ? caps.sms_number : 'MMS number awaiting connection']
    ].map(([i,v,l,s])=>`<div class="lf-stat"><span class="lf-stat-icon">${i}</span><div><strong class="${v.length>5?'lf-word-stat':''}">${esc(v)}</strong><p>${l}</p><small>${esc(s)}</small></div></div>`).join('');
    $('#lfPreview').insertAdjacentHTML('beforeend',recoveryActivity());
    $('#lfMineCount').textContent=state.mine.length;
    $('#lfMatchCount').textContent=state.matches.filter(m=>!['dismissed','returned','withdrawn'].includes(m.status)).length+state.recoveryAlerts.length;
    document.querySelectorAll('[data-lf-tab]').forEach(b=>{b.classList.toggle('active', b.dataset.lfTab===state.tab);b.setAttribute('aria-selected', String(b.dataset.lfTab===state.tab));});
    let rows = state.tab==='mine'?state.mine:state.tab==='inbox'?state.matches:state.reports;
    rows = rows.filter(r=>(!state.category || (r.category || state.mine.find(x=>x.id===r.report_id)?.category)===state.category) && JSON.stringify([r.title,r.brand,r.model,r.location,r.details,r.report_title,r.sighting?.description]).toLowerCase().includes(state.query.toLowerCase()));
    $('#lfResultCount').textContent = `${rows.length} ${state.tab==='inbox'?'leads':'items'}`;
    let content;
    if(location.protocol==='file:') content=localPreviewHelp();
    else if (state.loading) content='<div class="lf-empty"><span class="lf-loader"></span><h3>Checking the recovery network…</h3></div>';
    else if (state.error) content=`<div class="lf-empty"><span class="lf-empty-symbol">${icon('link')}</span><h3>Let’s reconnect.</h3><p>${esc(state.error)}</p><button class="primary-button" data-lf="refresh">Try again</button></div>`;
    else if (state.tab!=='discover' && !signedIn()) content='<div class="lf-empty"><span class="lf-empty-symbol">'+icon('shield')+'</span><h3>Your recovery workspace is private.</h3><p>Sign in to manage reports and review potential matches.</p><button class="primary-button" data-lf="signin">Sign in to LockX</button></div>';
    else if (!rows.length) content=`<div class="lf-empty"><span class="lf-empty-symbol">${icon(state.tab==='inbox'?'photo':'search')}</span><h3>${state.query||state.category?'No results for these filters.':state.tab==='inbox'?'The next lead could be the one.':state.tab==='mine'?'Give your missing item a way home.':'Every reunion starts with a report.'}</h3><p>${state.tab==='inbox'?'Relevant finder submissions will appear here. Refresh to check for new leads.':'Add identifying details and photos so the right person can recognize your item.'}</p><button class="primary-button" data-lf="${state.query||state.category?'clear':'report'}">${state.query||state.category?'Clear filters':'Report a missing item'}</button></div>`;
    else content = state.tab==='inbox'?`<div class="lf-inbox">${rows.map(matchCard).join('')}</div>`:`<div class="lf-cards">${rows.map(reportCard).join('')}</div>`;
    if(state.tab==='inbox'&&signedIn()&&!state.loading&&!state.error&&state.recoveryAlerts.length) content='<div class="lf-inbox">'+state.recoveryAlerts.map(a=>`<article class="lf-lead"><div class="lf-lead-copy"><p class="eyebrow">MARKETPLACE PHOTO MATCH · ${esc(a.source)}</p><h3>${esc(a.listing.title)}</h3><p>${esc((a.comparison.reasons||[]).join(' · '))}</p><p>Visual similarity ${Math.round(a.comparison.score*100)} / 100. A lead for review; ownership is unverified.</p><a class="primary-button" href="${esc(/^https:\/\//.test(a.listing.url)?a.listing.url:'#')}" target="_blank" rel="noopener noreferrer">Review listing ↗</a></div></article>`).join('')+'</div>'+content;
    $('#lfContent').innerHTML = content;
    hydratePhotos($('#lfContent'));
  }
  function reportCard(r) {
    const thumb = r.photos?.[0];
    return `<article class="lf-item-card"><button class="lf-item-image lf-art-${esc(r.category).toLowerCase()}" data-lf-detail="${esc(r.id)}" aria-label="View ${esc(r.title)}">${thumb?`<img data-photo="${esc(thumb)}" data-public="${r.publish && r.status==='active'?'true':'false'}" alt="${esc(r.title)}"/>`:itemArt(r.category)}<span class="lf-item-status ${r.incident==='stolen'?'lf-stolen':''}"><i></i>${r.status==='recovered'?'Returned':r.status==='archived'?'Archived':r.incident==='stolen'?'Reported stolen':'Missing'}</span><span class="lf-image-category">${esc(r.category)}</span></button><div class="lf-item-body"><p class="lf-item-brand">${esc(r.brand || r.category)}</p><h3><button data-lf-detail="${esc(r.id)}">${esc(r.title)}</button></h3><p class="lf-item-location">${icon('pin')} ${esc(r.location)}</p>${state.tab==='mine'?`<button class="lf-refresh" data-lf-monitor="${esc(r.id)}">${icon('clock')} Set up six-hour monitoring</button>`:''}<div class="lf-item-footer"><div><small>REWARD PLEDGED</small><strong>${money(r.reward)}</strong></div><button data-lf-detail="${esc(r.id)}" aria-label="View ${esc(r.title)}">${icon('arrow')}</button></div></div></article>`;
  }
  function matchCard(m) {
    const labels={new:'New lead',reviewing:'Under review',verified:'Owner verified',returned:'Returned',dismissed:'Dismissed',withdrawn:'No longer matches'};
    return `<article class="lf-lead"><div class="lf-lead-photo">${m.photos[0]?`<img data-photo="${esc(m.photos[0])}" alt="Finder submission"/>`:icon('photo')}</div><div class="lf-lead-copy"><div class="lf-lead-meta"><span class="state">${labels[m.status]}</span><span>${m.source==='mms'?'MMS photo':'Web submission'} · ${new Date(m.received_at).toLocaleDateString()}</span></div><h3>${esc(m.report_title)}</h3><p>${esc(m.reasons.join(' · '))}</p><small>${m.analysis_status==='analyzed'?'Photo attributes extracted; human verification required.':'Submitted details matched; photos need manual review.'}</small></div><div class="lf-lead-action"><strong>${m.score}<small>/100</small></strong><span>Evidence score</span><button class="primary-button ghost" data-lf-match="${esc(m.id)}">Review lead ${icon('arrow')}</button></div></article>`;
  }
  async function hydratePhotos(root) {
    await Promise.allSettled([...root.querySelectorAll('img[data-photo]')].map(async img=>{
      const id=img.dataset.photo, publicPhoto=img.dataset.public==='true', cacheKey=(publicPhoto?'public:':'private:')+id;
      try {
        if(!urls.has(cacheKey)) {
          const response=await fetch(API_BASE+'/lost-found/'+(publicPhoto?'public/':'')+'photos/'+encodeURIComponent(id),{headers:publicPhoto?{}:headers()});
          if(!response.ok)throw Error();
          urls.set(cacheKey,URL.createObjectURL(await response.blob()));
        }
        if(img.isConnected)img.src=urls.get(cacheKey);
      } catch {if(img.isConnected){img.replaceWith(Object.assign(document.createElement('span'),{className:'lf-photo-unavailable',textContent:'Photo unavailable'}));}}
    }));
  }
  function reportForm(existing = null) {
    if(needAccount())return;
    openModal(`<p class="eyebrow">A WAY BACK TO YOU</p><h2 id="lfModalTitle">${existing?'Update your report.':'Report a missing item.'}</h2><p>Details make the difference. Keep one identifying mark private for verification.</p><form id="lfReportForm" class="lf-form"><div class="lf-form-grid"><label class="lf-full">Listing title<input name="title" required minlength="3" maxlength="160" placeholder="e.g. Rolex Submariner with engraved case back"/></label><label>Category<select name="category">${categories.map(c=>`<option>${c}</option>`).join('')}</select></label><label>What happened?<select name="incident"><option value="lost">Lost</option><option value="stolen">Stolen</option></select></label><label>Brand<input name="brand" maxlength="100" placeholder="e.g. Rolex"/></label><label>Model / reference<input name="model" maxlength="120" placeholder="e.g. Submariner 124060"/></label><label>Serial number <span>Private</span><input name="serial" maxlength="100" placeholder="Optional, but a strong identifier"/></label><label>Color / material<input name="color" maxlength="100" placeholder="e.g. Black / stainless steel"/></label><label>Last-seen area<input name="location" required minlength="2" maxlength="200" placeholder="City, neighborhood, or venue"/></label><label>Date lost or stolen<input name="incident_date" type="date" required max="${new Date().toLocaleDateString('en-CA')}"/></label><label class="lf-full">Recognizable details<textarea name="details" required minlength="10" maxlength="3000" placeholder="Describe the item, accessories, and visible distinguishing marks. This description is public if you publish."></textarea></label><label class="lf-full">Private ownership evidence<textarea name="private_details" maxlength="3000" placeholder="An unpublished engraving, receipt reference, or other identifying detail. Only visible in your account."></textarea></label><label>Police report reference <span>Private</span><input name="police_reference" maxlength="150" placeholder="Optional"/></label><label>Estimated value (USD)<input name="value" type="number" required min="1" max="1000000" step="0.01" placeholder="10000"/></label></div><div class="lf-reward-box"><div><span class="lf-kicker">GIVE SOMEONE A REASON TO LOOK</span><h3>Offer a recovery reward.</h3><p>A 30% starting point. You choose the amount.</p></div><label>Reward %<input name="reward_percent" type="number" min="0" max="100" required value="30"/></label><strong id="lfRewardAmount">$0</strong></div><p class="lf-small">Rewards are owner pledges. LockX does not hold funds or process payouts yet.</p>${existing?'<p class="lf-small">Your existing reference photos will be retained.</p>':uploadField(false)}<label class="lf-checkbox"><input name="publish" type="checkbox" checked/><span>Publish this listing to the recovery network. Serial numbers and private evidence stay private. Avoid photos that expose private documents or identifiers.</span></label><p class="lf-form-error" role="alert"></p><div class="lf-form-footer"><span>${icon('shield')} Your private evidence stays in your account</span><button type="submit" class="primary-button">${existing?'Save changes':'Create report'} ${icon('arrow')}</button></div></form>`);
    const f=$('#lfReportForm');
    f.addEventListener('input',()=>{$('#lfRewardAmount').textContent=money(Math.round(Number(f.elements.value.value||0)*100)*Number(f.elements.reward_percent.value||0)/100);});
    if(existing){for(const [key,value] of Object.entries(existing)){const control=f.elements.namedItem(key);if(control){if(control.type==='checkbox')control.checked=Boolean(value);else control.value=key==='value'?value/100:String(value??'');}}$('#lfRewardAmount').textContent=money(existing.reward);}else wireUpload(f);
    f.onsubmit=async event=>{
      event.preventDefault();
      const d=new FormData(f), payload=Object.fromEntries([...d].filter(([k])=>!['photos','publish'].includes(k)));
      payload.value=Math.round(Number(d.get('value'))*100);payload.reward_percent=Number(d.get('reward_percent'));payload.publish=d.has('publish');
      if(existing){const button=f.querySelector('[type=submit]');button.disabled=true;try{await api('/reports/'+encodeURIComponent(existing.id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({report:payload,expected_revision:existing.revision})});closeModal();await load();detail(existing.id);toast('Report updated','Existing leads were checked against the updated details.');}catch(error){$('.lf-form-error',f).textContent=error.message;}finally{button.disabled=false;}}else await submit(f,'/reports',payload,()=>{closeModal();state.tab='mine';load();toast('Report created','Your item is ready for finder matching.');});
    };
  }
  function uploadField(required) {
    return `<label class="lf-upload">${icon('photo')}<strong>${required?'Send a photo of the item':'Add detailed reference photos'}</strong><span>JPG, PNG, or WebP · Up to 4 photos · 5 MB each</span><input name="photos" type="file" accept="image/jpeg,image/png,image/webp" multiple ${required?'required':''}/><span class="lf-upload-names">Choose photos or take a picture</span></label><div class="lf-upload-previews"></div>`;
  }
  function wireUpload(form) {
    let previews=[];
    form.elements.photos.onchange=()=>{
      previews.forEach(URL.revokeObjectURL);previews=[];
      const files=[...form.elements.photos.files];
      $('.lf-upload-names',form).textContent=files.length?`${files.length} photo${files.length===1?'':'s'} selected`:'Choose photos or take a picture';
      $('.lf-upload-previews',form).replaceChildren(...files.slice(0,4).map(file=>{const img=new Image();img.alt=file.name;img.src=URL.createObjectURL(file);previews.push(img.src);return img;}));
    };
    form.addEventListener('reset',()=>previews.forEach(URL.revokeObjectURL));
  }
  async function submit(form,path,payload,done) {
    const button=form.querySelector('[type="submit"]'), error=$('.lf-form-error',form);
    error.textContent='';const files=[...form.elements.photos.files];
    if(files.length>4 || files.some(f=>f.size>5*1024*1024)){error.textContent='Choose up to 4 photos, each 5 MB or smaller.';return;}
    const body=new FormData();body.set('payload',JSON.stringify(payload));files.forEach(file=>body.append('photos',file));
    button.disabled=true;const label=button.innerHTML;button.textContent='Saving securely…';
    try{await api(path,{method:'POST',body});done();}catch(e){error.textContent=e.message;}finally{button.disabled=false;button.innerHTML=label;}
  }
  function finderForm(target = null) {
    const vision=state.capabilities?.vision_ready;
    openModal(`<p class="eyebrow">ONE PHOTO CAN MAKE A DIFFERENCE</p><h2 id="lfModalTitle">Help it find its person.</h2><p>No account needed. Send a photo of an item you found or spotted.</p><form id="lfFinderForm" class="lf-form">${uploadField(true)}<div class="lf-form-grid"><label>Did you find or see it?<select name="kind"><option value="found">I have the item</option><option value="sighted">I saw it somewhere</option></select></label><label>Nearby landmark / area<input name="location" maxlength="200" placeholder="Optional, e.g. Union Square, SF"/></label><label class="lf-full">Anything else we should know?<textarea name="description" maxlength="3000" placeholder="Brand, color, visible serial, or where you saw it. A few details can help."></textarea></label><label>Category<select name="category"><option value="">Not sure</option>${categories.map(c=>`<option>${c}</option>`).join('')}</select></label><label>Visible serial number<input name="serial" maxlength="100" placeholder="Optional — don't guess"/></label><label class="lf-full">Contact email or phone <span>Optional</span><input name="contact" maxlength="200" placeholder="Shared with an owner only after ownership review"/></label></div><div class="lf-intake-note">${icon('photo')}<p>${vision?'Photo analysis is configured. We’ll extract visible item details and look for potential matches.':'Photo analysis is awaiting connection. Add a category, serial, or description to help match the photos for manual review.'}</p></div><label class="lf-checkbox"><input type="checkbox" name="consent" required/><span>I agree that LockX can store and analyze these photos and share relevant item details with potential owners. I have permission to submit them.</span></label><p class="lf-small">No payment is required. Don’t send identity documents, passwords, or verification codes. Rewards require a verified return and the owner’s terms.</p><p class="lf-form-error" role="alert"></p><div class="lf-form-footer"><span>${icon('shield')} No account. No public contact details.</span><button class="primary-button" type="submit">Send finder report ${icon('arrow')}</button></div></form>`);
    const form=$('#lfFinderForm');if(target){form.insertAdjacentHTML('afterbegin',`<div class="lf-target-note">${icon('link')}<div><strong>Lead for ${esc(target.title)}</strong><p>This photo will reach the owner of this listing for review.</p></div></div>`);form.elements.category.value=target.category;}wireUpload(form);
    form.onsubmit=async event=>{
      event.preventDefault();const d=new FormData(form);
      const payload={kind:d.get('kind'),location:d.get('location'),description:d.get('description'),category:d.get('category')||null,serial:d.get('serial'),contact:d.get('contact'),consent:d.has('consent'),target_report_id:target?.id||null};
      await submit(form,'/sightings',payload,()=>{openModal(`<div class="lf-success"><span>${icon('check')}</span><p class="eyebrow">A LITTLE CLOSER TO HOME</p><h2 id="lfModalTitle">Thank you for looking out.</h2><p>Your photos are saved. We’ll check them against missing-item reports, including new reports added later.</p><p>Potential owners can review leads in LockX. If you provided contact details, they become available after ownership review.</p><button class="primary-button" data-lf="close">Back to the network ${icon('arrow')}</button></div>`);});
    };
  }
  function smsDialog() {
    const caps=state.capabilities;
    openModal(`<p class="eyebrow">TEXT TO FIND</p><h2 id="lfModalTitle">A photo. A text. A possibility.</h2><p>Send up to four photos of an item you found or spotted. LockX asks for a nearby landmark, then checks for potential matches.</p><div class="lf-sms-number">${icon('phone')}<strong>${caps?.sms_ready?esc(caps.sms_number):'Number not connected yet'}</strong><span>${caps?.sms_ready?'MMS intake configured':'Photo upload is available now'}</span></div><ol class="lf-sms-steps"><li>Photograph the item and any visible identifying marks.</li><li>Text the photos and the area where you found it.</li><li>Reply to a short follow-up. No app or account needed.</li></ol><p class="lf-small">MMS availability depends on your country and carrier. Standard messaging rates may apply. A reward is not guaranteed.</p>${caps?.sms_ready?`<a class="primary-button lf-sms-link" href="sms:${esc(caps.sms_number)}">Text LockX ${icon('arrow')}</a>`:'<button class="primary-button" data-lf="finder">Upload photos instead '+icon('arrow')+'</button>'}`);
  }
  function detail(id) {
    const r=[...state.mine,...state.reports].find(r=>r.id===id);if(!r)return;
    const owned=state.mine.some(item=>item.id===id);
    state.detail=r;
    openModal(`<p class="eyebrow">${r.status==='recovered'?'RETURNED':r.status==='archived'?'ARCHIVED':r.incident==='stolen'?'REPORTED STOLEN':'MISSING ITEM'} · ${esc(r.category)}</p><h2 id="lfModalTitle">${esc(r.title)}</h2><p>${esc(r.brand)} ${esc(r.model)}</p><div class="lf-detail-photos">${r.photos.length?r.photos.map(p=>`<img data-photo="${esc(p)}" data-public="${r.publish&&r.status==='active'?'true':'false'}" alt="Reference photo"/>`).join(''):itemArt(r.category)}</div><div class="lf-detail-facts"><span>${icon('pin')} ${esc(r.location)}</span><span>${icon('clock')} ${esc(r.incident_date)}</span></div><p class="lf-detail-description">${esc(r.details)}</p>${owned&&(r.serial||r.private_details||r.police_reference)?`<div class="lf-private-box">${icon('shield')}<div><strong>Private ownership record</strong>${r.serial?`<p>Serial: ${esc(r.serial)}</p>`:''}${r.police_reference?`<p>Police reference: ${esc(r.police_reference)}</p>`:''}${r.private_details?`<p>${esc(r.private_details)}</p>`:''}</div></div>`:''}<div class="lf-detail-reward"><div><small>OWNER-PLEDGED REWARD</small><strong>${money(r.reward)}</strong></div><p>${r.reward_percent}% of estimated value<br/>Not funded or held by LockX</p></div><div class="lf-form-footer">${r.publish&&r.status==='active'?`<button class="primary-button ghost" data-lf="share">Copy listing link ${icon('link')}</button><button class="primary-button" data-lf="target-finder">I found or saw this ${icon('arrow')}</button>`:'<span>This report is not publicly listed.</span>'}</div>`);
    if(owned){$('#lfModalBody').insertAdjacentHTML('beforeend',`<div class="lf-owner-tools">${r.status!=='recovered'?`<button class="primary-button ghost" data-lf="edit">Edit report</button><button class="text-button" data-lf="archive">${r.status==='archived'?'Restore report':'Archive report'}</button>`:''}<button class="primary-button ghost" data-lf="export">Export evidence</button></div><p class="lf-small">Evidence exports include private owner records. Photos are referenced; image files are not embedded.</p><div class="lf-report-activity" id="lfReportActivity" data-report="${esc(r.id)}"><h3>Report activity</h3><p>Loading activity…</p></div><p class="lf-form-error" role="alert"></p>`);loadActivity(r.id);}
    hydratePhotos($('#lfModalBody'));
  }
  function review(id) {
    const m=state.matches.find(m=>m.id===id);if(!m)return;
    const reportActive=state.mine.find(r=>r.id===m.report_id)?.status==='active';
    const next=reportActive?{new:['reviewing','Start review'],reviewing:['verified','Confirm ownership evidence'],verified:['returned','Confirm item returned'],dismissed:['reviewing','Reopen review'] }[m.status]:null;
    openModal(`<p class="eyebrow">FINDER MATCH · ${esc(m.source.toUpperCase())}</p><h2 id="lfModalTitle">${esc(m.report_title)}</h2><p>Evidence score ${m.score}/100. This is not an ownership probability.</p><div class="lf-detail-photos">${m.photos.map(p=>`<img data-photo="${esc(p)}" alt="Finder photo"/>`).join('')}</div><ul class="lf-match-reasons">${m.reasons.map(r=>`<li>${icon('check')} ${esc(r)}</li>`).join('')}</ul><div class="lf-private-box"><div><strong>Finder’s report</strong><p>${esc(m.sighting.description||'Photo-only submission')}</p><p>Area / context: ${esc(m.sighting.location||'Not yet provided')}</p>${m.sighting.contact?`<p>Contact: ${esc(m.sighting.contact)}</p>`:''}</div></div><p class="lf-small">Compare the original photos and private ownership records. For suspected theft, preserve evidence and coordinate with police. LockX does not independently certify ownership or release reward funds.</p><form id="lfReviewForm">${next&&['verified','returned'].includes(next[0])?`<label>${next[0]==='verified'?'What private evidence establishes ownership?':'Confirm the completed handoff'}<textarea name="verification_note" required minlength="10" maxlength="3000" placeholder="Document the evidence or return details…"></textarea></label>`:''}<p class="lf-form-error" role="alert"></p><div class="lf-form-footer">${reportActive&&!['returned','dismissed','withdrawn'].includes(m.status)?'<button class="text-button" type="button" data-lf-dismiss="'+esc(m.id)+'">Dismiss lead</button>':'<span>Status: '+esc(m.status)+'</span>'}${next?`<button type="submit" class="primary-button">${next[1]} ${icon('arrow')}</button>`:''}</div></form>`);
    hydratePhotos($('#lfModalBody'));
    $('#lfReviewForm').onsubmit=async event=>{
      event.preventDefault();if(!next)return;
      const form=event.target, button=form.querySelector('[type="submit"]');button.disabled=true;
      try{await api('/matches/'+encodeURIComponent(m.id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:next[0],verification_note:form.elements.verification_note?.value||''})});closeModal();await load();toast(next[0]==='returned'?'Welcome home.':'Match updated',next[0]==='returned'?'Item marked returned. Reward payment remains the owner’s responsibility.':'Your review has been saved.');}catch(error){$('.lf-form-error',form).textContent=error.message;}finally{button.disabled=false;}
    };
  }

  function localPreviewHelp() {
    return `<div class="lf-empty lf-local-help"><span class="lf-empty-symbol">${icon('link')}</span><h3>This is a local file, not the running app.</h3><p>Start the preview from your LockX folder, then open it over HTTP to use reports and photo uploads.</p><code>.venv/bin/python dev_server.py --demo</code><a class="primary-button lf-sms-link" href="http://127.0.0.1:8080/#lost-found">Open local preview ${icon('arrow')}</a><p class="lf-small">Local preview only. This does not deploy Lost &amp; Found to lockx.ai.</p></div>`;
  }
  async function loadActivity(id) {
    try {
      const activity=await api('/reports/'+encodeURIComponent(id)+'/activity');
      const root=$('#lfReportActivity');if(!root||root.dataset.report!==id)return;
      root.innerHTML='<h3>Report activity</h3>'+(activity.length?`<ol>${activity.map(e=>`<li><time>${esc(new Date(e.created_at).toLocaleString())}</time><p>${esc(e.detail)}</p></li>`).join('')}</ol>`:'<p>No activity recorded yet. Older reports start their history with the next update.</p>');
    } catch(error){const root=$('#lfReportActivity');if(root&&root.dataset.report===id)root.textContent=error.message;}
  }
  async function changeReportStatus() {
    const r=state.mine.find(r=>r.id===state.detail?.id);if(!r)return;
    const button=$('[data-lf="archive"]');button.disabled=true;
    try{
      await api('/reports/'+encodeURIComponent(r.id)+'/status',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:r.status==='archived'?'active':'archived',expected_revision:r.revision})});
      closeModal();await load();detail(r.id);toast(r.status==='archived'?'Report restored':'Report archived',r.status==='archived'?'Matching is active again.':'The public listing is hidden. You can restore it from My reports.');
    }catch(error){$('.lf-form-error',$('#lfModalBody')).textContent=error.message;}finally{button.disabled=false;}
  }
  async function exportEvidence() {
    const r=state.mine.find(r=>r.id===state.detail?.id);if(!r)return;
    const button=$('[data-lf="export"]');button.disabled=true;
    try{
      const evidence=await api('/reports/'+encodeURIComponent(r.id)+'/evidence');
      const url=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='lockx-evidence-'+r.id+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      toast('Evidence export ready','The JSON file contains private records. Share it deliberately.');
    }catch(error){$('.lf-form-error',$('#lfModalBody')).textContent=error.message;}finally{button.disabled=false;}
  }
  async function monitorDialog(id) {
    try {
      const m=await api('/reports/'+encodeURIComponent(id)+'/monitor');
      openModal(`<p class="eyebrow">CONTINUOUS RECOVERY</p><h2 id="lfModalTitle">Keep looking. Every six hours.</h2><p>No automatic expiry. Monitoring stops while your report is archived or recovered.</p><p>Worker: ${m.worker_enabled?'enabled':'awaiting deployment'} · Photo comparison: ${m.vision_ready?'configured':'not configured'} · Email: ${m.email_ready?'configured':'not configured'}</p><p>${Object.entries(m.sources).map(([k,v])=>esc(k)+': '+esc(v)).join('<br>')}</p><p>Last run: ${m.last_run?esc(new Date(m.last_run*1000).toLocaleString())+' · '+esc(m.last_status):'Not run'}<br>Next due: ${m.enabled&&m.next_run?esc(new Date(m.next_run*1000).toLocaleString()):'Not scheduled'}</p><form id="lfMonitorForm" class="lf-form"><label>Search ZIP code<input name="postal" pattern="[0-9]{5}" maxlength="5" value="${esc(m.search_settings?.postal||'')}" placeholder="95111"></label><label>Craigslist radius (miles)<input name="radius" type="number" min="1" max="500" value="${esc(m.search_settings?.radius||50)}"></label><label>Saved Facebook search URL (optional)<input name="facebook_url" type="url" value="${esc(m.search_settings?.facebook_url||'')}" placeholder="Facebook controls its own location"></label><label class="lf-checkbox"><input name="enabled" type="checkbox" ${m.enabled?'checked':''}><span>Enable recurring searches</span></label><label>Notification email (optional)<input name="notification_email" type="email" maxlength="254" value="${esc(m.notification_email||'')}" placeholder="Leave blank for in-app alerts only"></label><label class="lf-checkbox"><input name="consent" type="checkbox" ${m.consent?'checked':''}><span>I authorize LockX to send my reference photos and candidate listing photos to its configured AI provider for comparison, and email close-match alerts to the address above.</span></label><p>Alerts require distinctive matching features. Same-model watches alone should not trigger an alert. Sources shown as not connected are not being searched.</p><p class="lf-form-error" role="alert"></p><button class="primary-button" type="submit">Save monitoring</button></form>`);
      $('#lfMonitorForm').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button');b.disabled=true;try{await api('/reports/'+encodeURIComponent(id)+'/monitor',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:f.elements.enabled.checked,photo_analysis_consent:f.elements.consent.checked,notification_email:f.elements.notification_email.value,postal:f.elements.postal.value,radius:Number(f.elements.radius.value),facebook_url:f.elements.facebook_url.value,region:m.search_settings?.region||'www'})});closeModal();toast('Monitoring settings saved','Source and worker readiness determine when searches can run.');}catch(error){$('.lf-form-error',f).textContent=error.message;}finally{b.disabled=false;}};
    }catch(error){toast('Could not load monitoring',error.message);}
  }
  document.addEventListener('click',async event=>{
    const motion=event.target.closest('[data-lf-motion]');if(motion){const paused=motion.closest('.lf-activity').classList.toggle('is-paused');motion.textContent=paused?'Play animation':'Pause animation';motion.setAttribute('aria-pressed',String(paused));motion.setAttribute('aria-label',paused?'Play recovery animation':'Pause recovery animation');}
    const monitor=event.target.closest('[data-lf-monitor]');if(monitor)await monitorDialog(monitor.dataset.lfMonitor);
    const action=event.target.closest('[data-lf]')?.dataset.lf;
    if(action==='close')closeModal();
    if(action==='report'&&location.protocol!=='file:')reportForm();
    if(location.protocol==='file:'&&['report','finder','target-finder','sms','signin'].includes(action)){openModal('<h2 id="lfModalTitle">Open the local app.</h2>'+localPreviewHelp());return;}
    if(action==='finder')finderForm();
    if(action==='target-finder')finderForm(state.detail);
    if(action==='edit')reportForm(state.mine.find(r=>r.id===state.detail?.id));
    if(action==='archive')changeReportStatus();
    if(action==='export')exportEvidence();
    if(action==='sms')smsDialog();
    if(action==='refresh')load();
    if(action==='signin')needAccount();
    if(action==='clear'){state.query='';state.category='';$('#lfSearch').value='';$('#lfCategory').value='';render();}
    if(action==='share'){
      const url=new URL(location.href);url.hash='lost-found';url.searchParams.set('item',state.detail.id);
      try{await navigator.clipboard.writeText(url.href);toast('Link copied','Share this report with someone who might recognize the item.');}catch{toast('Copy this link',url.href);}
    }
    const tab=event.target.closest('[data-lf-tab]');if(tab){state.tab=tab.dataset.lfTab;render();}
    const report=event.target.closest('[data-lf-detail]');if(report)detail(report.dataset.lfDetail);
    const match=event.target.closest('[data-lf-match]');if(match)review(match.dataset.lfMatch);
    const dismiss=event.target.closest('[data-lf-dismiss]');if(dismiss){dismiss.disabled=true;try{await api('/matches/'+encodeURIComponent(dismiss.dataset.lfDismiss),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'dismissed'})});closeModal();load();}catch(e){$('.lf-form-error',$('#lfModalBody')).textContent=e.message;dismiss.disabled=false;}}
    if(event.target.id==='lfModal')closeModal();
    if(event.target.closest('[data-page="lost-found"]')){document.querySelector('.sidebar')?.classList.remove('open');location.hash='lost-found';load();}
  });
  document.addEventListener('keydown',event=>{
    if(!$('#lfModal').classList.contains('open'))return;
    if(event.key==='Escape')closeModal();
    if(event.key==='Tab'){
      const all=[...$('#lfModalBody').querySelectorAll('button:not([disabled]),a,input,select,textarea')].filter(el=>el.offsetParent!==null), first=all[0],last=all.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  $('#lfSearch').oninput=event=>{state.query=event.target.value;render();};
  $('#lfCategory').onchange=event=>{state.category=event.target.value;render();};
  window.addEventListener('lockx-session',()=>{if(state.tab!=='discover')state.tab='discover';load();});
  window.addEventListener('hashchange',()=>{if(['#lost-found','#found'].includes(location.hash)){go('lost-found');if(location.hash==='#found')finderForm();}});
  if(['#lost-found','#found'].includes(location.hash)||window.LOCKX_LOCAL_PREVIEW)go('lost-found');
  load().then(async()=>{const id=new URLSearchParams(location.search).get('item');if(id&&location.protocol!=='file:'){if(![...state.mine,...state.reports].some(r=>r.id===id)){try{state.reports.push(await api('/public/reports/'+encodeURIComponent(id)));}catch{toast('Listing unavailable','This report may be private, archived, or already recovered.');return;}}detail(id);}if(location.hash==='#found'&&location.protocol!=='file:')finderForm();});
  setInterval(()=>{if(document.visibilityState==='visible'&&location.hash==='#lost-found'&&signedIn()&&!state.loading&&!$('#lfModal').classList.contains('open'))load();},60000);
})();
