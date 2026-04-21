# core/views.py

import re
import json
import random
import base64
import hashlib
import logging

import cv2
import numpy as np

from django.shortcuts             import render, redirect
from django.contrib               import messages
from django.contrib.auth          import authenticate, login, logout
from django.http                  import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils                 import timezone
from datetime                     import timedelta
from rest_framework.decorators    import api_view
from rest_framework.response      import Response
from rest_framework               import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models                   import Student
from .serializers              import RegisterSerializer, LoginSerializer
from .services.face_embedding  import FaceEmbedding, EMBEDDING_QUALITY_MIN
from .services.face_verifier   import FaceVerifier, SPOOF_COSINE_FLOOR, COSINE_THRESHOLD
from .services.anti_spoof      import AntiSpoofChecker
from .services.liveness        import LivenessChallenge, generate_random_challenges, CHALLENGE_POOL
from admin_dashboard.models    import FraudAlert

logger = logging.getLogger(__name__)


_anti_spoof_checker = None


def _get_anti_spoof_checker() -> AntiSpoofChecker:
    global _anti_spoof_checker
    if _anti_spoof_checker is None:
        _anti_spoof_checker = AntiSpoofChecker()
    return _anti_spoof_checker


MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_MINUTES    = 15

PW_MAX_ATTEMPTS    = MAX_LOGIN_ATTEMPTS
PW_LOCKOUT_MIN     = LOCKOUT_MINUTES
FACE_MAX_ATTEMPTS  = MAX_LOGIN_ATTEMPTS
FACE_LOCKOUT_MIN   = LOCKOUT_MINUTES

# Registration: block session after this many liveness failures
REG_MAX_LIVENESS_ATTEMPTS = 3
REG_LIVENESS_BLOCK_SECS   = 900   

REG_CHALLENGE_COUNT      = 3
LOGIN_CHALLENGE_COUNT    = 1
FACE_VERIFY_SESSION_SECS = 300    

CHALLENGE_LABELS = {
    'blink':      'Blink your eyes',
    'turn_left':  'Turn head left',
    'turn_right': 'Turn head right',
}


# Private helpers 
def _decode_b64(b64: str):
    try:
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.error('_decode_b64: %s', exc)
        return None


def _jerr(msg: str, code: int = 400) -> JsonResponse:
    return JsonResponse({'success': False, 'error': msg}, status=code)


def _role_redirect(user):
    if user.is_staff or user.is_superuser:
        return redirect('admin_dashboard:dashboard')
    return redirect('voter_dashboard:dashboard')


def _get_ip(request) -> str:
    fwd = request.META.get('HTTP_X_FORWARDED_FOR')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _device_fingerprint(request) -> str:
    ua     = request.META.get('HTTP_USER_AGENT', '')
    accept = request.META.get('HTTP_ACCEPT', '')
    return hashlib.sha256(f'{ua}||{accept}'.encode()).hexdigest()[:32]


def _is_face_verify_session_valid(request) -> 'tuple[bool, str]':
    """Return (valid, reason).  Clears stale keys when expired."""
    ts = request.session.get('face_verify_started_at')
    if not ts:
        return False, 'Session expired. Please log in again.'
    elapsed = timezone.now().timestamp() - ts
    if elapsed > FACE_VERIFY_SESSION_SECS:
        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)
        return False, (
            f'Face verification session expired ({int(elapsed)}s). '
            'Please log in again.'
        )
    return True, ''





# home
def index(request):
    return render(request, 'core/index.html')




@require_GET
def get_liveness_challenges(request):
    mode = request.GET.get('mode', 'register')

    if mode == 'login':
        if not request.session.get('pending_face_pk'):
            return JsonResponse({'error': 'No active login session.'}, status=403)
        valid, reason = _is_face_verify_session_valid(request)
        if not valid:
            return JsonResponse({'error': reason}, status=403)

    if mode == 're_register':
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required.'}, status=403)

    count    = LOGIN_CHALLENGE_COUNT if mode == 'login' else REG_CHALLENGE_COUNT
    selected = generate_random_challenges(count)
    request.session['liveness_challenges'] = selected
    request.session['liveness_mode']       = mode
    request.session.save()

    logger.debug('Liveness challenges (%s): %s', mode, selected)
    return JsonResponse({'challenges': selected, 'mode': mode})



