'use strict';

const MP_CDN    = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/';
const LEFT_EYE  = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE = [263, 387, 385, 362, 373, 380];
const NOSE_IDX  = 1;

// Liveness detection thresholds (match liveness.py)
const BLINK_EAR  = 0.22;   // EAR below this = eye closing = blink detected
const MOVE_DELTA = 0.015;  // nose movement above this = head moved

// Module-level — survive DOM transitions
let _capturedFrame = '';
let _livenessOK    = false;

function dbg(msg) { console.log(`[login.js v7] ${msg}`); }


document.addEventListener('DOMContentLoaded', () => {

  // DOM refs — Step 1
  const step1El   = document.getElementById('loginStep1');
  const step1Next = document.getElementById('step1Next');

  // DOM refs — Step 2
  const step2El     = document.getElementById('loginStep2');
  const step2Prev   = document.getElementById('step2Prev');
  const loginSubmit = document.getElementById('loginSubmit');
  const video       = document.getElementById('loginWebcam');
  const statusWrap  = document.getElementById('webcamStatus');
  const statusText  = document.getElementById('webcamStatusText');
  const instructEl  = document.getElementById('livenessInstruction');
  const instructTxt = document.getElementById('instructionText');
  const dot1        = document.getElementById('dot1');
  const dot2        = document.getElementById('dot2');
  const attemptsEl  = document.getElementById('attemptsLeft');

  // Shared
  const progressBar = document.getElementById('progressBar');
  const asideStep1  = document.querySelector('.aside-step[data-step="1"]');
  const asideStep2  = document.querySelector('.aside-step[data-step="2"]');
  const connector   = document.querySelector('.aside-step-connector');
  const msgBox      = document.getElementById('ajaxMessages');

  const getCsrf = () =>
    document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

  // Camera state
  let cameraStream  = null;
  let faceMesh      = null;
  let animFrame     = null;
  let prevNose      = null;
  let livenessTimer = null;

  dbg('loaded ✓');

  /*
     STEP 1 — Password check
  */
  step1Next?.addEventListener('click', async () => {
    if (!validateStep1()) return;
    setButtonLoading(step1Next, '<span class="spinner"></span> Checking…');
    clearMsg();

    const fd = new FormData();
    fd.append('student_id',          sidVal().trim());
    fd.append('password',            pwVal());
    fd.append('csrfmiddlewaretoken', getCsrf());

    try {
      const resp = await fetch('/login/', {
        method:  'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body:    fd,
      });
      const data = await resp.json();
      dbg(`step1 → ${JSON.stringify(data)}`);

      // Admin: password passed, no face step needed → redirect immediately
      if (data.success && !data.require_face && data.redirect) {
        showMsg(data.message || 'Login successful!', 'success');
        setTimeout(() => { window.location.href = data.redirect; }, 600);
        return;
      }

      // Voter: password passed → open face verification step
      if (data.success && data.require_face) {
        resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');
        showStep2();
        return;
      }

      // Failure (wrong password, locked, pending approval, etc.)
      showMsg(data.error || 'Login failed.', data.type || 'error');
      resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');

    } catch {
      showMsg('Network error. Check your connection.', 'error');
      resetBtn(step1Next, 'Continue <i class="fa-solid fa-arrow-right"></i>');
    }
  });

  step2Prev?.addEventListener('click', () => {
    stopCamera();
    hideStep2();
    clearMsg();
  });

  /* 
     STEP VISIBILITY
 */
  function showStep2() {
    step1El?.classList.remove('active');
    step2El.style.display = '';
    step2El.classList.add('active');
    asideStep1?.classList.replace('active', 'completed');
    asideStep2?.classList.add('active');
    connector?.classList.add('filled');
    if (progressBar) progressBar.style.width = '100%';
    document.querySelector('.login-main')?.scrollTo({ top: 0, behavior: 'smooth' });
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

  /*
     CAMERA + LIVENESS
 */
  async function startCamera() {
    _capturedFrame = '';
    _livenessOK    = false;
    prevNose       = null;

    dot1?.classList.remove('done');
    dot2?.classList.remove('done');
    instructEl?.classList.remove('success', 'error');
    if (loginSubmit) loginSubmit.disabled = true;

    setStatus('Requesting camera…', '');
    setInstr('Allow camera access to continue.');

    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      video.srcObject = cameraStream;
      await video.play();
      setStatus('Camera active — look at the camera', 'ready');
    } catch {
      setStatus('Camera access denied', 'error');
      setInstr('Enable camera permissions, then click Back and try again.', 'error');
      return;
    }

    setInstr('Loading face detection…');
    try {
      faceMesh = new window.FaceMesh({ locateFile: f => `${MP_CDN}${f}` });
      faceMesh.setOptions({
        maxNumFaces: 1, refineLandmarks: true,
        minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
      });
      await faceMesh.initialize();
      faceMesh.onResults(onFaceResults);
      dbg('FaceMesh ready');
    } catch {
      setInstr('Face detection failed to load. Check your internet connection.', 'error');
      return;
    }

    setInstr('Blink once or move your head slightly to confirm liveness…');

    // 15-second timeout — if no liveness detected the user must retry
    livenessTimer = setTimeout(() => {
      if (!_livenessOK) {
        setInstr('Timed out. Click Back and try again.', 'error');
        setStatus('Timed out', 'error');
      }
    }, 15000);

    runLoop();
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
    if (_livenessOK) return;
    const lm = results.multiFaceLandmarks?.[0];
    if (!lm) { setStatus('No face detected — move closer', ''); return; }
    setStatus('Face detected', 'ready');

    // Liveness detection: blink (EAR drops) OR head movement (nose shifts)
    const earL  = calcEAR(lm, LEFT_EYE);
    const earR  = calcEAR(lm, RIGHT_EYE);
    const blink = earL < BLINK_EAR || earR < BLINK_EAR;

    const nose  = { x: lm[NOSE_IDX].x, y: lm[NOSE_IDX].y };
    const moved = prevNose
      ? Math.hypot(nose.x - prevNose.x, nose.y - prevNose.y) > MOVE_DELTA
      : false;
    prevNose = nose;

    if (blink || moved) {
      clearTimeout(livenessTimer);
      cancelAnimationFrame(animFrame);
      _livenessOK = true;

      // Wait one extra animation frame so the video element renders the
      // peak-closed eye frame before we snapshot it.
      const doCapture = () => {
        const canvas  = document.createElement('canvas');
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        _capturedFrame = canvas.toDataURL('image/jpeg', 0.85);
        dbg(`Frame captured len=${_capturedFrame.length}`);

        dot1?.classList.add('done');
        dot2?.classList.add('done');
        setInstr(
          `✓ ${blink ? 'Blink' : 'Movement'} confirmed! Click Verify & Login.`,
          'success'
        );
        setStatus('Liveness confirmed', 'ready');
        instructEl?.classList.add('success');
        if (loginSubmit) loginSubmit.disabled = false;
      };

      if (blink) requestAnimationFrame(doCapture);
      else       doCapture();
    }
  }

  // stopCamera does NOT clear capturedFrame intentionally 
  // the frame is needed by the submit handler after the camera stops.
  function stopCamera() {
    clearTimeout(livenessTimer);
    cancelAnimationFrame(animFrame);
    if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
    faceMesh    = null;
    _livenessOK = false;
    prevNose    = null;
    dbg('Camera stopped');
  }

  /* 
     SUBMIT — POST frame to face-verify API
 */
  loginSubmit?.addEventListener('click', async () => {
    dbg(`Submit: livenessOK=${_livenessOK} frameLen=${_capturedFrame.length}`);

    if (!_livenessOK || !_capturedFrame) {
      setInstr('Please complete the liveness check first.', 'error');
      return;
    }

    stopCamera();
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
        }),
      });

      const data = await resp.json();
      dbg(`face-verify ${resp.status} → ${JSON.stringify(data)}`);

      // SUCCESS: same person confirmed
      if (data.success && data.redirect) {
        setInstr('✓ Face matched! Redirecting…', 'success');
        setStatus('Verified', 'ready');
        showMsg(data.message || 'Login successful!', 'success');
        setTimeout(() => { window.location.href = data.redirect; }, 700);
        return;
      }

      //  ACCOUNT BLOCKED (403): 3 face failures 
      if (resp.status === 403) {
        setInstr('🔒 ' + (data.error || 'Account blocked.'), 'error');
        setStatus('Account blocked', 'error');
        showMsg(data.error || 'Account blocked. Contact the administrator.', 'error');
        resetBtn(loginSubmit, '<i class="fa-solid fa-right-to-bracket"></i> Verify & Login');
        loginSubmit.disabled = true;   // can't retry — account is locked
        if (attemptsEl) {
          attemptsEl.textContent = '0 attempts remaining';
          attemptsEl.style.display = '';
        }
        return;
      }

      //  FACE MISMATCH: attempts remaining  restart camera for retry 
      const errMsg = data.error || 'Face not recognised. Try again.';
      setInstr('✗ ' + errMsg, 'error');
      setStatus('Verification failed', 'error');
      showMsg(errMsg, 'error');
      resetBtn(loginSubmit, '<i class="fa-solid fa-right-to-bracket"></i> Verify & Login');

      // Update attempts badge
      const m = errMsg.match(/(\d+) attempt/);
      if (attemptsEl && m) {
        attemptsEl.textContent  = `${m[1]} attempt${m[1] === '1' ? '' : 's'} remaining`;
        attemptsEl.style.display = '';
      }

      // Reset liveness state and restart camera so user can try again
      _capturedFrame = '';
      _livenessOK    = false;
      setTimeout(() => startCamera(), 2000);

    } catch (exc) {
      dbg(`fetch error: ${exc}`);
      setInstr('Network error. Check your connection.', 'error');
      resetBtn(loginSubmit, '<i class="fa-solid fa-right-to-bracket"></i> Verify & Login');
    }
  });

  /* 
     STEP 1 VALIDATION
 */
  function validateStep1() {
    clearErrors();
    let ok = true;

    const sid = document.getElementById('student_id');
    if (!sid?.value || !/^ISL-\d{4}$/.test(sid.value.trim())) {
      markErr('student_id', 'Format: ISL-XXXX (e.g. ISL-1234)');
      ok = false;
    } else markOk(sid);

    const pw = document.getElementById('password');
    if (!pw?.value || pw.value.length < 6) {
      markErr('password', 'Enter your password (min 6 characters).');
      ok = false;
    } else markOk(pw);

    if (!ok) {
      const first = document.querySelector('.form-control.invalid');
      first?.focus();
      first?.classList.add('shake');
      first?.addEventListener('animationend',
        () => first.classList.remove('shake'), { once: true });
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
  function markOk(el) { el.classList.remove('invalid'); el.classList.add('valid'); }
  function clearErrors() {
    document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
    document.querySelectorAll('.form-control').forEach(e => e.classList.remove('invalid', 'valid'));
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

  // Password toggle
  const togBtn  = document.getElementById('togglePw');
  const togIcon = document.getElementById('togglePwIcon');
  const pwEl    = document.getElementById('password');
  togBtn?.addEventListener('click', () => {
    const h = pwEl.type === 'password';
    pwEl.type         = h ? 'text' : 'password';
    togIcon.className = h ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  });

  /* ══════════════════════════════════════════════════════════════════════
     UTILITIES
  ══════════════════════════════════════════════════════════════════════ */
  function sidVal() { return document.getElementById('student_id')?.value || ''; }
  function pwVal()  { return document.getElementById('password')?.value   || ''; }

  function calcEAR(lm, idx) {
    const p   = idx.map(i => lm[i]);
    const num = ptDist(p[1], p[5]) + ptDist(p[2], p[4]);
    return num / (2 * ptDist(p[0], p[3]) + 1e-6);
  }
  function ptDist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

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

  /* Injected styles */
  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}
      40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
    .shake{animation:shake .4s ease both}
    .spinner{display:inline-block;width:14px;height:14px;border:2px solid
      rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;
      animation:_sp .7s linear infinite;vertical-align:middle}
    @keyframes _sp{to{transform:rotate(360deg)}}
    .liveness-instruction.success{color:var(--clr-green,#2dce89)!important}
    .liveness-instruction.error  {color:var(--clr-red,#ff4d6d)!important}
    .capture-dot.done{background:var(--clr-gold,#f0b429)!important;
      box-shadow:0 0 8px rgba(240,180,41,.6)}
    .attempts-badge{display:inline-block;padding:.3rem .8rem;border-radius:6px;
      background:rgba(255,77,109,.15);color:#ff4d6d;font-size:.85rem;
      font-weight:600;margin-bottom:.75rem}
  `;
  document.head.appendChild(style);

  dbg('DOMContentLoaded done ✓');
});