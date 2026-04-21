# core/services/anti_spoof.py

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)



# Laplacian texture variance   
LOW_TEXTURE_THRESHOLD  = 0.0008   
HIGH_TEXTURE_THRESHOLD = 0.22
HIGH_FREQ_THRESHOLD    = 0.70     
DFT_CROP_SIZE          = 96       
MIN_SATURATION         = 12
MAX_SATURATION         = 185      



MIN_GRADIENT_VARIANCE  = 0.0004
MIN_FACE_HEIGHT_RATIO  = 0.10
MAX_FACES_ALLOWED      = 1


class AntiSpoofResult:

    __slots__ = ("is_spoof", "reason", "details")

    def __init__(self, is_spoof: bool, reason: str, details: dict | None = None):
        self.is_spoof = is_spoof
        self.reason   = reason
        self.details  = details or {}

    def __bool__(self):
        return not self.is_spoof

    def __repr__(self):
        return (
            f"AntiSpoofResult(is_spoof={self.is_spoof}, "
            f"reason={self.reason!r}, details={self.details})"
        )


class AntiSpoofChecker:

    def __init__(self):
        import mediapipe as mp
        mp_fm = mp.solutions.face_mesh
        self._face_mesh = mp_fm.FaceMesh(
            static_image_mode        = True,
            max_num_faces            = MAX_FACES_ALLOWED + 1,   
            refine_landmarks         = False,
            min_detection_confidence = 0.45,
            min_tracking_confidence  = 0.45,
        )

    # Public entry point 

    def check(self, frame) -> 'tuple[bool, str, str]':
        result = self._run_pipeline(frame)
        if result.is_spoof:
            msg = result.details.get('msg', result.reason)
            return False, msg, result.reason
        return True, 'Anti-spoof checks passed.', 'live'

    def _run_pipeline(self, frame) -> AntiSpoofResult:
        """Internal pipeline that returns an AntiSpoofResult."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
            return AntiSpoofResult(True, "invalid_frame",
                                   {"msg": "Frame is None or not a valid BGR array"})

        h, w = frame.shape[:2]
        if h < 64 or w < 64:
            return AntiSpoofResult(True, "frame_too_small", {"h": h, "w": w})


        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self._face_mesh.process(rgb)
        except Exception as exc:
            logger.error("AntiSpoofChecker: MediaPipe error — %s", exc)
            return AntiSpoofResult(True, "mediapipe_error", {"exc": str(exc)})

        if not res.multi_face_landmarks:
            return AntiSpoofResult(True, "no_face_detected",
                                   {"msg": "No face found in frame"})

        num_faces = len(res.multi_face_landmarks)
        if num_faces > MAX_FACES_ALLOWED:
            logger.warning("AntiSpoofChecker: %d faces detected", num_faces)
            return AntiSpoofResult(True, "multiple_faces",
                                   {"count": num_faces,
                                    "msg": f"Multiple faces detected ({num_faces} people visible). "
                                           "Only one person may be in the frame during verification."})

        lm = res.multi_face_landmarks[0].landmark

        # Face size guard 
        ys = [l.y * h for l in lm]
        face_height = max(ys) - min(ys)
        if face_height / h < MIN_FACE_HEIGHT_RATIO:
            return AntiSpoofResult(True, "face_too_small",
                                   {"face_height_ratio": face_height / h,
                                    "msg": "Face is too far from the camera. Please move closer."})

        # Compute face bounding box
        xs     = [l.x * w for l in lm]
        x1, x2 = int(max(0, min(xs))), int(min(w, max(xs)))
        y1, y2 = int(max(0, min(ys))), int(min(h, max(ys)))
        if x2 <= x1 or y2 <= y1:
            return AntiSpoofResult(True, "invalid_bbox",
                                   {"bbox": (x1, y1, x2, y2)})

        face_crop = frame[y1:y2, x1:x2]
        bbox_area = (x2 - x1) * (y2 - y1)

        #  Laplacian texture variance 
        lap_result = self._check_laplacian(face_crop, bbox_area)
        if lap_result.is_spoof:
            return lap_result

        #  HSV saturation 
        hsv_result = self._check_hsv_saturation(face_crop)
        if hsv_result.is_spoof:
            return hsv_result

        #  DFT high-frequency ratio 
        dft_result = self._check_dft_frequency(face_crop)
        if dft_result.is_spoof:
            return dft_result

        #  Gradient magnitude variance 
        grad_result = self._check_gradient_variance(face_crop)
        if grad_result.is_spoof:
            return grad_result

        logger.info(
            "AntiSpoofChecker: LIVE — all checks passed (bbox=%dx%d, faces=%d)",
            x2 - x1, y2 - y1, num_faces,
        )
        return AntiSpoofResult(False, "live")

    # Individual checks 

    @staticmethod
    def _check_laplacian(face_crop, bbox_area: int) -> AntiSpoofResult:
        gray     = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        lap      = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(np.var(lap))
        norm_var = variance / max(bbox_area, 1)

        logger.debug("AntiSpoofChecker [Laplacian]: raw_var=%.6f  norm_var=%.8f",
                     variance, norm_var)

        if norm_var < LOW_TEXTURE_THRESHOLD:
            return AntiSpoofResult(
                True, "low_texture",
                {
                    "norm_var": norm_var,
                    "threshold": LOW_TEXTURE_THRESHOLD,
                    "msg": (
                        "Image appears to be a photo or screen (low texture). "
                        "Please use your live camera."
                    ),
                },
            )
        if norm_var > HIGH_TEXTURE_THRESHOLD:
            return AntiSpoofResult(
                True, "high_texture",
                {
                    "norm_var": norm_var,
                    "threshold": HIGH_TEXTURE_THRESHOLD,
                    "msg": (
                        "Image texture is abnormally high — "
                        "possible synthetic or AI-generated face."
                    ),
                },
            )
        return AntiSpoofResult(False, "texture_ok", {"norm_var": norm_var})

    @staticmethod
    def _check_hsv_saturation(face_crop) -> AntiSpoofResult:
        """
        Checks mean HSV saturation of the face region.
        Washed-out printed photographs: saturation < MIN_SATURATION.
        Over-bright LCD screen glow: saturation > MAX_SATURATION.
        """
        hsv    = cv2.cvtColor(face_crop, cv2.COLOR_BGR2HSV)
        mean_s = float(np.mean(hsv[:, :, 1]))

        logger.debug("AntiSpoofChecker [HSV]: mean_saturation=%.2f", mean_s)

        if mean_s < MIN_SATURATION:
            return AntiSpoofResult(
                True, "low_saturation",
                {
                    "mean_saturation": mean_s,
                    "threshold": MIN_SATURATION,
                    "msg": (
                        "Face image appears washed out (very low colour saturation). "
                        "This may be a printed photograph."
                    ),
                },
            )
        if mean_s > MAX_SATURATION:
            return AntiSpoofResult(
                True, "high_saturation",
                {
                    "mean_saturation": mean_s,
                    "threshold": MAX_SATURATION,
                    "msg": (
                        "Unusually high colour saturation detected "
                        "(possible screen glow or digital display)."
                    ),
                },
            )
        return AntiSpoofResult(False, "saturation_ok", {"mean_saturation": mean_s})

    @staticmethod
    def _check_dft_frequency(face_crop) -> AntiSpoofResult:
        gray    = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (DFT_CROP_SIZE, DFT_CROP_SIZE))

    
        win      = np.hanning(DFT_CROP_SIZE)
        window   = np.outer(win, win)
        windowed = resized.astype(np.float32) * window

        dft     = np.fft.fft2(windowed)
        dft_mag = np.abs(np.fft.fftshift(dft))

        total_power = float(np.sum(dft_mag))
        if total_power < 1e-9:
            return AntiSpoofResult(False, "dft_skip",
                                   {"msg": "total DFT power too low — skip check"})

        
        cx, cy = DFT_CROP_SIZE // 2, DFT_CROP_SIZE // 2
        ys, xs = np.ogrid[:DFT_CROP_SIZE, :DFT_CROP_SIZE]
        r      = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        r_max  = DFT_CROP_SIZE / 2.0
        mask   = (r >= 0.30 * r_max) & (r <= 0.50 * r_max)

        high_freq_ratio = float(np.sum(dft_mag[mask])) / total_power

        logger.debug("AntiSpoofChecker [DFT]: high_freq_ratio=%.4f  threshold=%.2f",
                     high_freq_ratio, HIGH_FREQ_THRESHOLD)

        if high_freq_ratio >= HIGH_FREQ_THRESHOLD:
            return AntiSpoofResult(
                True, "screen_display",
                {
                    "high_freq_ratio": high_freq_ratio,
                    "threshold": HIGH_FREQ_THRESHOLD,
                    "msg": (
                        "Screen display detected (pixel-grid frequency pattern). "
                        "Please use your live camera."
                    ),
                },
            )
        return AntiSpoofResult(False, "dft_ok", {"high_freq_ratio": high_freq_ratio})

    @staticmethod
    def _check_gradient_variance(face_crop) -> AntiSpoofResult:
        gray    = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag     = np.sqrt(sobel_x ** 2 + sobel_y ** 2)

        mean_mag = float(np.mean(mag))
        if mean_mag < 1e-6:
            return AntiSpoofResult(True, "gradient_flat",
                                   {"mean_mag": mean_mag,
                                    "msg": "Gradient magnitude is essentially zero — blank frame?"})

        norm_mag = mag / mean_mag
        variance = float(np.var(norm_mag))

        logger.debug(
            "AntiSpoofChecker [Gradient]: normalised_variance=%.6f  threshold=%.6f",
            variance, MIN_GRADIENT_VARIANCE,
        )

        if variance < MIN_GRADIENT_VARIANCE:
            return AntiSpoofResult(
                True, "uniform_gradient",
                {
                    "gradient_variance": variance,
                    "threshold": MIN_GRADIENT_VARIANCE,
                    "msg": (
                        "Edge distribution is suspiciously uniform "
                        "(possible printed photo or screen replay)."
                    ),
                },
            )
        return AntiSpoofResult(False, "gradient_ok", {"gradient_variance": variance})