#  Register
def register_view(request):
    if request.method == 'GET':
        return render(request, 'core/register.html')

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg):
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('core:register')

    # Check registration liveness lockout
    block_until = request.session.get('reg_liveness_blocked_until')
    if block_until:
        remaining = block_until - timezone.now().timestamp()
        if remaining > 0:
            mins = max(1, int(remaining / 60))
            return err(
                f'Too many failed liveness attempts during registration. '
                f'Please try again in {mins} minute{"s" if mins != 1 else ""}.'
            )
        else:
            request.session.pop('reg_liveness_blocked_until', None)
            request.session.pop('reg_liveness_attempts', None)

    #  Basic field validation 
    student_id    = request.POST.get('student_id',    '').strip()
    full_name     = request.POST.get('full_name',     '').strip()
    department    = request.POST.get('department',    '').strip()
    year_of_study = request.POST.get('year_of_study', '').strip()
    phone         = request.POST.get('phone',         '').strip() or None
    password      = request.POST.get('password',      '')
    age_raw       = request.POST.get('age',           '').strip()
    gender        = request.POST.get('gender',        '').strip() or None

    if not all([student_id, full_name, department, year_of_study, password]):
        return err('All required fields must be filled.')
    if not re.match(r'^ISL-\d{4}$', student_id):
        return err('Student ID must match format ISL-XXXX (e.g. ISL-1234).')
    if Student.objects.filter(student_id=student_id).exists():
        return err('This Student ID is already registered.')
    if len(password) < 8:
        return err('Password must be at least 8 characters.')

    age = None
    if age_raw:
        try:
            age = int(age_raw)
            if not (18 <= age <= 35):
                return err('Age must be between 18 and 35.')
        except ValueError:
            return err('Age must be a whole number.')

    # Liveness frames
    face_frames_raw = [
        request.POST.get(f'face_data_challenge_{i}', '').strip()
        for i in range(REG_CHALLENGE_COUNT)
    ]
    neutral_raw = request.POST.get('face_data_neutral', '').strip()

    for i, raw in enumerate(face_frames_raw):
        if not raw:
            return err(
                f'Liveness frame {i + 1} is missing. '
                f'Please go back and complete all {REG_CHALLENGE_COUNT} stages.'
            )

    decoded_frames = []
    for i, raw in enumerate(face_frames_raw):
        frame = _decode_b64(raw)
        if frame is None:
            return err(f'Could not decode liveness frame {i + 1}. Please try again.')
        decoded_frames.append(frame)

    challenges = request.session.get('liveness_challenges', [])
    if (
        len(challenges) != REG_CHALLENGE_COUNT
        or not all(c in CHALLENGE_POOL for c in challenges)
    ):
        logger.warning(
            'register_view: bad session challenges %s for [%s] — regenerating',
            challenges, student_id,
        )
        challenges = generate_random_challenges(REG_CHALLENGE_COUNT)

    logger.info('register_view: verifying %s for [%s]', challenges, student_id)

  
    liveness_checker = LivenessChallenge()
    embedder         = FaceEmbedding()
    quality_scores   = []

    liveness_fail = False
    fail_reason   = ''

    for i, (frame, ch_type) in enumerate(zip(decoded_frames, challenges)):
        label = CHALLENGE_LABELS.get(ch_type, ch_type)
        ok, reason = liveness_checker.verify(frame, ch_type)
        if not ok:
            liveness_fail = True
            fail_reason   = (
                f'"{label}" not verified (stage {i + 1}): {reason} '
                f'Please go back and complete all liveness stages again.'
            )
            logger.warning(
                'register_view: FAIL [%s] stage %d (%s): %s',
                student_id, i + 1, ch_type, reason,
            )
            break
        _, q = embedder.get_embedding(frame)
        quality_scores.append(q)

    if liveness_fail:
        attempts = request.session.get('reg_liveness_attempts', 0) + 1
        request.session['reg_liveness_attempts'] = attempts
        remaining = REG_MAX_LIVENESS_ATTEMPTS - attempts

        logger.warning(
            'register_view: liveness fail attempt %d/%d for student_id=%s',
            attempts, REG_MAX_LIVENESS_ATTEMPTS, student_id,
        )

        if attempts >= REG_MAX_LIVENESS_ATTEMPTS:
            # Block the session for REG_LIVENESS_BLOCK_SECS seconds
            block_until_ts = timezone.now().timestamp() + REG_LIVENESS_BLOCK_SECS
            request.session['reg_liveness_blocked_until'] = block_until_ts
            request.session['reg_liveness_attempts']      = 0  # reset for next window
            request.session.save()
            logger.warning(
                'register_view: REGISTRATION LIVENESS BLOCKED for %d min — student_id=%s',
                REG_LIVENESS_BLOCK_SECS // 60, student_id,
            )
            return err(
                f'Registration blocked: {REG_MAX_LIVENESS_ATTEMPTS} consecutive '
                f'liveness failures detected. '
                f'Please try again in {REG_LIVENESS_BLOCK_SECS // 60} minutes.'
            )

        request.session.save()
        hint = (
            f' ({remaining} attempt{"s" if remaining != 1 else ""} remaining '
            f'before a {REG_LIVENESS_BLOCK_SECS // 60}-minute block.)'
            if remaining > 0 else ''
        )
        return err(fail_reason + hint)

    # Liveness passed — reset the attempt counter
    request.session.pop('reg_liveness_attempts', None)
    request.session.pop('reg_liveness_blocked_until', None)

    logger.info(
        'register_view: all %d stages PASSED [%s]',
        REG_CHALLENGE_COUNT, student_id,
    )

 
    embed_frame   = None
    embed_quality = 0.0

    if neutral_raw:
        neutral_frame = _decode_b64(neutral_raw)
        if neutral_frame is not None:
            _, embed_quality = embedder.get_embedding(neutral_frame)
            if embed_quality >= EMBEDDING_QUALITY_MIN:
                embed_frame = neutral_frame

    if embed_frame is None:
        best_idx      = int(np.argmax(quality_scores))
        embed_frame   = decoded_frames[best_idx]
        embed_quality = quality_scores[best_idx]

    if embed_quality < EMBEDDING_QUALITY_MIN:
        return err(
            f'Face image quality too low (score={embed_quality:.2f}, '
            f'need ≥ {EMBEDDING_QUALITY_MIN:.2f}). '
            f'Ensure good lighting, face the camera directly, and move closer.'
        )

    embedding, _ = embedder.get_embedding(embed_frame)
    if embedding is None:
        return err(
            'Could not extract face features. '
            'Ensure good lighting and try again.'
        )

    # Create account 
    try:
        student = Student.objects.create_user(
            student_id    = student_id,
            full_name     = full_name,
            department    = department,
            year_of_study = year_of_study,
            phone         = phone,
            password      = password,
        )
    except Exception as exc:
        logger.error('Registration DB error [%s]: %s', student_id, exc)
        return err('Server error while creating your account. Please try again.')

    student.face_embedding    = embedding.astype(np.float64).tobytes()
    student.approval_status   = 'pending'
    student.registered_device = _device_fingerprint(request)
    if age:
        student.age = age
    if gender:
        student.gender = gender
    student.save(update_fields=[
        'face_embedding', 'approval_status', 'registered_device',
        'age', 'gender',
    ])

    request.session.pop('liveness_challenges', None)
    request.session.pop('liveness_mode', None)

    logger.info(
        'REGISTERED (pending, challenges=%s, dim=%d, quality=%.3f): %s',
        challenges, embedding.shape[0], embed_quality, student_id,
    )

    if is_ajax:
        return JsonResponse({
            'success': True,
            'message': (
                'Registration complete! '
                'Your account is pending admin approval. '
                'You will be able to log in once approved.'
            ),
            'redirect': '/login/',
        })
    messages.success(request, 'Registration complete! Awaiting admin approval.')
    return redirect('core:login')



