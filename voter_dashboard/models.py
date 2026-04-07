# voter_dashboard/models.py

from django.db   import models
from django.utils import timezone
from core.models import Student
from .services.vote_service import encrypt_vote, decrypt_vote


class Election(models.Model):
    title       = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_time  = models.DateTimeField()
    end_time    = models.DateTimeField()
    is_active   = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class Candidate(models.Model):
    election    = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name='candidates'
    )
    name        = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    photo       = models.ImageField(upload_to='candidate_photos/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.election.title})"


class Vote(models.Model):
    voter          = models.ForeignKey(Student, on_delete=models.CASCADE)
    election       = models.ForeignKey(Election, on_delete=models.CASCADE)
    candidate      = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    timestamp      = models.DateTimeField(auto_now_add=True)
    encrypted_data = models.BinaryField(blank=True, null=True)

    class Meta:
        unique_together = ('voter', 'election')

    def save(self, *args, **kwargs):
        if self.candidate and not self.encrypted_data:
            self.encrypted_data = encrypt_vote(self.candidate.name)
        super().save(*args, **kwargs)

    def get_decrypted_vote(self) -> str | None:
        if self.encrypted_data:
            return decrypt_vote(self.encrypted_data)
        return None

    def __str__(self):
        return f"{self.voter.full_name} → {self.candidate.name}"


# Notification 

class Notification(models.Model):
    """
    In-app notification for a voter.

    Types
    ─────
    election_open    → created when an election's is_active flips to True
    election_close   → created when an election closes (end_time passed / deactivated)
    results_published → created when admin publishes results
    general          → any other admin-broadcast message
    """

    TYPE_CHOICES = [
        ('election_open',      'Election Opened'),
        ('election_close',     'Election Closed'),
        ('results_published',  'Results Published'),
        ('general',            'General'),
    ]

    voter      = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='notifications'
    )
    election   = models.ForeignKey(
        Election, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='notifications'
    )
    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='general')
    title      = models.CharField(max_length=200)
    message    = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notif_type}] {self.voter.student_id} — {self.title}"


    @classmethod
    def send_to_all_approved(cls, election, notif_type: str, title: str, message: str):
        """
        Broadcast a notification to every approved voter who has the
        corresponding notify_* preference enabled.
        """
        pref_map = {
            'election_open':     'notify_election_open',
            'election_close':    'notify_election_close',
            'results_published': 'notify_election_results',
        }
        pref_field = pref_map.get(notif_type)

        voters = Student.objects.filter(
            is_staff=False,
            approval_status='approved',
            is_active=True,
        )
        if pref_field:
            voters = voters.filter(**{pref_field: True})

        notifications = [
            cls(
                voter      = voter,
                election   = election,
                notif_type = notif_type,
                title      = title,
                message    = message,
            )
            for voter in voters
        ]
        cls.objects.bulk_create(notifications)
        return len(notifications)