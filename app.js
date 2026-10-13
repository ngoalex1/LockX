
const API_BASE = 'https://lockx-production.up.railway.app/api/v1';
let cases = [];

function caseNumber(id) { return 'LX-' + id.replace(/-/g, '').slice(-6).toUpperCase(); }
function displayCase(c) { return {...c, name: c.brand + ' ' + c.model, ref: c.reference || 'REFERENCE PENDING', serial: c.serial_number || 'NOT PROVIDED', status: c.status === 'paused' ? 'Paused' : 'Monitoring'}; }
function emptyState() { return '<div class="empty-state"><strong>No recovery cases yet.</strong><p>Report a stolen watch to begin protected monitoring.</p></div>'; }
function renderCases() {
  const dashboard = document.querySelector('#dashCases');
  const cards = document.querySelector('#caseCards');
  const count = document.querySelector('#caseCount');
  if (count) count.textContent = String(cases.length).padStart(2, '0');
  if (dashboard) dashboard.innerHTML = cases.length ? cases.slice(0, 3).map(c => '<div class="case-row"><span class="watch-thumb"></span><div class="case-copy"><strong>' + c.name + '</strong><p>' + c.ref + ' · CASE ' + caseNumber(c.id) + '</p></div><span class="state">' + c.status + '</span><span class="case-arrow">›</span></div>').join('') : emptyState();
  if (cards) cards.innerHTML = cases.length ? cases.map(c => '<article class="case-card"><div class="card-img"></div><div class="card-body"><div class="case-meta"><span class="state">' + c.status + '</span></div><h2>' + c.name + '</h2><p>' + c.ref + ' · CASE ' + caseNumber(c.id) + '</p><div class="case-data"><span>Serial <strong>' + c.serial + '</strong></span><span>Reported <strong>' + new Date(c.created_at).toLocaleDateString(undefined,{month:'short',day:'numeric'}) + '</strong></span></div></div><div class="case-footer"><span>Monitoring profile active</span><b>0 matches →</b></div></article>').join('') : emptyState();
}
function go(page) { document.querySelectorAll('.page,.nav-item').forEach(e => e.classList.remove('active')); document.getElementById(page)?.classList.add('active'); document.querySelector('.nav-item[data-page="' + page + '"]')?.classList.add('active'); document.getElementById('pageName').textContent = ({dashboard:'Overview',cases:'My cases',matches:'Potential matches',alerts:'Alerts',monitoring:'Monitoring',sources:'Sources'})[page] || 'Overview'; }
function toast(title, text) { const el=document.getElementById('toast'); document.getElementById('toastTitle').textContent=title; document.getElementById('toastText').textContent=text; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 3600); }
async function loadCases() { try { const response = await fetch(API_BASE + '/cases'); if (!response.ok) throw new Error(); cases = (await response.json()).map(displayCase); } catch { toast('Case service unavailable', 'Your saved cases will appear when the connection is restored.'); } renderCases(); }
document.addEventListener('click', e => { const page=e.target.closest('[data-page]'); if(page) go(page.dataset.page); if(e.target.matches('#newCaseBtn,#newCaseBtn2')) document.getElementById('caseModal').classList.add('open'); if(e.target.dataset.close) document.getElementById(e.target.dataset.close).classList.remove('open'); if(e.target.closest('.mobile-menu')) document.querySelector('.sidebar').classList.toggle('open'); });
document.getElementById('caseForm').addEventListener('submit', async e => { e.preventDefault(); const form=e.target, data=new FormData(form), submit=form.querySelector('[type="submit"]'); submit.disabled=true; submit.textContent='Saving…'; try { const response=await fetch(API_BASE + '/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({brand:data.get('brand'),model:data.get('model'),reference:data.get('reference')||null,serial_number:data.get('serial')||null,distinctive_details:data.get('details')||null})}); if(!response.ok) throw new Error(); cases.unshift(displayCase(await response.json())); renderCases(); form.reset(); document.getElementById('caseModal').classList.remove('open'); toast('Case created','Your protected monitoring profile is ready.'); go('cases'); } catch { toast('Unable to save case','Please try again in a moment.'); } finally { submit.disabled=false; submit.innerHTML='Create case <span>→</span>'; } });
document.getElementById('caseModal').addEventListener('click', e => { if(e.target.id==='caseModal') e.currentTarget.classList.remove('open'); });
loadCases();