#  Re-register face


def re_register_face_view(request):
    if not request.user.is_authenticated:
        messages.warning(request, 'Please log in first.')
        return redirect('core:login')

    student = request.user
    if student.is_staff:
        messages.error(request, 'Admin accounts do not use face verification.')
        return redirect('admin_dashboard:dashboard')

    if request.method == 'GET':
        return render(request, 'core/re_register_face.html', {'student': student})

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg):
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('core:re_register_face')

    password = request.POST.get('password', '')
    if not password:
        return err('Please confirm your password to update your face data.')
    if not authenticate(request, username=student.student_id, password=password):
        return err('Incorrect password. Please try again.')

    face_frames_raw = [
        request.POST.get(f'face_data_challenge_{i}', '').strip()
        for i in range(REG_CHALLENGE_COUNT)
    ]
    neutral_raw = request.POST.get('face_data_neutral', '').strip()

    for i, raw in enumerate(face_frames_raw):
        if not raw:
            return err(f'Liveness frame {i + 1} is missing.')

    decoded_frames = []
    for i, raw in enumerate(face_frames_raw):
        frame = _decode_b64(raw)
        if frame is None:
            return err(f'Could not decode liveness frame {i + 1}.')
        decoded_frames.append(frame)

    challenges = request.session.get('liveness_challenges', [])
    if (
        len(challenges) != REG_CHALLENGE_COUNT
        or not all(c in CHALLENGE_POOL for c in challenges)
    ):
        challenges = generate_random_challenges(REG_CHALLENGE_COUNT)

    liveness_checker = LivenessChallenge()
    embedder         = FaceEmbedding()
    quality_scores   = []

    for i, (frame, ch_type) in enumerate(zip(decoded_frames, challenges)):
        label = CHALLENGE_LABELS.get(ch_type, ch_type)
        ok, reason = liveness_checker.verify(frame, ch_type)
        if not ok:
            return err(f'"{label}" not verified: {reason}')
        _, q = embedder.get_embedding(frame)
        quality_scores.append(q)

    embed_frame   = None
    embed_quality = 0.0

    if neutral_raw:
        neutral_frame = _decode_b64(neutral_raw)
        if neutral_frame is not None:
            _, embed_quality = embedder.get_embedding(neutral_frame)
            if embed_quality >= EMBEDDING_QUALITY_MIN:
                embed_frame = neutral_frame

    if embed_frame is None:
        best_idx      = int(np.argmax(quality_scores))
        embed_frame   = decoded_frames[best_idx]
        embed_quality = quality_scores[best_idx]

    if embed_quality < EMBEDDING_QUALITY_MIN:
        return err(
            f'Face image quality too low (score={embed_quality:.2f}). '
            f'Use better lighting and move closer.'
        )

    embedding, _ = embedder.get_embedding(embed_frame)
    if embedding is None:
        return err('Could not extract face features. Please try again.')

    student.face_embedding        = embedding.astype(np.float64).tobytes()
    student.failed_login_attempts = 0
    student.locked_until          = None
    student.registered_device     = _device_fingerprint(request)
    student.save(update_fields=[
        'face_embedding', 'failed_login_attempts',
        'locked_until', 'registered_device',
    ])

    request.session.pop('liveness_challenges', None)
    request.session.pop('liveness_mode', None)

    if is_ajax:
        return JsonResponse({
            'success':  True,
            'message':  'Face updated successfully. You can now log in.',
            'redirect': '/voter-dashboard/',
        })
    messages.success(request, 'Face updated successfully.')
    return redirect('voter_dashboard:dashboard')



