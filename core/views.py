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
from rest_framework.decorators    import api_view
from rest_framework.response      import Response
from rest_framework               import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models                   import Student
from .serializers              import RegisterSerializer, LoginSerializer
from .services.face_embedding  import FaceEmbedding, EMBEDDING_QUALITY_MIN
from .services.face_verifier   import FaceVerifier, SPOOF_COSINE_FLOOR
from .services.liveness        import LivenessChallenge, generate_random_challenges
from admin_dashboard.models    import FraudAlert

logger = logging.getLogger(__name__)

# ── Constants 
FACE_MAX_ATTEMPTS        = 3
FACE_LOCKOUT_MIN         = 15    
PW_MAX_ATTEMPTS          = 5
PW_LOCKOUT_MIN           = 15



# Login         → 1 selected at random via generate_random_challenges(1).
CHALLENGE_POOL           = ['blink', 'turn_left', 'turn_right']
REG_CHALLENGE_COUNT      = 3     
LOGIN_CHALLENGE_COUNT    = 1

FACE_VERIFY_SESSION_SECS = 300   

CHALLENGE_LABELS = {
    'blink':      'Blink your eyes',
    'turn_left':  'Turn head left',
    'turn_right': 'Turn head right',
}


# ── Private helpers 
def _decode_b64(b64: str):
    """Decode a base64 string or data-URI into an OpenCV BGR ndarray."""
    try:
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.error(f'_decode_b64: {exc}')
        return None


def _jerr(msg: str, code: int = 400) -> JsonResponse:
    return JsonResponse({'success': False, 'error': msg}, status=code)


def _role_redirect(user):
    if user.is_staff or user.is_superuser:
        return redirect('admin_dashboard:dashboard')
    return redirect('voter_dashboard:dashboard')


def _get_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _device_fingerprint(request) -> str:
    ua     = request.META.get('HTTP_USER_AGENT', '')
    accept = request.META.get('HTTP_ACCEPT', '')
    return hashlib.sha256(f'{ua}||{accept}'.encode()).hexdigest()[:32]


def _is_face_verify_session_valid(request) -> 'tuple[bool, str]':
    timestamp = request.session.get('face_verify_started_at')
    if not timestamp:
        return False, 'Session expired. Please log in again.'
    elapsed = timezone.now().timestamp() - timestamp
    if elapsed > FACE_VERIFY_SESSION_SECS:
        for key in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(key, None)
        return False, (
            f'Face verification session expired ({int(elapsed)}s). '
            f'Please log in again.'
        )
    return True, ''


#  Home 

def index(request):
    return render(request, 'core/index.html')


# Liveness challenge API 

@require_GET
def get_liveness_challenges(request):
    """
    GET /api/liveness-challenges/

    ?mode=register    → all 3 unique challenges in random order
    ?mode=login       → 1 random challenge (requires pending_face_pk in session)
    ?mode=re_register → all 3 unique challenges (requires authenticated user)
    """
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

    logger.debug(f'Liveness challenges ({mode}): {selected}')
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

    #  Form validation 
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

    # Collect liveness frames 
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

    #  Resolve challenge order from session
    challenges = request.session.get('liveness_challenges', [])
    if (
        len(challenges) != REG_CHALLENGE_COUNT
        or not all(c in CHALLENGE_POOL for c in challenges)
    ):
        logger.warning(
            f'register_view: bad session challenges {challenges} '
            f'for [{student_id}] — generating fresh set'
        )
        challenges = generate_random_challenges(REG_CHALLENGE_COUNT)

    logger.info(f'register_view: verifying {challenges} for [{student_id}]')

    #  Run liveness sequence — all 3 challenges must pass 
    liveness_checker = LivenessChallenge()
    embedder         = FaceEmbedding()
    quality_scores   = []

    for i, (frame, ch_type) in enumerate(zip(decoded_frames, challenges)):
        label = CHALLENGE_LABELS.get(ch_type, ch_type)
        ok, reason = liveness_checker.verify(frame, ch_type)
        if not ok:
            logger.warning(
                f'register_view: FAIL [{student_id}] '
                f'stage {i + 1} ({ch_type}): {reason}'
            )
            return err(
                f'"{label}" not verified (stage {i + 1}): {reason} '
                f'Please go back and complete all liveness stages again.'
            )
        _, q = embedder.get_embedding(frame)
        quality_scores.append(q)

    logger.info(
        f'register_view: all {REG_CHALLENGE_COUNT} stages PASSED [{student_id}]'
    )

    # Select best frame for embedding 
    embed_frame   = None
    embed_quality = 0.0

    if neutral_raw:
        neutral_frame = _decode_b64(neutral_raw)
        if neutral_frame is not None:
            _, embed_quality = embedder.get_embedding(neutral_frame)
            if embed_quality >= EMBEDDING_QUALITY_MIN:
                embed_frame = neutral_frame
                logger.info(
                    f'register_view: using neutral frame '
                    f'(quality={embed_quality:.3f}) [{student_id}]'
                )

    if embed_frame is None:
        best_idx      = int(np.argmax(quality_scores))
        embed_frame   = decoded_frames[best_idx]
        embed_quality = quality_scores[best_idx]
        logger.info(
            f'register_view: using gesture frame {best_idx + 1} '
            f'(quality={embed_quality:.3f}) [{student_id}]'
        )

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

    # Create Student 
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
        logger.error(f'Registration DB error [{student_id}]: {exc}')
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
        f'REGISTERED (pending, challenges={challenges}, '
        f'dim={embedding.shape[0]}, quality={embed_quality:.3f}): {student_id}'
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


