# core/views.py  

import re
import random
import base64
import json
import cv2
import numpy as np
import logging

from django.shortcuts              import render, redirect
from django.contrib                import messages
from django.contrib.auth           import authenticate, login, logout
from django.http                   import JsonResponse
from django.views.decorators.csrf  import csrf_exempt
from django.views.decorators.http  import require_POST, require_GET
from django.utils                  import timezone
from rest_framework.decorators     import api_view
from rest_framework.response       import Response
from rest_framework                import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models                       import Student
from .serializers                  import RegisterSerializer, LoginSerializer
from .services.face_embedding      import FaceEmbedding
from .services.face_verifier       import FaceVerifier
from .services.liveness            import LivenessChallenge
from admin_dashboard.models        import FraudAlert

logger = logging.getLogger(__name__)

#  Global constants 
FACE_MAX_ATTEMPTS = 3
FACE_LOCKOUT_MIN  = 30

PW_MAX_ATTEMPTS   = 5
PW_LOCKOUT_MIN    = 15



CHALLENGE_POOL = ['blink', 'turn_left', 'turn_right', 'smile']



# PRIVATE HELPERS

def _decode_b64(b64: str):
    """Decode a base64 string or data-URI into an OpenCV BGR ndarray."""
    try:
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.error(f'_decode_b64 error: {exc}')
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



# HOME


def index(request):
    return render(request, 'core/index.html')

# ADAPTIVE LIVENESS CHALLENGES API
@require_GET
def get_liveness_challenges(request):
    selected = random.sample(CHALLENGE_POOL, 3)
    request.session['liveness_challenges'] = selected
    request.session.save()
    logger.debug(f'Liveness challenges assigned: {selected}')
    return JsonResponse({'challenges': selected})


 
# REGISTER
def register_view(request):
    """
    GET  → render register.html.
    POST → validate fields, verify 3 liveness frames server-side,
           extract face embedding, create Student (approval_status=pending).
    """
    if request.method == 'GET':
        return render(request, 'core/register.html')

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg: str):
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('core:register')

    student_id    = request.POST.get('student_id',    '').strip()
    full_name     = request.POST.get('full_name',     '').strip()
    department    = request.POST.get('department',    '').strip()
    year_of_study = request.POST.get('year_of_study', '').strip()
    phone         = request.POST.get('phone',         '').strip() or None
    password      = request.POST.get('password',      '')

    face_frames_raw = [
        request.POST.get('face_data_challenge_0', '').strip(),
        request.POST.get('face_data_challenge_1', '').strip(),
        request.POST.get('face_data_challenge_2', '').strip(),
    ]

    if not all([student_id, full_name, department, year_of_study, password]):
        return err('All required fields must be filled.')

    if not re.match(r'^ISL-\d{4}$', student_id):
        return err('Student ID must match format ISL-XXXX (e.g. ISL-1234).')

    if Student.objects.filter(student_id=student_id).exists():
        return err('This Student ID is already registered.')

    if len(password) < 8:
        return err('Password must be at least 8 characters.')

    for i, raw in enumerate(face_frames_raw):
        if not raw:
            return err(
                f'Liveness frame {i + 1} is missing. '
                f'Please go back and complete all 3 stages again.'
            )

    challenges = request.session.get(
        'liveness_challenges',
        ['blink', 'turn_left', 'turn_right'],
    )

    known = set(CHALLENGE_POOL)
    if len(challenges) != 3 or not all(c in known for c in challenges):
        logger.warning(
            f'register_view: invalid session challenges {challenges} '
            f'for [{student_id}] — using fallback order'
        )
        challenges = ['blink', 'turn_left', 'turn_right']

    logger.info(
        f'register_view: verifying challenges {challenges} for [{student_id}]'
    )

    decoded_frames = []
    for i, raw in enumerate(face_frames_raw):
        frame = _decode_b64(raw)
        if frame is None:
            return err(
                f'Could not decode liveness frame {i + 1}. Please try again.'
            )
        decoded_frames.append(frame)

    checker = LivenessChallenge()
    challenge_labels = {
        'blink':      'Blink',
        'turn_left':  'Head-left turn',
        'turn_right': 'Head-right turn',
        'smile':      'Smile',
    }

    for i, (frame, challenge_type) in enumerate(zip(decoded_frames, challenges)):
        label = challenge_labels.get(challenge_type, challenge_type)
        ok, reason = checker.verify(frame, challenge_type)
        if not ok:
            logger.warning(
                f'Registration liveness FAIL [{student_id}] '
                f'stage {i + 1} ({challenge_type}): {reason}'
            )
            return err(
                f'{label} not verified: {reason} '
                f'Please go back and complete all liveness stages again.'
            )

    embedding = FaceEmbedding().get_embedding(decoded_frames[0])
    if embedding is None:
        return err(
            'No face detected in the captured frames. '
            'Ensure good lighting, face the camera directly, and try again.'
        )

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

    student.face_embedding  = embedding.astype(np.float64).tobytes()
    student.approval_status = 'pending'
    student.save(update_fields=['face_embedding', 'approval_status'])

    request.session.pop('liveness_challenges', None)

    logger.info(
        f'REGISTERED (3/3 liveness OK [{" → ".join(challenges)}], '
        f'pending approval): {student_id}'
    )

    if is_ajax:
        return JsonResponse({
            'success':  True,
            'message':  (
                'Registration complete! '
                'Your account is pending admin approval. '
                'You will be able to log in once approved.'
            ),
            'redirect': '/login/',
        })

    messages.success(
        request,
        'Registration complete! Your account is awaiting admin approval.'
    )
    return redirect('core:login')



