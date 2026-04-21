# core/services/liveness.py


import cv2
import mediapipe as mp
import numpy as np
import logging
import random

logger = logging.getLogger(__name__)


LEFT_EYE      = [33, 160, 158, 133, 153, 144]
RIGHT_EYE     = [263, 387, 385, 362, 373, 380]
NOSE_TIP      = 1
LEFT_EAR_IDX  = 234
RIGHT_EAR_IDX = 454



EAR_OPEN_THRESH    = 0.22     
EAR_CLOSED_THRESH  = 0.20     


NEUTRAL_BAND       = 0.06     
TURN_THRESH        = 0.09     


TURN_CONFIRM_FRAMES = 1      


LOW_TEXTURE  = 0.0006
HIGH_TEXTURE = 0.20
HIGH_FREQ    = 0.73
MIN_SAT      = 15
MAX_SAT      = 178
MIN_FACE_H   = 0.10


CHALLENGE_POOL = ['blink', 'turn_left', 'turn_right']


def generate_random_challenges(count: int = 3) -> list:
    if count > len(CHALLENGE_POOL):
        raise ValueError(
            f"count={count} exceeds pool size ({len(CHALLENGE_POOL)}). "
            "Cannot generate more unique challenges than the pool contains."
        )
    pool = list(CHALLENGE_POOL)
    random.shuffle(pool)
    return pool[:count]


