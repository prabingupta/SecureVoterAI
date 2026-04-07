# core/management/commands/reset_embeddings.py


import numpy as np
from django.core.management.base import BaseCommand
from core.models import Student
from core.services.face_embedding import EMBEDDING_DIM, EMBEDDING_BYTES

_DLIB_DIM   = 128
_DLIB_BYTES = _DLIB_DIM * 8   


def _classify(raw) -> "tuple[str, bool]":
    """
    Return (label, needs_reset) for a stored embedding field value.
    """
    if raw is None:
        return "none (never registered)", False

    b = bytes(raw)
    n = len(b)

    if n == 0:
        return "empty (0 bytes)", True

    if n % 8 != 0:
        return f"corrupted ({n} bytes, not divisible by 8)", True

    dims = n // 8
    if dims == EMBEDDING_DIM:
        return f"OK — MediaPipe {dims}-d ({n} bytes)", False
    if dims == _DLIB_DIM:
        return f"WRONG — old dlib {dims}-d ({n} bytes) — must reset", True
    return f"WRONG — unknown {dims}-d ({n} bytes) — must reset", True


class Command(BaseCommand):
    help = (
        "Diagnose and optionally wipe face embeddings so voters re-register "
        "with the current MediaPipe system. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action  = "store_true",
            help    = "Apply resets. Without this flag → dry-run only.",
        )
        parser.add_argument(
            "--student",
            metavar = "STUDENT_ID",
            default = None,
            help    = "Reset only this one student (e.g. ISL-1234).",
        )
        parser.add_argument(
            "--force-all",
            action  = "store_true",
            dest    = "force_all",
            help    = (
                "Wipe ALL voter embeddings including correct-format ones. "
                "Use after upgrading MediaPipe to a version that changes "
                "landmark layout."
            ),
        )

    def handle(self, *args, **options):
        confirm   = options["confirm"]
        force_all = options["force_all"]
        target_id = options["student"]

        # Build queryset
        qs = Student.objects.filter(is_staff=False)
        if target_id:
            qs = qs.filter(student_id=target_id)
            if not qs.exists():
                self.stdout.write(
                    self.style.ERROR(
                        f"No voter found with student_id='{target_id}'"
                    )
                )
                return

        all_voters = list(qs.order_by("student_id"))
        if not all_voters:
            self.stdout.write(self.style.SUCCESS("No voters found."))
            return

        # Diagnostic report
        self._print_header(len(all_voters), force_all)

        no_embedding  = []
        already_ok    = []
        needs_reset   = []

        for student in all_voters:
            label, should_reset = _classify(student.face_embedding)
            if force_all and student.face_embedding is not None:
                should_reset = True
                label = label.replace("OK —", "FORCE-RESET —")
            if student.face_embedding is None:
                no_embedding.append((student, label))
            elif should_reset:
                needs_reset.append((student, label))
            else:
                already_ok.append((student, label))

        # Print each group
        if no_embedding:
            self.stdout.write(
                self.style.WARNING(
                    f"\n  No embedding (never registered face): "
                    f"{len(no_embedding)}"
                )
            )
            for s, lbl in no_embedding:
                self.stdout.write(
                    f"    {s.student_id:<14}  {s.full_name:<30}  [{lbl}]"
                )

        if already_ok and not force_all:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n  Correct format (MediaPipe {EMBEDDING_DIM}-d): "
                    f"{len(already_ok)}"
                )
            )
            for s, lbl in already_ok:
                self.stdout.write(
                    f"    {s.student_id:<14}  {s.full_name:<30}  [{lbl}]"
                )

        if needs_reset:
            self.stdout.write(
                self.style.ERROR(
                    f"\n  Needs resetting: {len(needs_reset)}"
                )
            )
            for s, lbl in needs_reset:
                self.stdout.write(
                    f"    {s.student_id:<14}  {s.full_name:<30}  [{lbl}]"
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n  All stored embeddings are correct format — "
                    "nothing to reset."
                )
            )

        self.stdout.write("")

        # Dry-run stops here
        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    "DRY-RUN complete — no data changed.\n"
                    "Re-run with --confirm to apply the changes above."
                )
            )
            return

        if not needs_reset:
            self.stdout.write(self.style.SUCCESS("Nothing to reset. Done."))
            return

        # Apply resets
        self.stdout.write(
            self.style.HTTP_INFO(
                f"Resetting {len(needs_reset)} voter(s)…"
            )
        )
        done = 0
        for student, label in needs_reset:
            student.face_embedding        = None
            student.approval_status       = "pending"
            student.failed_login_attempts = 0
            student.locked_until          = None
            student.save(update_fields=[
                "face_embedding",
                "approval_status",
                "failed_login_attempts",
                "locked_until",
            ])
            self.stdout.write(
                f"  RESET  {student.student_id:<14}  "
                f"{student.full_name:<30}  (was: {label})"
            )
            done += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {done} voter(s) cleared.\n"
                "\n"
                "Next steps for affected voters:\n"
                "  1. They re-register at /register/\n"
                "  2. Admin re-approves at /admin-dashboard/voters/\n"
                "  3. They log in normally.\n"
                "\n"
                f"Current system: MediaPipe {EMBEDDING_DIM}-d "
                f"({EMBEDDING_BYTES} bytes per voter)."
            )
        )

    def _print_header(self, total: int, force_all: bool) -> None:
        line = "═" * 62
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(line))
        self.stdout.write(
            self.style.HTTP_INFO(
                "  SecureVoterAI — Face Embedding Diagnostic Report"
            )
        )
        self.stdout.write(self.style.HTTP_INFO(line))
        self.stdout.write(
            f"  Current system : MediaPipe {EMBEDDING_DIM}-d "
            f"({EMBEDDING_BYTES} bytes)"
        )
        self.stdout.write(f"  Voters scanned : {total}")
        if force_all:
            self.stdout.write(
                self.style.WARNING(
                    "  Mode           : --force-all  "
                    "(wiping every embedding)"
                )
            )
        self.stdout.write("")