# voter_dashboard/views.py  



import json
import base64
import logging

import cv2
import numpy as np

from django.contrib.auth.decorators import login_required
from django.http                    import JsonResponse, HttpResponse
from django.shortcuts               import render, redirect, get_object_or_404
from django.utils                   import timezone
from django.views.decorators.csrf   import csrf_exempt
from django.views.decorators.http   import require_POST, require_GET
from django.db                      import IntegrityError

from .models import Election, Candidate, Vote, Notification

logger = logging.getLogger(__name__)


# Auth guard helper 

def _voter_required(view_func):
    @login_required(login_url='core:login')
    def wrapper(request, *args, **kwargs):
        if request.user.is_staff or request.user.is_superuser:
            return redirect('admin_dashboard:dashboard')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def _get_ip(request) -> str:
    fwd = request.META.get('HTTP_X_FORWARDED_FOR')
    return fwd.split(',')[0].strip() if fwd else request.META.get('REMOTE_ADDR', '')


def _decode_b64_frame(b64: str):
    """Decode a base64 or data-URI string to a BGR OpenCV ndarray."""
    try:
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.error(f'_decode_b64_frame: {exc}')
        return None


# Dashboard 

@_voter_required
def dashboard(request):
    now              = timezone.now()
    active_elections = Election.objects.filter(is_active=True, end_time__gt=now)
    voted_ids        = list(
        Vote.objects.filter(voter=request.user, election__in=active_elections)
                    .values_list('election_id', flat=True)
    )
    unread_count = Notification.objects.filter(voter=request.user, is_read=False).count()
    return render(request, 'voter_dashboard/dashboard.html', {
        'active_elections': active_elections,
        'voted_ids':        voted_ids,
        'active_count':     active_elections.count(),
        'votes_cast':       Vote.objects.filter(voter=request.user).count(),
        'remaining':        active_elections.count() - len(voted_ids),
        'unread_count':     unread_count,
    })


#  Cast vote GET shows the gate; POST submits the ballot 

@_voter_required
def cast_vote(request, election_id):
    election   = get_object_or_404(Election, pk=election_id, is_active=True)
    candidates = election.candidates.all()
    now        = timezone.now()

    if now > election.end_time:
        return render(request, 'voter_dashboard/election_closed.html', {'election': election})

    if Vote.objects.filter(voter=request.user, election=election).exists():
        return redirect('voter_dashboard:dashboard')

    if request.method == 'POST':
        if not request.session.get(f'vote_liveness_ok_{election_id}'):
            return render(request, 'voter_dashboard/cast_vote.html', {
                'election':   election,
                'candidates': candidates,
                'error':      'Identity verification required. Please complete the face check.',
            })

        candidate_id = request.POST.get('candidate_id') or request.POST.get('candidate')
        if not candidate_id:
            return render(request, 'voter_dashboard/cast_vote.html', {
                'election': election, 'candidates': candidates,
                'error': 'Please select a candidate.',
            })
        candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)
        try:
            Vote.objects.create(voter=request.user, election=election, candidate=candidate)
            request.session.pop(f'vote_liveness_ok_{election_id}', None)
            logger.info(
                f"Vote cast: voter={request.user.student_id} "
                f"election={election_id} candidate={candidate.name}"
            )
            return redirect('voter_dashboard:election_results', election_id=election_id)
        except IntegrityError:
            return redirect('voter_dashboard:dashboard')

    # GET — clear any stale session flag, render the page
    request.session.pop(f'vote_liveness_ok_{election_id}', None)
    return render(request, 'voter_dashboard/cast_vote.html', {
        'election': election, 'candidates': candidates,
    })


