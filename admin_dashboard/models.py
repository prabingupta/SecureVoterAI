# admin_dashboard/models.py

from django.db import models
from core.models import Student
from voter_dashboard.models import Election


class ElectionLog(models.Model):
    election  = models.ForeignKey(Election, on_delete=models.CASCADE)
    action    = models.CharField(max_length=50)   # "created" | "opened" | "closed"
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.election.title} — {self.action} at {self.timestamp}"


class FraudAlert(models.Model):
    ALERT_TYPES = [
        ('face_mismatch',     'Face Mismatch'),
        ('spoof_attempt',     'Spoof Attempt'),
        ('too_many_attempts', 'Too Many Attempts'),
        ('multiple_faces',    'Multiple Faces'),
        ('unknown_device',    'Unknown Device'),
    ]

    
    voter = models.ForeignKey(
        Student,
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'fraud_alerts',
    )
    
    election = models.ForeignKey(
        Election,
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'fraud_alerts',
    )
    alert_type  = models.CharField(
        max_length = 30,
        choices    = ALERT_TYPES,
        default    = 'face_mismatch',
    )
    description = models.TextField()
    ip_address  = models.GenericIPAddressField(null=True, blank=True)

    reviewed  = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        voter = self.voter.student_id if self.voter else 'unknown'
        return f"[{self.alert_type}] {voter} — {self.timestamp:%Y-%m-%d %H:%M}"


    @classmethod
    def _active_election(cls):
        from voter_dashboard.models import Election as E
        return E.objects.filter(is_active=True).first()

    @classmethod
    def log_face_mismatch(cls, student, ip, euc, cos, attempt, max_attempts):
        """Called on every failed face-match attempt."""
        cls.objects.create(
            voter       = student,
            election    = cls._active_election(),
            alert_type  = 'face_mismatch',
            ip_address  = ip,
            description = (
                f"Face mismatch for {student.full_name} ({student.student_id}). "
                f"Attempt {attempt}/{max_attempts}. "
                f"euc={euc:.4f} cos={cos:.4f}."
            ),
        )

    @classmethod
    def log_spoof_attempt(cls, student, ip, euc, cos):
        """Called when scores indicate a clearly different person."""
        cls.objects.create(
            voter       = student,
            election    = cls._active_election(),
            alert_type  = 'spoof_attempt',
            ip_address  = ip,
            description = (
                f"Likely impersonation on {student.full_name} ({student.student_id}). "
                f"Live face clearly different from registered face. "
                f"euc={euc:.4f} cos={cos:.4f}."
            ),
        )

    @classmethod
    def log_account_locked(cls, student, ip, lockout_minutes):
        """Called when an account is locked after max face failures."""
        cls.objects.create(
            voter       = student,
            election    = cls._active_election(),
            alert_type  = 'too_many_attempts',
            ip_address  = ip,
            description = (
                f"Account locked for {lockout_minutes} min after repeated "
                f"face verification failures. "
                f"Student: {student.full_name} ({student.student_id})."
            ),
        )