#  Login credentials

def login_view(request):
    if request.method == 'GET':
        if request.user.is_authenticated:
            return _role_redirect(request.user)
        return render(request, 'core/login.html')

    student_id = request.POST.get('student_id', '').strip()
    password   = request.POST.get('password',   '')
    is_ajax    = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg, warn=False):
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error':   msg,
                'type':    'warning' if warn else 'error',
            })
        (messages.warning if warn else messages.error)(request, msg)
        return redirect('core:login')

    if not student_id or not password:
        return err('Student ID and password are required.')

    try:
        obj = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return err('Invalid credentials.')

    # Lockout checked before password auth 
    if not obj.is_staff:
        if obj.is_locked():
            mins = max(1, int(
                (obj.locked_until - timezone.now()).total_seconds() / 60
            ))
            return err(
                f'Account locked due to too many failed attempts. '
                f'Try again in {mins} minute{"s" if mins != 1 else ""}.',
                warn=True,
            )
        if obj.approval_status == 'pending':
            return err('Your account is awaiting admin approval.', warn=True)
        if obj.approval_status == 'rejected':
            note = obj.approval_note or 'Contact the administrator for details.'
            return err(f'Account rejected: {note}')

    user = authenticate(request, username=student_id, password=password)

    if user is None:
        if obj.is_staff:
            logger.warning('Failed admin login [%s]', student_id)
            return err('Invalid credentials.')

        # Increment password failure counter
        obj.increment_failed_attempts(
            max_attempts    = PW_MAX_ATTEMPTS,   
            lockout_minutes = PW_LOCKOUT_MIN,    
        )
        left = max(0, PW_MAX_ATTEMPTS - obj.failed_login_attempts)

        logger.warning(
            'login_view: wrong password [%s] attempt=%d/%d left=%d',
            student_id, obj.failed_login_attempts, PW_MAX_ATTEMPTS, left,
        )

        if obj.is_locked():
            return err(
                f'Too many failed attempts. '
                f'Account locked for {PW_LOCKOUT_MIN} minutes.'
            )

        return err(
            f'Invalid credentials. '
            f'{left} attempt{"s" if left != 1 else ""} remaining before lockout.'
        )

    # Admin bypass 
    if user.is_staff or user.is_superuser:
        user.reset_failed_attempts()
        login(request, user)
        logger.info('Admin login OK: %s', student_id)
        if is_ajax:
            return JsonResponse({
                'success':  True,
                'redirect': '/admin-dashboard/',
                'message':  f'Welcome back, {user.full_name}.',
            })
        return redirect('admin_dashboard:dashboard')

    #  Voter: require face verification 
    if not user.face_embedding:
        logger.error(
            'login_view: voter %s has no face embedding — cannot proceed.',
            student_id,
        )
        return err(
            'No biometric data found for your account. '
            'Please contact the administrator to re-register your face.'
        )

   
    # The face-verify stage maintains its own independent session counter.
    user.reset_failed_attempts()

    request.session['pending_face_pk']        = user.pk
    request.session['face_verify_attempts']   = 0
    request.session['face_verify_started_at'] = timezone.now().timestamp()
    request.session.save()

    logger.info('Step-1 OK [%s] → face verify', student_id)

    if is_ajax:
        return JsonResponse({'success': True, 'require_face': True})
    return redirect('core:face_verify')



