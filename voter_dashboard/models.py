# voter_dashboard/models.py
from django.db import models
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
        # Database-level guard: raises IntegrityError if a duplicate INSERT
        # races past the application-level check in cast_vote.
        unique_together = ('voter', 'election')

    def save(self, *args, **kwargs):
        """
        Encrypt the candidate name before the first save.

        This is the SINGLE place encryption happens.  The view must NOT
        call encrypt_vote() and pass encrypted_data= — doing so would mean
        the model skips encryption here (because encrypted_data is truthy),
        which works, but splits responsibility across two layers.

        Rule: views call Vote.objects.create(voter=, election=, candidate=)
              with NO encrypted_data argument.  This method handles the rest.
        """
        if self.candidate and not self.encrypted_data:
            self.encrypted_data = encrypt_vote(self.candidate.name)
        super().save(*args, **kwargs)

    def get_decrypted_vote(self) -> str | None:
        """Decrypt and return the plaintext candidate name, or None."""
        if self.encrypted_data:
            return decrypt_vote(self.encrypted_data)
        return None

    def __str__(self):
        return f"{self.voter.full_name} → {self.candidate.name}"