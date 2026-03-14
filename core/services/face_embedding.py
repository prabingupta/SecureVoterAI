# core/services/face_embedding.py

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)


class FaceEmbedding:

    def get_embedding(self, frame) -> np.ndarray | None:
        if frame is None:
            return None

        try:
            import face_recognition
        except ImportError:
            logger.error(
                'face_recognition library not installed. '
                'Run: pip install face-recognition'
            )
            return None

        # face_recognition expects RGB, OpenCV gives BGR
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect face bounding boxes first.
        # model='hog' is fast on CPU; use model='cnn' if GPU is available.
        locations = face_recognition.face_locations(rgb, model='hog')
        if not locations:
            logger.debug('FaceEmbedding: no face detected in frame')
            return None

        # Encode the first (largest) detected face into 128-d vector
        encodings = face_recognition.face_encodings(
            rgb, known_face_locations=locations
        )
        if not encodings:
            logger.debug('FaceEmbedding: face located but encoding failed')
            return None

        vec  = np.array(encodings[0], dtype=np.float64)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 1e-6 else vec