const cases = [
  { name: 'Rolex Submariner', ref: 'REF. 124060', serial: '8D7•••81', status: 'Monitoring', matches: 3, last: 'Scanned 8 min ago', shade: '' },
  { name: 'Audemars Piguet Royal Oak', ref: 'REF. 15500ST', serial: 'J4•••29', status: 'Monitoring', matches: 2, last: 'Scanned 8 min ago', shade: 'gold' },
  { name: 'Omega Speedmaster', ref: 'REF. 310.30.42', serial: '89•••06', status: 'Paused', matches: 2, last: 'Paused 3 days ago', shade: 'blue' }
];
const findings = [
  { title:'Rolex Submariner Date 41mm', meta:'Listed Sep 15 · New York, US', source:'Chrono24', type:'Dealer listing', confidence:'94%', level:'high', image:'' },
  { title:'Rolex 124060 Black Dial', meta:'Listed Sep 14 · Miami, US', source:'eBay', type:'Official API feed', confidence:'89%', level:'high', image:'b' },
  { title:'AP Royal Oak 15500ST', meta:'Listed Sep 14 · Los Angeles, US', source:'Web signal', type:'Permitted public result', confidence:'78%', level:'', image:'' },
  { title:'Omega Speedmaster Professional', meta:'Listed Sep 13 · London, UK', source:'Watchfinder', type:'Partner feed', confidence:'74%', level:'', image:'b' },
  { title:'Submariner No Date 41', meta:'Listed Sep 12 · Dallas, US', source:'Web signal', type:'Permitted public result', confidence:'68%', level:'', image:'' },
  { title:'Audemars Piguet Royal Oak', meta:'Listed Sep 11 · Chicago, US', source:'Dealer network', type:'Partner feed', confidence:'65%', level:'', image:'b' },
  { title:'Speedmaster Moonwatch', meta:'Listed Sep 10 · Toronto, CA', source:'Web signal', type:'Permitted public result', confidence:'61%', level:'', image:'' }
];
const activity = [
  ['New potential match found', 'Rolex Submariner · Chrono24', '8 min ago'],
  ['Marketplace scan completed', '326 new listings analyzed across 14 sources', '8 min ago'],
  ['Evidence record updated', 'AP Royal Oak · listing data snapshot captured', '1 hr ago'],
  ['New potential match found', 'Omega Speedmaster · Watchfinder', '3 hrs ago']
];
const alerts = [
  ['A high-confidence match needs review', 'A Rolex Submariner listing matched 94% with case LX-02481.', '8 min ago', 'orange', true],
  ['Daily monitoring summary is ready', '2,841 listings scanned. 3 new candidate matches added.', 'Today, 9:00 AM', '', true],
  ['Evidence was preserved', 'A snapshot and SHA-256 record were created for the AP Royal Oak listing.', 'Yesterday', '', false],
  ['Monitoring resumed', 'Your Rolex Submariner case is now actively searching 14 sources.', 'Sep 13', '', false]
];
const sources = [
  ['Chrono24', 'CH', 'Partner search feed with listing metadata.', 'Connected', ''],
  ['eBay', 'eb', 'Official marketplace API integration.', 'Connected', 'eb'],
  ['Watchfinder', 'WF', 'Authorized partner listing feed.', 'Connected', 'ch'],
  ['Google alerts', 'G', 'Permitted indexed-web signals.', 'Connected', 'g'],
  ['Dealer network', 'DN', 'Verified independent dealer feeds.', 'Connected', ''],
  ['Auction houses', 'AH', 'Approved auction catalog sources.', 'Reviewing access', 'ch']
];

