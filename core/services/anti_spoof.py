# core/services/anti_spoof.py

import cv2
import numpy as np
import mediapipe as mp
import logging

logger = logging.getLogger(__name__)

#  Thresholds 
LOW_TEXTURE_THRESHOLD  = 0.0005
HIGH_TEXTURE_THRESHOLD = 0.22
HIGH_FREQ_THRESHOLD    = 0.74
MIN_SATURATION         = 12
MAX_SATURATION         = 180
MIN_FACE_HEIGHT_RATIO  = 0.10    

class AntiSpoofChecker:

    def __init__(self):
        mp_fm = mp.solutions.face_mesh
        self._face_mesh = mp_fm.FaceMesh(
            static_image_mode        = True,
            max_num_faces            = 4,     
            refine_landmarks         = False, 
            min_detection_confidence = 0.45,
        )

    #  Public API 

    def check(self, frame) -> "tuple[bool, str, str]":
        
        if frame is None:
            return False, "Empty frame received.", "spoof_attempt"

        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            return False, "Invalid frame format.", "spoof_attempt"

        h, w = frame.shape[:2]

        try:
            rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res   = self._face_mesh.process(rgb)
            faces = res.multi_face_landmarks or []
        except Exception as exc:
            logger.error(f"AntiSpoofChecker: MediaPipe error — {exc}")
            return False, "Face detection failed internally.", "spoof_attempt"

        face_count = len(faces)

        #  Multi-face guard
        if face_count == 0:
            return False, "No face detected in frame.", "spoof_attempt"

        if face_count > 1:
            logger.warning(
                f"AntiSpoofChecker: {face_count} faces detected — REJECTED"
            )
            return (
                False,
                f"Multiple faces detected ({face_count} people visible). "
                f"Only one person may be in the frame during verification.",
                "multiple_faces",
            )

        #  Face bounding box
        lm  = faces[0].landmark
        xs  = [p.x for p in lm]
        ys  = [p.y for p in lm]
        pad = 10
        x1  = max(0,   int(min(xs) * w) - pad)
        y1  = max(0,   int(min(ys) * h) - pad)
        x2  = min(w-1, int(max(xs) * w) + pad)
        y2  = min(h-1, int(max(ys) * h) + pad)
        fh  = y2 - y1
        fw  = x2 - x1

        if fh < 10 or fw < 10:
            return False, "Face bounding box is degenerate.", "spoof_attempt"

        #  Face size guard
        if (fh / h) < MIN_FACE_HEIGHT_RATIO:
            return (
                False,
                "Face is too far from the camera. Please move closer.",
                "spoof_attempt",
            )

        crop = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        #  Laplacian texture variance
        lap     = cv2.Laplacian(gray, cv2.CV_64F)
        tex_var = float(lap.var() / max(fh * fw, 1))
        logger.debug(f"AntiSpoofChecker: tex_var={tex_var:.6f}")

        if tex_var < LOW_TEXTURE_THRESHOLD:
            return (
                False,
                "Image appears to be a photo or screen (low texture). "
                "Please use your live camera in person.",
                "spoof_attempt",
            )

        if tex_var > HIGH_TEXTURE_THRESHOLD:
            return (
                False,
                "Screen or printed image detected (high aliasing). "
                "Please use your live camera.",
                "spoof_attempt",
            )

        #  DFT high-frequency ratio
        freq = self._dft_high_freq(gray)
        logger.debug(f"AntiSpoofChecker: freq_ratio={freq:.4f}")

        if freq > HIGH_FREQ_THRESHOLD:
            return (
                False,
                "Screen display detected (pixel-grid pattern). "
                "Please do not show a phone screen — use your live camera.",
                "spoof_attempt",
            )

        #  HSV saturation
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        sat = float(hsv[:, :, 1].mean())
        logger.debug(f"AntiSpoofChecker: sat_mean={sat:.1f}")

        if sat < MIN_SATURATION:
            return (
                False,
                "Image appears washed out (possible printed photo). "
                "Please use your live camera.",
                "spoof_attempt",
            )

        if sat > MAX_SATURATION:
            return (
                False,
                "Unusually high colour saturation (possible screen glow). "
                "Please use your live camera.",
                "spoof_attempt",
            )

        return True, "Anti-spoof checks passed.", ""

   

    @staticmethod
    def _dft_high_freq(gray_crop: np.ndarray) -> float:
        resized = cv2.resize(gray_crop, (64, 64)).astype(np.float32)
        mag     = np.abs(np.fft.fftshift(np.fft.fft2(resized))) + 1e-10
        cx, cy  = 32, 32
        y_i, x_i = np.ogrid[:64, :64]
        dist    = np.sqrt((x_i - cx) ** 2 + (y_i - cy) ** 2)
        low     = float(mag[dist <= 8].sum())
        total   = float(mag.sum())
        return float(1.0 - low / max(total, 1e-6))