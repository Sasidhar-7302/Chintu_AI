"""Hand tracking using MediaPipe Hands."""

import numpy as np
import threading
import time
import sys
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Try to import required libraries
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except ImportError:
    HAS_MEDIAPIPE = False


@dataclass
class HandLandmarks:
    """21-point hand landmarks from MediaPipe."""
    landmarks: List[Tuple[float, float, float]]  # (x, y, z) for each of 21 points
    handedness: str  # "Left" or "Right"
    confidence: float
    
    # Landmark indices
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20
    
    def get_landmark(self, index: int) -> Tuple[float, float, float]:
        """Get a specific landmark by index."""
        return self.landmarks[index]
    
    def get_finger_tips(self) -> List[Tuple[float, float, float]]:
        """Get all fingertip positions."""
        return [
            self.landmarks[self.THUMB_TIP],
            self.landmarks[self.INDEX_TIP],
            self.landmarks[self.MIDDLE_TIP],
            self.landmarks[self.RING_TIP],
            self.landmarks[self.PINKY_TIP],
        ]


class HandTracker:
    """
    Tracks hand landmarks using MediaPipe Hands.
    Provides 21 3D landmarks per detected hand.
    """
    
    def __init__(
        self,
        max_hands: int = 1,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        camera_index: int = 0,
    ):
        self.max_hands = max_hands
        self.min_detection_confidence = min_detection_confidence
        self.min_tracking_confidence = min_tracking_confidence
        self.camera_index = camera_index
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._hands = None
        self._on_landmarks: Optional[Callable[[List[HandLandmarks]], None]] = None
        self._on_frame: Optional[Callable[[np.ndarray], None]] = None
        
        if not HAS_OPENCV:
            logger.error("OpenCV not installed")
        if not HAS_MEDIAPIPE:
            logger.error("MediaPipe not installed")
        
        self._initialized = HAS_OPENCV and HAS_MEDIAPIPE
    
    def set_landmarks_callback(self, callback: Callable[[List[HandLandmarks]], None]):
        """Set callback for when landmarks are detected."""
        self._on_landmarks = callback
    
    def set_frame_callback(self, callback: Callable[[np.ndarray], None]):
        """Set callback for processed frames (for debug visualization)."""
        self._on_frame = callback
    
    def start(self):
        """Start hand tracking."""
        if not self._initialized:
            logger.error("Cannot start - missing dependencies")
            return
        
        if self._running:
            return
        
        # Initialize MediaPipe
        self._mp_hands = mp.solutions.hands
        self._mp_drawing = mp.solutions.drawing_utils
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=self.max_hands,
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )
        
        # Open camera with backend fallbacks for Windows reliability
        self._cap = self._open_camera()
        if not self._cap:
            logger.error(f"Failed to open camera {self.camera_index}")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._thread.start()
        logger.info("Hand tracker started")
    
    def stop(self):
        """Stop hand tracking."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
        if self._hands:
            self._hands.close()
        logger.info("Hand tracker stopped")
    
    def _tracking_loop(self):
        """Main tracking loop."""
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                continue
            
            # Flip horizontally for selfie view
            frame = cv2.flip(frame, 1)
            
            # Convert to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._hands.process(rgb_frame)
            
            # Process results
            hand_landmarks_list = []
            
            if results.multi_hand_landmarks:
                for idx, hand_lms in enumerate(results.multi_hand_landmarks):
                    # Get handedness
                    handedness = "Right"
                    if results.multi_handedness:
                        handedness = results.multi_handedness[idx].classification[0].label
                        confidence = results.multi_handedness[idx].classification[0].score
                    else:
                        confidence = self.min_detection_confidence
                    
                    # Extract landmarks
                    landmarks = [
                        (lm.x, lm.y, lm.z)
                        for lm in hand_lms.landmark
                    ]
                    
                    hand_landmarks_list.append(HandLandmarks(
                        landmarks=landmarks,
                        handedness=handedness,
                        confidence=confidence,
                    ))
                    
                    # Draw landmarks on frame (for debug)
                    self._mp_drawing.draw_landmarks(
                        frame, hand_lms, self._mp_hands.HAND_CONNECTIONS
                    )
            
            # Callbacks
            if self._on_landmarks and hand_landmarks_list:
                self._on_landmarks(hand_landmarks_list)
            
            if self._on_frame:
                self._on_frame(frame)
    
    @property
    def is_running(self) -> bool:
        return self._running

    def _open_camera(self) -> Optional["cv2.VideoCapture"]:
        """Try multiple OpenCV backends to open the camera reliably."""
        if not HAS_OPENCV:
            return None

        backends = [cv2.CAP_ANY]
        if sys.platform.startswith("win"):
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

        for backend in backends:
            cap = cv2.VideoCapture(self.camera_index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            ready = False
            for _ in range(3):
                ret, frame = cap.read()
                if ret and frame is not None:
                    ready = True
                    break
                threading.Event().wait(0.1)  # Interruptible wait

            if ready:
                logger.info(f"Opened camera {self.camera_index} using backend {backend}")
                return cap

            cap.release()

        return None
