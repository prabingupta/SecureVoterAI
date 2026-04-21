# admin_dashboard/views_analytics.py


import json
from datetime import date, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models                       import Count, Q
from django.db.models.functions             import TruncDate
from django.shortcuts                       import render
from django.utils                           import timezone

from core.models import Student



def _jdump(obj) -> str:
    """Safely dump a Python object to a JSON string for inline template use."""
    return json.dumps(obj, default=str)



@staff_member_required(login_url='core:login')
def analytics_dashboard(request):

    voters = Student.objects.filter(is_staff=False)

   
    total_voters    = voters.count()
    approved_voters = voters.filter(approval_status='approved').count()
    pending_voters  = voters.filter(approval_status='pending').count()
    rejected_voters = voters.filter(approval_status='rejected').count()
    with_face       = voters.filter(face_embedding__isnull=False).count()
    without_face    = total_voters - with_face

    
    with_photo      = voters.filter(profile_photo__isnull=False).exclude(profile_photo='').count()
    without_photo   = total_voters - with_photo

   
    gender_qs = (
        voters
        .values('gender')
        .annotate(n=Count('id'))
        .order_by('gender')
    )
    gender_map = {}
    for g in gender_qs:
        key = g['gender'] if g['gender'] else 'not_specified'
        gender_map[key] = g['n']

    gender_data = {
        'labels': ['Male', 'Female', 'Not Specified'],
        'values': [
            gender_map.get('male',          0),
            gender_map.get('female',        0),
            gender_map.get('not_specified', 0),
        ],
    }

   
    age_groups = {'18-22': 0, '23-27': 0, '28-35': 0, 'Unknown': 0}
    for v in voters.values('age'):
        a = v['age']
        if a is None:
            age_groups['Unknown'] += 1
        elif a <= 22:
            age_groups['18-22'] += 1
        elif a <= 27:
            age_groups['23-27'] += 1
        else:
            age_groups['28-35'] += 1

    age_data = {
        'labels': list(age_groups.keys()),
        'values': list(age_groups.values()),
    }

  
    dept_qs = (
        voters
        .values('department')
        .annotate(n=Count('id'))
        .order_by('department')
    )
    dept_data = {
        'labels': [d['department'] or 'Unknown' for d in dept_qs],
        'values': [d['n'] for d in dept_qs],
    }

     
    year_qs = (
        voters
        .values('year_of_study')
        .annotate(n=Count('id'))
        .order_by('year_of_study')
    )
    year_data = {
        'labels': [f"Year {y['year_of_study']}" if y['year_of_study'] else 'Unknown'
                   for y in year_qs],
        'values': [y['n'] for y in year_qs],
    }


    notif_base = approved_voters if approved_voters else 1   
    notif_open_count    = voters.filter(notify_election_open=True).count()
    notif_close_count   = voters.filter(notify_election_close=True).count()
    notif_results_count = voters.filter(notify_election_results=True).count()

    notif_data = {
        'labels': ['Election Opens', 'Election Closes', 'Results Published'],
        'opted_in': [
            notif_open_count,
            notif_close_count,
            notif_results_count,
        ],
        'opted_out': [
            approved_voters - notif_open_count,
            approved_voters - notif_close_count,
            approved_voters - notif_results_count,
        ],
        'pcts': [
            round(notif_open_count    / notif_base * 100, 1),
            round(notif_close_count   / notif_base * 100, 1),
            round(notif_results_count / notif_base * 100, 1),
        ],
    }

  
    total_votes    = 0
    voted_voters   = 0
    not_voted      = approved_voters
    elections_data = {'labels': [], 'cast': [], 'eligible': [], 'turnout_pct': []}

    try:
        from voter_dashboard.models import Vote, Election

        total_votes  = Vote.objects.count()
        voted_voters = Vote.objects.values('voter').distinct().count()
        not_voted    = max(0, approved_voters - voted_voters)

        
       
        elections = list(Election.objects.order_by('-start_time')[:8])
        for el in reversed(elections):
            cast     = Vote.objects.filter(election=el).count()
            eligible = approved_voters
            pct      = round(cast / eligible * 100, 1) if eligible else 0
            short    = el.title[:22] + ('…' if len(el.title) > 22 else '')
            elections_data['labels'].append(short)
            elections_data['cast'].append(cast)
            elections_data['eligible'].append(eligible)
            elections_data['turnout_pct'].append(pct)

    except Exception:
        pass   

   
    fraud_data  = {'labels': [], 'values': [], 'colors': []}
    total_fraud = 0

    try:
        from admin_dashboard.models import FraudAlert

        fraud_type_colors = {
            'spoof_attempt':     '#9B1821',
            'face_mismatch':     '#E8B800',
            'multiple_faces':    '#C84B31',
            'too_many_attempts': '#D96470',
            'unknown_device':    '#1E40AF',
        }

        fraud_qs = (
            FraudAlert.objects
            .values('alert_type')
            .annotate(n=Count('id'))
            .order_by('-n')
        )
        for row in fraud_qs:
            label = row['alert_type'].replace('_', ' ').title()
            fraud_data['labels'].append(label)
            fraud_data['values'].append(row['n'])
            fraud_data['colors'].append(
                fraud_type_colors.get(row['alert_type'], '#8F7060')
            )

        total_fraud = sum(fraud_data['values'])

    except Exception:
        pass

   
   
    today      = date.today()
    thirty_ago = today - timedelta(days=29)

    trend_labels: list[str] = []
    trend_values: list[int] = []

    try:
        reg_qs = (
            voters
            .filter(last_login__date__gte=thirty_ago)
            .annotate(day=TruncDate('last_login'))
            .values('day')
            .annotate(n=Count('id'))
            .order_by('day')
        )
        reg_map = {row['day']: row['n'] for row in reg_qs}
    except Exception:
        reg_map = {}

    for i in range(30):
        d = thirty_ago + timedelta(days=i)
        trend_labels.append(d.strftime('%b %d'))
        trend_values.append(reg_map.get(d, 0))

    
    approval_rate = round(approved_voters / total_voters   * 100, 1) if total_voters   else 0
    turnout_rate  = round(voted_voters    / approved_voters * 100, 1) if approved_voters else 0
    face_rate     = round(with_face       / total_voters   * 100, 1) if total_voters   else 0
    photo_rate    = round(with_photo      / total_voters   * 100, 1) if total_voters   else 0

   
    now          = timezone.now()
    locked_count = voters.filter(locked_until__gt=now).count()
    high_fail    = voters.filter(failed_login_attempts__gte=2).count()

    context = { 
        'total_voters':    total_voters,
        'approved_voters': approved_voters,
        'pending_voters':  pending_voters,
        'rejected_voters': rejected_voters,
        'with_face':       with_face,
        'without_face':    without_face,
        'with_photo':      with_photo,
        'without_photo':   without_photo,
        'total_votes':     total_votes,
        'voted_voters':    voted_voters,
        'not_voted':       not_voted,
        'total_fraud':     total_fraud,
        'locked_count':    locked_count,
        'high_fail':       high_fail,
 
        'approval_rate':   approval_rate,
        'turnout_rate':    turnout_rate,
        'face_rate':       face_rate,
        'photo_rate':      photo_rate,

        'gender_json':    _jdump(gender_data),
        'age_json':       _jdump(age_data),
        'dept_json':      _jdump(dept_data),
        'year_json':      _jdump(year_data),
        'notif_json':     _jdump(notif_data),
        'elections_json': _jdump(elections_data),
        'fraud_json':     _jdump(fraud_data),
        'trend_labels':   _jdump(trend_labels),
        'trend_values':   _jdump(trend_values),
    }

    return render(request, 'admin_dashboard/analytics_dashboard.html', context)