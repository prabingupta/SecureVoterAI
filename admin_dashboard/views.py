# admin_dashboard/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse

from core.models import Student
from voter_dashboard.models import Election, Candidate, Vote
from .models import ElectionLog, FraudAlert


# Guard decorator 

def admin_required(view_func):
    decorated = user_passes_test(
        lambda u: u.is_active and (u.is_staff or u.is_superuser),
        login_url='core:login'
    )(view_func)
    return login_required(login_url='core:login')(decorated)


# Shared context 

def _base_ctx():
    unresolved = FraudAlert.objects.filter(reviewed=False)
    return {
        'pending_count':          Student.objects.filter(
                                      approval_status='pending',
                                      is_staff=False
                                  ).count(),
        'unresolved_fraud_count': unresolved.count(),
        'recent_fraud_alerts':    unresolved.select_related('voter')
                                            .order_by('-timestamp')[:5],
    }


#  DATETIME HELPER 

def _parse_dt(value: str):
    if not value:
        return None
    dt = parse_datetime(value)           
    if dt is None:
        return None
    return timezone.make_aware(dt, timezone.get_current_timezone())


#  DASHBOARD 

@admin_required
def dashboard(request):
    all_alerts       = FraudAlert.objects.select_related('voter', 'election').order_by('-timestamp')
    active_elections = Election.objects.filter(is_active=True)
    pending_voters   = Student.objects.filter(approval_status='pending', is_staff=False)
    total_votes      = Vote.objects.count()
    total_approved   = Student.objects.filter(approval_status='approved', is_staff=False).count()
    unresolved_count = all_alerts.filter(reviewed=False).count()
    resolved_count   = all_alerts.filter(reviewed=True).count()

    ctx = _base_ctx()
    ctx.update({
        'active_elections':      active_elections,
        'pending_voters':        pending_voters,
        'total_votes':           total_votes,
        'fraud_alerts':          all_alerts,
        'total_approved_voters': total_approved,
        'unresolved_count':      unresolved_count,
        'resolved_count':        resolved_count,
    })
    return render(request, 'admin_dashboard/dashboard.html', ctx)


# VOTER MANAGEMENT 

@admin_required
def manage_voters(request):
    voters = Student.objects.filter(is_staff=False).order_by('-id')
    ctx = _base_ctx()
    ctx['voters'] = voters
    return render(request, 'admin_dashboard/manage_voters.html', ctx)


@admin_required
def approve_voter(request, student_id):
    student = get_object_or_404(Student, pk=student_id, is_staff=False)
    student.approval_status = 'approved'
    student.approval_note   = ''
    student.save(update_fields=['approval_status', 'approval_note'])
    messages.success(request, f'{student.full_name} has been approved and can now vote.')
    return redirect('admin_dashboard:manage_voters')


@admin_required
def reject_voter(request, student_id):
    student = get_object_or_404(Student, pk=student_id, is_staff=False)
    note    = request.POST.get('note', '').strip()
    student.approval_status = 'rejected'
    student.approval_note   = note
    student.save(update_fields=['approval_status', 'approval_note'])
    messages.warning(request, f'{student.full_name} has been rejected.')
    return redirect('admin_dashboard:manage_voters')


#  ELECTION MANAGEMENT 

@admin_required
def manage_elections(request):
    elections = Election.objects.all().order_by('-id')
    ctx = _base_ctx()
    ctx['elections'] = elections
    return render(request, 'admin_dashboard/manage_elections.html', ctx)


@admin_required
def add_election(request):
    form_data = {}
    if request.method == 'POST':
        title            = request.POST.get('title', '').strip()
        description      = request.POST.get('description', '').strip()
        start_time_raw   = request.POST.get('start_time', '')
        end_time_raw     = request.POST.get('end_time', '')
        is_active        = request.POST.get('is_active') == 'on'

        
        form_data = {
            'title':       title,
            'description': description,
            'start_time':  start_time_raw,
            'end_time':    end_time_raw,
            'is_active':   is_active,
        }

        start_time = _parse_dt(start_time_raw)
        end_time   = _parse_dt(end_time_raw)

        if not title or not start_time_raw or not end_time_raw:
            messages.error(request, 'Title, start time, and end time are required.')
        elif start_time is None:
            messages.error(request, 'Start time is not a valid date/time.')
        elif end_time is None:
            messages.error(request, 'End time is not a valid date/time.')
        elif end_time <= start_time:
            messages.error(request, 'End time must be after start time.')
        else:
            election = Election.objects.create(
                title=title,
                description=description,
                start_time=start_time,   
                end_time=end_time,       
                is_active=is_active,
            )
            ElectionLog.objects.create(election=election, action='created')
            messages.success(request, f'Election "{title}" created successfully.')
            return redirect('admin_dashboard:manage_elections')

    ctx = _base_ctx()
    ctx.update({'form_data': form_data, 'election': None})
    return render(request, 'admin_dashboard/add_election.html', ctx)


