'use strict';

/* 
   MEDIAPIPE LOADER
    */
const MP_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/';

async function loadFaceMesh() {
  return new Promise((resolve, reject) => {
    if (typeof window.FaceMesh === 'undefined') {
      reject(new Error('MediaPipe FaceMesh not loaded.'));
      return;
    }
    const fm = new window.FaceMesh({ locateFile: f => `${MP_CDN}${f}` });
    fm.setOptions({
      maxNumFaces: 1, refineLandmarks: true,
      minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
    });
    fm.initialize().then(() => resolve(fm)).catch(reject);
  });
}

/* 
   LANDMARK HELPERS
    */
const L_EYE  = [33, 160, 158, 133, 153, 144];
const R_EYE  = [263, 387, 385, 362, 373, 380];
const NOSE   = 1;
const L_EAR  = 234;
const R_EAR  = 454;

function pd(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

function ear(lm, idx) {
  const p = idx.map(i => lm[i]);
  return (pd(p[1], p[5]) + pd(p[2], p[4])) / (2 * pd(p[0], p[3]) + 1e-6);
}
function avgEar(lm) { return (ear(lm, L_EYE) + ear(lm, R_EYE)) / 2; }

function headRelX(lm) {
  const faceW = pd(lm[L_EAR], lm[R_EAR]) + 1e-6;
  return -((lm[NOSE].x - (lm[L_EAR].x + lm[R_EAR].x) / 2) / faceW);
}

/* 
   THRESHOLDS
  */
const EAR_OPEN_THRESH     = 0.27;
const EAR_CLOSED_THRESH   = 0.24;
const NEUTRAL_BAND        = 0.04;
const TURN_THRESH         = 0.06;
const TURN_CONFIRM_FRAMES = 3;

const CHALLENGE_MS = 3000; // 3 seconds per challenge

/*
   CHALLENGE CATALOGUE look_up intentionally absent
   */
const CATALOGUE = {
  blink: {
    icon:        'fa-eye',
    label:       'Blink both eyes',
    usePreFrame: true,
    createState() { return { phase: 'waiting_open', closedFrames: 0 }; },
    update(s, lm) {
      const e = avgEar(lm);
      if (s.phase === 'waiting_open') {
        if (e >= EAR_OPEN_THRESH) s.phase = 'waiting_blink';
        return false;
      }
      if (e < EAR_CLOSED_THRESH) {
        s.closedFrames++;
        if (s.closedFrames >= 1) return true;
      } else {
        s.closedFrames = 0;
      }
      return false;
    },
  },
  turn_left: {
    icon:        'fa-arrow-left',
    label:       'Turn head LEFT and hold',
    usePreFrame: false,
    createState() { return { phase: 'waiting_neutral', turnFrames: 0 }; },
    update(s, lm) {
      const rx = headRelX(lm);
      if (s.phase === 'waiting_neutral') {
        if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn';
        return false;
      }
      if (rx < -TURN_THRESH) {
        s.turnFrames++;
        if (s.turnFrames >= TURN_CONFIRM_FRAMES) return true;
      } else {
        s.turnFrames = 0;
      }
      return false;
    },
  },
  turn_right: {
    icon:        'fa-arrow-right',
    label:       'Turn head RIGHT and hold',
    usePreFrame: false,
    createState() { return { phase: 'waiting_neutral', turnFrames: 0 }; },
    update(s, lm) {
      const rx = headRelX(lm);
      if (s.phase === 'waiting_neutral') {
        if (Math.abs(rx) <= NEUTRAL_BAND) s.phase = 'waiting_turn';
        return false;
      }
      if (rx > TURN_THRESH) {
        s.turnFrames++;
        if (s.turnFrames >= TURN_CONFIRM_FRAMES) return true;
      } else {
        s.turnFrames = 0;
      }
      return false;
    },
  },
};


const POOL = Object.keys(CATALOGUE); // ['blink', 'turn_left', 'turn_right']

/* 
   MODULE-LEVEL STATE
   */
let _capturedFrames    = {};   
let _challenges        = [];   
let _allDone           = false;
let _pendingFrame      = '';
let _challengeLocked   = false;
let _challengeState    = null;
let _firstFaceDetected = false;
let video;

function dbg(msg) { console.log(`[register.js v14] ${msg}`); }

function captureFromVideo() {
  const c = document.createElement('canvas');
  c.width  = video.videoWidth  || 640;
  c.height = video.videoHeight || 480;
  c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.80);
}

