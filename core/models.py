# core/models.py

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

    GENDER_CHOICES = [
        ('male',   'Male'),
        ('female', 'Female'),
    ]

    #  Core identity fields
    student_id    = models.CharField(max_length=20,  unique=True)
    full_name     = models.CharField(max_length=100)
    department    = models.CharField(max_length=20,  choices=DEPARTMENTS)
    year_of_study = models.CharField(max_length=1,   choices=YEARS)
    phone         = models.CharField(max_length=20,  blank=True, null=True)

    #  Profile photo 
    profile_photo = models.ImageField(
        upload_to='profile_photos/', blank=True, null=True
    )

    #  Demographics (for analytics dashboard)
    age = models.PositiveSmallIntegerField(null=True, blank=True)

    # gender: Male or Female
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICES, null=True, blank=True
    )

    #  Face embedding storage (MediaPipe 1404-d vector, binary) 
    face_embedding = models.BinaryField(blank=True, null=True)

    #  Admin approval 
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_CHOICES, default='pending'
    )
    approval_note = models.TextField(blank=True, null=True)

    #  Security / lockout 
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until          = models.DateTimeField(null=True, blank=True)

    #  Device fingerprint (recorded at registration) 
    registered_device = models.CharField(max_length=500, blank=True, null=True)

    # Audit trail 
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    # Notification preferences 
    
    notify_election_open    = models.BooleanField(default=True)
    notify_election_close   = models.BooleanField(default=True)
    notify_election_results = models.BooleanField(default=True)

    
    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    objects = StudentManager()

    USERNAME_FIELD  = 'student_id'
    REQUIRED_FIELDS = ['full_name', 'department', 'year_of_study']

    def __str__(self):
        return self.student_id

    
    @property
    def username(self):
        return self.student_id

    
    @property
    def has_face(self):
        """True if a face embedding has been stored for this student."""
        return bool(self.face_embedding)

    @property
    def is_approved(self):
        return self.approval_status == 'approved'

    @property
    def age_group(self):
        
        if self.age is None:
            return 'Unknown'
        if self.age <= 22:
            return '18-22'
        if self.age <= 27:
            return '23-27'
        return '28-35'

    # Security helpers 
    def is_locked(self):
        
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