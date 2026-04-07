# core/services/face_embedding.py

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ── Public constants 
EMBEDDING_DIM         = 1404       
EMBEDDING_BYTES       = EMBEDDING_DIM * 8   
EMBEDDING_QUALITY_MIN = 0.18     

# Anchor indices 
_NOSE_TIP  = 1
_LEFT_EAR  = 234
_RIGHT_EAR = 454


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

    def get_embedding(self, frame) -> "tuple[np.ndarray | None, float]":
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
            logger.debug("FaceEmbedding: invalid frame")
            return None, 0.0

        h, w = frame.shape[:2]

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self._face_mesh.process(rgb)
        except Exception as exc:
            logger.error(f"FaceEmbedding: MediaPipe error — {exc}")
            return None, 0.0

        if not res.multi_face_landmarks:
            logger.debug("FaceEmbedding: no face detected")
            return None, 0.0

        lm = res.multi_face_landmarks[0].landmark

        if len(lm) < 468:
            logger.error(f"FaceEmbedding: only {len(lm)} landmarks (need ≥ 468)")
            return None, 0.0

        
        l_ear_px = np.array([lm[_LEFT_EAR].x * w,  lm[_LEFT_EAR].y * h])
        r_ear_px = np.array([lm[_RIGHT_EAR].x * w, lm[_RIGHT_EAR].y * h])
        quality  = float(np.linalg.norm(r_ear_px - l_ear_px) / max(w, 1))

        embedding = self._build_embedding(lm)
        return embedding, quality

    @staticmethod
    def _build_embedding(lm) -> "np.ndarray | None":
        try:
            pts = np.array(
                [[lm[i].x, lm[i].y, lm[i].z] for i in range(468)],
                dtype=np.float64,
            )
            # Centre on nose tip
            pts -= pts[_NOSE_TIP].copy()
            scale = float(np.linalg.norm(pts[_RIGHT_EAR] - pts[_LEFT_EAR]))
            if scale < 1e-6:
                scale = 1.0
            pts /= scale
            vec  = pts.flatten()
            norm = float(np.linalg.norm(vec))
            if norm < 1e-6:
                return None
            return (vec / norm).astype(np.float64)
        except Exception as exc:
            logger.error(f"FaceEmbedding._build_embedding: {exc}")
            return None