'use strict';

const MP_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/';

//  Landmark indices 
const L_EYE  = [33, 160, 158, 133, 153, 144];
const R_EYE  = [263, 387, 385, 362, 373, 380];
const NOSE   = 1;
const L_EAR  = 234;
const R_EAR  = 454;

function pd(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

function avgEAR(lm) {
  function ear(idx) {
    const p = idx.map(i => lm[i]);
    return (pd(p[1], p[5]) + pd(p[2], p[4])) / (2 * pd(p[0], p[3]) + 1e-6);
  }
  return (ear(L_EYE) + ear(R_EYE)) / 2;
}

function headRelX(lm) {
  const faceW = pd(lm[L_EAR], lm[R_EAR]) + 1e-6;
  return -((lm[NOSE].x - (lm[L_EAR].x + lm[R_EAR].x) / 2) / faceW);
}

// Thresholds 
const EAR_OPEN_THRESH     = 0.27;
const EAR_CLOSED_THRESH   = 0.24;
const NEUTRAL_BAND        = 0.04;
const TURN_THRESH         = 0.06;
const TURN_CONFIRM_FRAMES = 3;

//  Challenge catalogue — look_up intentionally absent 
const CHALLENGES = {
  blink: {
    icon:  'fa-eye',
    label: 'Blink both eyes',
    createState: () => ({ phase: 'waiting_open', closedFrames: 0 }),
    update(s, lm) {
      const e = avgEAR(lm);
      if (s.phase === 'waiting_open') {
        if (e >= EAR_OPEN_THRESH) s.phase = 'waiting_blink';
        return false;
      }
      if (e < EAR_CLOSED_THRESH) { s.closedFrames++; if (s.closedFrames >= 1) return true; }
      else s.closedFrames = 0;
      return false;
    },
  },
  turn_left: {
    icon:  'fa-arrow-left',
    label: 'Turn head LEFT',
    createState: () => ({ phase: 'waiting_neutral', turnFrames: 0 }),
    update(s, lm) {
      const rx = headRelX(lm);
      if (s.phase === 'waiting_neutral') {
        if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn';
        return false;
      }
      if (rx < -TURN_THRESH) { s.turnFrames++; if (s.turnFrames >= TURN_CONFIRM_FRAMES) return true; }
      else s.turnFrames = 0;
      return false;
    },
  },
  turn_right: {
    icon:  'fa-arrow-right',
    label: 'Turn head RIGHT',
    createState: () => ({ phase: 'waiting_neutral', turnFrames: 0 }),
    update(s, lm) {
      const rx = headRelX(lm);
      if (s.phase === 'waiting_neutral') {
        if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn';
        return false;
      }
      if (rx > TURN_THRESH) { s.turnFrames++; if (s.turnFrames >= TURN_CONFIRM_FRAMES) return true; }
      else s.turnFrames = 0;
      return false;
    },
  },
};

//  Anti-spoof / session constants
const MOTION_FLOOR       = 0.3;
const STALE_FRAME_LIMIT  = 30;
const SESSION_WARN_MS    = 4 * 60 * 1000;
const SESSION_EXPIRE_MS  = 5 * 60 * 1000;

//  Module state
let _capturedFrame   = '';
let _livenessOK      = false;
let _motionScore     = 999;
let _challengeId     = null;
let _challengeState  = null;
let _challengeLocked = false;
let _firstFaceSeen   = false;
let _staleCount      = 0;
let _prevFrameData   = null;
let _step2StartedAt  = null;

function dbg(msg) { console.log(`[login.js v11] ${msg}`); }

document.addEventListener('DOMContentLoaded', () => {

  const step1El     = document.getElementById('loginStep1');
  const step2El     = document.getElementById('loginStep2');
  const step1Next   = document.getElementById('step1Next');
  const step2Prev   = document.getElementById('step2Prev');
  const loginSubmit = document.getElementById('loginSubmit');
  const progressBar = document.getElementById('progressBar');
  const asideStep1  = document.querySelector('.aside-step[data-step="1"]');
  const asideStep2  = document.querySelector('.aside-step[data-step="2"]');
  const connector   = document.querySelector('.aside-step-connector');
  const video       = document.getElementById('loginWebcam');
  const statusWrap  = document.getElementById('webcamStatus');
  const statusText  = document.getElementById('webcamStatusText');
  const instructEl  = document.getElementById('livenessInstruction');
  const instructTxt = document.getElementById('instructionText');
  const dot1        = document.getElementById('dot1');
  const dot2        = document.getElementById('dot2');
  const msgBox      = document.getElementById('ajaxMessages');

  const getCsrf = () =>
    document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

  let cameraStream       = null;
  let faceMesh           = null;
  let animFrame          = null;
  let challengeTimer     = null;
  let countdownInterval  = null;
  let sessionWarnTimer   = null;
  let sessionExpireTimer = null;

  // Off-screen canvas for optical-flow
  const _offCanvas  = document.createElement('canvas');
  _offCanvas.width  = 64;
  _offCanvas.height = 48;
  const _offCtx     = _offCanvas.getContext('2d', { willReadFrequently: true });

  dbg('loaded ✓');

  /*  credential check */
  step1Next?.addEventListener('click', async () => {
    if (!validateStep1()) return;
    setButtonLoading(step1Next, '<span class="spinner"></span> Checking…');
    clearMsg();

    const fd = new FormData();
    fd.append('student_id', document.getElementById('student_id')?.value.trim() || '');
    fd.append('password',   document.getElementById('password')?.value || '');
    fd.append('csrfmiddlewaretoken', getCsrf());

    try {
      const resp = await fetch('/login/', {
        method:  'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body:    fd,
      });
      const data = await resp.json();
      dbg(`step1 → ${JSON.stringify(data)}`);

      if (data.success && !data.require_face && data.redirect) {
        showMsg(data.message || 'Login successful!', 'success');
        setTimeout(() => { window.location.href = data.redirect; }, 600);
        return;
      }
      if (data.success && data.require_face) {
        resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');
        showStep2();
        return;
      }
      showMsg(data.error || 'Login failed.', data.type || 'error');
      resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');
    } catch (_) {
      showMsg('Network error. Check your connection.', 'error');
      resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');
    }
  });

  step2Prev?.addEventListener('click', () => {
    stopCamera();
    clearSessionTimers();
    hideStep2();
  });

  /*  Step visibility  */
  function showStep2() {
    step1El?.classList.remove('active');
    step2El.style.display = '';
    step2El.classList.add('active');
    asideStep1?.classList.replace('active', 'completed');
    asideStep2?.classList.add('active');
    connector?.classList.add('filled');
    if (progressBar) progressBar.style.width = '100%';
    document.querySelector('.login-main')?.scrollTo({ top: 0, behavior: 'smooth' });
    _step2StartedAt = Date.now();
    startSessionTimers();
    startCamera();
  }

  function hideStep2() {
    step2El.classList.remove('active');
    step2El.style.display = 'none';
    step1El?.classList.add('active');
    asideStep1?.classList.remove('completed');
    asideStep1?.classList.add('active');
    asideStep2?.classList.remove('active');
    connector?.classList.remove('filled');
    if (progressBar) progressBar.style.width = '50%';
  }

  /*  Session timers  */
  function startSessionTimers() {
    clearSessionTimers();
    sessionWarnTimer = setTimeout(() => {
      showMsg(
        'Your session expires in 1 minute. Please complete face verification.',
        'warning',
      );
    }, SESSION_WARN_MS);
    sessionExpireTimer = setTimeout(() => {
      stopCamera();
      showMsg('Session expired. Redirecting to login…', 'error');
      setTimeout(() => { window.location.href = '/login/'; }, 2500);
    }, SESSION_EXPIRE_MS);
  }
  function clearSessionTimers() {
    clearTimeout(sessionWarnTimer);
    clearTimeout(sessionExpireTimer);
  }

  /*  Camera + challenge liveness  */
  async function startCamera() {
    _capturedFrame   = '';
    _livenessOK      = false;
    _motionScore     = 999;
    _challengeId     = null;
    _challengeState  = null;
    _challengeLocked = false;
    _firstFaceSeen   = false;
    _staleCount      = 0;
    _prevFrameData   = null;

    dot1?.classList.remove('done', 'active');
    dot2?.classList.remove('done', 'active');
    instructEl?.classList.remove('success', 'error');
    if (loginSubmit) loginSubmit.disabled = true;

    setStatus('Requesting camera…', '');
    setInstr('Allow camera access to continue.', '');

    // Fetch server-issued challenge (1 random from blink/turn_left/turn_right)
    try {
      const res  = await fetch('/api/liveness-challenges/?mode=login');
      const data = await res.json();
      if (data.error) {
        setInstr(data.error, 'error');
        setStatus('Session error', 'error');
        return;
      }
      _challengeId = Array.isArray(data.challenges) ? data.challenges[0] : null;
    } catch (_) {}

    // Fallback — never look_up
    if (!_challengeId || !CHALLENGES[_challengeId]) {
      const fallback = ['blink', 'turn_left', 'turn_right'];
      _challengeId = fallback[Math.floor(Math.random() * fallback.length)];
    }
    _challengeState = CHALLENGES[_challengeId].createState();
    dbg(`Server challenge: ${_challengeId}`);

    // Open camera
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      video.srcObject = cameraStream;
      await video.play();
      setStatus('Camera active', 'ready');
    } catch (_) {
      setStatus('Camera access denied', 'error');
      setInstr('Enable camera permissions, then go Back and try again.', 'error');
      return;
    }

    // Load FaceMesh with maxNumFaces=4 for multi-face detection
    setInstr('Loading face detection…', '');
    try {
      faceMesh = new window.FaceMesh({ locateFile: f => `${MP_CDN}${f}` });
      faceMesh.setOptions({
        maxNumFaces: 4, refineLandmarks: true,
        minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
      });
      await faceMesh.initialize();
      faceMesh.onResults(onFaceResults);
      dbg('FaceMesh ready');
    } catch (_) {
      setInstr(
        'Face detection failed to load. Check your internet connection.',
        'error',
      );
      return;
    }

    const ch   = CHALLENGES[_challengeId];
    const icon = instructEl?.querySelector('i');
    if (icon) icon.className = `fa-solid ${ch.icon}`;
    setInstr('Look at the camera to begin…', '');
    runLoop();
  }

  function startChallengeClock() {
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);
    const ch = CHALLENGES[_challengeId];
    dot1?.classList.add('active');
    let secsLeft = 5;
    instructEl?.classList.remove('success', 'error');
    setInstr(`${ch.label} (${secsLeft}s)…`, '');
    countdownInterval = setInterval(() => {
      secsLeft--;
      if (secsLeft > 0) setInstr(`${ch.label} (${secsLeft}s)…`, '');
      else clearInterval(countdownInterval);
    }, 1000);
    challengeTimer = setTimeout(() => {
      clearInterval(countdownInterval);
      if (!_livenessOK) {
        dot1?.classList.remove('active');
        setInstr(
          `Timed out — "${ch.label}" not detected. Press Back to retry.`,
          'error',
        );
        setStatus('Timed out', 'error');
        stopCamera();
      }
    }, 5000);
  }

  function runLoop() {
    if (!cameraStream || _livenessOK) return;
    animFrame = requestAnimationFrame(async () => {
      if (!cameraStream) return;
      try { await faceMesh.send({ image: video }); } catch (_) {}
      if (!_livenessOK) runLoop();
    });
  }

  function onFaceResults(results) {
    if (_livenessOK || _challengeLocked) return;

    const faces = results.multiFaceLandmarks || [];

    // Multi-face guard
    if (faces.length > 1) {
      clearTimeout(challengeTimer);
      clearInterval(countdownInterval);
      cancelAnimationFrame(animFrame);
      dot1?.classList.remove('active');
      setStatus('Multiple faces detected', 'error');
      setInstr(
        `Security: ${faces.length} faces visible. Only you may be present. ` +
        'Press Back to retry.',
        'error',
      );
      showMsg(
        'Multiple faces detected. Only the voter may be in frame.',
        'error',
      );
      return;
    }
    if (faces.length === 0) {
      setStatus('No face detected — look at the camera', '');
      return;
    }

    const lm = faces[0];

    // Optical-flow motion score (anti-static-image)
    const score = computeMotionScore();
    _motionScore = Math.min(_motionScore, score);
    if (score < MOTION_FLOOR) {
      _staleCount++;
      if (_staleCount >= STALE_FRAME_LIMIT) {
        clearTimeout(challengeTimer);
        clearInterval(countdownInterval);
        cancelAnimationFrame(animFrame);
        dot1?.classList.remove('active');
        setStatus('Static image detected', 'error');
        setInstr(
          'Anti-spoof: static image detected. Use your live camera. ' +
          'Press Back to retry.',
          'error',
        );
        showMsg(
          'Anti-spoof: no natural camera movement detected.',
          'error',
        );
        return;
      }
    } else {
      _staleCount = 0;
    }

    // Start challenge clock on first face
    if (!_firstFaceSeen) {
      _firstFaceSeen = true;
      setStatus('Face detected — complete the gesture', 'ready');
      startChallengeClock();
      return;
    }

    setStatus('Face detected — complete the gesture', 'ready');
    const ch = CHALLENGES[_challengeId];
    if (!ch || !_challengeState) return;
    if (!ch.update(_challengeState, lm)) return;

    // Gesture confirmed 
    _challengeLocked = true;
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);
    cancelAnimationFrame(animFrame);
    _livenessOK = true;

    const canvas  = document.createElement('canvas');
    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    _capturedFrame = canvas.toDataURL('image/jpeg', 0.85);

    dot1?.classList.remove('active');
    dot1?.classList.add('done');
    dot2?.classList.add('done');
    setInstr(`✓ ${ch.label} confirmed! Click Verify & Login.`, 'success');
    setStatus('Liveness confirmed', 'ready');
    instructEl?.classList.add('success');
    if (loginSubmit) loginSubmit.disabled = false;

    dbg(
      `Challenge ${_challengeId} PASSED. ` +
      `motion=${_motionScore.toFixed(2)} frame=${_capturedFrame.length}`,
    );
  }

  function computeMotionScore() {
    _offCtx.drawImage(video, 0, 0, 64, 48);
    const curr = _offCtx.getImageData(0, 0, 64, 48).data;
    let score = MOTION_FLOOR + 1;
    if (_prevFrameData) {
      let diff = 0;
      for (let i = 0; i < curr.length; i += 4)
        diff += Math.abs(curr[i] - _prevFrameData[i]);
      score = diff / (64 * 48);
    }
    _prevFrameData = new Uint8ClampedArray(curr);
    return score;
  }

  function stopCamera() {
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);
    cancelAnimationFrame(animFrame);
    if (cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
      cameraStream = null;
    }
    faceMesh         = null;
    _livenessOK      = false;
    _challengeLocked = false;
    _prevFrameData   = null;
    _staleCount      = 0;
    _firstFaceSeen   = false;
  }

  /*  Submit: face verify */
  loginSubmit?.addEventListener('click', async () => {
    if (!_livenessOK || !_capturedFrame) {
      setInstr('Please complete the liveness challenge first.', 'error');
      return;
    }
    if (_step2StartedAt && (Date.now() - _step2StartedAt) > SESSION_EXPIRE_MS) {
      showMsg('Session expired. Please log in again.', 'error');
      setTimeout(() => { window.location.href = '/login/'; }, 2000);
      return;
    }

    stopCamera();
    clearSessionTimers();
    setButtonLoading(loginSubmit, '<span class="spinner"></span> Verifying face…');

    try {
      const resp = await fetch('/face-verify/api/', {
        method:  'POST',
        headers: {
          'Content-Type':     'application/json',
          'X-CSRFToken':      getCsrf(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
          frame:              _capturedFrame,
          liveness_confirmed: true,
          motion_score:       _motionScore,
        }),
      });

      const data = await resp.json();
      dbg(`face-verify ${resp.status} → ${JSON.stringify(data)}`);

      if (data.success && data.redirect) {
        setInstr('✓ Face matched! Redirecting…', 'success');
        setStatus('Verified', 'ready');
        setTimeout(() => { window.location.href = data.redirect; }, 700);
        return;
      }
      if (resp.status === 401) {
        showMsg(data.error || 'Session expired. Please log in again.', 'error');
        setTimeout(() => { window.location.href = '/login/'; }, 2500);
        return;
      }
      if (resp.status === 403) {
        setInstr('🔒 ' + (data.error || 'Account blocked.'), 'error');
        setStatus('Blocked', 'error');
        showMsg(data.error || 'Account blocked. Contact admin.', 'error');
        resetBtn(
          loginSubmit,
          '<i class="fa-solid fa-right-to-bracket"></i> Verify &amp; Login',
        );
        loginSubmit.disabled = true;
        return;
      }

      // Mismatch — allow retry
      const errMsg =
        data.error || 'Face not recognised. Try again with better lighting.';
      setInstr('✗ ' + errMsg, 'error');
      setStatus('Verification failed', 'error');
      showMsg(errMsg, 'error');
      resetBtn(
        loginSubmit,
        '<i class="fa-solid fa-right-to-bracket"></i> Verify &amp; Login',
      );

      _capturedFrame   = '';
      _livenessOK      = false;
      _motionScore     = 999;
      _challengeState  = null;
      _challengeLocked = false;
      _firstFaceSeen   = false;
      startSessionTimers();
      setTimeout(() => startCamera(), 2000);

    } catch (_) {
      setInstr('Network error. Check your connection.', 'error');
      resetBtn(
        loginSubmit,
        '<i class="fa-solid fa-right-to-bracket"></i> Verify &amp; Login',
      );
    }
  });

  /*  Step 1 validation */
  function validateStep1() {
    clearErrors();
    let ok = true;
    const sid = document.getElementById('student_id');
    if (!sid?.value || !/^ISL-\d{4}$/.test(sid.value.trim())) {
      markErr('student_id', 'Format: ISL-XXXX (e.g. ISL-1234)');
      ok = false;
    } else {
      markOk(sid);
    }
    const pw = document.getElementById('password');
    if (!pw?.value || pw.value.length < 6) {
      markErr('password', 'Enter your password.');
      ok = false;
    } else {
      markOk(pw);
    }
    if (!ok) {
      const first = document.querySelector('.form-control.invalid');
      if (first) {
        first.focus();
        first.classList.add('shake');
        first.addEventListener(
          'animationend',
          () => first.classList.remove('shake'),
          { once: true },
        );
      }
    }
    return ok;
  }

  function markErr(id, msg) {
    const el = document.getElementById(id);
    const e  = document.getElementById('err-' + id);
    el?.classList.add('invalid');
    el?.classList.remove('valid');
    if (e) e.textContent = msg;
  }
  function markOk(el) {
    el.classList.remove('invalid');
    el.classList.add('valid');
  }
  function clearErrors() {
    document.querySelectorAll('.field-error').forEach(e => (e.textContent = ''));
    document.querySelectorAll('.form-control').forEach(e =>
      e.classList.remove('invalid', 'valid'),
    );
  }

  ['student_id', 'password'].forEach(id => {
    document.getElementById(id)?.addEventListener('input', () => {
      const el = document.getElementById(id);
      if (el?.classList.contains('invalid')) {
        el.classList.remove('invalid');
        const e = document.getElementById('err-' + id);
        if (e) e.textContent = '';
      }
    });
  });

  const togBtn  = document.getElementById('togglePw');
  const togIcon = document.getElementById('togglePwIcon');
  const pwEl    = document.getElementById('password');
  togBtn?.addEventListener('click', () => {
    const h       = pwEl.type === 'password';
    pwEl.type     = h ? 'text' : 'password';
    togIcon.className = h ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  });

  /*  Helpers  */
  function setStatus(text, state) {
    if (!statusText || !statusWrap) return;
    statusText.textContent = text;
    statusWrap.className   = 'webcam-status' + (state ? ' ' + state : '');
  }
  function setInstr(text, state) {
    if (!instructTxt || !instructEl) return;
    instructTxt.textContent = text;
    instructEl.className    = 'liveness-instruction' + (state ? ' ' + state : '');
  }
  function setButtonLoading(btn, html) {
    if (btn) { btn.disabled = true;  btn.innerHTML = html; }
  }
  function resetBtn(btn, html) {
    if (btn) { btn.disabled = false; btn.innerHTML = html; }
  }
  function showMsg(msg, type) {
    if (!msgBox) return;
    const icons = {
      success: 'fa-circle-check',
      warning: 'fa-triangle-exclamation',
      error:   'fa-circle-xmark',
    };
    msgBox.style.display = '';
    msgBox.innerHTML = `<div class="alert alert-${type}">
      <i class="fa-solid ${icons[type] || icons.error}"></i> ${msg}</div>`;
    msgBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function clearMsg() {
    if (!msgBox) return;
    msgBox.style.display = 'none';
    msgBox.innerHTML = '';
  }

  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
    .shake{animation:shake .4s ease both}
    .spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:_sp .7s linear infinite;vertical-align:middle}
    @keyframes _sp{to{transform:rotate(360deg)}}
    .liveness-instruction.success{color:var(--clr-green,#2dce89)!important}
    .liveness-instruction.error  {color:var(--clr-red,#ff4d6d)!important}
    .capture-dot.done  {background:var(--clr-gold,#f0b429)!important;box-shadow:0 0 8px rgba(240,180,41,.6)}
    .capture-dot.active{background:#3b82f6!important;animation:dot-pulse 1s ease-in-out infinite}
    @keyframes dot-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.3);opacity:.7}}
  `;
  document.head.appendChild(style);
});