# core/services/liveness.py
import cv2
import mediapipe as mp
import numpy as np
import logging

logger = logging.getLogger(__name__)

# MediaPipe landmark indices 
LEFT_EYE      = [33, 160, 158, 133, 153, 144]
RIGHT_EYE     = [263, 387, 385, 362, 373, 380]
NOSE_TIP      = 1
LEFT_EAR_IDX  = 234
RIGHT_EAR_IDX = 454

# Mouth landmarks for smile detection
# Outer mouth corners (left, right) and top/bottom lip centre
MOUTH_LEFT    = 61    # left mouth corner
MOUTH_RIGHT   = 291   # right mouth corner
MOUTH_TOP     = 13    # upper lip centre
MOUTH_BOTTOM  = 14    # lower lip centre
LEFT_CHEEK    = 234   # reuse ear landmark as cheek reference
RIGHT_CHEEK   = 454

# ── Detection thresholds ───────────────────────────────────────────────────────
BLINK_EAR_THRESHOLD  = 0.30   # EAR below this = eye closed
HEAD_TURN_THRESHOLD  = 0.04   # nose offset ratio above this = head turned
SMILE_MAR_THRESHOLD  = 0.35   # Mouth Aspect Ratio above this = smiling
                               # neutral face ≈ 0.20–0.30, smile ≈ 0.35–0.55


class LivenessChallenge:
    def __init__(self):
        mp_fm = mp.solutions.face_mesh
        self.face_mesh = mp_fm.FaceMesh(
            max_num_faces            = 1,
            refine_landmarks         = True,
            min_detection_confidence = 0.5,
            min_tracking_confidence  = 0.5,
        )

    @staticmethod
    def _pt(lm, idx) -> np.ndarray:
        return np.array([lm[idx].x, lm[idx].y])

    @staticmethod
    def _ear(lm, indices) -> float:
        """Eye Aspect Ratio — drops below threshold when eye is closed."""
        p   = [np.array([lm[i].x, lm[i].y]) for i in indices]
        num = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
        den = np.linalg.norm(p[0] - p[3]) * 2 + 1e-6
        return float(num / den)

    @staticmethod
    def _mar(lm) -> float:
        m_left  = np.array([lm[MOUTH_LEFT].x,  lm[MOUTH_LEFT].y])
        m_right = np.array([lm[MOUTH_RIGHT].x, lm[MOUTH_RIGHT].y])
        f_left  = np.array([lm[LEFT_CHEEK].x,  lm[LEFT_CHEEK].y])
        f_right = np.array([lm[RIGHT_CHEEK].x, lm[RIGHT_CHEEK].y])

        mouth_width = np.linalg.norm(m_right - m_left)
        face_width  = np.linalg.norm(f_right - f_left) + 1e-6
        return float(mouth_width / face_width)

    def _landmarks(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.face_mesh.process(rgb)
        if not res.multi_face_landmarks:
            return None
        return res.multi_face_landmarks[0].landmark

    def verify(self, frame, challenge_type: str) -> tuple[bool, str]:
        lm = self._landmarks(frame)
        if lm is None:
            return False, 'No face detected in the challenge frame.'

        # ── Blink ──────────────────────────────────────────────────────────────
        if challenge_type == 'blink':
            ear_l = self._ear(lm, LEFT_EYE)
            ear_r = self._ear(lm, RIGHT_EYE)
            if ear_l < BLINK_EAR_THRESHOLD or ear_r < BLINK_EAR_THRESHOLD:
                return True, 'Blink confirmed.'
            return False, (
                f'Blink not detected '
                f'(EAR L={ear_l:.3f} R={ear_r:.3f}, '
                f'need below {BLINK_EAR_THRESHOLD}).'
            )

        #  Head turn 
        if challenge_type in ('turn_left', 'turn_right'):
            nose  = self._pt(lm, NOSE_TIP)
            l_ear = self._pt(lm, LEFT_EAR_IDX)
            r_ear = self._pt(lm, RIGHT_EAR_IDX)
            face_w = np.linalg.norm(r_ear - l_ear) + 1e-6
            rel_x  = float((nose[0] - (l_ear[0] + r_ear[0]) / 2) / face_w)

            if challenge_type == 'turn_left':
                if rel_x < -HEAD_TURN_THRESHOLD:
                    return True, 'Head-left turn confirmed.'
                return False, (
                    f'Head-left turn not detected '
                    f'(rel_x={rel_x:.3f}, need < -{HEAD_TURN_THRESHOLD}).'
                )
            else:
                if rel_x > HEAD_TURN_THRESHOLD:
                    return True, 'Head-right turn confirmed.'
                return False, (
                    f'Head-right turn not detected '
                    f'(rel_x={rel_x:.3f}, need > {HEAD_TURN_THRESHOLD}).'
                )

        #  Smile 
        if challenge_type == 'smile':
            mar = self._mar(lm)
            if mar > SMILE_MAR_THRESHOLD:
                return True, 'Smile confirmed.'
            return False, (
                f'Smile not detected '
                f'(MAR={mar:.3f}, need above {SMILE_MAR_THRESHOLD}). '
                f'Please show a bigger smile.'
            )

        return False, f'Unknown challenge type: "{challenge_type}".'


class LivenessDetector:
    def __init__(self):
        mp_fm = mp.solutions.face_mesh
        self.face_mesh = mp_fm.FaceMesh(
            max_num_faces            = 1,
            refine_landmarks         = True,
            min_detection_confidence = 0.5,
            min_tracking_confidence  = 0.5,
        )
        self.blink_threshold = BLINK_EAR_THRESHOLD
        self.prev_nose: np.ndarray | None = None

    def _ear(self, landmarks):
        left  = [landmarks[i] for i in LEFT_EYE]
        right = [landmarks[i] for i in RIGHT_EYE]

        def _e(pts):
            p   = np.array([[pt.x, pt.y] for pt in pts])
            num = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
            den = np.linalg.norm(p[0] - p[3]) * 2 + 1e-6
            return float(num / den)

        return _e(left), _e(right)

    def detect(self, frame) -> bool:
        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return False
        lm = results.multi_face_landmarks[0].landmark

        ear_l, ear_r = self._ear(lm)
        if ear_l < self.blink_threshold or ear_r < self.blink_threshold:
            return True

        nose = np.array([lm[NOSE_TIP].x, lm[NOSE_TIP].y])
        if self.prev_nose is not None:
            if np.linalg.norm(nose - self.prev_nose) > 0.005:
                self.prev_nose = nose
                return True
        self.prev_nose = nose
        return False