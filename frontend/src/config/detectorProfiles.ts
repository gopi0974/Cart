/**
 * Detector Profiles for In-Browser Privacy & Feature Detection.
 * 
 * Two Profiles:
 * 1. "privacy" (/cart-device):
 *    - Conservative protection for live shopper camera.
 *    - Lower confidence threshold (>= 0.30) to catch partial, side-on, or shadowed faces.
 *    - Fast trigger (1 frame) and longer retention (800ms) to ensure no face pixels leak.
 * 
 * 2. "enrollment" (Admin 360 Scan):
 *    - Optimized for product catalog enrollment without false-positive blocking.
 *    - Higher confidence threshold (>= 0.60) to ignore wrinkles, packaging logos, and barcodes.
 *    - Minimum box size of 6% frame width to ignore distant background specks.
 *    - Requires 3 consecutive frames to filter out single-frame camera noise.
 *    - Short cooldown (300ms / 0.3s) releasing immediately when clear.
 */

export interface DetectorProfile {
  name: 'privacy' | 'enrollment';
  minFaceConfidence: number;
  minFaceBoxWidthFraction: number; // Fraction of frame width (e.g. 0.06 = 6%)
  minConsecutiveFrames: number;     // Consecutive detections required to raise flag
  cooldownMs: number;              // Latch duration in ms after detection ceases
  cooldownFrames: number;          // Minimum cooldown frames
  largeFaceAreaThreshold: number;  // Face larger than ~15% of frame always flags
  guideBoxOverlapThreshold: number;// Overlap ratio with guide box / product crop
}

export const DETECTOR_PROFILES: Record<'privacy' | 'enrollment', DetectorProfile> = {
  privacy: {
    name: 'privacy',
    minFaceConfidence: 0.30,         // Conservative: flags any potential face >= 30%
    minFaceBoxWidthFraction: 0.02,   // Detects even tiny faces (2% of frame width)
    minConsecutiveFrames: 1,         // Immediate: 1 frame raises flag
    cooldownMs: 800,                 // Retains for 800ms to prevent leak during fast motion
    cooldownFrames: 5,
    largeFaceAreaThreshold: 0.15,    // 15% of frame area
    guideBoxOverlapThreshold: 0.05,  // Any 5% overlap blocks
  },
  enrollment: {
    name: 'enrollment',
    minFaceConfidence: 0.60,         // Robust: ignores package text, cartoon logos & folds
    minFaceBoxWidthFraction: 0.06,   // Ignores distant background noise < 6% frame width
    minConsecutiveFrames: 3,         // Temporal filter: requires 3 consecutive frames
    cooldownMs: 300,                 // Short 0.3s cooldown
    cooldownFrames: 1,               // Fast release as soon as frame is clear
    largeFaceAreaThreshold: 0.15,    // Face >15% frame area flags even if outside guide box
    guideBoxOverlapThreshold: 0.05,  // Overlap with guide box or product crop blocks
  },
};

export const getDetectorProfile = (name: 'privacy' | 'enrollment'): DetectorProfile => {
  return DETECTOR_PROFILES[name] || DETECTOR_PROFILES.privacy;
};