# LOGIN — STEP 1: CREDENTIALS
def login_view(request):
    """
    GET  → render login.html.
    POST → validate credentials, run lockout/approval checks, then either
           log in admins immediately or route voters to Step 2 (face verify).
    """
    if request.method == 'GET':
        if request.user.is_authenticated:
            return _role_redirect(request.user)
        return render(request, 'core/login.html')

    student_id = request.POST.get('student_id', '').strip()
    password   = request.POST.get('password',   '')
    is_ajax    = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg: str, warn: bool = False):
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

    # Lockout and approval checks — voters only, never admins.
    if not obj.is_staff and obj.is_locked():
        mins = max(1, int(
            (obj.locked_until - timezone.now()).total_seconds() / 60
        ))
        return err(
            f'Account is temporarily locked. '
            f'Try again in {mins} minute{"s" if mins != 1 else ""}.',
            warn=True,
        )

    if not obj.is_staff:
        if obj.approval_status == 'pending':
            return err(
                'Your account is awaiting admin approval. '
                'You will be notified once approved.',
                warn=True,
            )
        if obj.approval_status == 'rejected':
            note = obj.approval_note or 'Contact the administrator for details.'
            return err(f'Account rejected: {note}')

    user = authenticate(request, username=student_id, password=password)

    if user is None:
        if obj.is_staff:
            logger.warning(
                f'Failed admin login for [{student_id}] IP={_get_ip(request)}'
            )
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

    # Admin — log in immediately, no face step.
    if user.is_staff or user.is_superuser:
        user.reset_failed_attempts()
        login(request, user)
        logger.info(f'Admin login OK: {student_id} IP={_get_ip(request)}')
        if is_ajax:
            return JsonResponse({
                'success':  True,
                'redirect': '/admin-dashboard/',
                'message':  f'Welcome back, {user.full_name}.',
            })
        return redirect('admin_dashboard:dashboard')

    # Voter — must pass face verification (Step 2).
    if not obj.face_embedding:
        return err(
            'No face data found for your account. '
            'Please re-register or contact the administrator.'
        )

    request.session['pending_face_pk']      = user.pk
    request.session['face_verify_attempts'] = 0
    request.session.save()

    logger.info(f'Step-1 OK for voter [{student_id}] — proceeding to face verify')

    if is_ajax:
        return JsonResponse({'success': True, 'require_face': True})
    return redirect('core:face_verify')


# 
# FACE VERIFY — PAGE  (non-JS fallback only)
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

    used = request.session.get('face_verify_attempts', 0)
    return render(request, 'core/face_verify.html', {
        'student':       student,
        'attempts_left': max(0, FACE_MAX_ATTEMPTS - used),
        'max_attempts':  FACE_MAX_ATTEMPTS,
    })



