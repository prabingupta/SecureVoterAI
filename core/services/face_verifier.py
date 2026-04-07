# core/services/face_verifier.py

import numpy as np
import logging
from .face_embedding import FaceEmbedding, EMBEDDING_DIM

logger = logging.getLogger(__name__)

#  Thresholds 
COSINE_THRESHOLD = 0.97



SPOOF_COSINE_FLOOR = 0.80


class FaceVerifier:
    def __init__(self, stored_embedding_bytes: bytes):
        self._stored      = None
        self._valid       = False
        self._invalid_msg = ""
        self._embedder    = FaceEmbedding()
        self._validate(stored_embedding_bytes)

    # Stored-embedding validation 

    def _validate(self, raw: bytes) -> None:
        if not raw:
            self._invalid_msg = "stored embedding is empty"
            logger.error(f"FaceVerifier: {self._invalid_msg}")
            return

        if len(raw) % 8 != 0:
            self._invalid_msg = (
                f"byte length {len(raw)} is not a multiple of 8 — "
                f"data is corrupted or from an incompatible system"
            )
            logger.error(f"FaceVerifier: {self._invalid_msg}")
            return

        try:
            vec = np.frombuffer(raw, dtype=np.float64).copy()
        except Exception as exc:
            self._invalid_msg = f"np.frombuffer failed: {exc}"
            logger.error(f"FaceVerifier: {self._invalid_msg}")
            return

        if vec.shape[0] != EMBEDDING_DIM:
            self._invalid_msg = (
                f"embedding has {vec.shape[0]} dimensions "
                f"(expected {EMBEDDING_DIM}). "
                f"Student registered with an incompatible version — must re-register."
            )
            logger.error(f"FaceVerifier: {self._invalid_msg}")
            return

        norm = float(np.linalg.norm(vec))
        if norm < 1e-6:
            self._invalid_msg = "all-zero vector — uninitialised or corrupted embedding"
            logger.error(f"FaceVerifier: {self._invalid_msg}")
            return

        self._stored = vec
        self._valid  = True
        logger.debug(
            f"FaceVerifier: stored embedding OK "
            f"(dim={EMBEDDING_DIM}, norm={norm:.6f})"
        )

    # Public API 

    def verify(self, frame) -> bool:
        matched, _, _ = self.verify_with_score(frame)
        return matched

    def verify_with_score(self, frame) -> "tuple[bool, float, float]":
        
        if not self._valid or self._stored is None:
            logger.error(
                f"FaceVerifier: invalid stored embedding — "
                f"{self._invalid_msg}. Student must re-register."
            )
            return False, 999.0, 0.0

        live, quality = self._embedder.get_embedding(frame)

        if live is None:
            logger.warning("FaceVerifier: no face detected in live frame")
            return False, 999.0, 0.0

        if live.shape != self._stored.shape:
            logger.error(
                f"FaceVerifier: shape mismatch — "
                f"live={live.shape} stored={self._stored.shape}"
            )
            return False, 999.0, 0.0

      
        cos = float(np.dot(live, self._stored))
        cos = max(-1.0, min(1.0, cos))

       
        euc = float(np.sqrt(max(0.0, 2.0 * (1.0 - cos))))

        matched = cos >= COSINE_THRESHOLD

        logger.info(
            f"FaceVerifier: cos={cos:.4f} "
            f"({'≥' if matched else '<'} {COSINE_THRESHOLD}) "
            f"euc={euc:.4f} quality={quality:.3f} "
            f"→ {'MATCH ✓' if matched else 'REJECT ✗'}"
        )
        return matched, euc, cos

    @property
    def is_valid(self) -> bool:
        """True if the stored embedding was parsed successfully."""
        return self._valid