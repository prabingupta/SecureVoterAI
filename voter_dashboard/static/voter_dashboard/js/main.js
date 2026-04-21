/*
   voter_dashboard/static/voter_dashboard/js/main.js

   BUGS FIXED:
   ──────────
   BUG 1  HEAD_TURN_THRESHOLD was 0.06 — too tight. The screenshot shows
          rel_x=-0.093 being rejected when "turn_right" was expected. The
          client was accepting it as a completed gesture (dots filled green,
          "Liveness confirmed" shown) but the server was rejecting it because
          0.093 < server TURN_THRESH. Thresholds now match the server values.
          Client TURN_THRESH → 0.09 (matches server), NEUTRAL_BAND → 0.06.

   BUG 2  MAX_ATTEMPTS was 3. After a server rejection the client incremented
          _attempts but never reset _livenessOK / _capturedFrame before
          retrying, so the second attempt re-submitted the same rejected frame.
          FIX: On server rejection, _livenessOK, _capturedFrame, _locked,
          _firstFace, and _state are all cleared before restarting the gate.
          MAX_ATTEMPTS raised to 5 so users have enough tries.

   BUG 3  After MAX_ATTEMPTS the button was disabled but the camera kept
          running (loop continued). FIX: stopCamera() is now called on
          terminal failure.

   BUG 4  EAR thresholds: EAR_OPEN was 0.27 and EAR_CLOSED was 0.24 — the
          gap was only 0.03 which caused false blink triggers during normal
          eye movement. EAR_OPEN raised to 0.28, EAR_CLOSED lowered to 0.19
          for a reliable gap.

   BUG 5  _challengeId was fetched from the server but if the fetch failed
          the fallback randomly picked from ALL 3 challenges each time the
          gate restarted, so the challenge changed between attempts. FIX:
          challenge is locked for the entire session once fetched.
*/

'use strict';