#  Vote liveness verify 
@csrf_exempt
@require_POST
@login_required(login_url='core:login')
def vote_liveness_verify(request, election_id):
    """
    POST /voter-dashboard/vote/<id>/liveness/
    JSON body: { frame: "<base64-jpeg>", liveness_confirmed: true }

    Runs:
      1. Decode the JPEG frame
      2. Server-side liveness gesture check   (LivenessChallenge.verify)
      3. Face identity match against student's stored embedding (FaceVerifier)

    Returns:
      { verified: true,  message: "..." }  — on success, also sets session flag
      { verified: false, error:   "..." }  — on any failure
    """
    student = request.user
    ip      = _get_ip(request)

    def jerr(msg: str, code: int = 400):
        return JsonResponse({'verified': False, 'error': msg}, status=code)

    
    if not student.face_embedding:
        return jerr(
            'No face data registered for your account. '
            'Please contact the administrator.',
            400,
        )

    election = get_object_or_404(Election, pk=election_id)
    now      = timezone.now()
    if not election.is_active or now > election.end_time:
        return jerr('This election is no longer active.', 403)

    if Vote.objects.filter(voter=student, election=election).exists():
        return jerr('You have already voted in this election.', 403)

    
    try:
        body               = json.loads(request.body)
        frame_b64          = body.get('frame', '').strip()
        liveness_confirmed = body.get('liveness_confirmed', False)
    except (json.JSONDecodeError, TypeError):
        return jerr('Invalid request body.')

    if not frame_b64:
        return jerr('No image received.')
    if not liveness_confirmed:
        return jerr('Please complete the liveness gesture first.')

    frame = _decode_b64_frame(frame_b64)
    if frame is None:
        return jerr('Could not decode the submitted image. Please try again.')

    
    try:
        from core.services.liveness import LivenessChallenge, CHALLENGE_POOL
    except ImportError as exc:
        logger.error(f'vote_liveness_verify: cannot import LivenessChallenge: {exc}')
        return jerr('Server configuration error. Contact administrator.', 500)

    challenges   = request.session.get('liveness_challenges', [])
    challenge_id = (
        challenges[0]
        if challenges and challenges[0] in CHALLENGE_POOL
        else 'blink'
    )

    liveness_checker      = LivenessChallenge()
    live_ok, live_msg     = liveness_checker.verify(frame, challenge_id)

    if not live_ok:
        logger.warning(
            f'vote_liveness_verify: LIVENESS FAIL '
            f'[{student.student_id}] challenge={challenge_id}: {live_msg}'
        )
        spoof_kw = ('photo', 'screen', 'multiple', 'replay', 'pixel-grid', 'printout')
        if any(kw in live_msg.lower() for kw in spoof_kw):
            try:
                from admin_dashboard.models import FraudAlert
                FraudAlert.log_spoof_attempt(student, ip, euc=0.0, cos=0.0)
            except Exception:
                pass
            return jerr(f'Security alert: {live_msg}', 403)
        # Non-spoof liveness fail — report to user, allow retry
        return jerr(f'Liveness check failed: {live_msg}. Please try again.')

    #  Face identity match 
    try:
        from core.services.face_verifier import FaceVerifier
    except ImportError as exc:
        logger.error(f'vote_liveness_verify: cannot import FaceVerifier: {exc}')
        return jerr('Server configuration error. Contact administrator.', 500)

    verifier          = FaceVerifier(bytes(student.face_embedding))
    matched, euc, cos = verifier.verify_with_score(frame)

    logger.info(
        f'vote_liveness_verify [{student.student_id}] '
        f'challenge={challenge_id} cos={cos:.4f} euc={euc:.4f} '
        f'→ {"MATCH ✓" if matched else "REJECT ✗"}'
    )

    if not matched:
        try:
            from admin_dashboard.models import FraudAlert
            if cos < 0.80:
                FraudAlert.log_spoof_attempt(student, ip, euc, cos)
            else:
                FraudAlert.log_face_mismatch(
                    student=student, ip=ip, euc=euc, cos=cos,
                    attempt=1, max_attempts=3,
                )
        except Exception:
            pass
        return jerr(
            f'Face does not match your registered identity '
            f'(similarity {cos:.2f}). '
            f'Ensure good lighting, remove glasses, and look directly at the camera.',
            403,
        )

    #  Success — set session flag so the POST ballot submission is allowed
    request.session[f'vote_liveness_ok_{election_id}'] = True
    request.session.save()

    return JsonResponse({
        'verified': True,
        'message':  f'Identity confirmed, {student.full_name}. You may now cast your vote.',
    })


# Election results 

@_voter_required
def election_results(request, election_id):
    election   = get_object_or_404(Election, pk=election_id)
    candidates = election.candidates.all()
    results    = []
    total      = Vote.objects.filter(election=election).count()

    for c in candidates:
        count = Vote.objects.filter(election=election, candidate=c).count()
        results.append({
            'candidate': c,
            'count':     count,
            'pct':       round((count / total * 100) if total else 0, 1),
        })

    results.sort(key=lambda x: x['count'], reverse=True)

    voter_voted = Vote.objects.filter(voter=request.user, election=election).exists()

    # Winner / tie detection
    is_tie          = False
    winner          = None
    tied_candidates = []
    if results:
        top = results[0]['count']
        if top > 0:
            leaders = [r for r in results if r['count'] == top]
            if len(leaders) > 1:
                is_tie          = True
                tied_candidates = leaders
            else:
                winner = results[0]

    chart_labels = [r['candidate'].name for r in results]
    chart_votes  = [r['count']          for r in results]

    return render(request, 'voter_dashboard/election_results.html', {
        'election':         election,
        'results':          results,
        'total_votes':      total,
        'voter_voted':      voter_voted,
        'is_tie':           is_tie,
        'winner':           winner,
        'tied_candidates':  tied_candidates,
        'chart_labels':     json.dumps(chart_labels),
        'chart_votes':      json.dumps(chart_votes),
    })


