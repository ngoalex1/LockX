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
      return `<g stroke="#b78b72" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
        <path d="m221 126c10-3 18 7 21 23l5 28 11 30-38 12-9-29c-13-12-18-23-14-36l10-24Z" fill="url(#hand-${id})"/>
        <path d="m228 122 4-27c1-8 8-5 8 2l2 36-4 16" fill="#e4b797"/>
        <path d="m210 133-8-1c-8 0-11 7-5 12l14 10c7 4 12-3 7-8Z" fill="#edc4a6"/>
        <path d="m207 148-7-1c-7 0-9 7-4 12l15 10c7 3 11-3 7-8Z" fill="#e8ba9b"/>
        <path d="m209 164-7-2c-6-1-9 5-5 10l14 10c6 4 10-1 8-6Z" fill="#dfae8c"/>
      </g>
      <g transform="rotate(-8 193 72)"><g transform="translate(89 -5) scale(.77)">${card}</g></g>
      <g stroke="#b78b72" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
        <path d="m224 99c-5-4-12 0-11 6l4 21c2 9 7 16 14 18 6 1 10-4 8-10l-4-23c-2-7-6-11-11-12Z" fill="url(#hand-${id})"/>
        <path d="m222 102c-4-1-7 2-6 6l2 9c1 3 4 4 7 3s4-4 3-7l-2-7c-1-2-2-3-4-4Z" fill="#f4d9c4" stroke="#c79a7e"/>
        <path d="m225 133 8-2m-17 49q10-4 19-1m-31-32 5-4m-6 18 5-4m-3 18 5-4"/>
        <path d="m216 205 36-12 8 24-39 3Z" fill="#b69b99" stroke="#927876"/>
        <path d="m223 205 4 13m4-16 4 14m4-17 4 14m4-17 4 14" stroke="#a88c8a" stroke-width=".7"/>
      </g>`;
    };
    return `<svg class="lx-fan-capture" viewBox="0 0 260 220" fill="none" role="img" aria-label="A phone with its video-recording app open, recording a hand holding a Pokémon card" font-family="${font}">
      <title>A phone with its video-recording app open, recording a hand holding a Pokémon card</title>
      <defs><linearGradient id="hand-${id}" x1="192" y1="125" x2="250" y2="207" gradientUnits="userSpaceOnUse"><stop stop-color="#f0caae"/><stop offset="1" stop-color="#dca987"/></linearGradient><clipPath id="screen-${id}"><rect x="15" y="52" width="91" height="111" rx="6"/></clipPath></defs>
      <rect x="5" y="10" width="111" height="207" rx="20" fill="#343034" stroke="#64595d" stroke-width="1.4"/>
      <rect x="10" y="15" width="101" height="197" rx="15" fill="#202126"/>
      <rect x="40" y="20" width="40" height="7" rx="3.5" fill="#08090b"/>
      <circle cx="37" cy="39" r="2.5" fill="#e0776b"/><text x="46" y="42" font-size="8.5" font-weight="500" fill="#fff5ef">00:10</text>
      <rect x="15" y="52" width="91" height="111" rx="6" fill="#e8d6d0"/>
      <g clip-path="url(#screen-${id})"><svg x="15" y="52" width="91" height="111" viewBox="132 0 128 220">${heldCard(id+'-preview')}</svg></g>
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
      <div class="lx-hero lx-wrap lx-rose-hero">
        <div class="lx-rose-header">
          <div><p class="lx-eyebrow">Details make the difference.</p><h1 id="lxHeroTitle">Your photos.<br>Your item. <em>Confirmed.</em></h1></div>
          <p class="lx-rose-intro">For the things you collect,<br>the stories you pass on,<br>and the details that matter.</p>
        </div>
        <section class="lx-steps-fan" id="lxHowItWorks" aria-label="How LockX works in three steps">
          <ol>
            <li class="lx-fan-card"><span class="lx-fan-number" aria-hidden="true">01</span><div class="lx-fan-art" aria-hidden="true"><div class="lx-fan-photos">${pokemonCard('front','fan-photo-front').replace('viewBox="0 0 260 200"','viewBox="60 10 140 180"')}${pokemonCard('back','fan-photo-back').replace('viewBox="0 0 260 200"','viewBox="60 10 140 180"')}</div></div><h3>Take photos</h3></li>
            <li class="lx-fan-card"><span class="lx-fan-number" aria-hidden="true">02</span><div class="lx-fan-art">${inHandCapture('fan-video')}</div><h3>Confirm with video</h3></li>
            <li class="lx-fan-card"><span class="lx-fan-number" aria-hidden="true">03</span><div class="lx-fan-art" aria-hidden="true"><div class="lx-fan-proof">${pokemonCard('front','fan-proof').replace('viewBox="0 0 260 200"','viewBox="60 10 140 180"')}<div class="lx-fan-seal"><span class="lx-fan-check">${check}</span>${qr()}</div></div></div><h3>Get verified</h3></li>
          </ol>
        </section>
        <div class="lx-steps-cta"><a class="lx-button" href="#in-hand">Verify your photos ${arrow}</a><p class="lx-hero-note">No app. No account. Just your photos and camera.</p></div>
        <p class="lx-rose-scope">Verification records a visual match at the capture time. It does not certify authenticity, ownership, or delivery.</p>
      </div>

      <section class="lx-details-section" aria-labelledby="lxDetailsTitle"><div class="lx-wrap lx-detail-layout"><div class="lx-detail-title"><p class="lx-eyebrow">The difference is in the details.</p><h2 id="lxDetailsTitle">More than<br>a similar-looking item.</h2><p>LockX compares the features that connect your photos to the item in the video.</p></div><div class="lx-detail-list"><article><span>01</span><div><h3>Markings. Text. Numbers.</h3><p>Distinctive details, visible wear, and readable numbers help establish a match. A different serial number matters.</p></div></article><article><span>02</span><div><h3>A result for every photo.</h3><p>Each selected photo is checked. If a view is unclear or the evidence does not match, you see what needs attention.</p></div></article><article><span>03</span><div><h3>A QR code that tells the story.</h3><p>Approved images link back to their LockX verification record, so a buyer can check the photo set.</p></div></article></div></div></section>

      <section class="lx-faq lx-section lx-wrap" id="lxQuestions" aria-labelledby="lxFAQTitle"><div class="lx-section-heading"><h2 id="lxFAQTitle">A few good questions.</h2></div><div class="lx-faq-list"><details><summary>What does In-hand Verified confirm?<span aria-hidden="true">+</span></summary><p>It checks whether your selected photos match the physical item shown in a newly recorded video. It does not establish brand authenticity, legal ownership, condition beyond what is visible, or a guarantee of a transaction.</p></details><details><summary>Do I need an app or an account?<span aria-hidden="true">+</span></summary><p>No. Add your photos and open the camera link in your phone’s browser. Keep your private link so you can return to your result.</p></details><details><summary>How long does it take?<span aria-hidden="true">+</span></summary><p>The recording lasts 10 seconds and stops automatically. Upload and AI comparison follow; the total time depends on your connection, photos, and the evidence captured.</p></details><details><summary>How do I save the verified photos?<span aria-hidden="true">+</span></summary><p>Your approved images appear with QR codes even if another selected photo does not match. Only verified photos are included when saving. Tap the save button, then choose Save Images on iPhone or a supported save option on Android. Your phone asks you to confirm. Individual image saving is also available.</p></details></div></section>

      <section class="lx-final-cta lx-wrap"><div class="lx-cta-emblem">${check}</div><h2>A little proof.<br>A lot more confidence.</h2><p>Start with the photos you already have.</p><a href="#in-hand" class="lx-button">Verify your photos ${arrow}</a></section>
      <footer class="lx-footer"><div class="lx-wrap"><a class="lx-wordmark" href="#landing" aria-label="LockX home">lock<span>x</span></a><span>In-hand verification. Made for your listing photos.</span><small>© ${new Date().getFullYear()} LockX</small></div></footer>
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
      header.innerHTML = `<nav class="lx-wrap" aria-label="LockX navigation"><a class="lx-wordmark" href="#landing" aria-label="LockX home">lock<span>x</span></a><div class="lx-header-links"><button type="button" data-home-scroll="lxHowItWorks">How it works</button><button type="button" data-home-scroll="lxQuestions">Questions</button></div><a class="lx-header-cta" href="#in-hand">Verify photos ${arrow}</a></nav>`;
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