function captureFromResults(results) {
  try {
    if (results.image) {
      const c = document.createElement('canvas');
      c.width  = results.image.width  || video.videoWidth  || 640;
      c.height = results.image.height || video.videoHeight || 480;
      c.getContext('2d').drawImage(results.image, 0, 0, c.width, c.height);
      return c.toDataURL('image/jpeg', 0.80);
    }
  } catch (_) {}
  return captureFromVideo();
}

/* 
   MAIN
    */
document.addEventListener('DOMContentLoaded', () => {

  const form        = document.getElementById('registrationForm');
  const steps       = document.querySelectorAll('.form-step');
  const asideSteps  = document.querySelectorAll('.aside-step');
  const connectors  = document.querySelectorAll('.aside-step-connector');
  const progressBar = document.getElementById('progressBar');

  video             = document.getElementById('webcam');
  const statusWrap  = document.getElementById('webcamStatus');
  const statusText  = document.getElementById('webcamStatusText');
  const instructEl  = document.getElementById('livenessInstruction');
  const instructTxt = document.getElementById('instructionText');
  const step2Next   = document.getElementById('step2Next');
  const dots        = ['dot1', 'dot2', 'dot3'].map(id => document.getElementById(id));
  const submitBtn   = document.getElementById('submitBtn');
  const msgBox      = document.getElementById('jsMessages');

  let currentStep       = 1;
  const TOTAL           = steps.length;
  let stream            = null;
  let faceMesh          = null;
  let animFrame         = null;
  let challengeIdx      = 0;
  let challengeTimer    = null;
  let countdownInterval = null;

  /* Step navigation  */
  function showStep(n) {
    steps.forEach((s, i) => s.classList.toggle('active', i + 1 === n));
    asideSteps.forEach((s, i) => {
      s.classList.remove('active', 'completed');
      if (i + 1 === n) s.classList.add('active');
      if (i + 1 < n)  s.classList.add('completed');
    });
    connectors.forEach((c, i) => c.classList.toggle('filled', i + 1 < n));
    if (progressBar) progressBar.style.width = `${(n / TOTAL) * 100}%`;
    currentStep = n;
    document.querySelector('.register-main')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* Next buttons  */
  document.querySelectorAll('.next-step').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = parseInt(btn.dataset.next);
      if (currentStep === 1 && !validateStep1()) return;
      if (currentStep === 2) {
        if (!_allDone) {
          setInstruction('Complete all 3 liveness challenges first.', 'error');
          return;
        }
        stopCamera();
      }
      if (next === 3) populateReview();
      showStep(next);
    });
  });

  /* Prev buttons  */
  document.querySelectorAll('.prev-step').forEach(btn => {
    btn.addEventListener('click', () => {
      const prev = parseInt(btn.dataset.prev);
      if (currentStep === 2) { stopCamera(); resetLiveness(); }
      showStep(prev);
    });
  });

  /*  Watch step 2 becoming active  */
  const obs = new MutationObserver(() => {
    const step2 = document.getElementById('step2');
    if (step2?.classList.contains('active') && !stream) {
      dbg('step2 active → startLiveness');
      startLiveness();
    }
  });
  steps.forEach(s => obs.observe(s, { attributes: true, attributeFilter: ['class'] }));

  /* 
     LIVENESS FLOW
      */
  async function startLiveness() {
    resetLiveness();
    setStatus('Requesting camera…', '');
    setInstruction('Allow camera access to continue.', '');

    // Fetch 3 challenges from server (all 3 gestures, random order)
    try {
      const res  = await fetch('/api/liveness-challenges/');
      const data = await res.json();
      const known = (data.challenges || []).filter(c => c in CATALOGUE);
      _challenges = known.slice(0, 3);
      dbg(`Challenges from server: ${data.challenges} → using: ${_challenges}`);
    } catch (_) {
      _challenges = [];
    }

    // Client-side fallback — ensure all 3 pool entries are present
    if (_challenges.length < 3) {
      const shuffled  = [...POOL].sort(() => Math.random() - 0.5);
      const existing  = new Set(_challenges);
      for (const ch of shuffled) {
        if (!existing.has(ch)) { _challenges.push(ch); existing.add(ch); }
        if (_challenges.length === 3) break;
      }
      dbg(`Padded to 3 with local fallback: ${_challenges}`);
    }

    // Open camera
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      setStatus('Camera active', 'ready');
    } catch {
      setStatus('Camera denied', 'error');
      setInstruction(
        'Enable camera in browser settings, then go Back and try again.',
        'error',
      );
      return;
    }

    // Load FaceMesh
    setInstruction('Loading face detection…', '');
    try {
      faceMesh = await loadFaceMesh();
      faceMesh.onResults(onResults);
      dbg('FaceMesh ready');
    } catch (e) {
      setInstruction(
        'Face detection failed to load. Check your internet connection.',
        'error',
      );
      console.error(e);
      return;
    }

    setInstruction('Look at the camera — detecting your face…', '');
    runLoop();
  }

  /* Begin one challenge  */
  function beginChallenge(idx) {
    _challengeLocked = false;
    challengeIdx     = idx;

    const chId = _challenges[idx];
    const ch   = CATALOGUE[chId];
    if (!ch) { failedAll('Unknown challenge.'); return; }

    _challengeState = ch.createState();
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);

    const icon = instructEl?.querySelector('i');
    if (icon) icon.className = `fa-solid ${ch.icon}`;

    let secs = Math.ceil(CHALLENGE_MS / 1000);
    setInstruction(`${ch.label} (${secs}s)`, '');
    instructEl?.classList.remove('success', 'error');

    countdownInterval = setInterval(() => {
      secs--;
      if (secs > 0) setInstruction(`${ch.label} (${secs}s)`, '');
      else clearInterval(countdownInterval);
    }, 1000);

    challengeTimer = setTimeout(() => {
      clearInterval(countdownInterval);
      dbg(`Challenge ${chId} TIMED OUT`);
      failedAll(
        `"${ch.label}" timed out — registration blocked. ` +
        'Go Back and try again.',
      );
    }, CHALLENGE_MS);
  }

  /*  Animation loop */
  function runLoop() {
    if (!stream || !faceMesh) return;
    animFrame = requestAnimationFrame(async () => {
      if (!stream) return;
      try {
        if (video.readyState < 2) { if (!_allDone) runLoop(); return; }
        const ch = CATALOGUE[_challenges[challengeIdx]];
        if (ch?.usePreFrame) _pendingFrame = captureFromVideo();
        await faceMesh.send({ image: video });
      } catch (_) {}
      if (!_allDone) runLoop();
    });
  }

  /*  MediaPipe result callback */
  function onResults(results) {
    if (_allDone || _challengeLocked || challengeIdx >= _challenges.length) return;

    const lm = results.multiFaceLandmarks?.[0];
    if (!lm) { setStatus('No face detected — move closer', ''); return; }
    setStatus(`Challenge ${challengeIdx + 1} of 3 — face detected`, 'ready');

    // Start first challenge on first face detection
    if (!_firstFaceDetected) {
      _firstFaceDetected = true;
      dbg('First face detected → starting challenge 0');
      beginChallenge(0);
      return;
    }

    if (!_challengeState) return;

    const chId = _challenges[challengeIdx];
    const ch   = CATALOGUE[chId];
    if (!ch) return;

    if (!ch.update(_challengeState, lm)) return;

    // Challenge PASSED 
    _challengeLocked = true;
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);

    const frame = ch.usePreFrame ? _pendingFrame : captureFromResults(results);
    _capturedFrames[challengeIdx] = frame;
    _pendingFrame = '';

    if (dots[challengeIdx]) dots[challengeIdx].classList.add('done');
    setInstruction(`✓ ${ch.label} confirmed!`, 'success');
    instructEl?.classList.remove('error');
    instructEl?.classList.add('success');
    dbg(`Challenge ${chId} PASSED (idx=${challengeIdx})`);

    const nextIdx = challengeIdx + 1;
    if (nextIdx < _challenges.length) {
      setTimeout(() => {
        instructEl?.classList.remove('success');
        beginChallenge(nextIdx);
      }, 600);
    } else {
      _allDone = true;
      cancelAnimationFrame(animFrame);
      animFrame = null;
      setStatus('All 3 challenges passed!', 'ready');
      setInstruction('✓ All liveness checks passed! Click Continue.', 'success');
      if (step2Next) step2Next.disabled = false;
      dbg('All 3 challenges PASSED');
    }
  }

  /* Failure handler  */
  function failedAll(reason) {
    cancelAnimationFrame(animFrame);
    animFrame = null;
    stopCamera();
    _allDone         = false;
    _capturedFrames  = {};
    _pendingFrame    = '';
    _challengeLocked = false;
    _challengeState  = null;
    if (step2Next) step2Next.disabled = true;
    dots.forEach(d => d?.classList.remove('done'));
    setStatus('Verification failed', 'error');
    setInstruction(`✗ ${reason}`, 'error');
    instructEl?.classList.remove('success');
    instructEl?.classList.add('error');
    for (let i = 0; i < 3; i++) {
      const el = document.getElementById(`face_data_challenge_${i}`);
      if (el) el.value = '';
    }
    showMsg(`Registration blocked: ${reason}`, 'error');
  }

  function stopCamera() {
    clearTimeout(challengeTimer);
    clearInterval(countdownInterval);
    cancelAnimationFrame(animFrame);
    animFrame = null;
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    faceMesh      = null;
    _pendingFrame = '';
  }

  function resetLiveness() {
    stopCamera();
    _capturedFrames    = {};
    _challenges        = [];
    _allDone           = false;
    _pendingFrame      = '';
    _challengeLocked   = false;
    _challengeState    = null;
    _firstFaceDetected = false;
    challengeIdx       = 0;
    if (step2Next) step2Next.disabled = true;
    dots.forEach(d => d?.classList.remove('done'));
    instructEl?.classList.remove('success', 'error');
    for (let i = 0; i < 3; i++) {
      const el = document.getElementById(`face_data_challenge_${i}`);
      if (el) el.value = '';
    }
  }

  /* 
     SUBMIT
      */
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    dbg(`submit: allDone=${_allDone} frames=${Object.keys(_capturedFrames).length}`);

    if (!document.getElementById('agreeTerms')?.checked) {
      showFieldError('terms', 'You must agree to the Terms & Conditions.');
      return;
    }
    if (
      !_allDone ||
      !_capturedFrames[0] ||
      !_capturedFrames[1] ||
      !_capturedFrames[2]
    ) {
      showMsg(
        'Please complete all 3 liveness challenges before submitting.',
        'error',
      );
      return;
    }

    // Write frames into hidden inputs
    for (let i = 0; i < 3; i++) {
      const el = document.getElementById(`face_data_challenge_${i}`);
      if (el) el.value = _capturedFrames[i];
    }

    if (submitBtn) {
      submitBtn.disabled  = true;
      submitBtn.innerHTML = '<span class="spinner"></span> Submitting…';
    }

    try {
      const resp = await fetch(form.action || window.location.pathname, {
        method:  'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body:    new FormData(form),
      });
      const data = await resp.json();
      dbg(`server → ${JSON.stringify(data)}`);

      if (data.success) {
        showMsg(data.message || 'Registration successful!', 'success');
        setTimeout(() => {
          window.location.href = data.redirect || '/login/';
        }, 2500);
      } else {
        showMsg(data.error || 'Registration failed. Please try again.', 'error');
        if (submitBtn) {
          submitBtn.disabled  = false;
          submitBtn.innerHTML =
            '<i class="fa-solid fa-paper-plane"></i> Submit Registration';
        }
      }
    } catch (err) {
      showMsg(
        'Network error. Please check your connection and try again.',
        'error',
      );
      if (submitBtn) {
        submitBtn.disabled  = false;
        submitBtn.innerHTML =
          '<i class="fa-solid fa-paper-plane"></i> Submit Registration';
      }
    }
  });

  /* 
     VALIDATION
      */
  function validateStep1() {
    clearAllErrors();
    let ok = true;

    if (!val('full_name') || val('full_name').trim().length < 3)
      ok = showFieldError('full_name', 'Full name must be at least 3 characters.') && false;
    if (!val('student_id') || !/^ISL-\d{4}$/.test(val('student_id').trim()))
      ok = showFieldError('student_id', 'Must match format ISL-XXXX (e.g. ISL-1234).') && false;
    if (!val('department'))
      ok = showFieldError('department', 'Please select your department.') && false;
    if (!val('year_of_study'))
      ok = showFieldError('year_of_study', 'Please select your year of study.') && false;

    const ageRaw = document.getElementById('age')?.value?.trim();
    if (!ageRaw) {
      ok = showFieldError('age', 'Age is required.') && false;
    } else {
      const ageNum = parseInt(ageRaw, 10);
      if (isNaN(ageNum) || ageNum < 18 || ageNum > 35)
        ok = showFieldError('age', 'Age must be a whole number between 18 and 35.') && false;
    }

    if (!document.getElementById('gender')?.value?.trim())
      ok = showFieldError('gender', 'Please select your gender.') && false;
    if (!val('password') || val('password').length < 8)
      ok = showFieldError('password', 'Password must be at least 8 characters.') && false;

    if (!ok) {
      const first = form?.querySelector('.form-control.invalid');
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

  /* 
     REVIEW PANEL
   */
  function populateReview() {
    const box = document.getElementById('reviewInfo');
    if (!box) return;
    const gLabel  = { male: 'Male', female: 'Female' };
    const ageVal  = document.getElementById('age')?.value?.trim() || '';
    const genVal  = document.getElementById('gender')?.value?.trim() || '';
    const fields  = [
      { label: 'Full Name',  id: 'full_name'     },
      { label: 'Student ID', id: 'student_id'    },
      { label: 'Department', id: 'department'    },
      { label: 'Year',       id: 'year_of_study' },
      { label: 'Phone',      id: 'phone'         },
      { label: 'Age',        id: null, value: ageVal || '—' },
      {
        label: 'Gender',
        id:    null,
        value: gLabel[genVal] || genVal || '—',
      },
      {
        label:    'Liveness',
        id:       null,
        value:    _allDone
          ? '✓ All 3 challenges passed'
          : '✗ Not completed',
        verified: _allDone,
      },
    ];
    box.innerHTML = fields
      .map(f => {
        const v = f.id
          ? document.getElementById(f.id)?.value || '—'
          : f.value;
        return `<div class="review-item">
          <span class="review-label">${f.label}</span>
          <span class="review-value${f.verified ? ' verified' : ''}">${v || '—'}</span>
        </div>`;
      })
      .join('');
  }

  /* 
     PASSWORD STRENGTH
      */
  const pwInput      = document.getElementById('password');
  const pwFill       = document.getElementById('pwStrengthFill');
  const pwLabel      = document.getElementById('pwStrengthLabel');
  const togglePwBtn  = document.getElementById('togglePw');
  const togglePwIcon = document.getElementById('togglePwIcon');

  pwInput?.addEventListener('input', () => {
    const levels = [
      { label: 'Too weak', pct: 20,  color: '#ff4d6d' },
      { label: 'Weak',     pct: 35,  color: '#ff8c42' },
      { label: 'Fair',     pct: 58,  color: '#f0b429' },
      { label: 'Good',     pct: 78,  color: '#5bc0de' },
      { label: 'Strong',   pct: 100, color: '#2dce89' },
    ];
    const score = Math.min(pwScore(pwInput.value), 4);
    if (pwFill)  pwFill.style.width = levels[score].pct + '%';
    if (pwLabel) {
      pwLabel.textContent = levels[score].label;
      pwLabel.style.color = levels[score].color;
    }
  });

  function pwScore(pw) {
    let s = 0;
    if (!pw) return 0;
    if (pw.length >= 8)  s++;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return Math.min(s, 4);
  }

  togglePwBtn?.addEventListener('click', () => {
    const h = pwInput.type === 'password';
    pwInput.type           = h ? 'text' : 'password';
    togglePwIcon.className = h ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  });

  /* utilities */
  function val(id) { return document.getElementById(id)?.value || ''; }

  function showFieldError(id, msg) {
    const errEl = document.getElementById('err-' + id);
    const input = document.getElementById(id);
    if (errEl) errEl.textContent = msg;
    if (input) { input.classList.add('invalid'); input.classList.remove('valid'); }
    return false;
  }
  function clearAllErrors() {
    document.querySelectorAll('.field-error').forEach(e => (e.textContent = ''));
    document.querySelectorAll('.form-control').forEach(e =>
      e.classList.remove('invalid'),
    );
  }
  function setStatus(text, state) {
    if (!statusText || !statusWrap) return;
    statusText.textContent = text;
    statusWrap.className   = 'webcam-status' + (state ? ' ' + state : '');
  }
  function setInstruction(text, state) {
    if (!instructTxt || !instructEl) return;
    instructTxt.textContent = text;
    instructEl.className    = 'liveness-instruction' + (state ? ' ' + state : '');
  }
  function showMsg(msg, type) {
    if (!msgBox) return;
    const icon = type === 'success' ? 'fa-circle-check' : 'fa-circle-xmark';
    msgBox.innerHTML = `<div class="alert alert-${type}">
      <i class="fa-solid ${icon}"></i> ${msg}</div>`;
    msgBox.scrollIntoView({ behavior: 'smooth' });
  }

  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
    .shake{animation:shake .4s ease both}
    .spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:_sp .7s linear infinite;vertical-align:middle}
    @keyframes _sp{to{transform:rotate(360deg)}}
    .liveness-instruction.success{color:var(--clr-green,#2dce89)!important;border-color:rgba(45,206,137,.3)!important}
    .liveness-instruction.error{color:var(--clr-red,#ff4d6d)!important;border-color:rgba(255,77,109,.3)!important}
    .capture-dot.done{background:var(--clr-gold,#f0b429);box-shadow:0 0 8px rgba(240,180,41,.6)}
    .req{color:var(--clr-red,#ff4d6d);margin-left:2px;font-weight:700;}
  `;
  document.head.appendChild(style);

  showStep(1);
  dbg('loaded ✓');
});