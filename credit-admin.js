/* Private administration. The server checks administrator access on every request. */
(() => {
  'use strict';
  const $ = (selector, root=document) => root.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const base = API_BASE + '/credits/admin';
  const money = value => Number.isFinite(value) ? new Intl.NumberFormat(undefined,{style:'currency',currency:'USD'}).format(value/100) : '—';
  const count = value => Number.isFinite(value) ? new Intl.NumberFormat().format(value) : '—';
  const percent = value => Number.isFinite(value)&&value>=0&&value<=1 ? new Intl.NumberFormat(undefined,{style:'percent',maximumFractionDigits:1}).format(value) : '—';
  const stamp = value => {
    if(value===null||value===undefined||value==='')return '—';
    const date=new Date(typeof value==='number'?value*1000:value);
    return Number.isNaN(date.valueOf())?'—':new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(date);
  };
  let access=null, accessFlight, opening, generation=0, refreshSequence=0, period=30;
  let recipient=null, lookupFlight, grantAttempt=null, review=null, granting=false;
  const page=document.createElement('section');
  page.id='admin';page.className='page ca-page';page.setAttribute('aria-labelledby','caTitle');
  (document.querySelector('main')||document.body).append(page);

  function notice(copy,error=false) {
    const target=$('#caNotice',page);if(!target)return;
    target.hidden=false;target.className='ca-notice'+(error?' ca-error':'');target.textContent=copy;
  }
  function accessNotice(unavailable=false) {
    page.innerHTML=`<div class="ca-shell"><header class="ca-heading"><div><p class="ca-eyebrow">LockX admin</p><h1 id="caTitle">${unavailable?'Access could not be checked.':'Administrator access required.'}</h1></div><a href="/#landing" class="ca-link">Back to LockX →</a></header><div class="ca-panel ca-access"><p>${unavailable?'Please try again. No account information has been loaded.':'Sign in with your administrator email to manage credits and view business activity.'}</p><div class="ca-button-row"><button type="button" class="ca-button" data-ca-signin>Sign in with email</button><button type="button" class="ca-button ca-secondary" data-ca-retry>Check access again</button></div></div></div>`;
  }
  function revoke() {
    access=false;recipient=null;review=null;grantAttempt=null;refreshSequence++;
    accessNotice();
    window.dispatchEvent(new CustomEvent('lockx-admin-access',{detail:{isAdmin:false}}));
  }
  async function request(path,options={}) {
    const current=generation;
    const client=await window.ensureLockXAuthClient();
    const {data,error}=await client.auth.getSession();
    if(current!==generation){const failure=Error('Your sign-in changed. Review this action again.');failure.status=401;throw failure;}
    if(error||!data.session?.access_token){if(current===generation)revoke();const failure=Error('Sign in with your administrator email.');failure.status=401;throw failure;}
    const response=await fetch(base+path,{...options,cache:'no-store',headers:{Authorization:'Bearer '+data.session.access_token,...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});
    const result=await response.json().catch(()=>({}));
    if(!response.ok){
      if(current===generation&&(response.status===401||response.status===403))revoke();
      const failure=Error(typeof result.detail==='string'?result.detail:'The request could not be completed. Please try again.');failure.status=response.status;throw failure;
    }
    return result;
  }
  function checkAccess(options={}) {
    if(accessFlight)return accessFlight;
    if(!options.force&&access!==null)return Promise.resolve(access);
    const current=generation;
    const task=(async()=>{
      try{
        const result=await request('/access');
        if(current!==generation)return false;
        access=result.is_admin===true;
        if(!access)accessNotice();
        window.dispatchEvent(new CustomEvent('lockx-admin-access',{detail:{isAdmin:access}}));
        return access;
      }catch(error){
        if(current===generation){access=false;accessNotice(![401,403,404].includes(error.status));window.dispatchEvent(new CustomEvent('lockx-admin-access',{detail:{isAdmin:false}}));}
        return false;
      }finally{if(accessFlight===task)accessFlight=null;}
    })();
    accessFlight=task;return task;
  }
  const metrics=[['gross_sales_cents','Gross sales','money'],['refunds_cents','Refunds on selected purchases','money'],['net_payments_cents','Net after refunds · before fees','money'],['payments_count','Payments'],['credits_purchased','Credits purchased'],['credits_granted','Credits granted'],['credits_used','Net credits used'],['current_credit_balance','Current credit balance'],['wallet_accounts','Wallet accounts'],['verifications_total','Item checks'],['verified','Matched'],['mismatch','Mismatch'],['inconclusive','Inconclusive'],['failed','Technical failures'],['pending','Pending']];
  const campaignSources=['instagram','tiktok','facebook','youtube','x','linkedin','pinterest','threads','other'];
  const campaignSourceLabels={instagram:'Instagram',tiktok:'TikTok',facebook:'Facebook',youtube:'YouTube',x:'X',linkedin:'LinkedIn',pinterest:'Pinterest',threads:'Threads',other:'Other'};
  const socialMetrics=[['visits','Tracked visits'],['verify_clicks','Verify clicks'],['wallet_opens','Wallet opens'],['checkout_starts','Checkouts started'],['paying_visits','Paying visits'],['payments_count','Payments'],['gross_sales_cents','Attributed sales','money'],['verifications_submitted','Checks submitted'],['verifications_completed','Checks completed'],['verifications_matched','Matched checks'],['payment_conversion_rate','Visit-to-purchase rate','percent']];
  const socialColumns=[['visits','Visits'],['verify_clicks','Verify clicks'],['checkout_starts','Checkouts'],['payments_count','Payments'],['gross_sales_cents','Sales','money'],['verifications_submitted','Submitted'],['verifications_completed','Completed'],['verifications_matched','Matched'],['payment_conversion_rate','Purchase rate','percent']];
  const socialValue=(value,type,visits)=>type==='money'?money(value):type==='percent'?(Number.isFinite(visits)&&visits>0?percent(value):'—'):count(value);
  function socialPanel() {
    return `<section class="ca-social" aria-labelledby="caSocialTitle"><div class="ca-section-heading"><div><h2 id="caSocialTitle">Social media impact</h2><p>Visits, credit purchases and item checks connected to your campaign links.</p></div></div><div class="ca-metrics" aria-live="polite">${socialMetrics.map(([key,label])=>`<article class="ca-metric"><p>${esc(label)}</p><strong data-ca-social="${key}">—</strong></article>`).join('')}</div><p id="caSocialStatus" class="ca-quiet" role="status">Loading campaign activity…</p><p id="caTrackingSince" class="ca-tracking-note">Tracking starts with this release. Earlier activity is not backfilled.</p><div id="caSocialNotes" class="ca-quiet"></div>
      <div class="ca-panel ca-social-tables"><div class="ca-panel-heading"><h3>Sources</h3><p>Scroll horizontally to see all metrics.</p></div><div id="caSocialSources" class="ca-table-wrap"><p class="ca-empty">Loading sources…</p></div><div class="ca-panel-heading ca-table-section"><h3>Campaigns</h3><p>Compare the visits and outcomes attached to each campaign and content label.</p></div><div id="caSocialCampaigns" class="ca-table-wrap"><p class="ca-empty">Loading campaigns…</p></div></div>
      <section class="ca-panel ca-campaign-builder" aria-labelledby="caCampaignTitle"><div class="ca-panel-heading"><h3 id="caCampaignTitle">Create a campaign link</h3><p>Use a different campaign or content label to compare posts. These links open the LockX homepage.</p></div><form id="caCampaignForm" class="ca-campaign-form"><label for="caCampaignSource">Source<select id="caCampaignSource">${campaignSources.map(source=>`<option value="${source}">${esc(campaignSourceLabels[source])}</option>`).join('')}</select></label><label for="caCampaignName">Campaign<input id="caCampaignName" required maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,79}" placeholder="summer-launch" autocomplete="off"></label><label for="caCampaignContent">Content <span class="ca-optional">optional</span><input id="caCampaignContent" maxlength="120" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,119}" placeholder="reel-01" autocomplete="off"></label><p class="ca-campaign-help">Use letters, numbers, dots, dashes or underscores. Links use the social medium.</p><button class="ca-button" type="submit">Generate link</button><div class="ca-campaign-output"><label for="caCampaignLink">Your campaign link<input id="caCampaignLink" type="url" readonly placeholder="Generate a link above" autocomplete="off"></label><button class="ca-button ca-secondary" type="button" data-ca-copy-link disabled>Copy link</button></div><p id="caCampaignStatus" class="ca-quiet" role="status"></p></form></section></section>`;
  }
  function shell() {
    page.innerHTML=`<div class="ca-shell"><header class="ca-heading"><div><p class="ca-eyebrow">Private workspace · LockX admin</p><h1 id="caTitle">Credits & activity</h1><p class="ca-subtitle">Manage complimentary credits and see how LockX is being used.</p></div><a class="ca-link" href="/#landing">Back to LockX →</a></header>
      <div id="caNotice" class="ca-notice" role="status" hidden></div>
      <section class="ca-analytics" aria-labelledby="caAnalyticsTitle"><div class="ca-section-heading"><div><h2 id="caAnalyticsTitle">Business activity</h2><p>Sales and refunds refer to purchases in the selected period. Credit balances and wallet accounts are current totals.</p></div><div class="ca-toolbar"><label for="caPeriod">Period<select id="caPeriod"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option></select></label><button class="ca-button ca-secondary" data-ca-refresh type="button">Refresh</button></div></div>
      <div id="caMetrics" class="ca-metrics" aria-live="polite">${metrics.map(([key,label])=>`<article class="ca-metric"><p>${esc(label)}</p><strong data-ca-metric="${key}">—</strong></article>`).join('')}</div><div id="caAnalyticsStatus" class="ca-quiet" role="status">Loading activity…</div><div id="caAnalyticsNotes" class="ca-quiet"></div><div id="caDaily" class="ca-panel ca-chart-panel"></div></section>
      ${socialPanel()}<div class="ca-columns"><section class="ca-panel" aria-labelledby="caGrantTitle"><div class="ca-panel-heading"><h2 id="caGrantTitle">Add complimentary credits</h2><p>Look up a customer, then review the grant before adding credits.</p></div><form id="caGrantForm" class="ca-form"><label for="caEmail">Customer email<input id="caEmail" name="email" type="email" autocomplete="off" required maxlength="254" placeholder="customer@example.com"></label><button class="ca-button ca-secondary" type="button" data-ca-lookup>Look up customer</button><div id="caRecipient" class="ca-recipient" hidden></div><div class="ca-form-row"><label for="caCredits">Credits to add<input id="caCredits" name="credits" type="number" inputmode="numeric" min="1" max="10000" step="1" required placeholder="10"></label></div><label for="caReason">Reason<textarea id="caReason" name="reason" rows="3" required maxlength="300" placeholder="For example, customer support adjustment"></textarea></label><button class="ca-button" type="submit">Review credit grant</button><div id="caGrantReview" class="ca-review" hidden></div></form></section>
      <section class="ca-panel ca-audit" aria-labelledby="caAuditTitle"><div class="ca-panel-heading"><h2 id="caAuditTitle">Credit grant history</h2><p>Complimentary credits are recorded separately from purchases.</p></div><div id="caGrants" class="ca-table-wrap"><p class="ca-empty">Loading grant history…</p></div></section></div></div>`;
    $('#caPeriod',page).value=String(period);
  }
  function renderAnalytics(data) {
    const summary=data.summary||data.totals||data;
    metrics.forEach(([key,,type])=>{const target=$(`[data-ca-metric="${key}"]`,page);if(target)target.textContent=type==='money'?money(summary[key]):count(summary[key]);});
    const notes=$('#caAnalyticsNotes',page);if(notes)notes.innerHTML=Array.isArray(data.notes)?data.notes.map(note=>`<p>${esc(note)}</p>`).join(''):'';
    const daily=Array.isArray(data.daily)?data.daily:null;
    const target=$('#caDaily',page);if(!target)return;
    if(!daily?.length){target.innerHTML=`<h3>Daily volume</h3><p class="ca-quiet">${daily?'No daily activity for this period.':'Daily activity is not available.'}</p>`;return;}
    const rows=daily.slice(0,366).map(row=>({date:String(row.date||row.day||''),payments:row.payments_count,checks:row.verifications}));
    const maximum=Math.max(1,...rows.flatMap(row=>[row.payments,row.checks]).filter(Number.isFinite));
    const bars=rows.map(row=>`<div class="ca-bar-day" title="${esc(row.date)}: ${esc(count(row.payments))} payments, ${esc(count(row.checks))} item checks"><i class="ca-bar ca-bar-payments" style="height:${Number.isFinite(row.payments)?Math.min(100,Math.max(0,row.payments/maximum*100)):0}%"></i><i class="ca-bar ca-bar-checks" style="height:${Number.isFinite(row.checks)?Math.min(100,Math.max(0,row.checks/maximum*100)):0}%"></i></div>`).join('');
    target.innerHTML=`<div class="ca-chart-heading"><h3>Daily volume · UTC</h3><div class="ca-legend"><span>Payments</span><span>Item checks</span></div></div><div class="ca-chart-scroll"><div class="ca-bars" style="--ca-days:${rows.length}" aria-hidden="true">${bars}</div></div><p class="ca-chart-dates">${esc(rows[0].date)}<span>${esc(rows.at(-1).date)}</span></p><details class="ca-daily-table"><summary>Daily figures</summary><div class="ca-table-wrap"><table><thead><tr><th>Date (UTC)</th><th>Payments</th><th>Item checks</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.date)}</td><td>${esc(count(row.payments))}</td><td>${esc(count(row.checks))}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  function renderGrants(data) {
    const rows=Array.isArray(data)?data:(data.grants||[]);const target=$('#caGrants',page);if(!target)return;
    if(!rows.length){target.innerHTML='<p class="ca-empty">No complimentary credit grants have been recorded.</p>';return;}
    target.innerHTML=`<table><thead><tr><th>Recipient</th><th>Credits</th><th>Reason</th><th>Date</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.email||row.recipient_email||'—')}</td><td>+${esc(count(row.credits))}</td><td>${esc(row.reason||'—')}</td><td>${esc(stamp(row.created))}</td></tr>`).join('')}</tbody></table>`;
  }
  function socialTable(rows,campaigns=false) {
    if(!Array.isArray(rows)||!rows.length)return '<p class="ca-empty">Tracking starts with this release. No tracked activity for this period yet.</p>';
    const limit=campaigns?200:100;
    return `<table class="ca-social-table"><thead><tr><th>${campaigns?'Campaign / content':'Source'}</th>${campaigns?'<th>Source</th>':''}${socialColumns.map(([,label])=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,limit).map(row=>`<tr><td>${campaigns?`<strong>${esc(row.campaign||'Untagged')}</strong><small>${esc(row.content||'No content label')}</small>`:`<strong>${esc(row.source||'Direct / untagged')}</strong><small>${esc(row.medium||'Untagged medium')}</small>`}</td>${campaigns?`<td>${esc(row.source||'Direct / untagged')}<small>${esc(row.medium||'Untagged medium')}</small></td>`:''}${socialColumns.map(([key,,type])=>`<td>${esc(socialValue(row[key],type,row.visits))}</td>`).join('')}</tr>`).join('')}</tbody></table>${rows.length>limit?`<p class="ca-empty">Showing the first ${limit} ${campaigns?'campaigns':'sources'}.</p>`:''}`;
  }
  function renderSocial(data) {
    const summary=data.summary||{};
    socialMetrics.forEach(([key,,type])=>{const target=$(`[data-ca-social="${key}"]`,page);if(target)target.textContent=socialValue(summary[key],type,summary.visits);});
    const since=$('#caTrackingSince',page);if(since)since.textContent=data.tracking_since?`Tracking began ${stamp(data.tracking_since)}. Earlier activity is not backfilled.`:'Tracking starts with this release. Earlier activity is not backfilled.';
    const notes=$('#caSocialNotes',page);if(notes)notes.innerHTML=Array.isArray(data.notes)&&data.notes.length?data.notes.map(note=>`<p>${esc(note)}</p>`).join(''):'<p>Attribution follows tracked visits started during the selected UTC period and their linked outcomes. It can miss other devices and visits without tracking.</p>';
    const sources=$('#caSocialSources',page),campaigns=$('#caSocialCampaigns',page);
    if(sources)sources.innerHTML=socialTable(data.sources);
    if(campaigns)campaigns.innerHTML=socialTable(data.campaigns,true);
    const status=$('#caSocialStatus',page);if(status)status.textContent='Updated '+stamp(data.generated_at)+'. Visit-to-purchase rate is the share of tracked visits linked to a payment.';
  }
  function clearCampaignLink() {
    const output=$('#caCampaignLink',page),button=$('[data-ca-copy-link]',page);
    if(output)output.value='';if(button)button.disabled=true;
    const status=$('#caCampaignStatus',page);if(status)status.textContent='';
  }
  function generateCampaignLink() {
    const form=$('#caCampaignForm',page);if(!form?.reportValidity())return;
    const source=$('#caCampaignSource',page).value,campaign=$('#caCampaignName',page).value.trim().toLowerCase(),content=$('#caCampaignContent',page).value.trim().toLowerCase();
    const valid=(value,limit)=>value.length<=limit&&/^[a-z0-9][a-z0-9._-]*$/.test(value);
    if(!campaignSources.includes(source)||!valid(campaign,80)||(content&&!valid(content,120))){clearCampaignLink();$('#caCampaignStatus',page).textContent='Use a listed source and labels containing only letters, numbers, dots, dashes or underscores.';return;}
    const url=new URL('https://lockx.ai/');url.searchParams.set('utm_source',source);url.searchParams.set('utm_medium','social');url.searchParams.set('utm_campaign',campaign);if(content)url.searchParams.set('utm_content',content);
    $('#caCampaignLink',page).value=url.href;$('[data-ca-copy-link]',page).disabled=false;$('#caCampaignStatus',page).textContent='Your link is ready. Publish it with the matching campaign or post.';
  }
  async function copyCampaignLink() {
    const input=$('#caCampaignLink',page);if(!input?.value)return;
    const status=$('#caCampaignStatus',page);
    try{await navigator.clipboard.writeText(input.value);status.textContent='Campaign link copied.';}
    catch{input.focus();input.select();status.textContent='Link selected. Use Copy on your device.';}
  }
  async function loadData() {
    const current=generation,sequence=++refreshSequence;
    const status=$('#caAnalyticsStatus',page);if(status)status.textContent='Updating activity…';
    const socialStatus=$('#caSocialStatus',page);if(socialStatus)socialStatus.textContent='Updating campaign activity…';
    const results=await Promise.allSettled([request('/analytics?days='+period),request('/grants'),request('/social?days='+period)]);
    if(current!==generation||sequence!==refreshSequence||!access)return;
    if(results[0].status==='fulfilled'){renderAnalytics(results[0].value);if(status)status.textContent='Updated '+stamp(results[0].value.generated_at)+'.';}
    else if(status)status.textContent='Activity could not refresh. Please try again.';
    if(results[1].status==='fulfilled')renderGrants(results[1].value);
    else {const target=$('#caGrants',page);if(target)target.innerHTML='<p class="ca-empty">Grant history could not load. Please refresh.</p>';}
    if(results[2].status==='fulfilled')renderSocial(results[2].value);
    else if(socialStatus)socialStatus.textContent='Campaign activity could not refresh. Please try again.';
  }
  async function refresh() {
    if(!await checkAccess({force:true}))return false;
    if(!$('#caMetrics',page))shell();
    await loadData();return true;
  }
  function activate() {
    document.querySelectorAll('.page.active').forEach(element=>element.classList.remove('active'));
    page.classList.add('active');document.body.classList.add('lockx-public');document.body.classList.remove('landing-active');
  }
  function open() {
    document.title='LockX Admin';
    if(!adminPath()||location.hash){const method=location.hash==='#admin'?'replaceState':'pushState';history[method](null,'','/Ngoalex1');}
    if(typeof window.go==='function')window.go('admin');else activate();
    if(opening)return opening;
    const current=generation;
    page.innerHTML='<div class="ca-shell"><p class="ca-eyebrow">LockX admin</p><h1 id="caTitle">Checking administrator access…</h1></div>';
    opening=(async()=>{if(!await checkAccess({force:true})||current!==generation)return;recipient=null;review=null;shell();await loadData();})().finally(()=>{opening=null;});
    return opening;
  }
  function draft() {
    const form=$('#caGrantForm',page);if(!form||!form.reportValidity())return null;
    const email=$('#caEmail',page).value.trim().toLowerCase(),credits=Number($('#caCredits',page).value),reason=$('#caReason',page).value.trim();
    if(!Number.isSafeInteger(credits)||credits<1||credits>10000||reason.length<1||reason.length>300){notice('Enter 1–10,000 whole credits and a reason of up to 300 characters.',true);return null;}
    return {email,credits,reason};
  }
  async function lookup() {
    const emailField=$('#caEmail',page);if(!emailField?.reportValidity())return null;
    const email=emailField.value.trim().toLowerCase(),current=generation;
    if(lookupFlight?.email===email)return lookupFlight.promise;
    const button=$('[data-ca-lookup]',page);if(button)button.disabled=true;
    const promise=(async()=>{
      try{
        const data=await request('/users?email='+encodeURIComponent(email));
        if(current!==generation||$('#caEmail',page)?.value.trim().toLowerCase()!==email)return null;
        const user=data.user||(Array.isArray(data.users)?data.users[0]:data);
        if(!user?.email||user.email.toLowerCase()!==email)throw Error('No matching customer was found. Ask them to sign in to LockX first.');
        recipient=user;
        const target=$('#caRecipient',page);target.hidden=false;target.innerHTML=`<strong>${esc(user.email)}</strong><span>Current balance: ${esc(count(user.balance))} credits</span>`;
        return user;
      }catch(error){if(current===generation){recipient=null;notice(error.message,true);}return null;}
      finally{if(button?.isConnected)button.disabled=false;if(lookupFlight?.promise===promise)lookupFlight=null;}
    })();
    lookupFlight={email,promise};return promise;
  }
  async function reviewGrant() {
    if(granting)return;const values=draft();if(!values)return;
    if(!recipient||recipient.email.toLowerCase()!==values.email){if(!await lookup())return;}
    const current=draft();if(!current||current.email!==values.email||!recipient)return;
    const fingerprint=JSON.stringify(current);
    if(!grantAttempt||grantAttempt.fingerprint!==fingerprint)grantAttempt={fingerprint,key:crypto.randomUUID()};
    review={...current,request_key:grantAttempt.key};
    const target=$('#caGrantReview',page);target.hidden=false;target.innerHTML=`<h3>Review credit grant</h3><dl><div><dt>Customer</dt><dd>${esc(review.email)}</dd></div><div><dt>Credits to add</dt><dd>${esc(count(review.credits))}</dd></div><div><dt>Reason</dt><dd>${esc(review.reason)}</dd></div></dl><p>These are complimentary credits. No payment is created.</p><button type="button" class="ca-button" data-ca-confirm>Add ${esc(count(review.credits))} credits</button>`;
  }
  async function confirmGrant() {
    if(granting||!review)return;
    const current=draft();if(!current||JSON.stringify(current)!==grantAttempt?.fingerprint){notice('The details changed. Review this credit grant again.',true);return;}
    const payload={...review},version=generation;granting=true;
    $('#caGrantForm',page).querySelectorAll('input,textarea,button').forEach(control=>control.disabled=true);
    try{
      const result=await request('/grants',{method:'POST',body:JSON.stringify(payload)});
      if(version!==generation||!access)return;
      notice(`${result.duplicated?'This grant was already recorded.':'Credits added.'} ${result.email||payload.email} now has ${count(result.balance)} credits.`);
      grantAttempt=null;review=null;recipient=null;$('#caGrantForm',page).reset();$('#caGrantReview',page).hidden=true;$('#caRecipient',page).hidden=true;
      await loadData();window.LockXCredits?.refresh?.().catch(()=>null);
    }catch(error){if(version===generation&&access)notice(error.status?error.message:'The grant could not be confirmed. Retry this same grant to safely check its status.',true);}
    finally{granting=false;$('#caGrantForm',page)?.querySelectorAll('input,textarea,button').forEach(control=>control.disabled=false);}
  }
  page.addEventListener('submit',event=>{if(event.target.id==='caGrantForm'){event.preventDefault();reviewGrant();}if(event.target.id==='caCampaignForm'){event.preventDefault();generateCampaignLink();}});
  page.addEventListener('input',event=>{
    if(event.target.closest('#caCampaignForm')&&event.target.id!=='caCampaignLink'){clearCampaignLink();return;}
    if(!event.target.closest('#caGrantForm')||granting)return;
    review=null;const target=$('#caGrantReview',page);if(target)target.hidden=true;
    if(event.target.id==='caEmail'){recipient=null;const target=$('#caRecipient',page);if(target)target.hidden=true;}
  });
  page.addEventListener('change',event=>{if(event.target.id==='caPeriod'){period=Number(event.target.value);if([7,30,90].includes(period))loadData();}if(event.target.id==='caCampaignSource')clearCampaignLink();});
  page.addEventListener('click',event=>{
    const control=event.target.closest('button');if(!control)return;
    if(control.hasAttribute('data-ca-signin'))window.LockXCredits?.open();
    if(control.hasAttribute('data-ca-retry'))open();
    if(control.hasAttribute('data-ca-refresh'))refresh();
    if(control.hasAttribute('data-ca-lookup'))lookup();
    if(control.hasAttribute('data-ca-confirm'))confirmGrant();
    if(control.hasAttribute('data-ca-copy-link'))copyCampaignLink();
  });
  function adminPath(){return location.pathname.replace(/\/+$/,'').toLowerCase()==='/ngoalex1';}
  const isAdminRoute=()=>location.hash==='#admin'||(adminPath()&&!location.hash);
  const onAdminRoute=()=>{if(isAdminRoute())open();};
  window.addEventListener('hashchange',onAdminRoute);
  window.addEventListener('popstate',onAdminRoute);
  window.addEventListener('lockx-session',()=>{
    generation++;access=null;accessFlight=null;opening=null;recipient=null;review=null;grantAttempt=null;lookupFlight=null;refreshSequence++;accessNotice();
    setTimeout(()=>{if(isAdminRoute())open();else checkAccess({force:true});},0);
  });
  window.LockXAdmin={checkAccess,open,refresh};
  window.dispatchEvent(new Event('lockx-admin-ready'));
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',onAdminRoute,{once:true});else onAdminRoute();
})();