(function () {

  /* ── UTILITIES ─────────────────────────────────────────────────────────── */

  function getCsrf() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }

  async function postJSON(url) {
    try {
      const resp = await fetch(url, {
        method:  'POST',
        headers: {
          'X-CSRFToken':      getCsrf(),
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type':     'application/json',
        },
      });
      return await resp.json();
    } catch (err) {
      console.error('[main.js] postJSON error:', url, err);
      return null;
    }
  }

  /* ── TOAST ─────────────────────────────────────────────────────────────── */

  const TOAST_ICONS = {
    success: 'fa-circle-check',
    error:   'fa-circle-xmark',
    info:    'fa-circle-info',
    warning: 'fa-triangle-exclamation',
  };

  function ensureToastContainer() {
    let c = document.getElementById('toastContainer');
    if (!c) {
      c = document.createElement('div');
      c.id        = 'toastContainer';
      c.className = 'toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  window.showToast = function (message, type = 'info', duration = 3500) {
    const container = ensureToastContainer();
    const toast     = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML =
      `<i class="fa-solid ${TOAST_ICONS[type] || TOAST_ICONS.info}"></i><span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('removing');
      toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }, duration);
  };

  /* ── SIDEBAR COLLAPSE ───────────────────────────────────────────────────── */

  const shell         = document.querySelector('.app-shell');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar       = document.querySelector('.sidebar');

  if (sidebarToggle && shell) {
    if (localStorage.getItem('sidebarCollapsed') === '1') {
      shell.classList.add('sidebar-collapsed');
    }

    sidebarToggle.addEventListener('click', () => {
      if (window.innerWidth <= 680) {
        sidebar?.classList.toggle('open');
      } else {
        shell.classList.toggle('sidebar-collapsed');
        localStorage.setItem(
          'sidebarCollapsed',
          shell.classList.contains('sidebar-collapsed') ? '1' : '0'
        );
      }
    });
  }

  document.addEventListener('click', (e) => {
    if (
      window.innerWidth <= 680 &&
      sidebar?.classList.contains('open') &&
      !sidebar.contains(e.target) &&
      e.target !== sidebarToggle
    ) {
      sidebar.classList.remove('open');
    }
  });

  /* ── USER DROPDOWN ─────────────────────────────────────────────────────── */

  const dropdownTrigger = document.getElementById('userDropdownBtn');
  const dropdownMenu    = document.getElementById('userDropdownMenu');

  if (dropdownTrigger && dropdownMenu) {
    dropdownTrigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = dropdownMenu.classList.toggle('open');
      dropdownTrigger.setAttribute('aria-expanded', String(isOpen));
    });

    document.addEventListener('click', (e) => {
      if (!dropdownMenu.contains(e.target) && e.target !== dropdownTrigger) {
        dropdownMenu.classList.remove('open');
        dropdownTrigger.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        dropdownMenu.classList.remove('open');
        dropdownTrigger.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* ── NOTIFICATION BADGE POLLING ─────────────────────────────────────────── */

  const bellBadge    = document.getElementById('notifBadge');
  const sidebarBadge = document.getElementById('sidebarNotifBadge');
  const POLL_URL      = '/voter-dashboard/notifications/count/';
  const POLL_INTERVAL = 30_000;

  function updateBadge(count) {
    [bellBadge, sidebarBadge].forEach(badge => {
      if (!badge) return;
      if (count > 0) {
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.classList.add('visible');
      } else {
        badge.classList.remove('visible');
      }
    });
  }

  async function pollNotifications() {
    try {
      const resp = await fetch(POLL_URL, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!resp.ok) return;
      const data = await resp.json();
      updateBadge(data.count || 0);
    } catch (_) { /* non-critical */ }
  }

  if (bellBadge) {
    pollNotifications();
    setInterval(pollNotifications, POLL_INTERVAL);
  }

  /* ── NOTIFICATION PAGE ACTIONS ──────────────────────────────────────────── */

  document.querySelectorAll('[data-mark-read]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id   = btn.dataset.markRead;
      const row  = document.getElementById(`notif-${id}`);
      const data = await postJSON(`/voter-dashboard/notifications/${id}/read/`);
      if (data?.success && row) {
        row.classList.remove('unread');
        row.querySelector('.notif-unread-dot')?.remove();
        btn.remove();
        pollNotifications();
      }
    });
  });

  document.querySelectorAll('[data-delete-notif]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id   = btn.dataset.deleteNotif;
      const row  = document.getElementById(`notif-${id}`);
      const data = await postJSON(`/voter-dashboard/notifications/${id}/delete/`);
      if (data?.success && row) {
        row.style.transition = 'opacity .25s ease, transform .25s ease';
        row.style.opacity    = '0';
        row.style.transform  = 'translateX(16px)';
        setTimeout(() => row.remove(), 280);
        pollNotifications();
      }
    });
  });

  const markAllBtn = document.getElementById('markAllReadBtn');
  if (markAllBtn) {
    markAllBtn.addEventListener('click', async () => {
      const data = await postJSON('/voter-dashboard/notifications/mark-all-read/');
      if (data?.success) {
        document.querySelectorAll('.notif-item.unread').forEach(row => {
          row.classList.remove('unread');
          row.querySelector('.notif-unread-dot')?.remove();
          row.querySelector('[data-mark-read]')?.remove();
        });
        updateBadge(0);
        window.showToast('All notifications marked as read.', 'success');
      }
    });
  }

  /* ── SETTINGS PAGE — AJAX FORM SUBMISSIONS ─────────────────────────────── */

  function wireSettingsForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      const origHtml  = submitBtn?.innerHTML || '';
      if (submitBtn) {
        submitBtn.disabled  = true;
        submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving…';
      }
      try {
        const resp = await fetch(form.action || window.location.href, {
          method:  'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          body:    new FormData(form),
        });
        const data = await resp.json();
        window.showToast(
          data.message || (data.success ? 'Saved.' : 'Could not save.'),
          data.success ? 'success' : 'error'
        );
        if (data.success && (formId === 'passwordForm' || formId === 'phoneForm')) {
          form.reset();
        }
      } catch (_) {
        window.showToast('Network error. Please try again.', 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled  = false;
          submitBtn.innerHTML = origHtml;
        }
      }
    });
  }

  wireSettingsForm('prefsForm');
  wireSettingsForm('phoneForm');
  wireSettingsForm('passwordForm');

  /* ── DJANGO FLASH MESSAGES → TOAST ─────────────────────────────────────── */

  document.querySelectorAll('[data-django-message]').forEach(el => {
    const type = el.dataset.djangoMessage || 'info';
    const text = el.textContent.trim();
    if (text) window.showToast(text, type);
    el.remove();
  });

  /* ── ACTIVE SIDEBAR LINK HIGHLIGHT ─────────────────────────────────────── */

  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-nav-item[data-href]').forEach(link => {
    if (link.dataset.href && currentPath.startsWith(link.dataset.href)) {
      link.classList.add('active');
    }
  });

  /* ═══════════════════════════════════════════════════════════════════════════
     CAST VOTE PAGE — LIVENESS GATE + BALLOT FORM
     ═══════════════════════════════════════════════════════════════════════ */

  const castVoteConfig = document.getElementById('castVoteConfig');
  if (!castVoteConfig) return;

  const LIVENESS_URL  = castVoteConfig.dataset.livenessUrl;
  const CHALLENGE_API = '/api/liveness-challenges/?mode=login';
  const MP_CDN        = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/';

  // BUG 2 FIX: Raised from 3 to 5 so users have more chances
  const MAX_ATTEMPTS  = 5;

  // ── Landmark indices ──────────────────────────────────────────────────────
  const L_EYE_IDX = [33, 160, 158, 133, 153, 144];
  const R_EYE_IDX = [263, 387, 385, 362, 373, 380];
  const NOSE_IDX  = 1;
  const L_EAR_IDX = 234;
  const R_EAR_IDX = 454;

  function lmDist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

  function avgEAR(lm) {
    function ear(idx) {
      const p = idx.map(i => lm[i]);
      return (lmDist(p[1], p[5]) + lmDist(p[2], p[4])) /
             (2 * lmDist(p[0], p[3]) + 1e-6);
    }
    return (ear(L_EYE_IDX) + ear(R_EYE_IDX)) / 2;
  }

  function headRelX(lm) {
    const fw = lmDist(lm[L_EAR_IDX], lm[R_EAR_IDX]) + 1e-6;
    // Sign convention: negative = left turn, positive = right turn
    return -((lm[NOSE_IDX].x - (lm[L_EAR_IDX].x + lm[R_EAR_IDX].x) / 2) / fw);
  }

  // ── Client-side thresholds (MUST match server values in liveness.py) ──────
  // BUG 1 FIX: Raised TURN_THRESH from 0.06 to 0.09 to match server.
  //   The screenshot showed rel_x=-0.093 failing "need > 0.025" on the server —
  //   client was accepting 0.025 but server required 0.09. Now they match.
  const EAR_OPEN_THRESH     = 0.28;   // was 0.27 — BUG 4 FIX
  const EAR_CLOSED_THRESH   = 0.19;   // was 0.24 — BUG 4 FIX (wider gap)
  const NEUTRAL_BAND        = 0.06;   // was 0.04 — BUG 1 FIX
  const TURN_THRESH         = 0.09;   // was 0.06 — BUG 1 FIX (matches server)
  const TURN_CONFIRM_FRAMES = 3;      // client uses 3 for smoothing; server uses 1

  const CHALLENGES = {
    blink: {
      icon: 'fa-eye', label: 'Blink both eyes',
      createState: () => ({ phase: 'waiting_open', cf: 0 }),
      update(s, lm) {
        const e = avgEAR(lm);
        // BUG 4 FIX: use EAR_OPEN_THRESH / EAR_CLOSED_THRESH constants
        if (s.phase === 'waiting_open') { if (e >= EAR_OPEN_THRESH) s.phase = 'waiting_blink'; return false; }
        if (e < EAR_CLOSED_THRESH) { s.cf++; if (s.cf >= 1) return true; } else s.cf = 0;
        return false;
      },
    },
    turn_left: {
      icon: 'fa-arrow-left', label: 'Turn head LEFT and hold',
      createState: () => ({ phase: 'waiting_neutral', tf: 0 }),
      update(s, lm) {
        const rx = headRelX(lm);
        if (s.phase === 'waiting_neutral') { if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn'; return false; }
        // BUG 1 FIX: turn_left = negative rel_x
        if (rx < -TURN_THRESH) { s.tf++; if (s.tf >= TURN_CONFIRM_FRAMES) return true; } else s.tf = 0;
        return false;
      },
    },
    turn_right: {
      icon: 'fa-arrow-right', label: 'Turn head RIGHT and hold',
      createState: () => ({ phase: 'waiting_neutral', tf: 0 }),
      update(s, lm) {
        const rx = headRelX(lm);
        if (s.phase === 'waiting_neutral') { if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn'; return false; }
        // BUG 1 FIX: turn_right = positive rel_x
        if (rx > TURN_THRESH) { s.tf++; if (s.tf >= TURN_CONFIRM_FRAMES) return true; } else s.tf = 0;
        return false;
      },
    },
  };

  let _stream = null, _faceMesh = null, _animFrame = null, _video = null;
  // BUG 5 FIX: _challengeId is set once and locked for the session
  let _challengeId = null, _challengeLocked = false;
  let _state = null;
  let _locked = false, _firstFace = false, _livenessOK = false;
  let _capturedFrame = '', _timer = null, _countdown = null, _attempts = 0;

  const $id = id => document.getElementById(id);

  function setStatus(text, cls = '') {
    const el = $id('camStatusText'), wrap = $id('camStatus');
    if (el)   el.textContent = text;
    if (wrap) wrap.className = 'cam-status' + (cls ? ' ' + cls : '');
  }

  function setBar(text, cls = '', icon = '') {
    const t = $id('challengeText'), b = $id('challengeBar'), i = $id('challengeIcon');
    if (t) t.textContent = text;
    if (b) b.className   = 'challenge-bar' + (cls ? ' ' + cls : '');
    if (icon && i) i.className = 'fa-solid ' + icon;
  }

  function showGateError(msg) {
    const m = $id('gateErrorMsg'), e = $id('gateError');
    if (m) m.textContent = msg;
    if (e) e.classList.add('show');
  }

  function hideGateError() { $id('gateError')?.classList.remove('show'); }

  function waitForFaceMesh(timeout = 12000) {
    return new Promise((resolve, reject) => {
      if (typeof window.FaceMesh !== 'undefined') { resolve(); return; }
      const start = Date.now();
      const chk = setInterval(() => {
        if (typeof window.FaceMesh !== 'undefined') { clearInterval(chk); resolve(); }
        else if (Date.now() - start > timeout) { clearInterval(chk); reject(new Error('FaceMesh timeout')); }
      }, 100);
    });
  }

  function stopCamera() {
    clearTimeout(_timer); clearInterval(_countdown);
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null; }
    if (_stream)    { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    _faceMesh = null;
  }

  function startClock() {
    clearTimeout(_timer); clearInterval(_countdown);
    const ch = CHALLENGES[_challengeId];
    let secs  = 8; // BUG 1 FIX: more time for deliberate head turn (was 6s)
    $id('gdot1')?.classList.remove('done');
    setBar(`${ch.label} (${secs}s)…`, '', ch.icon);
    _countdown = setInterval(() => {
      secs--;
      if (secs > 0) setBar(`${ch.label} (${secs}s)…`, '', ch.icon);
      else          clearInterval(_countdown);
    }, 1000);
    _timer = setTimeout(() => {
      clearInterval(_countdown);
      if (_livenessOK) return;
      setBar('Timed out — gesture not detected. Retrying…', 'error', 'fa-clock');
      setStatus('Timed out', 'error');
      _attempts++;
      if (_attempts >= MAX_ATTEMPTS) {
        stopCamera();
        showGateError(`Liveness failed after ${MAX_ATTEMPTS} attempts. Refresh to try again.`);
        setBar('Too many failed attempts. Refresh to try again.', 'error', 'fa-ban');
        return;
      }
      // BUG 2 FIX: Fully reset liveness state before retry
      setTimeout(() => resetLivenessState(), 1500);
    }, 8000); // BUG 1 FIX: 8s window (was 6s)
  }

  // BUG 2 FIX: New function — cleanly resets liveness state for a retry
  function resetLivenessState() {
    _firstFace     = false;
    _locked        = false;
    _livenessOK    = false;
    _capturedFrame = '';
    // Recreate challenge state but KEEP the same _challengeId (BUG 5 FIX)
    if (_challengeId && CHALLENGES[_challengeId]) {
      _state = CHALLENGES[_challengeId].createState();
    }
    const ch = _challengeId ? CHALLENGES[_challengeId] : null;
    if (ch) {
      setBar(`Look at the camera — ${ch.label}`, '', ch.icon);
    } else {
      setBar('Look at the camera to begin…', '');
    }
    setStatus('Camera active', 'ready');
    $id('gdot1')?.classList.remove('done');
    $id('gdot2')?.classList.remove('done');
    const vb = $id('btnVerify');
    if (vb) { vb.disabled = true; vb.innerHTML = '<i class="fa-solid fa-circle-check"></i> Confirm Identity'; }
  }

  function onResults(results) {
    if (_livenessOK || _locked) return;
    const faces = results.multiFaceLandmarks || [];
    if (faces.length > 1) {
      clearTimeout(_timer); clearInterval(_countdown);
      resetLivenessState();
      setStatus(`${faces.length} faces detected`, 'error');
      setBar(`Security: ${faces.length} people in frame. Only you may be present.`, 'error', 'fa-users');
      return;
    }
    if (faces.length === 0) { setStatus('No face detected — look at the camera'); return; }
    const lm = faces[0];
    setStatus('Face detected', 'ready');
    if (!_firstFace) { _firstFace = true; startClock(); return; }
    const ch = CHALLENGES[_challengeId];
    if (!ch || !_state || !ch.update(_state, lm)) return;

    // Gesture confirmed on client ─────────────────────────────────────────────
    _locked = true;
    clearTimeout(_timer); clearInterval(_countdown);
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null; }
    _livenessOK = true;
    const canvas = document.createElement('canvas');
    canvas.width  = _video.videoWidth  || 640;
    canvas.height = _video.videoHeight || 480;
    canvas.getContext('2d').drawImage(_video, 0, 0, canvas.width, canvas.height);
    _capturedFrame = canvas.toDataURL('image/jpeg', 0.85);
    $id('gdot1')?.classList.add('done');
    $id('gdot2')?.classList.add('done');
    setBar(`✓ ${ch.label} confirmed! Click Confirm Identity.`, 'success', ch.icon);
    setStatus('Liveness confirmed', 'ready');
    const vb = $id('btnVerify');
    if (vb) vb.disabled = false;
  }

  function loop() {
    if (!_stream || _livenessOK || !_faceMesh) return;
    _animFrame = requestAnimationFrame(async () => {
      if (!_stream || !_faceMesh) return;
      try { if (_video && _video.readyState >= 2) await _faceMesh.send({ image: _video }); }
      catch (_) {}
      if (!_livenessOK) loop();
    });
  }

  async function startGate() {
    // Reset full state
    _livenessOK    = false;
    _capturedFrame = '';
    _locked        = false;
    _firstFace     = false;
    _state         = null;
    clearTimeout(_timer); clearInterval(_countdown);
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null; }
    hideGateError();
    const vb = $id('btnVerify');
    if (vb) vb.disabled = true;
    $id('gdot1')?.classList.remove('done');
    $id('gdot2')?.classList.remove('done');
    setBar('Loading face detection…', '', 'fa-spinner');
    setStatus('Starting camera…');

    try { await waitForFaceMesh(); }
    catch (e) {
      setBar('Face detection library failed to load. Check your connection.', 'error', 'fa-triangle-exclamation');
      return;
    }

    // BUG 5 FIX: Only fetch challenge once; reuse on retry
    if (!_challengeId || !_challengeLocked) {
      try {
        const r = await fetch(CHALLENGE_API, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const d = await r.json();
        const fetched = (d.challenges || [])[0];
        if (fetched && CHALLENGES[fetched]) {
          _challengeId     = fetched;
          _challengeLocked = true;
        }
      } catch (_) {}
      if (!_challengeId || !CHALLENGES[_challengeId]) {
        const fallbacks = ['blink', 'turn_left', 'turn_right'];
        _challengeId     = fallbacks[Math.floor(Math.random() * fallbacks.length)];
        _challengeLocked = true;
      }
    }
    _state = CHALLENGES[_challengeId].createState();

    setStatus('Requesting camera…');
    try {
      _stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      _video           = $id('voteWebcam');
      _video.srcObject = _stream;
      await _video.play();
      setStatus('Camera active', 'ready');
    } catch (e) {
      const denied = e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError';
      setStatus('Camera access denied', 'error');
      setBar(
        denied ? 'Camera permission denied. Allow access and refresh.'
               : 'Could not start camera. Check your device and refresh.',
        'error', 'fa-camera-slash'
      );
      return;
    }

    try {
      _faceMesh = new window.FaceMesh({ locateFile: f => `${MP_CDN}${f}` });
      _faceMesh.setOptions({
        maxNumFaces: 4, refineLandmarks: true,
        minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
      });
      await _faceMesh.initialize();
      _faceMesh.onResults(onResults);
    } catch (e) {
      setBar('Face detection failed to initialise: ' + e.message, 'error', 'fa-triangle-exclamation');
      stopCamera(); return;
    }

    const ch = CHALLENGES[_challengeId];
    setBar(`Look at the camera — ${ch.label}`, '', ch.icon);
    loop();
  }

  $id('btnVerify')?.addEventListener('click', async () => {
    if (!_livenessOK || !_capturedFrame) { setBar('Please complete the liveness gesture first.', 'error'); return; }
    const vb    = $id('btnVerify');
    vb.disabled  = true;
    vb.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verifying face…';
    stopCamera(); hideGateError();
    try {
      const resp = await fetch(LIVENESS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
        body:   JSON.stringify({ frame: _capturedFrame, liveness_confirmed: true }),
      });
      const data = await resp.json();
      if (data.verified) {
        $id('livenessGate').style.display = 'none';
        $id('verifiedBanner').classList.add('show');
        const fs = $id('candidateFormSection');
        fs.classList.add('show');
        fs.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else {
        const msg = data.error || 'Verification failed. Please try again.';
        showGateError(msg); setBar('✗ ' + msg, 'error');
        vb.innerHTML = '<i class="fa-solid fa-circle-check"></i> Confirm Identity';

        const hardBlock = resp.status === 403 &&
          (msg.toLowerCase().includes('locked') || msg.toLowerCase().includes('security'));

        if (hardBlock) {
          vb.disabled = true;
          stopCamera();
        } else {
          // BUG 2 FIX: Properly reset liveness state before retry
          _livenessOK    = false;
          _capturedFrame = '';
          _locked        = false;
          _firstFace     = false;
          _state         = _challengeId ? CHALLENGES[_challengeId]?.createState() : null;
          vb.disabled    = false;

          _attempts++;
          if (_attempts < MAX_ATTEMPTS) {
            // Restart camera after short delay
            setTimeout(() => startGate(), 2000);
          } else {
            vb.disabled = true;
            stopCamera();
            setBar('Too many attempts. Refresh the page to try again.', 'error', 'fa-ban');
          }
        }
      }
    } catch (e) {
      console.error('[cast_vote] fetch error:', e);
      showGateError('Network error. Check your connection and try again.');
      setBar('Network error.', 'error', 'fa-wifi');
      $id('btnVerify').innerHTML = '<i class="fa-solid fa-circle-check"></i> Confirm Identity';
      $id('btnVerify').disabled  = false;
    }
  });

  document.querySelectorAll('.candidate-radio').forEach(radio => {
    radio.addEventListener('change', () => {
      const sb = $id('openModalBtn');
      if (sb) sb.disabled = ![...document.querySelectorAll('.candidate-radio')].some(r => r.checked);
    });
  });

  $id('openModalBtn')?.addEventListener('click', () => {
    const sel   = document.querySelector('.candidate-radio:checked');
    if (!sel) return;
    const name  = document.querySelector(`label[for="${sel.id}"] .candidate-name`)
                  ?.textContent?.trim() || 'Selected Candidate';
    $id('modalCandidateName').textContent = name;
    $id('confirmModal').classList.add('open');
    $id('cancelModalBtn')?.focus();
  });

  $id('cancelModalBtn')?.addEventListener('click', () => { $id('confirmModal').classList.remove('open'); });

  $id('confirmModal')?.addEventListener('click', (e) => {
    if (e.target === $id('confirmModal')) $id('confirmModal').classList.remove('open');
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $id('confirmModal')?.classList.remove('open');
  });

  $id('finalSubmitBtn')?.addEventListener('click', () => {
    const btn    = $id('finalSubmitBtn');
    btn.disabled  = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Encrypting…';
    setTimeout(() => $id('voteForm').submit(), 800);
  });

  if (document.readyState === 'complete') {
    startGate();
  } else {
    window.addEventListener('load', () => startGate(), { once: true });
  }

})();