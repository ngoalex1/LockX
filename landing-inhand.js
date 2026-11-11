/* The public LockX experience. No account or application state is needed. */
(() => {
  'use strict';

  const check = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const arrow = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  const markup = `
    <section id="landing" class="page landing-page lx-home" aria-labelledby="lxHeroTitle">
      <div class="lx-hero lx-wrap lx-rose-hero">
        <div class="lx-rose-header">
          <div><p class="lx-eyebrow">Details make the difference.</p><h1 id="lxHeroTitle">Your photos.<br>Your item. <em>Confirmed.</em></h1></div>
          <p class="lx-rose-intro">For the things you collect,<br>the stories you pass on,<br>and the details that matter.</p>
        </div>
        <section class="lx-rose-animation" id="lxHowItWorks" aria-label="How LockX works">
<div id="lockx-pokemon-demo">
  <div class="lx-demo" id="lockx-photo-demo" data-phase="photos" data-playing="false" data-ended="false" data-motion="true" aria-label="Photo to proof — Pokémon card demonstration">
    <div class="demo-top"><span class="demo-brand">lock<span>x</span></span><small>Illustrative sequence</small></div>
    <div class="step-nav" aria-label="Animation steps">
      <button type="button" data-step="0" aria-current="step"><b>01</b><span>Take photos.</span></button>
      <button type="button" data-step="1"><b>02</b><span>10-second video.</span></button>
      <button type="button" data-step="2"><b>03</b><span>Photos verified.</span></button>
    </div>
    <div class="stage" aria-label="Pokémon card photos, followed by a phone recording a hand turning the card through 360 degrees, then verified photos">
      <div class="photo-pile" data-photos aria-label="Front, back, and detail photos of a Pokémon card">
        <div class="photo-shot"><div class="photo-image"><span class="card-slot"></span><span class="verified-stamp"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="photo-meta"><span data-photo-label="Front">Front</span><svg class="qr" viewBox="0 0 29 29" fill="currentColor" aria-hidden="true"><path d="M1 1h9v9H1zm2 2v5h5V3zm16-2h9v9h-9zm2 2v5h5V3zM1 19h9v9H1zm2 2v5h5v-5z" fill-rule="evenodd"/><path d="M4 4h3v3H4zm18 0h3v3h-3zM4 22h3v3H4zm8-21h2v4h-2zm3 3h2v7h-2zm-4 4h3v3h-3zm0 5h3v3h-3zm5-1h3v3h-3zm5 0h5v2h-5zm4 4h3v4h-3zM1 12h4v3H1zm6 0h3v5H7zm-5 4h3v2H2zm10 3h3v3h-3zm4-3h5v2h-5zm1 4h3v5h-3zm5 1h2v3h-2zm3 3h3v4h-3zm-4 2h2v2h-2zm-9-1h3v3h-3zm11-10h2v3h-2z"/></svg></div></div>
        <div class="photo-shot"><div class="photo-image"><span class="card-slot"></span><span class="verified-stamp"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="photo-meta"><span data-photo-label="Back">Back</span><svg class="qr" viewBox="0 0 29 29" fill="currentColor" aria-hidden="true"><path d="M1 1h9v9H1zm2 2v5h5V3zm16-2h9v9h-9zm2 2v5h5V3zM1 19h9v9H1zm2 2v5h5v-5z" fill-rule="evenodd"/><path d="M4 4h3v3H4zm18 0h3v3h-3zM4 22h3v3H4zm8-21h2v4h-2zm3 3h2v7h-2zm-4 4h3v3h-3zm0 5h3v3h-3zm5-1h3v3h-3zm5 0h5v2h-5zm4 4h3v4h-3zM1 12h4v3H1zm6 0h3v5H7zm-5 4h3v2H2zm10 3h3v3h-3zm4-3h5v2h-5zm1 4h3v5h-3zm5 1h2v3h-2zm3 3h3v4h-3zm-4 2h2v2h-2zm-9-1h3v3h-3zm11-10h2v3h-2z"/></svg></div></div>
        <div class="photo-shot"><div class="photo-image"><span class="card-slot"></span><span class="verified-stamp"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 12 4 4 8-8" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="photo-meta"><span data-photo-label="Details">Details</span><svg class="qr" viewBox="0 0 29 29" fill="currentColor" aria-hidden="true"><path d="M1 1h9v9H1zm2 2v5h5V3zm16-2h9v9h-9zm2 2v5h5V3zM1 19h9v9H1zm2 2v5h5v-5z" fill-rule="evenodd"/><path d="M4 4h3v3H4zm18 0h3v3h-3zM4 22h3v3H4zm8-21h2v4h-2zm3 3h2v7h-2zm-4 4h3v3h-3zm0 5h3v3h-3zm5-1h3v3h-3zm5 0h5v2h-5zm4 4h3v4h-3zM1 12h4v3H1zm6 0h3v5H7zm-5 4h3v2H2zm10 3h3v3h-3zm4-3h5v2h-5zm1 4h3v5h-3zm5 1h2v3h-2zm3 3h3v4h-3zm-4 2h2v2h-2zm-9-1h3v3h-3zm11-10h2v3h-2z"/></svg></div></div>
      </div>
      <div class="recording-scene" data-camera aria-hidden="true">
        <div class="recording-column">
          <div class="phone"><div class="phone-top"><span class="phone-brand">lockx</span><span class="countdown" data-countdown>00:10</span></div><div class="camera-view"><div class="grip-view" data-grip></div><span class="camera-frame"></span></div><div class="phone-status" data-camera-status>Live view</div></div>
          <span class="recording-caption">Camera recording</span>
        </div>
        <div class="hand-column"><span class="turn-orbit"></span><div class="grip-view" data-grip></div><span class="recording-caption" data-angle>Front · 0°</span></div>
      </div>
    </div>
    <div class="demo-footer">
      <button class="play-demo" type="button" data-play><svg class="play-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m8 5 11 7-11 7Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg><svg class="pause-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 5v14M16 5v14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><svg class="replay-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 11a8 8 0 1 1 2 6M4 4v7h7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg><span data-play-label>Play animation</span></button>
      <small>10-second recording. Comparison time varies.<br>Only photos that pass receive verification.</small>
    </div>
    <span class="sr-only" data-live-state aria-live="polite">Step 1. Take photos of the Pokémon card.</span>
  </div>
</div>
        </section>
        <div class="lx-animation-cta"><a class="lx-button" href="#in-hand">Verify your photos ${arrow}</a><p class="lx-hero-note">No app. No account. Just your photos and camera.</p></div>
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
    window.LockXAnimation?.install();
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