@admin_required
def edit_election(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        description    = request.POST.get('description', '').strip()
        start_time_raw = request.POST.get('start_time', '')
        end_time_raw   = request.POST.get('end_time', '')
        is_active      = request.POST.get('is_active') == 'on'

        start_time = _parse_dt(start_time_raw)
        end_time   = _parse_dt(end_time_raw)

        if not title or not start_time_raw or not end_time_raw:
            messages.error(request, 'Title, start time, and end time are required.')
        elif start_time is None:
            messages.error(request, 'Start time is not a valid date/time.')
        elif end_time is None:
            messages.error(request, 'End time is not a valid date/time.')
        elif end_time <= start_time:
            messages.error(request, 'End time must be after start time.')
        else:
            election.title       = title
            election.description = description
            election.start_time  = start_time   # ← datetime object
            election.end_time    = end_time     # ← datetime object
            election.is_active   = is_active
            election.save()
            messages.success(request, f'Election "{title}" updated.')
            return redirect('admin_dashboard:manage_elections')

    ctx = _base_ctx()
    ctx['election'] = election
    return render(request, 'admin_dashboard/add_election.html', ctx)


@admin_required
def delete_election(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    title = election.title
    election.delete()
    messages.success(request, f'Election "{title}" deleted.')
    return redirect('admin_dashboard:manage_elections')


@admin_required
def open_election(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    election.is_active = True
    election.save(update_fields=['is_active'])
    ElectionLog.objects.create(election=election, action='opened')
    messages.success(request, f'"{election.title}" is now open for voting.')
    return redirect('admin_dashboard:manage_elections')


@admin_required
def close_election(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    election.is_active = False
    election.save(update_fields=['is_active'])
    ElectionLog.objects.create(election=election, action='closed')
    messages.success(request, f'"{election.title}" has been closed.')
    return redirect('admin_dashboard:manage_elections')


#  CANDIDATE MANAGEMENT
@admin_required
def manage_candidates(request):
    candidates = Candidate.objects.select_related('election').all().order_by('election', 'name')
    elections  = Election.objects.all()
    ctx = _base_ctx()
    ctx.update({'candidates': candidates, 'elections': elections})
    return render(request, 'admin_dashboard/manage_candidates.html', ctx)


@admin_required
def add_candidate(request):
    elections = Election.objects.all()
    form_data = {'name': '', 'description': '', 'election_id': ''}

    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        election_id = request.POST.get('election', '')
        description = request.POST.get('description', '').strip()
        photo       = request.FILES.get('photo')

        form_data = {'name': name, 'description': description, 'election_id': election_id}

        if not name or not election_id:
            messages.error(request, 'Candidate name and election are required.')
        else:
            election  = get_object_or_404(Election, pk=election_id)
            candidate = Candidate(name=name, election=election, description=description)
            if photo:
                candidate.photo = photo
            candidate.save()
            messages.success(request, f'Candidate "{name}" added to {election.title}.')
            return redirect('admin_dashboard:manage_candidates')

    ctx = _base_ctx()
    ctx.update({'elections': elections, 'candidate': None, 'form_data': form_data})
    return render(request, 'admin_dashboard/candidate_form.html', ctx)


@admin_required
def edit_candidate(request, candidate_id):
    candidate = get_object_or_404(Candidate, pk=candidate_id)
    elections = Election.objects.all()

    if request.method == 'POST':
        name         = request.POST.get('name', '').strip()
        election_id  = request.POST.get('election', '')
        description  = request.POST.get('description', '').strip()
        photo        = request.FILES.get('photo')
        remove_photo = request.POST.get('photo-clear') == 'on'

        if not name or not election_id:
            messages.error(request, 'Candidate name and election are required.')
        else:
            candidate.name        = name
            candidate.election    = get_object_or_404(Election, pk=election_id)
            candidate.description = description
            if remove_photo and candidate.photo:
                candidate.photo.delete(save=False)
                candidate.photo = None
            elif photo:
                candidate.photo = photo
            candidate.save()
            messages.success(request, f'Candidate "{name}" updated.')
            return redirect('admin_dashboard:manage_candidates')

    ctx = _base_ctx()
    ctx.update({
        'candidate': candidate,
        'elections': elections,
        'form_data': {
            'name':        candidate.name,
            'description': candidate.description,
            'election_id': str(candidate.election_id),
        },
    })
    return render(request, 'admin_dashboard/candidate_form.html', ctx)


@admin_required
def delete_candidate(request, candidate_id):
    candidate = get_object_or_404(Candidate, pk=candidate_id)
    name = candidate.name
    candidate.delete()
    messages.success(request, f'Candidate "{name}" removed.')
    return redirect('admin_dashboard:manage_candidates')


#  FRAUD ALERTS 

@admin_required
def view_fraud_alerts(request):
    fraud_alerts     = FraudAlert.objects.select_related('voter', 'election').order_by('-timestamp')
    unresolved_count = fraud_alerts.filter(reviewed=False).count()
    resolved_count   = fraud_alerts.filter(reviewed=True).count()

    ctx = _base_ctx()
    ctx.update({
        'fraud_alerts':     fraud_alerts,
        'unresolved_count': unresolved_count,
        'resolved_count':   resolved_count,
    })
    return render(request, 'admin_dashboard/fraud_alerts.html', ctx)


@admin_required
def mark_reviewed(request, alert_id):
    alert          = get_object_or_404(FraudAlert, pk=alert_id)
    alert.reviewed = True
    alert.save(update_fields=['reviewed'])
    messages.success(request, 'Fraud alert marked as reviewed.')
    referer = request.META.get('HTTP_REFERER', '')
    if 'fraud-log' in referer:
        return redirect('admin_dashboard:fraud_log_report')
    return redirect('admin_dashboard:view_fraud_alerts')


#  NOTIFICATIONS 

@admin_required
def notifications(request):
    fraud_alerts = FraudAlert.objects.select_related('voter', 'election').order_by('-timestamp')

    unresolved_count = fraud_alerts.filter(reviewed=False).count()
    resolved_count   = fraud_alerts.filter(reviewed=True).count()
    spoof_count      = fraud_alerts.filter(alert_type='spoof_attempt').count()
    locked_count     = fraud_alerts.filter(alert_type='too_many_attempts').count()

    ctx = _base_ctx()
    ctx.update({
        'fraud_alerts':     fraud_alerts,
        'unresolved_count': unresolved_count,
        'resolved_count':   resolved_count,
        'spoof_count':      spoof_count,
        'locked_count':     locked_count,
    })
    return render(request, 'admin_dashboard/notifications.html', ctx)


#  LIVE RESULTS 
def live_results(request, election_id):
    election   = get_object_or_404(Election, pk=election_id)
    candidates = Candidate.objects.filter(election=election)
    results    = [
        {'candidate': c, 'votes': Vote.objects.filter(candidate=c).count()}
        for c in candidates
    ]
    total = sum(r['votes'] for r in results)
    for r in results:
        r['pct'] = round((r['votes'] / total * 100), 1) if total > 0 else 0

    ctx = _base_ctx()
    ctx.update({'election': election, 'results': results, 'total': total})
    return render(request, 'admin_dashboard/live_results.html', ctx)


@admin_required
def generate_reports(request):
    elections = Election.objects.all()
    report = []
    for e in elections:
        candidates = Candidate.objects.filter(election=e)
        report.append({
            'election':    e,
            'total_votes': Vote.objects.filter(candidate__election=e).count(),
            'candidates':  [
                {'name': c.name, 'votes': Vote.objects.filter(candidate=c).count()}
                for c in candidates
            ],
        })
    ctx = _base_ctx()
    ctx['report'] = report
    return render(request, 'admin_dashboard/reports.html', ctx)


#  FRAUD LOG REPORT 

@admin_required
def fraud_log_report(request):
    fraud_alerts = FraudAlert.objects.select_related('voter', 'election').order_by('-timestamp')

    unresolved_count = fraud_alerts.filter(reviewed=False).count()
    resolved_count   = fraud_alerts.filter(reviewed=True).count()
    spoof_count      = fraud_alerts.filter(alert_type='spoof_attempt').count()
    locked_count     = fraud_alerts.filter(alert_type='too_many_attempts').count()

    ctx = _base_ctx()
    ctx.update({
        'fraud_alerts':     fraud_alerts,
        'unresolved_count': unresolved_count,
        'resolved_count':   resolved_count,
        'spoof_count':      spoof_count,
        'locked_count':     locked_count,
    })
    return render(request, 'admin_dashboard/fraud_log_report.html', ctx)