# Re-register face 

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

    logger.info(
        f'RE-REGISTERED face for [{student.student_id}] quality={embed_quality:.3f}'
    )

    if is_ajax:
        return JsonResponse({
            'success':  True,
            'message':  'Face updated successfully. You can now log in.',
            'redirect': '/voter-dashboard/',
        })
    messages.success(request, 'Face updated successfully.')
    return redirect('voter_dashboard:dashboard')


# Login — Step 1: credentials 

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

    if not obj.is_staff:
        if obj.is_locked():
            mins = max(1, int(
                (obj.locked_until - timezone.now()).total_seconds() / 60
            ))
            return err(
                f'Account locked. Try again in '
                f'{mins} minute{"s" if mins != 1 else ""}.',
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
            logger.warning(f'Failed admin login [{student_id}]')
            return err('Invalid credentials.')
        obj.increment_failed_attempts(
            max_attempts    = PW_MAX_ATTEMPTS,
            lockout_minutes = PW_LOCKOUT_MIN,
        )
        left = max(0, PW_MAX_ATTEMPTS - obj.failed_login_attempts)
        if left > 0:
            return err(
                f'Invalid credentials. '
                f'{left} attempt{"s" if left != 1 else ""} remaining.'
            )
        return err(
            f'Too many failed attempts. '
            f'Account locked for {PW_LOCKOUT_MIN} minutes.'
        )

    # Admin 
    if user.is_staff or user.is_superuser:
        user.reset_failed_attempts()
        login(request, user)
        logger.info(f'Admin login OK: {student_id}')
        if is_ajax:
            return JsonResponse({
                'success':  True,
                'redirect': '/admin-dashboard/',
                'message':  f'Welcome back, {user.full_name}.',
            })
        return redirect('admin_dashboard:dashboard')

    # Voter — needs face step
    if not obj.face_embedding:
        return err(
            'No face data found for your account. '
            'Please re-register or contact the administrator.'
        )

    request.session['pending_face_pk']        = user.pk
    request.session['face_verify_attempts']   = 0
    request.session['face_verify_started_at'] = timezone.now().timestamp()
    request.session.save()

    logger.info(f'Step-1 OK [{student_id}] → face verify')

    if is_ajax:
        return JsonResponse({'success': True, 'require_face': True})
    return redirect('core:face_verify')


# Face verify 

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


# Face verify — API 

@csrf_exempt
@require_POST
def face_verify_api(request):
    pk = request.session.get('pending_face_pk')
    if not pk:
        return _jerr('Session expired. Please log in again.', 401)

    valid, reason = _is_face_verify_session_valid(request)
    if not valid:
        return _jerr(reason, 401)

    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        return _jerr('Account not found.', 404)

    if student.is_staff:
        for key in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
            request.session.pop(key, None)
        return _jerr('Invalid session state.', 400)

    ip = _get_ip(request)

    
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

    frame = _decode_b64(frame_b64)
    if frame is None:
        return _jerr('Could not decode the submitted image.')

    #  Server-side liveness re-check 
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
            f'face_verify_api: liveness FAIL [{student.student_id}] '
            f'challenge={challenge_type}: {liveness_msg}'
        )
        spoof_keywords = ('photo', 'screen', 'multiple', 'replay', 'printout', 'pixel-grid')
        if any(kw in liveness_msg.lower() for kw in spoof_keywords):
            FraudAlert.log_spoof_attempt(student, ip, euc=0.0, cos=0.0)
            return _jerr(f'Security check failed: {liveness_msg}', 403)
        
        logger.info(
            f'face_verify_api: soft liveness miss [{student.student_id}], '
            f'continuing to face match'
        )

    #  Device fingerprint (soft warning — never blocks login) 
    current_device = _device_fingerprint(request)
    if student.registered_device and current_device != student.registered_device:
        logger.warning(
            f'face_verify_api: UNKNOWN DEVICE [{student.student_id}] IP={ip}'
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
            logger.error(f'face_verify_api: FraudAlert create error: {exc}')

    #  Attempt counter
    attempt   = request.session.get('face_verify_attempts', 0) + 1
    remaining = max(0, FACE_MAX_ATTEMPTS - attempt)
    request.session['face_verify_attempts'] = attempt
    request.session.save()

    #  Face matching
    verifier          = FaceVerifier(bytes(student.face_embedding))
    matched, euc, cos = verifier.verify_with_score(frame)

    logger.info(
        f'face_verify [{student.student_id}] '
        f'attempt={attempt}/{FACE_MAX_ATTEMPTS} '
        f'cos={cos:.4f} euc={euc:.4f} '
        f'→ {"MATCH" if matched else "REJECT"}'
    )

    # Handle mismatch 
    if not matched:
        if cos < SPOOF_COSINE_FLOOR:
            logger.warning(
                f'face_verify_api: SPOOF/DIFFERENT PERSON '
                f'[{student.student_id}] cos={cos:.4f} < {SPOOF_COSINE_FLOOR}'
            )
            try:
                FraudAlert.log_spoof_attempt(student, ip, euc, cos)
            except Exception as exc:
                logger.error(f'face_verify_api: FraudAlert.log_spoof_attempt error: {exc}')
        else:
        
            try:
                FraudAlert.log_face_mismatch(
                    student      = student,
                    ip           = ip,
                    euc          = euc,
                    cos          = cos,
                    attempt      = attempt,
                    max_attempts = FACE_MAX_ATTEMPTS,
                )
            except Exception as exc:
                logger.error(f'face_verify_api: FraudAlert.log_face_mismatch error: {exc}')

        if attempt >= FACE_MAX_ATTEMPTS:
            student.locked_until = (
                timezone.now()
                + timezone.timedelta(minutes=FACE_LOCKOUT_MIN)
            )
            student.failed_login_attempts = FACE_MAX_ATTEMPTS
            student.save(update_fields=['locked_until', 'failed_login_attempts'])

            for key in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
                request.session.pop(key, None)

            try:
                FraudAlert.log_account_locked(student, ip, FACE_LOCKOUT_MIN)
            except Exception as exc:
                logger.error(f'face_verify_api: FraudAlert.log_account_locked error: {exc}')

            logger.warning(
                f'Voter [{student.student_id}] BLOCKED '
                f'{FACE_LOCKOUT_MIN} min after {FACE_MAX_ATTEMPTS} failures.'
            )
            return _jerr(
                f'Face verification failed {FACE_MAX_ATTEMPTS} times. '
                f'Account blocked for {FACE_LOCKOUT_MIN} minutes. '
                f'Contact the administrator if this is a mistake.',
                403,
            )

        return _jerr(
            f'Face does not match. '
            f'{remaining} attempt{"s" if remaining != 1 else ""} remaining. '
            f'Ensure good lighting and look directly at the camera.'
        )

    # Match — complete login 
    student.reset_failed_attempts()
    login(request, student)
    try:
        student.record_login(ip)
    except Exception as exc:
        logger.error(f'face_verify_api: record_login error: {exc}')

    for key in ('pending_face_pk', 'face_verify_attempts', 'face_verify_started_at'):
        request.session.pop(key, None)

    logger.info(
        f'Voter login SUCCESS: [{student.student_id}] cos={cos:.4f} IP={ip}'
    )
    return JsonResponse({
        'success':  True,
        'message':  f'Face matched! Welcome, {student.full_name}.',
        'redirect': '/voter-dashboard/',
    })


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


# JWT REST API 

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