/* The public LockX experience. No account or application state is needed. */
(() => {
  'use strict';

  const check = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const arrow = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  const font = '-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif';

  function pokemonCard(view, id) {
    const foil = `foil-${id}`;
    const sky = `sky-${id}`;
    const pika = `<path d="m139 88 12-16 10 3-9 15 12 5-16 12-10-5" fill="#f7d241" stroke="#c19b21" stroke-width="1.2"/><ellipse cx="126" cy="107" rx="19" ry="18" fill="#fbd645"/><path d="m111 85-9-23 8-2 11 23m13 0 13-23 7 4-9 25" fill="#fbd645" stroke="#c19b21" stroke-width="1.2"/><path d="m102 62 8-2 4 9-8 3m41-12 7 4-5 9-7-4" fill="#37312e"/><ellipse cx="127" cy="89" rx="22" ry="18" fill="#ffdc48"/><ellipse cx="118" cy="86" rx="2.5" ry="3.2" fill="#30282a"/><ellipse cx="135" cy="86" rx="2.5" ry="3.2" fill="#30282a"/><circle cx="117.4" cy="85" r=".8" fill="white"/><circle cx="134.4" cy="85" r=".8" fill="white"/><circle cx="110" cy="94" r="4.2" fill="#e96445"/><circle cx="144" cy="94" r="4.2" fill="#e96445"/><path d="m125 91 2 1 2-1m-7 7q5 4 10-1" stroke="#52332c" stroke-width="1.5" stroke-linecap="round"/><path d="m109 104-7 9m39-9 7 7" stroke="#ebba26" stroke-width="7" stroke-linecap="round"/><ellipse cx="116" cy="122" rx="8" ry="4" fill="#eac231"/><ellipse cx="137" cy="122" rx="8" ry="4" fill="#eac231"/>`;
    const front = `<rect x="78" y="21" width="104" height="154" rx="7" fill="#ddae36"/><rect x="82" y="25" width="96" height="146" rx="4" fill="#f6da75"/><rect x="85" y="28" width="90" height="14" rx="2" fill="#f9e69e"/><text x="88" y="38" fill="#3a352c" font-size="8" font-weight="750">Pikachu</text><text x="156" y="38" fill="#51422c" font-size="5.2" font-weight="600">HP 60</text><circle cx="170" cy="35" r="3.4" fill="#e7bf38"/><path d="m170 32-2 4h2l-1 3 3-5h-2Z" fill="#51422c"/><rect x="87" y="45" width="86" height="83" rx="1" fill="url(#${sky})" stroke="#bc9430" stroke-width="2"/><path d="M88 108q19-21 44-8t40-6v33H88Z" fill="#78b987"/><path d="M88 118q32-18 84-6v15H88Z" fill="#a4cd7d"/>${pika}<rect x="88" y="133" width="84" height="5" rx="1" fill="#eed18a"/><circle cx="92" cy="146" r="3" fill="#f4bd2e" stroke="#b18c25" stroke-width=".5"/><path d="m93 143-2 3h2l-1 3" stroke="#735b30" stroke-width=".7"/><text x="100" y="148" fill="#51442a" font-size="6" font-weight="650">Thunder Shock</text><text x="163" y="148" fill="#51442a" font-size="6" font-weight="650">20</text><path d="M88 153h74m-74 3h65" stroke="#b49b59" stroke-width=".7"/><text x="88" y="165" fill="#695735" font-size="4.2">025 / 102</text><path d="m169 161 .8 1.7 1.8.3-1.3 1.3.3 1.8-1.6-.9-1.6.9.3-1.8-1.3-1.3 1.8-.3Z" fill="#817036"/><rect x="82" y="25" width="96" height="146" rx="4" fill="url(#${foil})" opacity=".23"/>`;
    const back = `<rect x="78" y="21" width="104" height="154" rx="7" fill="#293f8d"/><rect x="83" y="26" width="94" height="144" rx="4" fill="#2366b5" stroke="#d2e6fa" stroke-width="1"/><path d="M86 59q64-56 87 36t-76 50q75 22 60-46T88 88" stroke="#c0d9ed" stroke-width="9" opacity=".7"/><path d="M91 75q69-54 78 34t-70 28q54 9 52-31t-52-19" stroke="#f6f8fa" stroke-width="3" opacity=".75"/><g transform="rotate(-9 130 101)"><circle cx="130" cy="101" r="26" fill="#fff" stroke="#183854" stroke-width="3"/><path d="M104 101a26 26 0 0 1 52 0Z" fill="#db4b48"/><path d="M104 101h52" stroke="#183854" stroke-width="4"/><circle cx="130" cy="101" r="8" fill="#fff" stroke="#183854" stroke-width="3"/></g><text x="130" y="58" text-anchor="middle" font-size="18" font-weight="900" font-style="italic" fill="#ffdb3f" stroke="#183e7e" stroke-width="2.8" paint-order="stroke">Pokémon</text><text x="130" y="155" text-anchor="middle" font-size="18" font-weight="900" font-style="italic" fill="#ffdb3f" stroke="#183e7e" stroke-width="2.8" paint-order="stroke" transform="rotate(180 130 150)">Pokémon</text>`;
    let art = view === 'back' ? back : front;
    if (view === 'detail') art = `<g transform="translate(-72 -110) scale(1.55)">${front}</g>`;
    if (view === 'angle') art = `<g transform="translate(10 4) rotate(-9 130 100) skewY(-2)">${front}</g>`;
    return `<svg viewBox="0 0 260 200" class="lx-camera lx-item-art" fill="none" aria-hidden="true" font-family="${font}"><defs><linearGradient id="${sky}" x1="88" y1="47" x2="173" y2="128" gradientUnits="userSpaceOnUse"><stop stop-color="#a9d9ee"/><stop offset=".5" stop-color="#d8efca"/><stop offset="1" stop-color="#b3d6a1"/></linearGradient><linearGradient id="${foil}" x1="82" y1="30" x2="178" y2="165" gradientUnits="userSpaceOnUse"><stop stop-color="#fff" stop-opacity="0"/><stop offset=".4" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff"/><stop offset=".6" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs><ellipse cx="133" cy="184" rx="54" ry="6" fill="#24384d" opacity=".1"/><g>${art}</g></svg>`;
  }

  function inHandCapture(id) {
    const heldCard = viewId => {
      const card = pokemonCard('front', viewId).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '');
      return `<svg x="124" y="28" width="176" height="160" viewBox="0 0 420 380" data-original-hand="fine-line-option-1">
        <defs>
          <clipPath id="art-${viewId}"><path d="M23 39Q22 29 32 28L165 19Q175 18 176 29L182 143Q197 138 209 144L266 163Q279 168 285 187L308 242Q320 269 335 282L389 316 368 350 351 368 313 349Q284 344 260 337Q230 330 209 316Q187 300 175 281L165 273Q148 269 143 273Q132 275 127 267Q124 261 130 254Q118 254 114 245Q112 239 118 230L122 224 38 229Q28 230 28 220Z"/></clipPath>
          <mask id="card-${viewId}" maskUnits="userSpaceOnUse" x="15" y="10" width="190" height="230"><path d="m28 36 142-9 10 187-143 9Z" fill="white"/><path d="M139 172c-10 4-7 16 3 27l24 23 20 4 1-24-22-22c-9-9-18-11-26-8Z" fill="black"/></mask>
        </defs>
        <image href="assets/fine-line-original-selected.png" width="420" height="380" clip-path="url(#art-${viewId})"/>
        <g mask="url(#card-${viewId})"><g transform="matrix(1.365 -.0865 .0584 1.2208 -79.7 17.11)">${card}</g></g>
      </svg>`;
    };
    return `<svg class="lx-fan-capture" viewBox="0 0 300 220" fill="none" role="img" aria-label="A phone recording a Pokémon card held by the original selected Fine line hand illustration" font-family="${font}">
      <title>A phone recording a Pokémon card held by the original selected Fine line hand illustration</title>
      <defs><clipPath id="screen-${id}"><rect x="15" y="52" width="91" height="111" rx="6"/></clipPath></defs>
      <rect x="5" y="10" width="111" height="207" rx="20" fill="#343034" stroke="#64595d" stroke-width="1.4"/>
      <rect x="10" y="15" width="101" height="197" rx="15" fill="#202126"/>
      <rect x="40" y="20" width="40" height="7" rx="3.5" fill="#08090b"/>
      <circle cx="37" cy="39" r="2.5" fill="#e0776b"/><text x="46" y="42" font-size="8.5" font-weight="500" fill="#fff5ef">00:10</text>
      <rect x="15" y="52" width="91" height="111" rx="6" fill="#e8d6d0"/>
      <g clip-path="url(#screen-${id})"><svg x="15" y="52" width="91" height="111" viewBox="124 20 176 175">${heldCard(id+'-preview')}</svg></g>
      <path d="M21 66v-8h8m63 0h8v8m0 83v8h-8m-63 0h-8v-8" stroke="#fffcf7" stroke-width="1.2" stroke-linecap="round"/>
      <text x="60.5" y="175" text-anchor="middle" font-size="7.5" font-weight="600" letter-spacing=".6" fill="#f6d78d">VIDEO</text>
      <circle cx="60.5" cy="191" r="12" stroke="#fffcf7" stroke-width="1.4"/>
      <rect x="54.5" y="185" width="12" height="12" rx="2.5" fill="#df7467"/>
      <rect x="44" y="207" width="33" height="2" rx="1" fill="#f3eae6"/>
      <path d="m121 102 13-10" stroke="#aa8588" stroke-width="1.2" stroke-dasharray="2 4" stroke-linecap="round"/>
      ${heldCard(id+'-held')}
    </svg>`;
  }

  function qr() {
    return '<svg class="lx-example-qr" viewBox="0 0 29 29" fill="currentColor" aria-hidden="true"><path d="M1 1h9v9H1zm2 2v5h5V3zm16-2h9v9h-9zm2 2v5h5V3zM1 19h9v9H1zm2 2v5h5v-5z" fill-rule="evenodd"/><path d="M4 4h3v3H4zm18 0h3v3h-3zM4 22h3v3H4zm8-21h2v4h-2zm3 3h2v7h-2zm-4 4h3v3h-3zm0 5h3v3h-3zm5-1h3v3h-3zm5 0h5v2h-5zm4 4h3v4h-3zM1 12h4v3H1zm6 0h3v5H7zm-5 4h3v2H2zm10 3h3v3h-3zm4-3h5v2h-5zm1 4h3v5h-3zm5 1h2v3h-2zm3 3h3v4h-3zm-4 2h2v2h-2zm-9-1h3v3h-3zm11-10h2v3h-2z"/></svg>';
  }

  const markup = `
    <section id="landing" class="page landing-page lx-home" aria-labelledby="lxHeroTitle">
      <div class="lx-hero lx-wrap lx-compact-hero">
        <div class="lx-compact-intro">
          <p class="lx-eyebrow">LockX in-hand verification</p>
          <h1 id="lxHeroTitle"><span class="lx-compact-stat">45%</span><span class="lx-compact-headline">more buying<br>confidence.</span></h1>
          <p class="lx-compact-price">For just 50¢.</p>
          <p class="lx-compact-roi">The best ROI in sales.</p>
          <p class="lx-compact-description">Match your listing photos to a fresh 10-second item video. Give buyers a verification record they can check.</p>
          <div class="lx-compact-actions"><a class="lx-button" href="#in-hand">Verify your listing photos ${arrow}</a><p class="lx-compact-note">50¢ per item check · Credit packs from $5</p></div>
        </div>
        <div class="lx-compact-art">${inHandCapture('compact-video')}</div>
        <section class="lx-compact-steps" id="lxHowItWorks" aria-label="How LockX works in three steps">
          <ol>
            <li><span aria-hidden="true">01</span><div><h2>Take photos</h2><p>Add the photos you plan to list.</p></div></li>
            <li><span aria-hidden="true">02</span><div><h2>Confirm with video</h2><p>Record the item in hand for 10 seconds.</p></div></li>
            <li><span aria-hidden="true">03</span><div><h2>Get verified</h2><p>Share matched photos with a QR verification link.</p></div></li>
          </ol>
        </section>
        <p class="lx-rose-scope">Verification records a visual match at the capture time. It does not certify authenticity, ownership, or delivery.</p>
      </div>

      <section class="lx-faq lx-section lx-wrap" id="lxQuestions" aria-labelledby="lxFAQTitle"><div class="lx-section-heading"><h2 id="lxFAQTitle">A few good questions.</h2></div><div class="lx-faq-list"><details><summary>What does In-hand Verified confirm?<span aria-hidden="true">+</span></summary><p>It checks whether your selected photos match the physical item shown in a newly recorded video. It does not establish brand authenticity, legal ownership, condition beyond what is visible, or a guarantee of a transaction.</p></details><details><summary>Do I need an app or an account?<span aria-hidden="true">+</span></summary><p>No. Add your photos and open the camera link in your phone’s browser. Keep your private link so you can return to your result.</p></details><details><summary>How long does it take?<span aria-hidden="true">+</span></summary><p>The recording lasts 10 seconds and stops automatically. Upload and AI comparison follow; the total time depends on your connection, photos, and the evidence captured.</p></details><details><summary>How do I save the verified photos?<span aria-hidden="true">+</span></summary><p>Your approved images appear with QR codes even if another selected photo does not match. Only verified photos are included when saving. Tap the save button, then choose Save Images on iPhone or a supported save option on Android. Your phone asks you to confirm. Individual image saving is also available.</p></details></div></section>

      <section class="lx-final-cta lx-wrap"><div class="lx-cta-emblem">${check}</div><h2>A little proof.<br>A lot more confidence.</h2><p>Start with the photos you already have.</p><a href="#in-hand" class="lx-button">Verify your photos ${arrow}</a></section>
      <footer class="lx-footer"><div class="lx-wrap"><a class="lx-wordmark" href="#landing" aria-label="LockX home">lock<span>x</span><small class="lx-brand-credit">OpenAI technology</small></a><span>In-hand verification. Made for your listing photos.</span><small>© ${new Date().getFullYear()} LockX</small></div></footer>
    </section>`;

  function scrollToSection(id) {
    if (!document.getElementById('landing')?.classList.contains('active')) {
      if (typeof window.go === 'function') window.go('landing');
      if (location.hash !== '#landing') location.hash = '#landing';
    }
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }));
  }

  function install() {
    const old = document.getElementById('landing');
    if (old && !old.classList.contains('lx-home')) {
      const active = old.classList.contains('active');
      old.outerHTML = markup;
      document.getElementById('landing')?.classList.toggle('active', active);
    }
    if (!document.getElementById('lockxPublicHeader')) {
      const header = document.createElement('header');
      header.id = 'lockxPublicHeader';
      header.className = 'lx-public-header';
      header.innerHTML = `<nav class="lx-wrap" aria-label="LockX navigation"><a class="lx-wordmark" href="#landing" aria-label="LockX home">lock<span>x</span><small class="lx-brand-credit">OpenAI technology</small></a><div class="lx-header-links"><button type="button" data-home-scroll="lxHowItWorks">How it works</button><button type="button" data-home-scroll="lxQuestions">Questions</button></div><a class="lx-header-cta" href="#in-hand">Verify photos ${arrow}</a></nav>`;
      document.body.prepend(header);
    }
  }

  document.addEventListener('click', event => {
    const control = event.target.closest('[data-home-scroll]');
    if (control) { event.preventDefault(); scrollToSection(control.dataset.homeScroll); }
  });
  window.LockXHome = { install, scrollTo: scrollToSection };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
