/* The public LockX experience. No account or application state is needed. */
(() => {
  'use strict';

  const check = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const arrow = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function camera(view, id) {
    const silver = `lxSilver${id}`;
    const glass = `lxGlass${id}`;
    const front = `<rect x="28" y="51" width="204" height="128" rx="17" fill="url(#${silver})"/><path d="M28 98h204v64a17 17 0 0 1-17 17H45a17 17 0 0 1-17-17Z" fill="#303439"/><path d="M47 116h26m-26 10h26m-26 10h26m-26 10h26m-26 10h26" stroke="#41464c" stroke-width="3"/><rect x="53" y="44" width="38" height="11" rx="4" fill="#b7bdc4"/><rect x="171" y="45" width="28" height="10" rx="4" fill="#1e2227"/><rect x="192" y="68" width="23" height="13" rx="3" fill="#e6edf2" stroke="#acb3bc"/><circle cx="137" cy="117" r="54" fill="#21252a" stroke="#b6bcc4" stroke-width="5"/><circle cx="137" cy="117" r="43" fill="#15191e" stroke="#535d68" stroke-width="3"/><circle cx="137" cy="117" r="29" fill="url(#${glass})" stroke="#1d2733" stroke-width="3"/><ellipse cx="129" cy="106" rx="9" ry="6" fill="#a5d1ff" opacity=".5"/><circle cx="176" cy="88" r="3" fill="#ff645b"/><text x="48" y="83" fill="#555d66" font-family="-apple-system,BlinkMacSystemFont,sans-serif" font-size="8" font-weight="600" letter-spacing="1">LUMEN</text>`;
    const back = `<rect x="28" y="51" width="204" height="128" rx="17" fill="url(#${silver})"/><path d="M28 91h204v71a17 17 0 0 1-17 17H45a17 17 0 0 1-17-17Z" fill="#303439"/><rect x="43" y="93" width="126" height="72" rx="5" fill="#131b23" stroke="#777f89" stroke-width="3"/><path d="m49 153 34-35 23 19 21-25 35 41" fill="#587f96"/><path d="m49 153 34-25 25 16 25-19 29 28" fill="#819da8"/><circle cx="146" cy="109" r="7" fill="#d8e9eb"/><rect x="49" y="62" width="40" height="18" rx="4" fill="#232a30"/><circle cx="196" cy="119" r="16" fill="#555e68" stroke="#89919a" stroke-width="2"/><circle cx="196" cy="119" r="7" fill="#333b44"/><circle cx="194" cy="153" r="5" fill="#848c95"/>`;
    const detail = `<rect x="28" y="51" width="204" height="128" rx="17" fill="url(#${silver})"/><rect x="45" y="78" width="170" height="73" rx="7" fill="#e8ebee" stroke="#aeb6bf"/><text x="63" y="103" fill="#4f5964" font-family="-apple-system,BlinkMacSystemFont,sans-serif" font-size="11" font-weight="600" letter-spacing="1">LUMEN / 35</text><text x="63" y="128" fill="#313943" font-family="ui-monospace,monospace" font-size="13" letter-spacing="1">001027</text><circle cx="54" cy="63" r="3" fill="#8e98a4"/><circle cx="207" cy="164" r="3" fill="#8e98a4"/>`;
    let art = front;
    if (view === 'back') art = back;
    if (view === 'detail') art = detail;
    if (view === 'angle') art = `<g transform="translate(19 5) skewY(-5) scale(.87 1)">${front}</g>`;
    return `<svg viewBox="0 0 260 220" fill="none" class="lx-camera" aria-hidden="true"><defs><linearGradient id="${silver}" x1="45" y1="54" x2="224" y2="174" gradientUnits="userSpaceOnUse"><stop stop-color="#f6f8fb"/><stop offset=".38" stop-color="#ced5dd"/><stop offset=".68" stop-color="#f0f2f5"/><stop offset="1" stop-color="#a9b1bc"/></linearGradient><radialGradient id="${glass}" cx=".35" cy=".28" r=".8"><stop stop-color="#577fb4"/><stop offset=".4" stop-color="#1b385e"/><stop offset="1" stop-color="#080e19"/></radialGradient></defs><ellipse cx="130" cy="187" rx="91" ry="9" fill="#24384d" opacity=".1"/>${art}</svg>`;
  }

  function qr() {
    return '<svg class="lx-example-qr" viewBox="0 0 29 29" fill="currentColor" aria-hidden="true"><path d="M1 1h9v9H1zm2 2v5h5V3zm16-2h9v9h-9zm2 2v5h5V3zM1 19h9v9H1zm2 2v5h5v-5z" fill-rule="evenodd"/><path d="M4 4h3v3H4zm18 0h3v3h-3zM4 22h3v3H4zm8-21h2v4h-2zm3 3h2v7h-2zm-4 4h3v3h-3zm0 5h3v3h-3zm5-1h3v3h-3zm5 0h5v2h-5zm4 4h3v4h-3zM1 12h4v3H1zm6 0h3v5H7zm-5 4h3v2H2zm10 3h3v3h-3zm4-3h5v2h-5zm1 4h3v5h-3zm5 1h2v3h-2zm3 3h3v4h-3zm-4 2h2v2h-2zm-9-1h3v3h-3zm11-10h2v3h-2z"/></svg>';
  }

  const markup = `
    <section id="landing" class="page landing-page lx-home" aria-labelledby="lxHeroTitle">
      <div class="lx-hero lx-wrap">
        <p class="lx-eyebrow">LockX In-hand Verified</p>
        <h1 id="lxHeroTitle">Your photos.<br>Your item. <span>Confirmed.</span></h1>
        <p class="lx-hero-copy">Show it once. Share it with confidence.<br>Match your listing photos to a 10-second video of the item in your hands.</p>
        <div class="lx-hero-actions"><a class="lx-button" href="#in-hand">Verify your photos ${arrow}</a><button class="lx-text-link" type="button" data-home-scroll="lxHowItWorks">See how it works <span aria-hidden="true">⌄</span></button></div>
        <p class="lx-hero-note">No app. No account. Just your photos and camera.</p>
      </div>

      <div class="lx-product-stage lx-wrap" role="img" aria-label="Illustrative example: four camera listing photos are compared with a ten-second video, then QR-marked photos link to a verification record.">
        <div class="lx-stage-halo"></div>
        <div class="lx-reference-set"><div class="lx-stage-label">Your listing photos <span>4 views</span></div><div class="lx-reference-grid"><div>${camera('front','ref1')}</div><div>${camera('angle','ref2')}</div><div>${camera('back','ref3')}</div><div>${camera('detail','ref4')}</div></div><div class="lx-set-caption">The details that make it yours.</div></div>
        <div class="lx-stage-connector lx-stage-connector--first">${arrow}</div>
        <div class="lx-demo-phone"><div class="lx-phone-island"></div><div class="lx-phone-topline"><span>lockx</span><span class="lx-phone-timer"><i></i> 00:10</span></div><div class="lx-phone-view"><div class="lx-focus-corner lx-focus-corner--tl"></div><div class="lx-focus-corner lx-focus-corner--tr"></div><div class="lx-focus-corner lx-focus-corner--bl"></div><div class="lx-focus-corner lx-focus-corner--br"></div>${camera('angle','video')}</div><div class="lx-phone-guidance"><span class="lx-small-check">${check}</span><strong>A little turn.<br>A clearer picture.</strong><span>Show the front, sides, and back.</span></div><div class="lx-phone-progress"><i></i></div><div class="lx-phone-bottom">10 seconds. Stops automatically.</div><div class="lx-phone-homebar"></div></div>
        <div class="lx-stage-connector lx-stage-connector--second">${arrow}</div>
        <div class="lx-demo-result"><div class="lx-result-heading"><span>${check}</span><div>Photo matched<small>Illustrative example</small></div></div><div class="lx-result-photo">${camera('front','result')}</div><div class="lx-result-footer"><span><strong>lockx</strong><small>In-hand Verified</small></span>${qr()}</div><div class="lx-result-record">Photos with a story you can check.</div></div>
        <p class="lx-illustration-note">Illustrative example. Actual results depend on the evidence captured.</p>
      </div>

      <section class="lx-process lx-section lx-wrap" id="lxHowItWorks" aria-labelledby="lxHowTitle">
        <div class="lx-section-heading"><p class="lx-eyebrow">Small effort. Clearer evidence.</p><h2 id="lxHowTitle">From listing photos<br>to a verified photo set.</h2><p>One simple flow, right in your phone’s browser.</p></div>
        <div class="lx-process-grid">
          <article><span class="lx-step">01</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="7" y="10" width="23" height="25" rx="4" stroke="currentColor" stroke-width="1.8"/><path d="M13 5h17a5 5 0 0 1 5 5v18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="m8 28 7-8 6 5 4-4 5 6" stroke="currentColor" stroke-width="1.8"/><circle cx="23" cy="17" r="2" fill="currentColor"/></svg></div><h3>Add your photos.</h3><p>Choose the exact listing photos you want to verify. Four views are a great place to start.</p></article>
          <article><span class="lx-step">02</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="11" y="3" width="19" height="34" rx="5" stroke="currentColor" stroke-width="1.8"/><path d="M17 7h7m-7 26h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="20.5" cy="20" r="7" stroke="currentColor" stroke-width="1.8"/><path d="m19 17 4 3-4 3v-6Z" fill="currentColor"/></svg></div><h3>Show it for 10 seconds.</h3><p>Turn the item to show its different sides. Recording stops automatically, then AI compares the views.</p></article>
          <article><span class="lx-step">03</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M6 6h10v10H6zm18 0h10v10H24zM6 24h10v10H6z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M24 23h4v5h6v6H23v-5m10-7v2M9 10h4v3H9zm18 0h4v3h-4zM9 28h4v3H9z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></div><h3>Save. List. Share.</h3><p>When every photo matches, your QR-marked images appear on the same page, ready to save.</p></article>
        </div>
      </section>

      <section class="lx-details-section" aria-labelledby="lxDetailsTitle"><div class="lx-wrap lx-detail-layout"><div class="lx-detail-title"><p class="lx-eyebrow">The difference is in the details.</p><h2 id="lxDetailsTitle">More than<br>a similar-looking item.</h2><p>LockX compares the features that connect your photos to the item in the video.</p></div><div class="lx-detail-list"><article><span>01</span><div><h3>Markings. Text. Numbers.</h3><p>Distinctive details, visible wear, and readable numbers help establish a match. A different serial number matters.</p></div></article><article><span>02</span><div><h3>A result for every photo.</h3><p>Each selected photo is checked. If a view is unclear or the evidence does not match, you see what needs attention.</p></div></article><article><span>03</span><div><h3>A QR code that tells the story.</h3><p>Approved images link back to their LockX verification record, so a buyer can check the photo set.</p></div></article></div></div></section>

      <section class="lx-faq lx-section lx-wrap" id="lxQuestions" aria-labelledby="lxFAQTitle"><div class="lx-section-heading"><h2 id="lxFAQTitle">A few good questions.</h2></div><div class="lx-faq-list"><details><summary>What does In-hand Verified confirm?<span aria-hidden="true">+</span></summary><p>It checks whether your selected photos match the physical item shown in a newly recorded video. It does not establish brand authenticity, legal ownership, condition beyond what is visible, or a guarantee of a transaction.</p></details><details><summary>Do I need an app or an account?<span aria-hidden="true">+</span></summary><p>No. Add your photos and open the camera link in your phone’s browser. Keep your private link so you can return to your result.</p></details><details><summary>How long does it take?<span aria-hidden="true">+</span></summary><p>The recording lasts 10 seconds and stops automatically. Upload and AI comparison follow; the total time depends on your connection, photos, and the evidence captured.</p></details><details><summary>How do I save the verified photos?<span aria-hidden="true">+</span></summary><p>Your QR-marked images appear after all selected photos match. Tap the save button, then choose Save Images on iPhone or a supported save option on Android. Your phone asks you to confirm. Individual image saving is also available.</p></details></div></section>

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
