# core/management/commands/reset_embeddings.py
"""


Usage
─────
    python manage.py reset_embeddings              # dry-run (no changes)
    python manage.py reset_embeddings --confirm    # actually wipes embeddings
"""

from django.core.management.base import BaseCommand
from core.models import Student


class Command(BaseCommand):
    help = 'Wipe face embeddings so all voters re-register with the new dlib system.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually wipe embeddings. Without this flag the command is a dry-run.',
        )

    def handle(self, *args, **options):
        voters = Student.objects.filter(is_staff=False).exclude(face_embedding=None)
        count  = voters.count()

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('No voters with stored embeddings found.')
            )
            return

        if not options['confirm']:
            self.stdout.write(
                self.style.WARNING(
                    f'DRY-RUN: {count} voter(s) would have their face embedding cleared.\n'
                    f'Re-run with --confirm to apply the changes.'
                )
            )
            for s in voters:
                self.stdout.write(f'  would reset: {s.student_id} ({s.full_name})')
            return

        reset = 0
        for s in voters:
            s.face_embedding        = None
            s.failed_login_attempts = 0
            s.locked_until          = None
            s.approval_status       = 'pending'
            s.save(update_fields=[
                'face_embedding',
                'failed_login_attempts',
                'locked_until',
                'approval_status',
            ])
            self.stdout.write(f'  reset: {s.student_id} ({s.full_name})')
            reset += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. {reset} voter(s) cleared. '
                f'They must re-register before they can log in.'
            )
        )