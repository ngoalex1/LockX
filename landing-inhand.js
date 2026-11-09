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

  function concertTickets(view, id) {
    const violet = `violet-${id}`;
    const cyan = `cyan-${id}`;
    const bars = Array.from({length:29},(_,n)=>`<path d="M${60+n*4} 143v12" stroke="#374251" stroke-width="${n%4===0?2.6:n%3===0?1.8:.8}"/>`).join('');
    const front = `<rect x="32" y="63" width="195" height="105" rx="7" fill="#fff" stroke="#d5d9e3"/><path d="M39 63h181a7 7 0 0 1 7 7v28H32V70a7 7 0 0 1 7-7Z" fill="url(#${violet})"/><path d="m170 63-45 35h30l45-35Z" fill="#ffffff" opacity=".13"/><circle cx="32" cy="119" r="6" fill="#eaf0f5"/><circle cx="227" cy="119" r="6" fill="#eaf0f5"/><path d="M185 99v63" stroke="#d9dce4" stroke-dasharray="2 3"/><text x="44" y="76" fill="#e8dfff" font-size="5" letter-spacing="1.6" font-weight="600">WORLD TOUR</text><text x="43" y="91" fill="#fff" font-size="13" letter-spacing="-.5" font-weight="800">MIDNIGHT LIVE</text><text x="44" y="111" fill="#4c5364" font-size="5.3" font-weight="600">SAT 21 NOV  •  8:00 PM</text><text x="44" y="124" fill="#262f40" font-size="7.2" font-weight="700">SEC A   ROW 04   SEAT 12</text><text x="44" y="134" fill="#7a8291" font-size="4.7">THE GRAND ARENA · ADMIT ONE</text>${bars}<text x="44" y="163" fill="#8d93a0" font-size="3.6" letter-spacing=".3">SAMPLE · NOT VALID FOR ENTRY</text><text x="207" y="90" transform="rotate(90 207 90)" fill="#fff" font-size="5" letter-spacing="1">LIVE</text><text x="205" y="115" text-anchor="middle" fill="#354056" font-size="7" font-weight="700">A</text><text x="205" y="128" text-anchor="middle" fill="#667085" font-size="4.5">ROW 04</text><text x="205" y="143" text-anchor="middle" fill="#354056" font-size="11" font-weight="750">12</text><path d="M196 153h19m-19 3h19m-19 3h19" stroke="#bcc3cf" stroke-width="1"/>`;
    const rear = `<g transform="translate(2 -27) rotate(7 130 110)"><rect x="32" y="63" width="195" height="105" rx="7" fill="#fff" stroke="#d5d9e3"/><path d="M39 63h181a7 7 0 0 1 7 7v28H32V70a7 7 0 0 1 7-7Z" fill="url(#${cyan})"/><text x="44" y="76" fill="#dcf4ff" font-size="5" letter-spacing="1.6" font-weight="600">WORLD TOUR</text><text x="43" y="91" fill="#fff" font-size="13" font-weight="800" letter-spacing="-.5">MIDNIGHT LIVE</text><text x="44" y="116" fill="#364152" font-size="7.2" font-weight="700">SEC A   ROW 04   SEAT 13</text><path d="M44 130h117m-117 7h92m-92 7h111" stroke="#c5cbd5" stroke-width="2"/><path d="M185 99v63" stroke="#d9dce4" stroke-dasharray="2 3"/><text x="205" y="142" text-anchor="middle" fill="#354056" font-size="11" font-weight="750">13</text></g>`;
    const back = `<rect x="32" y="55" width="195" height="113" rx="7" fill="#fff" stroke="#d5d9e3"/><rect x="44" y="68" width="48" height="5" rx="2.5" fill="#8a6cbd"/><text x="44" y="89" fill="#3b4354" font-size="8" font-weight="700">A night to remember.</text><path d="M44 103h166m-166 7h153m-153 7h161m-161 7h118" stroke="#b7bdc8" stroke-width="1.6"/>${bars}<text x="44" y="163" fill="#8d93a0" font-size="3.6">SAMPLE · NOT VALID FOR ENTRY</text>`;
    let art = `${rear}${front}`;
    if(view === 'back') art = back;
    if(view === 'detail') art = `<g transform="translate(-16 -35) scale(1.15)">${front}</g>`;
    if(view === 'angle') art = `<g transform="translate(-2 1) rotate(-7 130 110)">${rear}${front}</g>`;
    return `<svg viewBox="0 0 260 200" class="lx-camera lx-item-art" fill="none" aria-hidden="true" font-family="${font}"><defs><linearGradient id="${violet}" x1="32" y1="63" x2="227" y2="98" gradientUnits="userSpaceOnUse"><stop stop-color="#3e367d"/><stop offset=".5" stop-color="#7750b4"/><stop offset="1" stop-color="#9a79cb"/></linearGradient><linearGradient id="${cyan}" x1="32" y1="63" x2="227" y2="98" gradientUnits="userSpaceOnUse"><stop stop-color="#214e76"/><stop offset="1" stop-color="#58a8c2"/></linearGradient></defs><ellipse cx="130" cy="181" rx="93" ry="7" fill="#24384d" opacity=".1"/>${art}</svg>`;
  }

  function royalOakSketch(id) {
    const dial = `lxRoyalOakDial${id}`;
    const brushed = `lxRoyalOakBrushed${id}`;
    const bezel = `lxRoyalOakBezel${id}`;
    const screws = [[107,61],[153,61],[180,87],[180,133],[153,159],[107,159],[80,133],[80,87]]
      .map(([x,y]) => `<g transform="translate(${x} ${y})"><path d="m0-3.2 2.8 1.6v3.2L0 3.2l-2.8-1.6v-3.2Z" fill="#fbfcfd" stroke="#65717c" stroke-width=".7"/><path d="m-1.6 1.8 3.2-3.6" stroke="#65717c" stroke-width=".75"/></g>`).join('');
    const indices = Array.from({length:12}, (_,n) => n === 3 ? '' : `<g transform="rotate(${n*30} 130 110)"><rect x="128.2" y="74.5" width="3.6" height="10" rx=".5" fill="#ecf0f2" stroke="#8e9ca7" stroke-width=".65"/><path d="M130 75.8v7.4" stroke="#fff" stroke-width=".7"/></g>`).join('');
    const minuteMarks = Array.from({length:60}, (_,n) => `<path d="M130 69.5v${n%5 === 0 ? '2.7' : '1.3'}" transform="rotate(${n*6} 130 110)" stroke="#c9d6df" stroke-width="${n%5 === 0 ? '.7' : '.45'}"/>`).join('');
    const links = [9,24,39,180,195,210].map(y => `<path d="M101 ${y}h58m-58 2h58" stroke="#8996a1" stroke-width=".65"/><path d="M112 ${y-11}v10m36-10v10" stroke="#96a1ac" stroke-width=".65"/><path d="M115 ${y-10}h29m-29 3h29m-29 3h29" stroke="#9ba7b0" stroke-width=".3" opacity=".6"/>`).join('');
    return `<svg class="lx-camera lx-watch-sketch" viewBox="0 0 260 220" fill="none" aria-hidden="true" font-family="${font}">
      <defs>
        <pattern id="${dial}" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="5" height="5" fill="#36526d"/><rect x=".6" y=".6" width="3.8" height="3.8" rx=".15" fill="#45637d"/><path d="M.6 4.4h3.8V.6" stroke="#263f57" stroke-width=".55"/><path d="M.6 4.4V.6h3.8" stroke="#8096a8" stroke-width=".35" opacity=".7"/></pattern>
        <pattern id="${brushed}" width="3" height="4" patternUnits="userSpaceOnUse"><path d="M.7 0v4" stroke="#9da8b2" stroke-width=".3" opacity=".4"/></pattern>
        <clipPath id="${bezel}"><path d="M99 53h62l28 28v58l-28 28H99l-28-28V81Z"/></clipPath>
      </defs>
      <ellipse cx="135" cy="201" rx="56" ry="5" fill="#24384d" opacity=".07"/>
      <g transform="rotate(-22 130 110)" stroke-linejoin="round" stroke-linecap="round">
        <path d="M106 1h48l10 53H96Zm-10 165h68l-10 53h-48Z" fill="#e7ebef" stroke="#6f7d89" stroke-width="1.15"/>
        <path d="M112 2h36l5 51h-46Zm-5 165h46l-5 51h-36Z" fill="#f6f8fa" stroke="#a3adb7" stroke-width=".7"/>
        <path d="M106 2h48l9 51H97Zm-9 165h66l-9 51h-48Z" fill="url(#${brushed})"/>
        ${links}
        <path d="M99 51h62l31 29v61l-31 28H99l-31-28V80Z" fill="#b7c2cc" stroke="#61717e" stroke-width="1.1"/>
        <path d="M191 101h7l3 3v12l-3 3h-7" fill="#d8dfe5" stroke="#63727e" stroke-width=".9"/><path d="M196 103v14m2-13v12" stroke="#87949e" stroke-width=".6"/>
        <path d="M99 53h62l28 28v58l-28 28H99l-28-28V81Z" fill="#edf0f3" stroke="#5e6e7a" stroke-width="1.25"/>
        <path d="M99 53h62l28 28v58l-28 28H99l-28-28V81Z" fill="url(#${brushed})"/>
        <path d="M100 55h60l27 27v56l-27 27h-60l-27-27V82Z" stroke="#fff" stroke-width=".75"/>
        <g clip-path="url(#${bezel})" stroke="#6b7c89" stroke-width=".35" opacity=".3"><path d="m72 81 27-27m-25 31 30-30m-29 34 34-34m49 110 30-30m-34 30 34-34m-39 34 39-39"/></g>
        <circle cx="130" cy="110" r="45.5" fill="#9aa8b3" stroke="#6c7c88" stroke-width=".85"/>
        <circle cx="130" cy="110" r="43" fill="url(#${dial})" stroke="#293f50" stroke-width="1.1"/>
        <circle cx="130" cy="110" r="40.8" stroke="#98aab7" stroke-width=".45"/>
        ${minuteMarks}${indices}${screws}
        <text x="130" y="93" text-anchor="middle" fill="#f3f5f6" font-family="Georgia,serif" font-size="7.8">AP</text>
        <text x="130" y="99.5" text-anchor="middle" fill="#edf1f4" font-size="3.4" font-weight="550" letter-spacing=".25">AUDEMARS PIGUET</text>
        <text x="130" y="133" text-anchor="middle" fill="#dce5eb" font-size="3" letter-spacing=".65">AUTOMATIC</text>
        <rect x="155" y="106" width="11" height="8" rx=".5" fill="#e8edf1" stroke="#152f44" stroke-width=".8"/><text x="160.5" y="111.7" text-anchor="middle" fill="#283847" font-size="5.5">9</text>
        <path d="m130 112-24-19 1.8-2.3 25 17.3Z" fill="#edf2f5" stroke="#8c9caa" stroke-width=".65"/>
        <path d="m128 109 26-22 2 2.3-24 24Z" fill="#f6f8fa" stroke="#8c9caa" stroke-width=".65"/>
        <path d="m125 129 13-49" stroke="#cbd8e0" stroke-width=".65"/>
        <circle cx="130" cy="110" r="2.8" fill="#dce5ec" stroke="#8c9ba5" stroke-width=".6"/>
        <path d="m97 53-27 29v57l29 29h63l28-29" stroke="#4f6170" stroke-width=".45" opacity=".3" transform="translate(-1 1)"/>
      </g>
    </svg>`;
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

      <div class="lx-product-stage lx-wrap" role="img" aria-label="Illustrative examples: four Pokémon card listing photos, a ten-second concert ticket video, and a QR-marked AP Royal Oak watch sketch linking to a verification record.">
        <div class="lx-stage-halo"></div>
        <div class="lx-reference-set"><div class="lx-stage-label">Your listing photos <span>4 views</span></div><div class="lx-reference-grid"><div>${pokemonCard('front','ref1')}</div><div>${pokemonCard('angle','ref2')}</div><div>${pokemonCard('back','ref3')}</div><div>${pokemonCard('detail','ref4')}</div></div><div class="lx-set-caption">The details that make it yours.</div></div>
        <div class="lx-stage-connector lx-stage-connector--first">${arrow}</div>
        <div class="lx-demo-phone"><div class="lx-phone-island"></div><div class="lx-phone-topline"><span>lockx</span><span class="lx-phone-timer"><i></i> 00:10</span></div><div class="lx-phone-view"><div class="lx-focus-corner lx-focus-corner--tl"></div><div class="lx-focus-corner lx-focus-corner--tr"></div><div class="lx-focus-corner lx-focus-corner--bl"></div><div class="lx-focus-corner lx-focus-corner--br"></div>${concertTickets('angle','video')}</div><div class="lx-phone-guidance"><span class="lx-small-check">${check}</span><strong>A little turn.<br>A clearer picture.</strong><span>Show the front, sides, and back.</span></div><div class="lx-phone-progress"><i></i></div><div class="lx-phone-bottom">10 seconds. Stops automatically.</div><div class="lx-phone-homebar"></div></div>
        <div class="lx-stage-connector lx-stage-connector--second">${arrow}</div>
        <div class="lx-demo-result"><div class="lx-result-heading"><span>${check}</span><div>Photo matched<small>Illustrative example</small></div></div><div class="lx-result-photo">${royalOakSketch('result')}</div><div class="lx-result-footer"><span><strong>lockx</strong><small>In-hand Verified</small></span>${qr()}</div><div class="lx-result-record">Photos with a story you can check.</div></div>
        <p class="lx-illustration-note">Illustrative example. Actual results depend on the evidence captured.</p>
      </div>

      <section class="lx-process lx-section lx-wrap" id="lxHowItWorks" aria-labelledby="lxHowTitle">
        <div class="lx-section-heading"><p class="lx-eyebrow">Small effort. Clearer evidence.</p><h2 id="lxHowTitle">From listing photos<br>to a verified photo set.</h2><p>One simple flow, right in your phone’s browser.</p></div>
        <div class="lx-process-grid">
          <article><span class="lx-step">01</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="7" y="10" width="23" height="25" rx="4" stroke="currentColor" stroke-width="1.8"/><path d="M13 5h17a5 5 0 0 1 5 5v18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="m8 28 7-8 6 5 4-4 5 6" stroke="currentColor" stroke-width="1.8"/><circle cx="23" cy="17" r="2" fill="currentColor"/></svg></div><h3>Add your photos.</h3><p>Choose the exact listing photos you want to verify. Four views are a great place to start.</p></article>
          <article><span class="lx-step">02</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="11" y="3" width="19" height="34" rx="5" stroke="currentColor" stroke-width="1.8"/><path d="M17 7h7m-7 26h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="20.5" cy="20" r="7" stroke="currentColor" stroke-width="1.8"/><path d="m19 17 4 3-4 3v-6Z" fill="currentColor"/></svg></div><h3>Show it for 10 seconds.</h3><p>Turn the item to show its different sides. Recording stops automatically, then AI compares the views.</p></article>
          <article><span class="lx-step">03</span><div class="lx-process-icon"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M6 6h10v10H6zm18 0h10v10H24zM6 24h10v10H6z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M24 23h4v5h6v6H23v-5m10-7v2M9 10h4v3H9zm18 0h4v3h-4zM9 28h4v3H9z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></div><h3>Save. List. Share.</h3><p>Each photo that passes verification appears on the same page with a QR code, ready to save.</p></article>
        </div>
      </section>

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
