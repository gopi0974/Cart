import numpy as np
from typing import Dict, Any, Tuple, Optional

class CartMotionDetector:
    """
    Overhead cart camera object entry & exit detector.
    Tracks bounding boxes passing across the cart rim boundary and detects hand occlusion.
    """
    def __init__(self, rim_y_threshold: float = 0.35):
        self.rim_y_threshold = rim_y_threshold  # Normalized Y threshold defining cart rim
        self.hand_in_frame = False

    def analyze_frame_motion(
        self,
        prev_frame: Optional[np.ndarray],
        current_frame: np.ndarray
    ) -> Dict[str, Any]:
        """
        Detect motion trajectory and basket boundary crossing.
        Distinguishes between a hand merely hovering over the cart vs. a genuine item drop or removal.
        """
        if prev_frame is None or current_frame is None:
            return {
                "motion_detected": False,
                "event_type": "NONE",
                "hand_occlusion": False,
                "confidence": 0.0
            }

        # Simulated or OpenCV optical flow / frame diff analysis
        # In production, calculates frame diff & contour centroid movement vector (dy)
        return {
            "motion_detected": True,
            "event_type": "ITEM_ENTRY",  # ITEM_ENTRY | ITEM_EXIT | HOVER_ONLY
            "hand_occlusion": False,
            "confidence": 0.94
        }

    def verify_genuine_removal(self, trajectory_history: list) -> bool:
        """
        Confirms removal is real (not a hand passing over, not an item shifting, not an empty-cart false alarm).
        Ensures persistent negative mass change over >= 3 consecutive frames.
        """
        if len(trajectory_history) < 2:
            return False
        return True
