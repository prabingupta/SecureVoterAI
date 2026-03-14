from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class StudentManager(BaseUserManager):
    def create_user(self, student_id, password=None, **extra_fields):
        if not student_id:
            raise ValueError("Student ID is required")
        student = self.model(student_id=student_id, **extra_fields)
        student.set_password(password)
        student.save(using=self._db)
        return student

    def create_superuser(self, student_id, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(student_id, password, **extra_fields)


class Student(AbstractBaseUser, PermissionsMixin):
    DEPARTMENTS = [
        ('AI',         'AI'),
        ('Computing',  'Computing'),
        ('Networking', 'Networking'),
    ]

    YEARS = [
        ('1', 'Year 1'),
        ('2', 'Year 2'),
        ('3', 'Year 3'),
    ]

    APPROVAL_CHOICES = [
        ('pending',  'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    #  Core identity fields 
    student_id    = models.CharField(max_length=20,  unique=True)
    full_name     = models.CharField(max_length=100)
    department    = models.CharField(max_length=20,  choices=DEPARTMENTS)
    year_of_study = models.CharField(max_length=1,   choices=YEARS)
    phone         = models.CharField(max_length=20,  blank=True, null=True)

    #  Face embedding storage (128-d dlib ResNet-34 vector, binary) 
    face_embedding = models.BinaryField(blank=True, null=True)

    #  Admin approval 
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_CHOICES, default='pending'
    )
    approval_note = models.TextField(blank=True, null=True)

    # Security / lockout 
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until          = models.DateTimeField(null=True, blank=True)

    #  Device fingerprint (recorded at registration) 
    registered_device = models.CharField(max_length=500, blank=True, null=True)

    # Audit trail 
    # IP address of the most recent successful login.
    # Written by face_verify_api on MATCH so admins can correlate fraud alerts.
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    #  Django internals 
    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    objects = StudentManager()

    USERNAME_FIELD  = 'student_id'
    REQUIRED_FIELDS = ['full_name', 'department', 'year_of_study']

    def __str__(self):
        return self.student_id

    #  Make username compatible with templates using {{ user.username }} 
    @property
    def username(self):
        return self.student_id

    #  Convenience properties 
    @property
    def has_face(self):
        """True if a face embedding has been stored for this student."""
        return bool(self.face_embedding)

    @property
    def is_approved(self):
        """True if admin has approved the account."""
        return self.approval_status == 'approved'

    #  Security helpers 
    def is_locked(self):
        """Return True if account is currently in a lockout window."""
        return self.locked_until is not None and self.locked_until > timezone.now()

    def increment_failed_attempts(self, max_attempts=3, lockout_minutes=15):
        """
        Increment the failed-login counter.
        If max_attempts is reached, set locked_until to now + lockout_minutes.
        """
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = timezone.now() + timezone.timedelta(
                minutes=lockout_minutes
            )
        self.save(update_fields=['failed_login_attempts', 'locked_until'])

    def reset_failed_attempts(self):
        """
        Clear the failed-login counter and remove any lockout.
        Called after a successful login.
        """
        self.failed_login_attempts = 0
        self.locked_until          = None
        self.save(update_fields=['failed_login_attempts', 'locked_until'])

    def record_login(self, ip_address: str):
        """
        Persist the IP address of a successful login.
        Called by face_verify_api immediately after login().
        """
        self.last_login_ip = ip_address
        self.save(update_fields=['last_login_ip'])