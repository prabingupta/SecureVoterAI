# core/services/face_embedding.py

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)


EMBEDDING_DIM         = 1404        
EMBEDDING_BYTES       = EMBEDDING_DIM * 8    
EMBEDDING_QUALITY_MIN = 0.20         

_NOSE_TIP  = 1
_LEFT_EAR  = 234
_RIGHT_EAR = 454
_MIN_LANDMARKS = 468


class FaceEmbedding:
    def __init__(self):
        import mediapipe as mp
        mp_fm = mp.solutions.face_mesh
        self._face_mesh = mp_fm.FaceMesh(
            static_image_mode        = True,
            max_num_faces            = 1,
            refine_landmarks         = True,   
            min_detection_confidence = 0.5,
            min_tracking_confidence  = 0.5,
        )

    def get_embedding(self, frame) -> 'tuple[np.ndarray | None, float]':
        """
        Process a BGR OpenCV frame and return (embedding, quality_score).

        embedding     : float64 unit vector of length 1404, or None on failure
        quality_score : float in [0, 1]; inter-ear distance / frame width.
                        Values below EMBEDDING_QUALITY_MIN should be rejected
                        by the caller.

        Returns (None, 0.0) on any failure.
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
            logger.debug("FaceEmbedding.get_embedding: invalid frame (None or wrong shape)")
            return None, 0.0

        h, w = frame.shape[:2]
        if h < 64 or w < 64:
            logger.debug("FaceEmbedding.get_embedding: frame too small (%dx%d)", w, h)
            return None, 0.0

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self._face_mesh.process(rgb)
        except Exception as exc:
            logger.error("FaceEmbedding.get_embedding: MediaPipe error — %s", exc)
            return None, 0.0

        if not res.multi_face_landmarks:
            logger.debug("FaceEmbedding.get_embedding: no face detected")
            return None, 0.0

        lm = res.multi_face_landmarks[0].landmark


        if len(lm) < _MIN_LANDMARKS:
            logger.error(
                "FaceEmbedding.get_embedding: only %d landmarks (need ≥ %d)",
                len(lm), _MIN_LANDMARKS,
            )
            return None, 0.0


        l_ear_px = np.array([lm[_LEFT_EAR].x  * w, lm[_LEFT_EAR].y  * h])
        r_ear_px = np.array([lm[_RIGHT_EAR].x * w, lm[_RIGHT_EAR].y * h])
        quality  = float(np.linalg.norm(r_ear_px - l_ear_px) / max(w, 1))

        if quality < EMBEDDING_QUALITY_MIN:
            logger.warning(
                "FaceEmbedding.get_embedding: quality %.4f < %.4f — "
                "face too small or occluded",
                quality, EMBEDDING_QUALITY_MIN,
            )
            return None, quality  

        embedding = self._build_embedding(lm)
        if embedding is None:
            return None, quality

        logger.debug(
            "FaceEmbedding.get_embedding: OK  quality=%.4f  norm=%.6f",
            quality, float(np.linalg.norm(embedding)),
        )
        return embedding, quality

    @staticmethod
    def _build_embedding(lm) -> 'np.ndarray | None':
        try:
            pts = np.array(
                [[lm[i].x, lm[i].y, lm[i].z] for i in range(468)],
                dtype=np.float64,
            )


            pts -= pts[_NOSE_TIP].copy()

         
            scale = float(np.linalg.norm(pts[_RIGHT_EAR] - pts[_LEFT_EAR]))
            if scale < 1e-6:
                logger.warning("FaceEmbedding._build_embedding: near-zero inter-ear scale")
                scale = 1.0
            pts /= scale

            vec  = pts.flatten()                  
            norm = float(np.linalg.norm(vec))
            if norm < 1e-6:
                logger.warning("FaceEmbedding._build_embedding: near-zero L2 norm")
                return None

            unit_vec = (vec / norm).astype(np.float64)


            final_norm = float(np.linalg.norm(unit_vec))
            if abs(final_norm - 1.0) > 0.01:
                logger.error(
                    "FaceEmbedding._build_embedding: final unit vector norm=%.6f ≠ 1.0",
                    final_norm,
                )
                return None

            return unit_vec

        except Exception as exc:
            logger.error("FaceEmbedding._build_embedding: %s", exc)
            return None