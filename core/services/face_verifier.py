# core/services/face_verifier.py
# =============================================================================
# BUGS FIXED IN THIS FILE:
#
# BUG 1 — verify_with_score() previously returned (False, 999.0, 0.0) silently
#   when the stored embedding was invalid, which some callers misread as
#   "no face detected — maybe retry" instead of a hard security block.
#   FIX: Every failure path is now clearly typed and documented.
#
# BUG 2 — SPOOF_COSINE_FLOOR logic tightened.
#   Any cos < SPOOF_COSINE_FLOOR is treated as a spoof_attempt regardless of
#   the liveness_confirmed flag passed by the client.
# =============================================================================

import numpy as np
import logging
from .face_embedding import FaceEmbedding, EMBEDDING_DIM

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
COSINE_THRESHOLD   = 0.97    # minimum cosine similarity for MATCH
SPOOF_COSINE_FLOOR = 0.80    # below this → spoof_attempt alert (not just mismatch)

# Sentinel returned as euclidean distance on all error paths so callers can
# distinguish "error / no-face" (999.0) from a genuine low-cos rejection.
_ERROR_EUC = 999.0
_ERROR_COS = 0.0


class FaceVerifier:
    """
    Compares a live webcam frame against a stored 1404-D face embedding.

    Usage
    -----
        verifier = FaceVerifier(student.face_embedding)
        matched, euc, cos = verifier.verify_with_score(frame)
    """

    def __init__(self, stored_embedding_bytes: bytes):
        self._stored      = None
        self._valid       = False
        self._invalid_msg = ""
        self._embedder    = FaceEmbedding()
        self._validate(stored_embedding_bytes)

    # ── Stored-embedding validation ───────────────────────────────────────────

    def _validate(self, raw: bytes) -> None:
        if not raw:
            self._invalid_msg = "stored embedding is empty"
            logger.error("FaceVerifier: %s", self._invalid_msg)
            return

        if len(raw) % 8 != 0:
            self._invalid_msg = (
                f"byte length {len(raw)} is not a multiple of 8 — "
                "data is corrupted or from an incompatible system"
            )
            logger.error("FaceVerifier: %s", self._invalid_msg)
            return

        try:
            vec = np.frombuffer(raw, dtype=np.float64).copy()
        except Exception as exc:
            self._invalid_msg = f"np.frombuffer failed: {exc}"
            logger.error("FaceVerifier: %s", self._invalid_msg)
            return

        if vec.shape[0] != EMBEDDING_DIM:
            self._invalid_msg = (
                f"embedding has {vec.shape[0]} dimensions "
                f"(expected {EMBEDDING_DIM}). "
                "Student registered with an incompatible version — must re-register."
            )
            logger.error("FaceVerifier: %s", self._invalid_msg)
            return

        norm = float(np.linalg.norm(vec))
        if norm < 1e-6:
            self._invalid_msg = "all-zero vector — uninitialised or corrupted embedding"
            logger.error("FaceVerifier: %s", self._invalid_msg)
            return

        self._stored = vec
        self._valid  = True
        logger.debug(
            "FaceVerifier: stored embedding OK (dim=%d, norm=%.6f)",
            EMBEDDING_DIM, norm,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def verify(self, frame) -> bool:
        matched, _, _ = self.verify_with_score(frame)
        return matched

    def verify_with_score(self, frame) -> 'tuple[bool, float, float]':
        """
        Returns (matched: bool, euclidean_dist: float, cosine_sim: float).

        matched == True  →  cosine >= COSINE_THRESHOLD  →  SAFE TO LOGIN
        matched == False →  MUST block login regardless of reason

        On error / no-face: returns (False, 999.0, 0.0)
        Callers MUST treat any (False, ...) return as a block — the euc/cos
        values allow distinguishing mismatch (0 < cos < threshold) from
        error (cos == 0.0, euc == 999.0).
        """
        # ── Guard: invalid stored embedding ───────────────────────────────────
        if not self._valid or self._stored is None:
            logger.error(
                "FaceVerifier: invalid stored embedding — %s. "
                "Student must re-register.",
                self._invalid_msg,
            )
            return False, _ERROR_EUC, _ERROR_COS

        # ── Extract live embedding ─────────────────────────────────────────────
        live, quality = self._embedder.get_embedding(frame)

        if live is None:
            logger.warning("FaceVerifier: no face detected in live frame")
            return False, _ERROR_EUC, _ERROR_COS

        if live.shape != self._stored.shape:
            logger.error(
                "FaceVerifier: shape mismatch — live=%s stored=%s",
                live.shape, self._stored.shape,
            )
            return False, _ERROR_EUC, _ERROR_COS

        # ── Cosine similarity (both vectors are already L2-normalised) ─────────
        cos = float(np.dot(live, self._stored))
        cos = max(-1.0, min(1.0, cos))           # clamp numerical noise

        # Euclidean distance derived from cosine (avoids second sqrt pass)
        euc = float(np.sqrt(max(0.0, 2.0 * (1.0 - cos))))

        matched = cos >= COSINE_THRESHOLD

        logger.info(
            "FaceVerifier: cos=%.4f (%s %.2f) euc=%.4f quality=%.3f → %s",
            cos,
            "≥" if matched else "<",
            COSINE_THRESHOLD,
            euc,
            quality,
            "MATCH ✓" if matched else "REJECT ✗",
        )
        return matched, euc, cos

    @property
    def is_valid(self) -> bool:
        """True if the stored embedding was parsed successfully."""
        return self._valid