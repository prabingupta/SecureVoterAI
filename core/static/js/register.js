'use strict';

const MP_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/';

// MediaPipe landmark indices (match liveness.py)
const LEFT_EYE_IDX  = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE_IDX = [263, 387, 385, 362, 373, 380];
const NOSE_TIP_IDX  = 1;
const L_EAR_IDX     = 234;
const R_EAR_IDX     = 454;
const MOUTH_LEFT    = 61;
const MOUTH_RIGHT   = 291;

// Detection thresholds (must match liveness.py)
const BLINK_EAR        = 0.22;   
const TURN_DELTA       = 0.04;   
const SMILE_MAR        = 0.35;   

// Challenge metadata — label + icon for each gesture key
const CHALLENGE_META = {
  blink:      { label: 'Blink your eyes',  icon: 'fa-eye'        },
  turn_left:  { label: 'Turn head LEFT',   icon: 'fa-arrow-left' },
  turn_right: { label: 'Turn head RIGHT',  icon: 'fa-arrow-right'},
  smile:      { label: 'Smile',            icon: 'fa-face-smile' },
};

const STAGE_TIMEOUT_MS = 4000;   // 4 seconds per stage (smile needs a bit more)

// Module-level state
let _stages  = [];           // filled by fetchChallenges() e.g. ['blink','smile','turn_right']
let _frames  = ['', '', '']; // captured JPEG data URLs indexed by stage position
let _allDone = false;

function dbg(msg) { console.log(`[register.js v8] ${msg}`); }