#  Results PDF (stub) 

@_voter_required
def results_pdf(request, election_id):
    return HttpResponse('PDF export not yet implemented.', content_type='text/plain')


# Profile 
@_voter_required
def profile(request):
    return render(request, 'voter_dashboard/profile.html', {'student': request.user})


# Settings 

@_voter_required
def settings_view(request):
    student = request.user
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def ok(msg):
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg})
        from django.contrib import messages as msgs
        msgs.success(request, msg)
        return redirect('voter_dashboard:settings')

    def err(msg):
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg})
        from django.contrib import messages as msgs
        msgs.error(request, msg)
        return redirect('voter_dashboard:settings')

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'preferences':
            student.notify_election_open    = 'notify_election_open'    in request.POST
            student.notify_election_close   = 'notify_election_close'   in request.POST
            student.notify_election_results = 'notify_election_results' in request.POST
            student.save(update_fields=[
                'notify_election_open',
                'notify_election_close',
                'notify_election_results',
            ])
            return ok('Notification preferences saved.')

        if form_type == 'change_phone':
            new_phone      = request.POST.get('new_phone', '').strip()
            phone_password = request.POST.get('phone_password', '')
            if not new_phone:
                return err('Please enter a new phone number.')
            if not phone_password:
                return err('Please confirm your password.')
            if not student.check_password(phone_password):
                return err('Incorrect password.')
            student.phone = new_phone
            student.save(update_fields=['phone'])
            return ok('Phone number updated successfully.')

        if form_type == 'change_password':
            current = request.POST.get('current_password', '')
            new_pw  = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            if not current or not new_pw or not confirm:
                return err('All password fields are required.')
            if not student.check_password(current):
                return err('Current password is incorrect.')
            if len(new_pw) < 8:
                return err('New password must be at least 8 characters.')
            if new_pw != confirm:
                return err('New passwords do not match.')
            student.set_password(new_pw)
            student.save(update_fields=['password'])
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, student)
            return ok('Password changed successfully.')

        return err('Unknown form submission.')

    return render(request, 'voter_dashboard/settings.html', {'student': student})


# Download  data 

@_voter_required
def download_my_data(request):
    student = request.user
    votes   = Vote.objects.filter(voter=student).select_related('election', 'candidate')
    data    = {
        'student_id': student.student_id,
        'full_name':  student.full_name,
        'department': student.department,
        'votes': [
            {
                'election':  v.election.title,
                'candidate': v.candidate.name,
                'timestamp': v.timestamp.isoformat(),
            }
            for v in votes
        ],
    }
    response = HttpResponse(
        json.dumps(data, indent=2),
        content_type='application/json',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="{student.student_id}_data.json"'
    )
    return response


#  NOTIFICATION VIEWS


@_voter_required
def notifications(request):
    notifs = Notification.objects.filter(voter=request.user).select_related('election')
    Notification.objects.filter(voter=request.user, is_read=False).update(is_read=True)
    return render(request, 'voter_dashboard/notifications.html', {
        'notifications': notifs,
        'unread_count':  0,
    })


@require_GET
@login_required(login_url='core:login')
def notifications_count(request):
    count = Notification.objects.filter(voter=request.user, is_read=False).count()
    return JsonResponse({'count': count})


@require_POST
@login_required(login_url='core:login')
def mark_notification_read(request, notif_id):
    notif = get_object_or_404(Notification, pk=notif_id, voter=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    return JsonResponse({'success': True})


@require_POST
@login_required(login_url='core:login')
def mark_all_read(request):
    Notification.objects.filter(voter=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True})


@require_POST
@login_required(login_url='core:login')
def delete_notification(request, notif_id):
    notif = get_object_or_404(Notification, pk=notif_id, voter=request.user)
    notif.delete()
    return JsonResponse({'success': True})