#  Face verify page
def face_verify_view(request):
    pk = request.session.get('pending_face_pk')
    if not pk:
        messages.warning(request, 'Session expired. Please log in again.')
        return redirect('core:login')
    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        return redirect('core:login')
    if student.is_staff:
        request.session.pop('pending_face_pk', None)
        return redirect('core:login')

    valid, reason = _is_face_verify_session_valid(request)
    if not valid:
        messages.warning(request, reason)
        return redirect('core:login')

    used = request.session.get('face_verify_attempts', 0)
    return render(request, 'core/face_verify.html', {
        'student':       student,
        'attempts_left': max(0, FACE_MAX_ATTEMPTS - used),
        'max_attempts':  FACE_MAX_ATTEMPTS,
    })



#  Face verify
@csrf_exempt
@require_POST
def face_verify_api(request):
    # Session validation 
    pk = request.session.get('pending_face_pk')
    if not pk:
        return _jerr('Session expired. Please log in again.', 401)

    valid, reason = _is_face_verify_session_valid(request)
    if not valid:
        return _jerr(reason, 401)

    #  Load student
    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        return _jerr('Account not found.', 404)

    if student.is_staff:
        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)
        return _jerr('Invalid session state.', 400)

    # Re-check lockout 
    if student.is_locked():
        remaining_secs = (student.locked_until - timezone.now()).total_seconds()
        mins = max(1, int(remaining_secs / 60))
        logger.warning(
            'face_verify_api: account already locked [%s] — %d min remaining',
            student.student_id, mins,
        )
        return _jerr(
            f'Account is locked due to too many failed attempts. '
            f'Try again in {mins} minute{"s" if mins != 1 else ""}.',
            403,
        )

    ip = _get_ip(request)

    # Parse request body 
    try:
        body               = json.loads(request.body)
        frame_b64          = body.get('frame', '').strip()
        liveness_confirmed = body.get('liveness_confirmed', False)
        motion_score       = float(body.get('motion_score', 999))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _jerr('Invalid request body.')

    if not frame_b64:
        return _jerr('No image received.')
    if not liveness_confirmed:
        return _jerr('Liveness check not confirmed. Please complete the gesture first.')

    # Decode frame 
    frame = _decode_b64(frame_b64)
    if frame is None:
        return _jerr('Could not decode the submitted image.')

    # Server-side anti-spoof 
    spoof_checker                    = _get_anti_spoof_checker()
    spoof_ok, spoof_msg, spoof_type  = spoof_checker.check(frame)

    if not spoof_ok:
        logger.warning(
            'face_verify_api: anti-spoof BLOCKED voter=%s reason=%s ip=%s',
            student.student_id, spoof_msg, ip,
        )
        quality_reasons = {
            'no_face_detected', 'face_too_small',
            'invalid_frame', 'frame_too_small', 'invalid_bbox',
        }
        is_attack = spoof_type not in quality_reasons

        if is_attack:
            try:
                FraudAlert.objects.create(
                    voter       = student,
                    election    = FraudAlert._active_election(),
                    alert_type  = 'spoof_attempt',
                    ip_address  = ip,
                    description = (
                        f'Anti-spoof block during login. '
                        f'Reason: {spoof_type}. Details: {spoof_msg}'
                    ),
                )
            except Exception as exc:
                logger.error('face_verify_api: FraudAlert create error: %s', exc)
            return _jerr(
                spoof_msg or 'Spoof attempt detected. Please use your live camera.',
                403,
            )
        return _jerr(
            spoof_msg or 'Face not clearly visible. Please adjust your camera.',
            400,
        )

    # Server-side liveness gesture check 
    login_challenges = request.session.get('liveness_challenges', [])
    challenge_type   = (
        login_challenges[0]
        if login_challenges and login_challenges[0] in CHALLENGE_POOL
        else random.choice(CHALLENGE_POOL)
    )

    liveness_checker          = LivenessChallenge()
    liveness_ok, liveness_msg = liveness_checker.verify(frame, challenge_type)

    if not liveness_ok:
        logger.warning(
            'face_verify_api: liveness FAIL [%s] challenge=%s: %s',
            student.student_id, challenge_type, liveness_msg,
        )
        spoof_keywords = ('photo', 'screen', 'multiple', 'replay', 'printout', 'pixel-grid')
        if any(kw in liveness_msg.lower() for kw in spoof_keywords):
            try:
                FraudAlert.log_spoof_attempt(student, ip, euc=0.0, cos=0.0)
            except Exception as exc:
                logger.error('face_verify_api: FraudAlert log error: %s', exc)
            return _jerr(f'Security check failed: {liveness_msg}', 403)
        logger.info(
            'face_verify_api: soft liveness miss [%s] — continuing to face match',
            student.student_id,
        )

    #  Device fingerprint check 
    current_device = _device_fingerprint(request)
    if student.registered_device and current_device != student.registered_device:
        logger.warning(
            'face_verify_api: UNKNOWN DEVICE [%s] IP=%s', student.student_id, ip,
        )
        try:
            FraudAlert.objects.create(
                voter       = student,
                election    = FraudAlert._active_election(),
                alert_type  = 'unknown_device',
                ip_address  = ip,
                description = (
                    f'Login from unrecognised device for '
                    f'{student.full_name} ({student.student_id}). '
                    f'Registered: {student.registered_device[:8]}… '
                    f'Current: {current_device[:8]}…'
                ),
            )
        except Exception as exc:
            logger.error('face_verify_api: FraudAlert create error: %s', exc)

    # Increment attempt counter BEFORE face match 
    
    attempt   = request.session.get('face_verify_attempts', 0) + 1
    remaining = max(0, FACE_MAX_ATTEMPTS - attempt)
    request.session['face_verify_attempts'] = attempt
    request.session.save()

    logger.info(
        'face_verify_api: voter=%s attempt=%d/%d',
        student.student_id, attempt, FACE_MAX_ATTEMPTS,
    )

    #  Verify stored embedding is valid 
    if not student.face_embedding:
        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)
        return _jerr(
            'No biometric data found for this account. '
            'Please contact an administrator.',
            403,
        )

    verifier = FaceVerifier(bytes(student.face_embedding))
    if not verifier.is_valid:
        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)
        return _jerr(
            'Biometric data for this account is corrupted. '
            'Please re-register or contact an administrator.',
            403,
        )

    #  Face embedding comparison 
    matched, euc, cos = verifier.verify_with_score(frame)

    logger.info(
        'face_verify_api: voter=%s cos=%.4f matched=%s attempt=%d/%d',
        student.student_id, cos, matched, attempt, FACE_MAX_ATTEMPTS,
    )

    # SUCCESS 
    if matched:
        student.reset_failed_attempts()      
        login(request, student)              

        try:
            student.record_login(ip)
        except Exception as exc:
            logger.error('face_verify_api: record_login error: %s', exc)

        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)

        logger.info(
            'Voter login SUCCESS: [%s] cos=%.4f IP=%s',
            student.student_id, cos, ip,
        )
        return JsonResponse({
            'success':  True,
            'message':  f'Face matched! Welcome, {student.full_name}.',
            'redirect': '/voter-dashboard/',
        })

    # FAILURE 
    if cos < SPOOF_COSINE_FLOOR:
        alert_type = 'spoof_attempt'
        alert_desc = (
            f'Cosine similarity {cos:.4f} is below SPOOF_COSINE_FLOOR '
            f'({SPOOF_COSINE_FLOOR}) — possible impersonation or photo attack.'
        )
    else:
        alert_type = 'face_mismatch'
        alert_desc = (
            f'Cosine similarity {cos:.4f} is below COSINE_THRESHOLD '
            f'({COSINE_THRESHOLD}) — face does not match registered voter.'
        )

    try:
        FraudAlert.objects.create(
            voter       = student,
            election    = FraudAlert._active_election(),
            alert_type  = alert_type,
            ip_address  = ip,
            description = alert_desc,
        )
    except Exception as exc:
        logger.error('face_verify_api: FraudAlert create error: %s', exc)

    # Lockout after FACE_MAX_ATTEMPTS 
    if attempt >= FACE_MAX_ATTEMPTS:
        lockout_until = timezone.now() + timedelta(minutes=FACE_LOCKOUT_MIN)

        # Persist lockout on the model 
        student.locked_until          = lockout_until
        student.failed_login_attempts = attempt
        student.save(update_fields=['locked_until', 'failed_login_attempts'])

        try:
            FraudAlert.log_account_locked(student, ip, FACE_LOCKOUT_MIN)
        except Exception as exc:
            logger.error('face_verify_api: FraudAlert.log_account_locked error: %s', exc)

        # Clear face-verify session keys
        for k in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(k, None)
        request.session.save()

        logger.warning(
            'face_verify_api: ACCOUNT LOCKED voter=%s after %d attempts — '
            'locked until %s (%d min)',
            student.student_id,
            FACE_MAX_ATTEMPTS,
            lockout_until.strftime('%H:%M'),
            FACE_LOCKOUT_MIN,
        )
        return _jerr(
            f'Face verification failed {FACE_MAX_ATTEMPTS} times. '
            f'Account locked for {FACE_LOCKOUT_MIN} minutes. '
            f'Contact the administrator if this is a mistake.',
            403,
        )

    
    student.failed_login_attempts = attempt
    student.save(update_fields=['failed_login_attempts'])

    logger.warning(
        'face_verify_api: FACE MISMATCH voter=%s cos=%.4f alert=%s '
        'attempt=%d/%d remaining=%d',
        student.student_id, cos, alert_type,
        attempt, FACE_MAX_ATTEMPTS, remaining,
    )
    return _jerr(
        f'Face does not match. '
        f'{remaining} attempt{"s" if remaining != 1 else ""} remaining '
        f'before account lockout. '
        f'Ensure good lighting and look directly at the camera.'
    )



#  Logout


def logout_view(request):
    name = (
        getattr(request.user, 'full_name', '')
        if request.user.is_authenticated else ''
    )
    logout(request)
    messages.info(
        request,
        f'Goodbye, {name}. You have been logged out securely.'
        if name else 'You have been logged out.',
    )
    return redirect('core:login')



#  JWT REST API

@api_view(['POST'])
def register_api(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user    = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'message': 'Registration successful.',
                'refresh': str(refresh),
                'access':  str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def login_api(request):
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        return Response(serializer.validated_data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)