document.addEventListener('DOMContentLoaded', () => {

  const form        = document.getElementById('registrationForm');
  const steps       = document.querySelectorAll('.form-step');
  const asideSteps  = document.querySelectorAll('.aside-step');
  const connectors  = document.querySelectorAll('.aside-step-connector');
  const progressBar = document.getElementById('progressBar');

  const video       = document.getElementById('webcam');
  const statusWrap  = document.getElementById('webcamStatus');
  const statusText  = document.getElementById('webcamStatusText');
  const instructEl  = document.getElementById('livenessInstruction');
  const instructTxt = document.getElementById('instructionText');
  const countdownEl = document.getElementById('livenessCountdown');

  const dots = [1, 2, 3].map(n => document.getElementById('dot' + n));

  // Hidden inputs — now generic: challenge_0, challenge_1, challenge_2
  // Make sure your register.html has these 3 hidden inputs with these IDs.
  const fb0 = document.getElementById('face_data_challenge_0');
  const fb1 = document.getElementById('face_data_challenge_1');
  const fb2 = document.getElementById('face_data_challenge_2');

  const step2NextBtn = document.getElementById('step2Next');
  const submitBtn    = document.getElementById('submitBtn');
  const msgBox       = document.getElementById('jsMessages');

  let currentStep = 1;
  const TOTAL     = steps.length;

  // Camera / MediaPipe state
  let stream       = null;
  let faceMesh     = null;
  let animFrame    = null;
  let stageIndex   = 0;
  let stageTimerID = null;
  let countdownID  = null;
  let secsLeft     = 4;
  let stageActive  = false;

  const getCsrf = () =>
    document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

  /*  Step navigation */
  function showStep(n) {
    steps.forEach((s, i) => s.classList.toggle('active', i + 1 === n));
    asideSteps.forEach((s, i) => {
      s.classList.remove('active', 'completed');
      if (i + 1 === n) s.classList.add('active');
      if (i + 1 < n)   s.classList.add('completed');
    });
    connectors.forEach((c, i) => c.classList.toggle('filled', i + 1 < n));
    if (progressBar) progressBar.style.width = `${(n / TOTAL) * 100}%`;
    currentStep = n;
    document.querySelector('.register-main')
      ?.scrollTo({ top: 0, behavior: 'smooth' });
    dbg(`showStep(${n})`);
  }

  /*  Next buttons  */
  document.querySelectorAll('.next-step').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = parseInt(btn.dataset.next);
      if (currentStep === 1 && !validateStep1()) return;
      if (currentStep === 2) {
        if (!_allDone) {
          setInstr('Complete all 3 liveness stages first.', 'error');
          return;
        }
        stopCamera();
      }
      if (next === 3) populateReview();
      showStep(next);
    });
  });

  /*  Prev buttons  */
  document.querySelectorAll('.prev-step').forEach(btn => {
    btn.addEventListener('click', () => {
      const prev = parseInt(btn.dataset.prev);
      if (currentStep === 2) {
        stopCamera();
        resetLivenessUI();
        _frames  = ['', '', ''];
        _stages  = [];
        _allDone = false;
        dbg('Frames + stages cleared on Back');
      }
      showStep(prev);
    });
  });

  /*  Start liveness when step 2 becomes active */
  const obs = new MutationObserver(() => {
    const step2 = document.getElementById('step2');
    if (step2?.classList.contains('active') && !stream && !_allDone) {
      startLiveness();
    }
  });
  steps.forEach(s => obs.observe(s, { attributes: true, attributeFilter: ['class'] }));

  /* 
     FETCH CHALLENGES FROM BACKEND
  */
  async function fetchChallenges() {
    try {
      const resp = await fetch('/api/liveness-challenges/', {
        method:  'GET',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await resp.json();
      if (data.challenges && data.challenges.length === 3) {
        _stages = data.challenges;
        dbg(`Challenges fetched: ${_stages.join(', ')}`);
        updateStageBadges();
        return true;
      }
    } catch (e) {
      dbg(`fetchChallenges error: ${e}`);
    }
    // Fallback to default order if API fails
    _stages = ['blink', 'turn_left', 'turn_right'];
    dbg('Using fallback challenges');
    updateStageBadges();
    return false;
  }

  /**
   * Overwrites the 3 stage badge elements in the HTML with the correct
   * icon + label for whichever random challenges were assigned this session.
   * Called immediately after fetchChallenges() resolves.
   */
  function updateStageBadges() {
    _stages.forEach((key, i) => {
      const badge = document.getElementById(`stageBadge${i + 1}`);
      if (!badge) return;
      const meta = CHALLENGE_META[key] || { label: key, icon: 'fa-circle' };
      badge.innerHTML = `
        <i class="fa-solid ${meta.icon}"></i>
        <span>${meta.label}</span>
      `;
      // Also update the dot tooltip so it matches the actual challenge
      const dot = dots[i];
      if (dot) dot.title = meta.label;
    });
  }

  /* 
     LIVENESS ENGINE
   */
  async function startLiveness() {
    stageIndex  = 0;
    stageActive = false;
    _allDone    = false;
    _frames     = ['', '', ''];
    resetLivenessUI();
    if (step2NextBtn) step2NextBtn.disabled = true;

    // 1. Fetch random challenges from backend
    setInstr('Preparing liveness challenges…');
    await fetchChallenges();

    // 2. Open camera
    setStatus('Requesting camera…', '');
    setInstr('Allow camera access to continue.');
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
      setInstr('Enable camera in browser settings, then go Back and try again.', 'error');
      return;
    }

    // 3. Load MediaPipe
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
      setInstr('Face detection failed. Check your internet connection.', 'error');
      return;
    }

    // 4. Brief pause then start stage 0
    setInstr('Look straight at the camera…');
    await sleep(800);
    beginStage(0);
    runLoop();
  }

  function beginStage(idx) {
    stageIndex  = idx;
    stageActive = true;
    secsLeft    = Math.round(STAGE_TIMEOUT_MS / 1000);

    const key  = _stages[idx];
    const meta = CHALLENGE_META[key] || { label: key, icon: 'fa-circle' };

    setInstr(`<i class="fa-solid ${meta.icon}"></i> ${meta.label} — ${secsLeft}s`);
    setCountdown(secsLeft);
    updateDot(idx, 'active');

    clearInterval(countdownID);
    countdownID = setInterval(() => {
      secsLeft--;
      setCountdown(secsLeft);
      setInstr(`<i class="fa-solid ${meta.icon}"></i> ${meta.label} — ${secsLeft}s`);
      if (secsLeft <= 0) clearInterval(countdownID);
    }, 1000);

    clearTimeout(stageTimerID);
    stageTimerID = setTimeout(() => {
      if (!stageActive) return;
      stageActive = false;
      clearInterval(countdownID);
      onStageTimeout(idx);
    }, STAGE_TIMEOUT_MS);
  }

  function onStageTimeout(idx) {
    cancelAnimationFrame(animFrame);
    updateDot(idx, 'fail');
    setCountdown(null);
    const key  = _stages[idx];
    const meta = CHALLENGE_META[key] || { label: key, icon: 'fa-circle' };
    setInstr(`✗ "${meta.label}" not detected in time. Try again.`, 'error');
    setStatus('Liveness failed', 'error');
    showRetry();
  }

  function onFaceResults(results) {
    if (!stageActive) return;
    const lm = results.multiFaceLandmarks?.[0];
    if (!lm) { setStatus('No face — move closer', ''); return; }
    setStatus('Face detected', 'ready');

    const key = _stages[stageIndex];
    let detected = false;

    if (key === 'blink') {
      detected = calcEAR(lm, LEFT_EYE_IDX) < BLINK_EAR
              || calcEAR(lm, RIGHT_EYE_IDX) < BLINK_EAR;

    } else if (key === 'turn_left' || key === 'turn_right') {
      const nose  = lm[NOSE_TIP_IDX].x;
      const lEar  = lm[L_EAR_IDX].x;
      const rEar  = lm[R_EAR_IDX].x;
      const faceW = Math.abs(rEar - lEar) + 1e-6;
      const relX  = (nose - (lEar + rEar) / 2) / faceW;
      if (key === 'turn_left')  detected = relX < -TURN_DELTA;
      if (key === 'turn_right') detected = relX >  TURN_DELTA;

    } else if (key === 'smile') {
      // MAR = mouth width / face width
      const mLeft  = lm[MOUTH_LEFT].x;
      const mRight = lm[MOUTH_RIGHT].x;
      const fLeft  = lm[L_EAR_IDX].x;
      const fRight = lm[R_EAR_IDX].x;
      const mar = Math.abs(mRight - mLeft) / (Math.abs(fRight - fLeft) + 1e-6);
      detected = mar > SMILE_MAR;
    }

    if (detected) {
      stageActive = false;
      clearTimeout(stageTimerID);
      clearInterval(countdownID);

      const doCapture = () => {
        const canvas  = document.createElement('canvas');
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        _frames[stageIndex] = canvas.toDataURL('image/jpeg', 0.85);
        dbg(`Stage ${stageIndex} (${key}) captured len=${_frames[stageIndex].length}`);

        updateDot(stageIndex, 'done');
        setCountdown(null);

        const next = stageIndex + 1;
        if (next < _stages.length) {
          const meta = CHALLENGE_META[key] || { label: key };
          setInstr(`✓ ${meta.label} confirmed! Get ready…`, 'success');
          setTimeout(() => { if (stream) beginStage(next); }, 700);
        } else {
          _allDone = true;
          cancelAnimationFrame(animFrame);
          setInstr('✓ All liveness checks passed! Click Continue.', 'success');
          setStatus('Liveness verified', 'ready');
          instructEl?.classList.add('success');
          if (step2NextBtn) step2NextBtn.disabled = false;
          dbg('All stages passed ✓');
        }
      };

      // For blink: wait one frame to capture peak-closed eye
      if (key === 'blink') requestAnimationFrame(doCapture);
      else doCapture();
    }
  }

  function runLoop() {
    if (!stream || !faceMesh) return;
    animFrame = requestAnimationFrame(async () => {
      if (!stream) return;
      try { await faceMesh.send({ image: video }); } catch (_) {}
      if (stream && !_allDone) runLoop();
    });
  }

  function stopCamera() {
    clearTimeout(stageTimerID);
    clearInterval(countdownID);
    cancelAnimationFrame(animFrame);
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    faceMesh    = null;
    stageActive = false;
    dbg('Camera stopped');
  }

  /*  Retry button */
  function showRetry() {
    const wrap = document.getElementById('retryWrap');
    if (wrap) wrap.style.display = '';
  }
  function hideRetry() {
    const wrap = document.getElementById('retryWrap');
    if (wrap) wrap.style.display = 'none';
  }
  document.getElementById('retryBtn')?.addEventListener('click', async () => {
    hideRetry();
    stopCamera();
    await sleep(300);
    startLiveness();   // re-fetches a NEW random set of challenges
  });

  /* 
     FORM SUBMIT
*/
  form?.addEventListener('submit', async e => {
    e.preventDefault();
    dbg(`submit: frames[0]=${_frames[0].length} [1]=${_frames[1].length} [2]=${_frames[2].length}`);

    const terms = document.getElementById('agreeTerms');
    if (!terms?.checked) {
      showFieldError('terms', 'You must agree to the Terms & Conditions.');
      return;
    }
    if (!_frames[0] || !_frames[1] || !_frames[2]) {
      showMsg('Face scan incomplete. Go back to step 2 and complete all 3 stages.', 'error');
      return;
    }

    // Write frames into generic hidden inputs RIGHT before FormData snapshot
    if (fb0) fb0.value = _frames[0];
    if (fb1) fb1.value = _frames[1];
    if (fb2) fb2.value = _frames[2];
    dbg(`Hidden inputs written: ${fb0?.value.length} / ${fb1?.value.length} / ${fb2?.value.length}`);

    if (submitBtn) {
      submitBtn.disabled  = true;
      submitBtn.innerHTML = '<span class="spinner"></span> Submitting…';
    }

    try {
      const fd   = new FormData(form);
      const resp = await fetch(form.action || window.location.pathname, {
        method:  'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body:    fd,
      });
      const data = await resp.json();
      dbg(`server → ${JSON.stringify(data)}`);

      if (data.success) {
        showMsg(data.message || 'Registration successful!', 'success');
        setTimeout(() => { window.location.href = data.redirect || '/login/'; }, 2800);
      } else {
        showMsg(data.error || 'Registration failed. Please try again.', 'error');
        if (submitBtn) {
          submitBtn.disabled  = false;
          submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit Registration';
        }
      }
    } catch (exc) {
      dbg(`fetch error: ${exc}`);
      showMsg('Network error. Check your connection and try again.', 'error');
      if (submitBtn) {
        submitBtn.disabled  = false;
        submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit Registration';
      }
    }
  });

  /* 
     STEP 1 VALIDATION
  */
  function validateStep1() {
    clearAllErrors();
    let ok = true;
    const v = id => document.getElementById(id)?.value || '';

    if (v('full_name').trim().length < 3)
      ok = showFieldError('full_name', 'Full name must be at least 3 characters.') && false;
    if (!/^ISL-\d{4}$/.test(v('student_id').trim()))
      ok = showFieldError('student_id', 'Must match format ISL-XXXX (e.g. ISL-1234).') && false;
    if (!v('department'))
      ok = showFieldError('department', 'Please select your department.') && false;
    if (!v('year_of_study'))
      ok = showFieldError('year_of_study', 'Please select your year of study.') && false;
    if (v('password').length < 8)
      ok = showFieldError('password', 'Password must be at least 8 characters.') && false;

    if (!ok) {
      const first = form?.querySelector('.form-control.invalid');
      first?.focus();
      first?.classList.add('shake');
      first?.addEventListener('animationend',
        () => first.classList.remove('shake'), { once: true });
    }
    return ok;
  }

  ['full_name','student_id','department','year_of_study','password'].forEach(id => {
    document.getElementById(id)?.addEventListener('input', () => {
      const el = document.getElementById(id);
      if (el?.classList.contains('invalid')) {
        el.classList.remove('invalid');
        const e = document.getElementById('err-' + id);
        if (e) e.textContent = '';
      }
    });
  });

  /*
     REVIEW PANEL
  */
  function populateReview() {
    const box = document.getElementById('reviewInfo');
    if (!box) return;
    const v = id => document.getElementById(id)?.value || '—';
    const challengeLabels = _stages
      .map(k => CHALLENGE_META[k]?.label || k)
      .join(' → ');
    const rows = [
      { label: 'Full Name',     val: v('full_name')     },
      { label: 'Student ID',    val: v('student_id')    },
      { label: 'Department',    val: v('department')    },
      { label: 'Year',          val: v('year_of_study') },
      { label: 'Phone',         val: v('phone') || '—'  },
      {
        label: 'Face Verified',
        val: _allDone
          ? `✓ ${challengeLabels}`
          : '✗ Not verified',
        ok: _allDone,
      },
    ];
    box.innerHTML = rows.map(r =>
      `<div class="review-item">
         <span class="review-label">${r.label}</span>
         <span class="review-value${r.ok ? ' verified' : ''}">${r.val}</span>
       </div>`
    ).join('');
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
    const lvls = [
      { label: 'Too weak', pct: 20,  color: '#ff4d6d' },
      { label: 'Weak',     pct: 35,  color: '#ff8c42' },
      { label: 'Fair',     pct: 58,  color: '#f0b429' },
      { label: 'Good',     pct: 78,  color: '#5bc0de' },
      { label: 'Strong',   pct: 100, color: '#2dce89' },
    ];
    const s = Math.min(pwScore(pwInput.value), 4);
    if (pwFill)  pwFill.style.width   = lvls[s].pct + '%';
    if (pwLabel) { pwLabel.textContent = lvls[s].label; pwLabel.style.color = lvls[s].color; }
  });

  function pwScore(pw) {
    let s = 0;
    if (!pw) return 0;
    if (pw.length >= 8)  s++;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
    if (/\d/.test(pw))   s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return Math.min(s, 4);
  }

  togglePwBtn?.addEventListener('click', () => {
    const h = pwInput.type === 'password';
    pwInput.type           = h ? 'text' : 'password';
    togglePwIcon.className = h ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  });

  /* 
     UTILITIES
 */
  function calcEAR(lm, idx) {
    const p   = idx.map(i => lm[i]);
    const num = ptDist(p[1], p[5]) + ptDist(p[2], p[4]);
    return num / (2 * ptDist(p[0], p[3]) + 1e-6);
  }
  function ptDist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function sleep(ms)    { return new Promise(r => setTimeout(r, ms)); }

  function setStatus(text, state) {
    if (!statusText || !statusWrap) return;
    statusText.textContent = text;
    statusWrap.className   = 'webcam-status' + (state ? ' ' + state : '');
  }
  function setInstr(html, state) {
    if (!instructTxt || !instructEl) return;
    instructTxt.innerHTML = html;
    instructEl.className  = 'liveness-instruction' + (state ? ' ' + state : '');
  }
  function setCountdown(n) {
    if (!countdownEl) return;
    if (n === null || n === undefined) { countdownEl.style.display = 'none'; return; }
    countdownEl.style.display = '';
    countdownEl.textContent   = n > 0 ? n : '✗';
    countdownEl.className     = 'liveness-countdown' + (n <= 1 && n > 0 ? ' urgent' : '');
  }
  function updateDot(idx, state) {
    const dot = dots[idx];
    if (!dot) return;
    dot.classList.remove('active', 'done', 'fail');
    dot.classList.add(state);
  }
  function resetLivenessUI() {
    dots.forEach(d => d?.classList.remove('active', 'done', 'fail'));
    setCountdown(null);
    setStatus('Initialising camera…', '');
    setInstr('Getting ready…');
    instructEl?.classList.remove('success', 'error');
    hideRetry();
  }
  function showFieldError(id, msg) {
    const errEl = document.getElementById('err-' + id);
    const input = document.getElementById(id);
    if (errEl) errEl.textContent = msg;
    if (input) { input.classList.add('invalid'); input.classList.remove('valid'); }
    return false;
  }
  function clearAllErrors() {
    document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
    document.querySelectorAll('.form-control').forEach(e => e.classList.remove('invalid'));
  }
  function showMsg(msg, type) {
    if (!msgBox) return;
    const icon = type === 'success' ? 'fa-circle-check' : 'fa-circle-xmark';
    msgBox.innerHTML = `<div class="alert alert-${type}">
      <i class="fa-solid ${icon}"></i> ${msg}</div>`;
    msgBox.scrollIntoView({ behavior: 'smooth' });
  }

  /* Injected styles */
  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}
      40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
    .shake{animation:shake .4s ease both}
    .spinner{display:inline-block;width:16px;height:16px;border:2px solid
      rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;
      animation:_sp .7s linear infinite;vertical-align:middle}
    @keyframes _sp{to{transform:rotate(360deg)}}
    .liveness-instruction.success{color:var(--clr-green,#2dce89)!important;
      border-color:rgba(45,206,137,.3)!important}
    .liveness-instruction.error{color:var(--clr-red,#ff4d6d)!important;
      border-color:rgba(255,77,109,.3)!important}
    .capture-dot.done{background:var(--clr-gold,#f0b429)!important;
      box-shadow:0 0 8px rgba(240,180,41,.6)}
    .capture-dot.fail{background:var(--clr-red,#ff4d6d)!important;
      box-shadow:0 0 8px rgba(255,77,109,.6)}
    .capture-dot.active{background:var(--clr-blue,#5bc0de)!important;
      box-shadow:0 0 8px rgba(91,192,222,.6);animation:_pulse 1s ease-in-out infinite}
    @keyframes _pulse{0%,100%{opacity:1}50%{opacity:.4}}
    .liveness-countdown{display:inline-flex;align-items:center;justify-content:center;
      min-width:36px;height:36px;border-radius:50%;background:rgba(91,192,222,.15);
      border:2px solid rgba(91,192,222,.4);color:#5bc0de;font-size:1.1rem;
      font-weight:700;margin-left:.75rem;flex-shrink:0;transition:all .3s}
    .liveness-countdown.urgent{background:rgba(255,77,109,.15);
      border-color:rgba(255,77,109,.5);color:#ff4d6d;
      animation:_pulse .5s ease-in-out infinite}
    #retryWrap{display:none;margin-top:1rem;text-align:center}
    #retryBtn{padding:.55rem 1.4rem;border:none;border-radius:8px;
      background:var(--clr-gold,#f0b429);color:#111;font-weight:600;
      cursor:pointer;font-size:.9rem;transition:opacity .2s}
    #retryBtn:hover{opacity:.85}
  `;
  document.head.appendChild(style);

  showStep(1);
  dbg('loaded ✓');
});