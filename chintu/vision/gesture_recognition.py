"""Gesture recognition from hand landmarks."""

import math
from enum import Enum
from typing import Optional, List, Callable, Tuple
from dataclasses import dataclass
import logging

from .hand_tracker import HandLandmarks
from ..utils.one_euro_filter import MultiDimensionalOneEuroFilter

logger = logging.getLogger(__name__)


class GestureType(Enum):
    """Recognized gesture types."""
    NONE = "none"
    OPEN_PALM = "open_palm"       # All fingers extended - can trigger listening
    FIST = "fist"                 # All fingers closed
    THUMBS_UP = "thumbs_up"       # Thumbs up - confirmation
    THUMBS_DOWN = "thumbs_down"   # Thumbs down - rejection
    PEACE = "peace"               # Peace sign (index + middle extended)
    POINTING = "pointing"         # Index finger pointing
    OK = "ok"                     # OK sign (thumb + index circle)
    WAVE = "wave"                 # Waving motion (detected over time)


@dataclass
class GestureResult:
    """Result of gesture recognition."""
    gesture: GestureType
    confidence: float
    hand: str  # "Left" or "Right"
    
    
class GestureRecognizer:
    """
    Recognizes hand gestures from MediaPipe landmarks.
    Uses One Euro Filter for smoothing.
    """
    
    def __init__(
        self,
        smoothing_enabled: bool = True,
        min_confidence: float = 0.7,
        gesture_hold_frames: int = 3,
    ):
        self.smoothing_enabled = smoothing_enabled
        self.min_confidence = min_confidence
        self.gesture_hold_frames = gesture_hold_frames
        
        self._filters: dict[int, MultiDimensionalOneEuroFilter] = {}
        self._on_gesture: Optional[Callable[[GestureResult], None]] = None
        self._last_gesture: GestureType = GestureType.NONE
        self._gesture_count = 0
    
    def set_gesture_callback(self, callback: Callable[[GestureResult], None]):
        """Set callback for gesture detection."""
        self._on_gesture = callback
    
    def process_landmarks(self, hands: List[HandLandmarks]) -> Optional[GestureResult]:
        """
        Process hand landmarks and detect gestures.
        
        Args:
            hands: List of detected hand landmarks
            
        Returns:
            Detected gesture or None
        """
        if not hands:
            self._last_gesture = GestureType.NONE
            self._gesture_count = 0
            return None
        
        # Process first hand (primary)
        hand = hands[0]
        
        # Apply smoothing
        smoothed_landmarks = self._smooth_landmarks(hand, hand_id=0)
        
        # Detect gesture
        gesture = self._classify_gesture(smoothed_landmarks, hand.handedness)
        
        # Apply temporal filtering (require consistent detection)
        if gesture == self._last_gesture:
            self._gesture_count += 1
        else:
            self._gesture_count = 1
            self._last_gesture = gesture
        
        if self._gesture_count >= self.gesture_hold_frames and gesture != GestureType.NONE:
            result = GestureResult(
                gesture=gesture,
                confidence=hand.confidence,
                hand=hand.handedness,
            )
            
            if self._on_gesture:
                self._on_gesture(result)
            
            return result
        
        return None
    
    def _smooth_landmarks(self, hand: HandLandmarks, hand_id: int) -> List[Tuple[float, float, float]]:
        """Apply One Euro Filter to landmarks."""
        if not self.smoothing_enabled:
            return hand.landmarks
        
        # Create filter for this hand if not exists
        if hand_id not in self._filters:
            self._filters[hand_id] = {
                i: MultiDimensionalOneEuroFilter(dimensions=3, min_cutoff=1.0, beta=0.007)
                for i in range(21)
            }
        
        filters = self._filters[hand_id]
        smoothed = []
        
        for i, (x, y, z) in enumerate(hand.landmarks):
            filtered = filters[i].filter([x, y, z])
            smoothed.append(tuple(filtered))
        
        return smoothed
    
    def _classify_gesture(self, landmarks: List[Tuple[float, float, float]], handedness: str) -> GestureType:
        """Classify gesture from landmarks."""
        # Check which fingers are extended
        fingers_extended = self._get_fingers_extended(landmarks, handedness)
        thumb, index, middle, ring, pinky = fingers_extended
        
        # Open palm - all fingers extended
        if all(fingers_extended):
            return GestureType.OPEN_PALM
        
        # Fist - no fingers extended
        if not any(fingers_extended):
            return GestureType.FIST
        
        # Thumbs up - only thumb extended
        if thumb and not any([index, middle, ring, pinky]):
            # Check thumb is pointing up
            thumb_tip = landmarks[HandLandmarks.THUMB_TIP]
            thumb_mcp = landmarks[HandLandmarks.THUMB_MCP]
            if thumb_tip[1] < thumb_mcp[1]:  # y is inverted
                return GestureType.THUMBS_UP
            else:
                return GestureType.THUMBS_DOWN
        
        # Peace sign - index and middle extended
        if index and middle and not ring and not pinky:
            return GestureType.PEACE
        
        # Pointing - only index extended
        if index and not any([middle, ring, pinky]):
            return GestureType.POINTING
        
        return GestureType.NONE
    
    def _get_fingers_extended(self, landmarks: List[Tuple[float, float, float]], handedness: str) -> Tuple[bool, bool, bool, bool, bool]:
        """
        Determine which fingers are extended.
        
        Returns:
            Tuple of (thumb, index, middle, ring, pinky) booleans
        """
        def distance(p1, p2):
            return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))
        
        wrist = landmarks[HandLandmarks.WRIST]
        
        # Thumb: compare tip to IP joint, considering handedness
        thumb_tip = landmarks[HandLandmarks.THUMB_TIP]
        thumb_ip = landmarks[HandLandmarks.THUMB_IP]
        thumb_mcp = landmarks[HandLandmarks.THUMB_MCP]
        
        # For thumb, check if tip is further from wrist than mcp
        thumb_extended = distance(thumb_tip, wrist) > distance(thumb_mcp, wrist) * 1.2
        
        # Other fingers: check if tip is above PIP (in y-coordinates)
        index_extended = landmarks[HandLandmarks.INDEX_TIP][1] < landmarks[HandLandmarks.INDEX_PIP][1]
        middle_extended = landmarks[HandLandmarks.MIDDLE_TIP][1] < landmarks[HandLandmarks.MIDDLE_PIP][1]
        ring_extended = landmarks[HandLandmarks.RING_TIP][1] < landmarks[HandLandmarks.RING_PIP][1]
        pinky_extended = landmarks[HandLandmarks.PINKY_TIP][1] < landmarks[HandLandmarks.PINKY_PIP][1]
        
        return (thumb_extended, index_extended, middle_extended, ring_extended, pinky_extended)
    
    def reset(self):
        """Reset gesture recognition state."""
        self._filters.clear()
        self._last_gesture = GestureType.NONE
        self._gesture_count = 0