# FACE VERIFY — API
@csrf_exempt
@require_POST
def face_verify_api(request):
    #  Session guard 
    pk = request.session.get('pending_face_pk')
    if not pk:
        return _jerr('Session expired. Please log in again.', 401)

    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        return _jerr('Account not found.', 404)

    if student.is_staff:
        request.session.pop('pending_face_pk', None)
        request.session.pop('face_verify_attempts', None)
        logger.error(
            f'face_verify_api: staff account [{student.student_id}] '
            f'found in session — rejected and session cleared. '
            f'IP={_get_ip(request)}'
        )
        return _jerr('Invalid session state. Please log in again.', 400)

    # Parse request body
    try:
        body               = json.loads(request.body)
        frame_b64          = body.get('frame', '').strip()
        liveness_confirmed = body.get('liveness_confirmed', False)
    except (json.JSONDecodeError, TypeError):
        return _jerr('Invalid request body. Expected JSON.')

    if not frame_b64:
        return _jerr('No image received. Ensure camera access is allowed.')
    if not liveness_confirmed:
        return _jerr(
            'Liveness check not confirmed. '
            'Please blink or move your head first.'
        )

    #  Decode frame
    frame = _decode_b64(frame_b64)
    if frame is None:
        return _jerr('Could not decode the submitted image. Please try again.')
    attempt   = request.session.get('face_verify_attempts', 0) + 1
    remaining = max(0, FACE_MAX_ATTEMPTS - attempt)
    request.session['face_verify_attempts'] = attempt
    request.session.save()

    ip = _get_ip(request)

    # Run face verification 
    verifier          = FaceVerifier(bytes(student.face_embedding))
    matched, euc, cos = verifier.verify_with_score(frame)

    logger.info(
        f'face_verify [{student.student_id}] '
        f'attempt={attempt}/{FACE_MAX_ATTEMPTS} '
        f'euc={euc:.4f} cos={cos:.4f} '
        f'-> {"MATCH" if matched else "REJECT"}'
    )

    #  MISMATCH 
    if not matched:
        if euc > 0.70 and cos < 0.65:
            logger.warning(
                f'SECURITY: Likely impersonation on [{student.student_id}] — '
                f'live face clearly different from registered face. '
                f'euc={euc:.4f} cos={cos:.4f} IP={ip}'
            )
            FraudAlert.log_spoof_attempt(student, ip, euc, cos)  

        else:
            FraudAlert.log_face_mismatch(                         
                student      = student,
                ip           = ip,
                euc          = euc,
                cos          = cos,
                attempt      = attempt,
                max_attempts = FACE_MAX_ATTEMPTS,
            )

        #  Lockout after FACE_MAX_ATTEMPTS failures
        if attempt >= FACE_MAX_ATTEMPTS:
            student.locked_until          = (
                timezone.now() + timezone.timedelta(minutes=FACE_LOCKOUT_MIN)
            )
            student.failed_login_attempts = FACE_MAX_ATTEMPTS
            student.save(update_fields=['locked_until', 'failed_login_attempts'])

            request.session.pop('pending_face_pk', None)
            request.session.pop('face_verify_attempts', None)

            FraudAlert.log_account_locked(student, ip, FACE_LOCKOUT_MIN)  

            logger.warning(
                f'Voter [{student.student_id}] BLOCKED after '
                f'{FACE_MAX_ATTEMPTS} face failures for {FACE_LOCKOUT_MIN} min.'
            )
            return _jerr(
                f'Face verification failed {FACE_MAX_ATTEMPTS} times. '
                f'Your account has been blocked for {FACE_LOCKOUT_MIN} minutes. '
                f'Contact the administrator if this is a mistake.',
                code=403,
            )

        return _jerr(
            f'Face does not match the registered face. '
            f'{remaining} attempt{"s" if remaining != 1 else ""} remaining. '
            f'Ensure good lighting and look directly at the camera.'
        )

    # MATCH — complete the login 
    student.reset_failed_attempts()
    login(request, student)
    student.record_login(ip)  

    request.session.pop('pending_face_pk', None)
    request.session.pop('face_verify_attempts', None)

    logger.info(
        f'Voter login SUCCESS: [{student.student_id}] '
        f'euc={euc:.4f} cos={cos:.4f} IP={ip}'
    )

    return JsonResponse({
        'success':  True,
        'message':  f'Face matched! Welcome, {student.full_name}.',
        'redirect': '/voter-dashboard/',
    })



# LOGOUT
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



# JWT REST API  (for mobile / external API clients)
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