class LivenessChallenge:

    def __init__(self):
        mp_fm = mp.solutions.face_mesh
        self._fm_single = mp_fm.FaceMesh(
            static_image_mode        = True,
            max_num_faces            = 1,
            refine_landmarks         = True,
            min_detection_confidence = 0.4,
            min_tracking_confidence  = 0.4,
        )
        self._fm_multi = mp_fm.FaceMesh(
            static_image_mode        = True,
            max_num_faces            = 4,
            refine_landmarks         = False,
            min_detection_confidence = 0.4,
            min_tracking_confidence  = 0.4,
        )

    

    def verify(self, frame, challenge_type: str) -> 'tuple[bool, str]':
        """
        Verify one captured frame against a challenge type.
        Returns (passed: bool, reason: str).
        """
        if challenge_type not in CHALLENGE_POOL:
            return False, (
                f'Unknown challenge type: "{challenge_type}". '
                f'Valid options are: {CHALLENGE_POOL}.'
            )

        if frame is None:
            return False, "Empty frame received."

        h, w = frame.shape[:2]
        rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Multi-face guard
        try:
            multi_res  = self._fm_multi.process(rgb)
            face_count = len(multi_res.multi_face_landmarks or [])
        except Exception as exc:
            logger.error(f"LivenessChallenge multi-face error: {exc}")
            face_count = 0

        if face_count == 0:
            return False, "No face detected in the challenge frame."
        if face_count > 1:
            logger.warning(f"LivenessChallenge: {face_count} faces — REJECTED")
            return (
                False,
                f"Multiple faces detected ({face_count}). "
                "Only one person may be present during verification.",
            )

        # Single-face landmarks
        try:
            single_res = self._fm_single.process(rgb)
        except Exception as exc:
            logger.error(f"LivenessChallenge landmark error: {exc}")
            return False, "Face landmark extraction failed."

        if not single_res.multi_face_landmarks:
            return False, "Could not extract face landmarks."

        lm = single_res.multi_face_landmarks[0].landmark

        # Anti-spoof checks
        spoof_ok, spoof_reason = self._anti_spoof(frame, lm, h, w)
        if not spoof_ok:
            return False, spoof_reason

        # Gesture verification
        return self._check_gesture(lm, challenge_type)

    def run_liveness_sequence(
        self,
        frames: list,
        challenges: list,
    ) -> 'tuple[bool, str]':
        if len(frames) != len(challenges):
            return False, "Frame / challenge count mismatch."
        for i, (frame, ch) in enumerate(zip(frames, challenges)):
            ok, reason = self.verify(frame, ch)
            if not ok:
                label = ch.replace('_', ' ').title()
                return False, f'Stage {i + 1} "{label}" failed: {reason}'
        return True, "All liveness challenges passed."


    def _anti_spoof(self, frame, lm, h, w) -> 'tuple[bool, str]':
        xs  = [p.x for p in lm]
        ys  = [p.y for p in lm]
        pad = 12
        x1  = max(0,   int(min(xs) * w) - pad)
        y1  = max(0,   int(min(ys) * h) - pad)
        x2  = min(w-1, int(max(xs) * w) + pad)
        y2  = min(h-1, int(max(ys) * h) + pad)
        fh  = y2 - y1
        fw  = x2 - x1

        if fh < 10 or fw < 10:
            return False, "Face crop too small — move closer to the camera."
        if (fh / h) < MIN_FACE_H:
            return False, "Face too far from camera. Please move closer."

        crop = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        tex_var = float(cv2.Laplacian(gray, cv2.CV_64F).var() / max(fh * fw, 1))
        logger.debug(f"anti-spoof tex_var={tex_var:.6f}")
        if tex_var < LOW_TEXTURE:
            return False, "Image appears to be a photo or screen. Use your live camera."
        if tex_var > HIGH_TEXTURE:
            return False, "Screen or printed image detected. Use your live camera."

        freq = self._dft_high_freq(gray)
        logger.debug(f"anti-spoof freq={freq:.4f}")
        if freq > HIGH_FREQ:
            return False, "Screen pixel-grid detected. Use your live camera."

        sat = float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1].mean())
        logger.debug(f"anti-spoof sat={sat:.1f}")
        if sat < MIN_SAT:
            return False, "Image appears washed out. Use your live camera."
        if sat > MAX_SAT:
            return False, "Unusually high saturation detected. Use your live camera."

        return True, "Anti-spoof checks passed."

    @staticmethod
    def _dft_high_freq(gray_crop: np.ndarray) -> float:
        resized   = cv2.resize(gray_crop, (64, 64)).astype(np.float32)
        mag       = np.abs(np.fft.fftshift(np.fft.fft2(resized))) + 1e-10
        cx, cy    = 32, 32
        y_i, x_i = np.ogrid[:64, :64]
        dist      = np.sqrt((x_i - cx) ** 2 + (y_i - cy) ** 2)
        return float(1.0 - mag[dist <= 8].sum() / max(float(mag.sum()), 1e-6))


    @staticmethod
    def _ear(lm, indices) -> float:
        p   = [np.array([lm[i].x, lm[i].y]) for i in indices]
        num = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
        den = np.linalg.norm(p[0] - p[3]) * 2.0 + 1e-6
        return float(num / den)

    @staticmethod
    def _head_rel_x(lm) -> float:
        nose_x  = lm[NOSE_TIP].x
        l_ear_x = lm[LEFT_EAR_IDX].x
        r_ear_x = lm[RIGHT_EAR_IDX].x
        face_w  = abs(l_ear_x - r_ear_x) + 1e-6
        return -(nose_x - (l_ear_x + r_ear_x) / 2.0) / face_w

    

    def _check_gesture(self, lm, challenge_type: str) -> 'tuple[bool, str]':

        if challenge_type == "blink":
            ear_l = self._ear(lm, LEFT_EYE)
            ear_r = self._ear(lm, RIGHT_EYE)
            logger.debug(
                f"blink: EAR L={ear_l:.3f} R={ear_r:.3f} "
                f"open_thresh={EAR_OPEN_THRESH} closed_thresh={EAR_CLOSED_THRESH}"
            )
            avg_ear = (ear_l + ear_r) / 2.0
            if avg_ear < EAR_CLOSED_THRESH or ear_l < EAR_CLOSED_THRESH or ear_r < EAR_CLOSED_THRESH:
                return True, "Blink confirmed."
            return False, (
                f"Blink not detected "
                f"(EAR avg={avg_ear:.3f}, L={ear_l:.3f} R={ear_r:.3f}, "
                f"need < {EAR_CLOSED_THRESH})."
            )

        if challenge_type in ("turn_left", "turn_right"):
            rel_x = self._head_rel_x(lm)
            logger.debug(
                f"head turn: rel_x={rel_x:.3f} "
                f"challenge={challenge_type} "
                f"TURN_THRESH={TURN_THRESH} NEUTRAL_BAND={NEUTRAL_BAND}"
            )
    
            if challenge_type == "turn_left":
                if rel_x < -TURN_THRESH:
                    return True, "Head-left turn confirmed."
                return False, (
                    f"Head-left not detected "
                    f"(rel_x={rel_x:.3f}, need < -{TURN_THRESH})."
                )
            else:  
                if rel_x > TURN_THRESH:
                    return True, "Head-right turn confirmed."
                return False, (
                    f"Head-right not detected "
                    f"(rel_x={rel_x:.3f}, need > {TURN_THRESH})."
                )

        return False, f'Unhandled challenge type: "{challenge_type}".'