function thumb(shade='') { return `<span class="watch-thumb ${shade}"></span>` }
function render() {
  document.querySelector('#dashCases').innerHTML = cases.map((c,i) => `<div class="case-row">${thumb(c.shade)}<div class="case-copy"><strong>${c.name}</strong><p>${c.ref} · CASE LX-0248${i+1}</p></div><span class="state ${c.status==='Paused'?'paused':''}">${c.status}</span><span class="case-arrow">›</span></div>`).join('');
  document.querySelector('#dashMatches').innerHTML = findings.slice(0,2).map(f => `<div class="mini-match"><span class="listing-image ${f.image}"></span><div><strong>${f.title}</strong><p>${f.source} · ${f.meta.split(' · ')[0]}</p></div><span class="confidence ${f.level}">${f.confidence}</span></div>`).join('');
  document.querySelector('#activityList').innerHTML = activity.map(x => `<div class="activity"><time>${x[2]}</time><p><strong>${x[0]}</strong><small>${x[1]}</small></p></div>`).join('');
  document.querySelector('#caseCards').innerHTML = cases.map((c,i) => `<article class="case-card"><div class="card-img ${c.shade}"></div><div class="card-body"><div class="case-meta"><span class="state ${c.status==='Paused'?'paused':''}">${c.status}</span><span class="case-arrow">•••</span></div><h2>${c.name}</h2><p>${c.ref} · CASE LX-0248${i+1}</p><div class="case-data"><span>Serial <strong>${c.serial}</strong></span><span>Reported <strong>Sep ${2+i}</strong></span></div></div><div class="case-footer"><span>${c.last}</span><b>${c.matches} matches →</b></div></article>`).join('');
  document.querySelector('#matchTable').innerHTML = `<div class="match-head"><span>LISTING</span><span>SOURCE</span><span>CONFIDENCE</span><span>STATUS</span><span></span></div>` + findings.map((f,i) => `<div class="match-row"><div class="match-item"><span class="listing-image ${f.image}"></span><div class="match-title"><strong>${f.title}</strong><p>${f.meta}</p></div></div><div class="source-label">${f.source}<small>${f.type}</small></div><span class="confidence ${f.level}">${f.confidence}</span><span class="state ${i<2?'':'paused'}">${i<2?'Review now':'Under review'}</span><button class="dots" title="More actions">•••</button></div>`).join('');
  document.querySelector('#alertList').innerHTML = alerts.map(a => `<article class="alert ${a[4]?'unread':''}"><span class="alert-icon ${a[3]}">${a[3]?'!':'✦'}</span><div class="alert-copy"><strong>${a[0]}</strong><p>${a[1]}</p></div><time>${a[2]}</time></article>`).join('');
  document.querySelector('#timeline').innerHTML = activity.concat([['Search profile refreshed','New visual descriptors added to Rolex case','6 hrs ago']]).map(x => `<div class="timeline-event"><p><strong>${x[0]}</strong><br /><span>${x[1]}</span><br /><small>${x[2]}</small></p></div>`).join('');
  document.querySelector('#sourceGrid').innerHTML = sources.map(s => `<article class="source"><div class="source-top"><span class="source-logo ${s[4]}">${s[1]}</span><button class="dots">•••</button></div><h2>${s[0]}</h2><p>${s[2]}</p><div class="source-footer"><small class="${s[3].startsWith('Review')?'wait':''}">● ${s[3]}</small><button class="text-button">Details →</button></div></article>`).join('');
}
function go(page) { document.querySelectorAll('.page,.nav-item').forEach(e=>e.classList.remove('active')); document.getElementById(page).classList.add('active'); document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active'); document.getElementById('pageName').textContent = ({dashboard:'Overview',cases:'My cases',matches:'Potential matches',alerts:'Alerts',monitoring:'Monitoring',sources:'Sources'})[page]; window.scrollTo({top:0,behavior:'smooth'}); document.querySelector('.sidebar').classList.remove('open'); }
function toast(title, text) { const el=document.getElementById('toast'); document.getElementById('toastTitle').textContent=title; document.getElementById('toastText').textContent=text; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),3600); }
render();
document.addEventListener('click', e => { const target=e.target.closest('[data-page]'); if(target) go(target.dataset.page); if(e.target.matches('#newCaseBtn,#newCaseBtn2')) document.getElementById('caseModal').classList.add('open'); if(e.target.dataset.close) document.getElementById(e.target.dataset.close).classList.remove('open'); if(e.target.id==='readAll'){document.querySelectorAll('.alert.unread').forEach(x=>x.classList.remove('unread'));toast('Alerts marked as read','You are all caught up.');} if(e.target.id==='runScan'){e.target.innerHTML='<span>↻</span> Scan started';toast('Fresh scan initiated','The agent is now checking approved sources.'); setTimeout(()=>e.target.innerHTML='<span>↻</span> Run a fresh scan',2200)} if(e.target.closest('.mobile-menu'))document.querySelector('.sidebar').classList.toggle('open'); });
document.getElementById('caseForm').addEventListener('submit', e => { e.preventDefault(); const data=new FormData(e.target); cases.unshift({name:`${data.get('brand')} ${data.get('model')}`,ref:data.get('reference')||'REFERENCE PENDING',serial:data.get('serial')||'NOT PROVIDED',status:'Monitoring',matches:0,last:'Profile processing',shade:''}); document.getElementById('caseCount').textContent=String(cases.length).padStart(2,'0'); render(); document.getElementById('caseModal').classList.remove('open'); e.target.reset(); toast('Case created','Your recovery profile is being prepared for monitoring.'); go('cases'); });
document.getElementById('caseModal').addEventListener('click',e=>{if(e.target.id==='caseModal')e.currentTarget.classList.remove('open')});
