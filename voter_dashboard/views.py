# voter_dashboard/views.py  (fixed)
#
# Changes from original
# ─────────────────────
# [FIX-7]  Import FraudAlert so cast_vote can write security records.
# [FIX-8]  Write a 'face_mismatch' FraudAlert when a voter attempts to vote
#          outside the election window.  Previously a silent redirect with
#          no admin visibility.
# [FIX-9]  Write a 'too_many_attempts' FraudAlert when a voter attempts to
#          vote a second time in the same election.  The alert_type closest
#          to "duplicate vote" in the existing ALERT_TYPES choices is
#          'too_many_attempts'; a dedicated 'duplicate_vote' type can be
#          added to FraudAlert.ALERT_TYPES and a new factory method added to
#          FraudAlert without touching this file.
# [FIX-10] The double-encryption bug is fixed: the view no longer calls
#          encrypt_vote() itself. Vote.save() is the single source of truth
#          for encryption — it encrypts the candidate name if encrypted_data
#          is not already set.  The view just calls Vote.objects.create()
#          without passing encrypted_data.

import logging

from django.shortcuts      import render, redirect, get_object_or_404
from django.contrib        import messages
from django.contrib.auth.decorators import login_required
from django.utils          import timezone

from core.models           import Student
from .models               import Election, Candidate, Vote
from .services.vote_service import decrypt_vote

# [FIX-7] Import FraudAlert to write security events from the voting layer.
from admin_dashboard.models import FraudAlert

logger = logging.getLogger(__name__)


def _get_ip(request) -> str:
    """Extract real client IP, respecting X-Forwarded-For."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


@login_required
def dashboard(request):
    """Voter dashboard: shows active elections and which ones this voter has voted in."""
    student = request.user
    active_elections = Election.objects.filter(
        start_time__lte=timezone.now(),
        end_time__gte=timezone.now(),
        is_active=True,
    )
    voted_election_ids = Vote.objects.filter(
        voter=student
    ).values_list('election_id', flat=True)

    return render(request, 'voter_dashboard/dashboard.html', {
        'active_elections':    active_elections,
        'voted_election_ids':  voted_election_ids,
    })


@login_required
def cast_vote(request, election_id):
    """
    Cast a vote for a candidate in a specific election.

    Gate 1 — election window check.
    Gate 2 — duplicate vote check.
    Both gates now write FraudAlert records so the admin dashboard
    surfaces attempted violations in real time.  [FIX-8, FIX-9]

    Encryption is handled entirely by Vote.save() — the view no longer
    calls encrypt_vote() directly.  [FIX-10]
    """
    student  = request.user
    election = get_object_or_404(Election, pk=election_id)
    ip       = _get_ip(request)

    # ── Gate 1: Election window ────────────────────────────────────────────────
    now = timezone.now()
    if not election.is_active or election.start_time > now or election.end_time < now:

        # [FIX-8] Write a FraudAlert so the admin knows someone tried to vote
        # outside the permitted window — could indicate session replay or a
        # race condition exploit.  alert_type='face_mismatch' is repurposed
        # here as the closest available catch-all; add 'invalid_vote_attempt'
        # to ALERT_TYPES for a cleaner label if preferred.
        FraudAlert.objects.create(
            voter       = student,
            election    = election,
            alert_type  = 'face_mismatch',   # closest existing type; rename if desired
            ip_address  = ip,
            description = (
                f"{student.full_name} ({student.student_id}) attempted to vote "
                f"in '{election.title}' outside the permitted window. "
                f"is_active={election.is_active} "
                f"start={election.start_time} end={election.end_time} now={now}."
            ),
        )

        logger.warning(
            f'Out-of-window vote attempt by [{student.student_id}] '
            f'on election [{election_id}] IP={ip}'
        )
        messages.error(request, 'This election is not active.')
        return redirect('voter_dashboard:dashboard')

    # ── Gate 2: Duplicate vote ─────────────────────────────────────────────────
    if Vote.objects.filter(voter=student, election=election).exists():

        # [FIX-9] Write a FraudAlert for the duplicate attempt.  The DB
        # unique_together constraint is still the hard backstop, but this
        # alert fires first so the admin sees it immediately.
        FraudAlert.objects.create(
            voter       = student,
            election    = election,
            alert_type  = 'too_many_attempts',
            ip_address  = ip,
            description = (
                f"{student.full_name} ({student.student_id}) attempted to vote "
                f"more than once in '{election.title}'. "
                f"A Vote record already exists for this voter/election pair."
            ),
        )

        logger.warning(
            f'Duplicate vote attempt by [{student.student_id}] '
            f'on election [{election_id}] IP={ip}'
        )
        messages.warning(request, 'You have already voted in this election.')
        return redirect('voter_dashboard:dashboard')

    candidates = election.candidates.all()

    if request.method == 'POST':
        candidate_id = request.POST.get('candidate')
        candidate    = get_object_or_404(Candidate, pk=candidate_id, election=election)

        # [FIX-10] Do NOT call encrypt_vote() here.  Vote.save() already
        # encrypts the candidate name when encrypted_data is absent.
        # Calling encrypt_vote() in the view AND letting save() re-encrypt
        # would result in the token being encrypted twice if the guard in
        # save() ever changes.  Single responsibility: model owns encryption.
        Vote.objects.create(
            voter     = student,
            election  = election,
            candidate = candidate,
            # encrypted_data intentionally omitted — Vote.save() handles it
        )

        logger.info(
            f'Vote cast: [{student.student_id}] → candidate [{candidate_id}] '
            f'in election [{election_id}] IP={ip}'
        )
        messages.success(request, f'Your vote for {candidate.name} has been recorded.')
        return redirect('voter_dashboard:dashboard')

    return render(request, 'voter_dashboard/cast_vote.html', {
        'election':   election,
        'candidates': candidates,
    })


@login_required
def profile(request):
    """Shows the voter's profile with decrypted vote history."""
    student = request.user
    votes   = Vote.objects.filter(voter=student).select_related('election', 'candidate')

    vote_history = []
    for vote in votes:
        decrypted_candidate = (
            decrypt_vote(vote.encrypted_data) if vote.encrypted_data else 'N/A'
        )
        vote_history.append({
            'election':           vote.election,
            'candidate':          vote.candidate,
            'decrypted_candidate': decrypted_candidate,
            'timestamp':          vote.timestamp,
        })

    return render(request, 'voter_dashboard/profile.html', {
        'student':      student,
        'vote_history': vote_history,
    })