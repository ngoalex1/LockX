/* Consented, publication-scoped evidence. No private media identifiers belong here. */
(() => {
  'use strict';
  const mounts = new WeakMap();
  const text = (value, limit = 1000) => typeof value === 'string' ? value.slice(0, limit) : '';
  const index = value => Number.isSafeInteger(value) && value >= 0;
  const time = seconds => {
    const whole = Math.floor(seconds), hours = Math.floor(whole / 3600);
    const minutes = Math.floor(whole / 60) % 60;
    const tail = (seconds % 60).toFixed(1).padStart(4, '0');
    return (hours ? `${hours}:${String(minutes).padStart(2, '0')}` : String(minutes).padStart(2, '0')) + ':' + tail;
  };
  const element = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  const button = (label, handler, className) => {
    const node = element('button', className, label);
    node.type = 'button';
    node.addEventListener('click', handler);
    return node;
  };
  function box(value) {
    if (!value || !['x', 'y', 'width', 'height'].every(k => typeof value[k] === 'number' && Number.isFinite(value[k]))) return null;
    const { x, y, width, height } = value;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1 || y + height > 1) return null;
    return { x, y, width, height };
  }
  function normalizedPayload(data) {
    if (!data || data.available !== true || !Array.isArray(data.photos)) return null;
    const seen = new Set();
    const photos = data.photos.slice(0, 100).flatMap(photo => {
      if (!photo || !index(photo.photo_index) || seen.has(photo.photo_index) || photo.finding !== 'supported'
          || photo.reference_key !== `reference-${photo.photo_index}` || !Array.isArray(photo.frames)) return [];
      const seenFrames = new Set();
      const frames = photo.frames.slice(0, 200).filter(frame => {
        if (!frame || !index(frame.frame_index) || seenFrames.has(frame.frame_index)
            || frame.media_key !== `frame-${frame.frame_index}` || typeof frame.seconds !== 'number'
            || !Number.isFinite(frame.seconds) || frame.seconds < 0 || frame.seconds > 86400) return false;
        seenFrames.add(frame.frame_index);
        return true;
      }).map(frame => ({ frame_index: frame.frame_index, seconds: frame.seconds, media_key: frame.media_key }));
      if (!frames.length) return [];
      seen.add(photo.photo_index);
      const regions = (Array.isArray(photo.regions) ? photo.regions : []).slice(0, 20).flatMap(region => {
        if (!region || region.photo_index !== photo.photo_index || !seenFrames.has(region.frame_index)
            || region.provenance !== 'ai_highlight_geometrically_supported') return [];
        const referenceBox = box(region.reference_box), frameBox = box(region.frame_box);
        if (!referenceBox || !frameBox) return [];
        return [{ frame_index: region.frame_index, label: text(region.label, 120) || 'Detail to compare',
          evidence: text(region.evidence), reference_box: referenceBox, frame_box: frameBox }];
      }).slice(0, 3);
      return [{ photo_index: photo.photo_index, reference_key: photo.reference_key, frames, regions, evidence: text(photo.evidence) }];
    });
    return photos.length ? { photos, video: data.video_key === 'video', scope: text(data.scope), listing: text(data.listing_url, 2048) } : null;
  }
  function safeLink(value) {
    try {
      const url = new URL(value);
      return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  }
  function apiURL(value, publicationId) {
    if (typeof value !== 'string' || typeof publicationId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(publicationId)) return null;
    try {
      const url = new URL(value, window.location.href);
      if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash
          || !/\/api\/v1\/in-hand\/?$/.test(url.pathname)) return null;
      return url.href.replace(/\/$/, '') + '/public/' + encodeURIComponent(publicationId) + '/evidence';
    } catch (_) { return null; }
  }

  function build(container, payload, endpoint, active) {
    const asset = key => endpoint + '/' + encodeURIComponent(key);
    const state = { photo: 0, frame: 0, region: null, highlights: true, videoLoaded: false, pendingSeek: null };
    const root = element('section', 'lxev');
    root.setAttribute('aria-label', 'Listing photo and recording comparison');
    const intro = element('header', 'lxev-intro');
    intro.append(element('span', 'lxev-kicker', 'LOCKX IN-HAND VERIFICATION'), element('h2', '', 'See what matched.'),
      element('p', '', 'Compare the listing photos with the recorded item.'));
    const tabs = element('div', 'lxev-photo-tabs');
    tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', 'Choose listing photo');
    const comparison = element('div', 'lxev-comparison');
    comparison.setAttribute('aria-label', 'Listing photograph beside a cited recording frame');
    function side(title, caption, recording) {
      const section = element('section', 'lxev-side');
      const label = element('div', 'lxev-photo-label'), name = element('span');
      label.append(element('strong', '', title), name);
      const surface = element('div', 'lxev-photo-surface' + (recording ? ' lxev-recording-surface' : ''));
      const stage = element('div', 'lxev-stage');
      const image = element('img', 'lxev-art'); image.decoding = 'async';
      const openImage=element('a','lxev-open-image');openImage.target='_blank';openImage.rel='noopener noreferrer';
      openImage.setAttribute('aria-label',recording?'Open full-size supporting frame':'Open full-size listing photo');
      const overlays = element('div', 'lxev-overlays'); overlays.setAttribute('aria-hidden', 'true');
      const failure = element('div', 'lxev-image-failure'); failure.hidden = true;
      failure.append(element('span', '', 'This image could not load.'), button('Retry image', () => {
        if (active()) { failure.hidden = true; image.hidden = false; image.src = image.dataset.source; }
      }, 'lxev-small-button'));
      image.addEventListener('load', () => { if (active()) { stage.dataset.ready = 'true'; failure.hidden = true; } });
      image.addEventListener('error', () => { if (active()) { stage.dataset.ready = 'false'; image.hidden = true; failure.hidden = false; } });
      openImage.append(image);stage.append(openImage, overlays); surface.append(stage, failure);
      section.append(label, surface, element('span', 'lxev-caption', caption)); comparison.append(section);
      return { name, stage, image, overlays, failure, openImage };
    }
    const reference = side('Listing photo', 'Original reference · preserved', false);
    const recording = side('Video frame', 'Cited moment · same recording', true);
    const framePicker = element('div', 'lxev-frame-picker');
    const frameButtons = element('div', 'lxev-frame-buttons');
    frameButtons.setAttribute('role', 'group'); frameButtons.setAttribute('aria-label', 'Cited recording frames');
    framePicker.append(element('span', '', 'Jump to a cited moment'), frameButtons);
    const reason = element('section', 'lxev-reason');
    const reasonText = element('p');
    reason.append(element('h3', '', 'Saved comparison reason'), reasonText);
    const detailsHead = element('div', 'lxev-details-head');
    const toggle = element('label', 'lxev-toggle');
    const check = element('input'); check.type = 'checkbox'; check.checked = true;
    toggle.append(check, document.createTextNode('Show highlights'));
    detailsHead.append(element('h3', '', 'Details to compare'), toggle);
    const annotation = element('p', 'lxev-annotation', 'AI-highlighted detail • compare for yourself');
    const features = element('div', 'lxev-features');
    features.setAttribute('role', 'group'); features.setAttribute('aria-label', 'Choose a detail to enlarge');
    const detail = element('section', 'lxev-detail'); detail.setAttribute('aria-live', 'polite');
    const noRegions = element('p', 'lxev-no-regions');
    const videoSection = element('section', 'lxev-video-section');
    videoSection.append(element('h3', '', 'Watch the source recording'),
      element('p', 'lxev-video-note', 'The full recording loads when you choose a timestamp or press play.'));
    // This element is deliberately created once and never replaced by photo/detail selection.
    const video = element('video', 'lxev-video');
    video.controls = true; video.playsInline = true; video.preload = 'none';
    video.setAttribute('aria-label', 'Full source recording');
    const videoActions = element('div', 'lxev-video-actions');
    const playButton = button('', () => seekVideo(currentFrame().seconds, true), 'lxev-play');
    const videoStatus = element('p', 'lxev-video-status'); videoStatus.setAttribute('role', 'status');
    videoActions.append(playButton); videoSection.append(video, videoActions, videoStatus);
    const footer = element('footer', 'lxev-footer');
    footer.append(element('span', '', 'Visual correspondence at recording time.'),
      element('span', '', 'Not an authenticity, ownership or delivery guarantee.'));
    if (payload.scope) footer.append(element('p', '', payload.scope));
    const listing = safeLink(payload.listing);
    if (listing) {
      const link = element('a', 'lxev-listing-link', 'Open the original listing');
      link.href = listing; link.target = '_blank'; link.rel = 'noopener noreferrer'; footer.append(link);
    }
    root.append(intro, tabs, comparison, framePicker, reason, detailsHead, annotation, features, detail, noRegions, videoSection, footer);
    container.replaceChildren(root); container.hidden = false;
    const currentPhoto = () => payload.photos[state.photo];
    const currentFrame = () => currentPhoto().frames[state.frame];
    let frameChoices = [], featureChoices = [];

    function applySeek() {
      if (!active() || state.pendingSeek === null || video.readyState < 1) return;
      const requested = state.pendingSeek;
      const limit = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.01) : requested;
      try {
        video.currentTime = Math.min(requested, limit);
        state.pendingSeek = null;
        videoStatus.textContent = `Recording set to ${time(video.currentTime)}.`;
      } catch (_) { videoStatus.textContent = 'Use the recording controls to reach this moment.'; }
    }
    function seekVideo(seconds, play) {
      if (!active() || !payload.video) return;
      state.pendingSeek = seconds;
      if (!state.videoLoaded || video.error) {
        state.videoLoaded = true;
        video.src = asset('video'); video.load();
      }
      videoStatus.textContent = `Loading the recording at ${time(seconds)}…`;
      applySeek();
      // play() stays in the original click handler so native user activation is preserved.
      if (play) {
        const result = video.play();
        if (result && typeof result.catch === 'function') result.catch(() => {
          if (active() && !video.error) videoStatus.textContent = 'Use the recording controls to start playback.';
        });
      }
    }
    video.addEventListener('loadedmetadata', applySeek);
    video.addEventListener('error', () => { if (active()) videoStatus.textContent = 'The recording could not load. Press play to try again; the photos and cited frames remain available.'; });
    if (!payload.video) {
      videoSection.hidden = true;
      framePicker.firstChild.textContent = 'Cited recording frames';
    }
    check.addEventListener('change', () => {
      state.highlights = check.checked;
      root.dataset.highlights = String(state.highlights);
    });
    payload.photos.forEach((photo, i) => {
      const tab = button(`Photo ${photo.photo_index + 1}`, () => {
        if (!active() || state.photo === i) return;
        state.photo = i; state.frame = 0; state.region = null; renderPhoto();
      });
      tab.setAttribute('aria-pressed', String(i === state.photo)); tabs.append(tab);
    });

    function loadImage(sideView, key, alt) {
      const url = asset(key);
      sideView.openImage.href=url;
      sideView.image.alt = alt;
      if (sideView.image.dataset.source === url) return;
      sideView.stage.dataset.ready = 'false'; sideView.failure.hidden = true; sideView.image.hidden = false;
      sideView.image.dataset.source = url; sideView.image.src = url;
    }
    function rect(node, bounds) {
      node.style.left = `${bounds.x * 100}%`; node.style.top = `${bounds.y * 100}%`;
      node.style.width = `${bounds.width * 100}%`; node.style.height = `${bounds.height * 100}%`;
    }
    function renderOverlays() {
      const photo = currentPhoto(), frame = currentFrame();
      [reference, recording].forEach((view, sideIndex) => {
        view.overlays.replaceChildren();
        photo.regions.forEach((region, regionIndex) => {
          if (region.frame_index !== frame.frame_index) return;
          const bounds = sideIndex ? region.frame_box : region.reference_box;
          if (regionIndex === state.region) {
            const outline = element('span', 'lxev-region'); rect(outline, bounds); view.overlays.append(outline);
          }
          // Numbers are visual references; the matching 44px buttons below provide
          // the interaction without overlapping touch targets on small photographs.
          const marker = element('span', 'lxev-point', String(regionIndex + 1));
          marker.classList.toggle('lxev-point-active', regionIndex === state.region);
          marker.style.left = `${(bounds.x + bounds.width / 2) * 100}%`;
          marker.style.top = `${(bounds.y + bounds.height / 2) * 100}%`;
          view.overlays.append(marker);
        });
      });
    }
    function crop(key, bounds, label) {
      const figure = element('figure');
      const surface = element('div', 'lxev-crop');
      const image = element('img'); image.alt = label; image.decoding = 'async';
      const outline = element('span', 'lxev-crop-region'); outline.setAttribute('aria-hidden', 'true');
      image.addEventListener('load', () => {
        const aspect = image.naturalWidth / image.naturalHeight;
        if (!Number.isFinite(aspect) || aspect <= 0) return;
        const zoom = Math.min(6, Math.max(1, Math.min(0.8 / bounds.width, 0.4 * aspect / bounds.height)));
        const width = zoom * 100, height = zoom * 200 / aspect;
        const centered = (size, center) => size >= 100 ? Math.max(100 - size, Math.min(0, 50 - center * size)) : (100 - size) / 2;
        const left = centered(width, bounds.x + bounds.width / 2), top = centered(height, bounds.y + bounds.height / 2);
        image.style.width = `${width}%`; image.style.left = `${left}%`; image.style.top = `${top}%`;
        outline.style.left = `${left + bounds.x * width}%`; outline.style.top = `${top + bounds.y * height}%`;
        outline.style.width = `${bounds.width * width}%`; outline.style.height = `${bounds.height * height}%`;
        surface.dataset.ready = 'true';
      });
      image.addEventListener('error', () => {
        surface.replaceChildren(element('span', 'lxev-crop-failure', 'Detail image unavailable.'));
      });
      image.src = asset(key); surface.append(image, outline);
      figure.append(surface, element('figcaption', '', label)); return figure;
    }
    function renderDetail() {
      const photo = currentPhoto(), region = photo.regions[state.region];
      detail.hidden = !region;
      detail.replaceChildren();
      if (!region) return;
      const title = element('div', 'lxev-detail-title');
      title.append(element('span', 'lxev-detail-number', String(state.region + 1)), element('strong', '', region.label));
      const crops = element('div', 'lxev-crops');
      crops.setAttribute('aria-label', 'Enlarged listing detail beside the cited recording detail');
      crops.append(crop(photo.reference_key, region.reference_box, 'Listing detail'),
        crop(currentFrame().media_key, region.frame_box, `Video detail · ${time(currentFrame().seconds)}`));
      detail.append(title, element('p', '', region.evidence || 'Compare this highlighted area in the two original views.'), crops);
    }
    function renderSelection() {
      const photo = currentPhoto(), frame = currentFrame();
      reference.name.textContent = `Photo ${photo.photo_index + 1}`;
      recording.name.textContent = `${time(frame.seconds)} · Frame ${frame.frame_index + 1}`;
      loadImage(reference, photo.reference_key, `Original listing photo ${photo.photo_index + 1}`);
      loadImage(recording, frame.media_key, `Cited recording frame ${frame.frame_index + 1} at ${time(frame.seconds)}`);
      frameChoices.forEach((choice, i) => choice.setAttribute('aria-pressed', String(i === state.frame)));
      featureChoices.forEach((choice, i) => choice.setAttribute('aria-pressed', String(i === state.region)));
      playButton.textContent = `Play from ${time(frame.seconds)}`;
      if (!state.videoLoaded) video.poster = asset(frame.media_key);
      renderOverlays(); renderDetail();
    }
    function renderPhoto() {
      const photo = currentPhoto();
      Array.from(tabs.children).forEach((tab, i) => tab.setAttribute('aria-pressed', String(i === state.photo)));
      reasonText.textContent = photo.evidence || 'No written comparison was saved. Compare the listing photo with the cited frames yourself.';
      frameButtons.replaceChildren();
      frameChoices = photo.frames.map((frame, i) => {
        const choice = button(`${time(frame.seconds)} · F${frame.frame_index + 1}`, () => {
          if (!active()) return;
          state.frame = i;
          state.region = photo.regions.findIndex(region => region.frame_index === frame.frame_index);
          if (state.region < 0) state.region = null;
          renderSelection(); seekVideo(frame.seconds, false);
        });
        choice.setAttribute('aria-label', `${payload.video ? 'Jump to' : 'Show'} frame ${frame.frame_index + 1} at ${time(frame.seconds)}`);
        frameButtons.append(choice); return choice;
      });
      features.replaceChildren();
      featureChoices = photo.regions.map((region, i) => {
        const choice = button('', () => {
          if (!active()) return;
          state.region = i; state.frame = photo.frames.findIndex(frame => frame.frame_index === region.frame_index);
          renderSelection();
        });
        choice.append(element('span', 'lxev-chip-number', String(i + 1)), document.createTextNode(region.label));
        features.append(choice); return choice;
      });
      const hasRegions = photo.regions.length > 0;
      toggle.hidden = !hasRegions; annotation.hidden = !hasRegions; features.hidden = !hasRegions;
      noRegions.hidden = hasRegions;
      noRegions.textContent = 'No precise highlights were saved for this photo. The cited frames and saved comparison reason are available above.';
      state.region = photo.regions.findIndex(region => region.frame_index === currentFrame().frame_index);
      if (state.region < 0) state.region = null;
      renderSelection();
    }
    root.dataset.highlights = 'true'; renderPhoto();
    return () => { video.pause(); video.removeAttribute('src'); video.load(); };
  }

  async function mount(container, options = {}) {
    if (!container || typeof container.replaceChildren !== 'function') return { available: false };
    const previous = mounts.get(container);
    if (previous) { previous.controller.abort(); if (previous.cleanup) previous.cleanup(); }
    const request = { controller: new AbortController(), cleanup: null };
    mounts.set(container, request);
    const active = () => mounts.get(container) === request && container.isConnected;
    const hide = () => { if (active()) { container.replaceChildren(); container.hidden = true; } };
    const destroy = () => {
      if (mounts.get(container) !== request) return;
      request.controller.abort(); if (request.cleanup) request.cleanup(); mounts.delete(container);
    };
    const endpoint = apiURL(options.apiBase, options.publicationId);
    if (!endpoint) { hide(); return { available: false, destroy }; }
    container.hidden = false;
    const pending = element('p', 'lxev-loading', 'Loading supporting comparison…'); pending.setAttribute('role', 'status');
    container.replaceChildren(pending);
    const timeout = setTimeout(() => request.controller.abort(), 15000);
    try {
      const response = await fetch(endpoint, { signal: request.controller.signal, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer' });
      if (!active()) return { available: false, destroy };
      if (response.status === 404) { hide(); return { available: false, destroy }; }
      if (!response.ok) throw new Error('Evidence unavailable');
      const data = await response.json();
      if (!active()) return { available: false, destroy };
      const payload = normalizedPayload(data);
      if (!payload) { hide(); return { available: false, destroy }; }
      request.cleanup = build(container, payload, endpoint, active);
      return { available: true, destroy };
    } catch (_) {
      if (!active()) return { available: false, destroy };
      const error = element('div', 'lxev-load-error');
      const message = element('p', '', 'The supporting comparison could not load. The proof record and photo gallery remain available.');
      error.append(message, button('Try comparison again', () => { if (active()) mount(container, options); }, 'lxev-small-button'));
      container.replaceChildren(error); container.hidden = false;
      return { available: false, destroy };
    } finally { clearTimeout(timeout); }
  }
  function unmount(container) {
    const request=container&&mounts.get(container);
    if(!request)return;
    request.controller.abort();if(request.cleanup)request.cleanup();mounts.delete(container);
  }
  window.LockXEvidence = Object.freeze({ mount, unmount });
})();
