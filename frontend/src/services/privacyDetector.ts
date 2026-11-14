/**
 * Real In-Browser Privacy & Feature Detector using @mediapipe/tasks-vision.
 * Self-hosted WASM and Models loaded from local /mediapipe/wasm and /mediapipe/models.
 * Lazily loaded on /cart-device, /detector-test and 360 Scan, never in shopper bundle.
 */

import { DETECTOR_PROFILES, DetectorProfile, getDetectorProfile } from '../config/detectorProfiles';

export interface NormalizedBox {
  x: number;      // 0..1 (top-left)
  y: number;      // 0..1 (top-left)
  width: number;  // 0..1
  height: number; // 0..1
}

export interface DetectedFaceBox extends NormalizedBox {
  score: number;             // Confidence 0..1
  areaFraction: number;      // width * height (0..1)
  widthFraction: number;     // width (0..1)
  heightFraction: number;    // height (0..1)
  consecutiveFrames: number; // How many consecutive frames this face box persisted
  isStaticBackground?: boolean; // True if matched to Step 0 static reference
}

export type DetectorStatus = 'uninitialized' | 'loading' | 'ready' | 'error';

export interface DetectorState {
  status: DetectorStatus;
  error: string | null;
  delegate: 'GPU' | 'CPU' | null;
}

export interface PrivacyDetectionResult {
  detector_ready: boolean;
  face_present: boolean;        // Whether active qualifying face is considered present
  hand_present: boolean;
  hand_count: number;
  face_boxes: DetectedFaceBox[];// All detected face boxes with score, size, consecutive frames
  active_face_boxes: DetectedFaceBox[]; // Qualifying boxes (non-static, >= minConsecutiveFrames, >= minConfidence)
  ignored_static_boxes: DetectedFaceBox[]; // Static boxes ignored (e.g. posters/background from Step 0)
  hand_boxes: NormalizedBox[];
  processing_ms: number;
  delegate: 'GPU' | 'CPU' | null;
  profile: 'privacy' | 'enrollment';
  error?: string;
}

interface TrackedFace {
  box: NormalizedBox;
  score: number;
  consecutiveFrames: number;
  lastSeenTimestamp: number;
}

function computeIoU(b1: NormalizedBox, b2: NormalizedBox): number {
  const x1 = Math.max(b1.x, b2.x);
  const y1 = Math.max(b1.y, b2.y);
  const x2 = Math.min(b1.x + b1.width, b2.x + b2.width);
  const y2 = Math.min(b1.y + b1.height, b2.y + b2.height);
  if (x2 <= x1 || y2 <= y1) return 0;
  const inter = (x2 - x1) * (y2 - y1);
  const union = (b1.width * b1.height) + (b2.width * b2.height) - inter;
  return union > 0 ? inter / union : 0;
}

function centerDistance(b1: NormalizedBox, b2: NormalizedBox): number {
  const c1x = b1.x + b1.width / 2;
  const c1y = b1.y + b1.height / 2;
  const c2x = b2.x + b2.width / 2;
  const c2y = b2.y + b2.height / 2;
  return Math.hypot(c1x - c2x, c1y - c2y);
}

class PrivacyDetectorService {
  private status: DetectorStatus = 'uninitialized';
  private error: string | null = null;
  private delegate: 'GPU' | 'CPU' | null = null;

  // MediaPipe task instances
  private faceDetector: any = null;
  private handLandmarker: any = null;

  // Cached loading promise
  private initPromise: Promise<void> | null = null;

  // Downscaled canvas for ~320px processing
  private downscaleCanvas: HTMLCanvasElement | null = null;
  private downscaleCtx: CanvasRenderingContext2D | null = null;

  // Multi-frame tracking state
  private trackedFaces: TrackedFace[] = [];
  private staticReferenceBoxes: NormalizedBox[] = [];
  private cooldownFramesRemaining: number = 0;
  private lastFaceSeenTimestamp: number = 0;

  // Listeners
  private stateListeners: Set<(state: DetectorState) => void> = new Set();

  constructor() {
    if (typeof document !== 'undefined') {
      this.downscaleCanvas = document.createElement('canvas');
      this.downscaleCtx = this.downscaleCanvas.getContext('2d', { willReadFrequently: true });
    }
  }

  public getState(): DetectorState {
    return {
      status: this.status,
      error: this.error,
      delegate: this.delegate
    };
  }

  public subscribeState(listener: (state: DetectorState) => void): () => void {
    this.stateListeners.add(listener);
    listener(this.getState());
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  private notifyState(): void {
    const s = this.getState();
    this.stateListeners.forEach((l) => {
      try { l(s); } catch {}
    });
  }

  /**
   * Lazily loads WASM and models once. Thread-safe and cached.
   */
  public async load(): Promise<void> {
    if (this.status === 'ready') return;
    if (this.initPromise) return this.initPromise;

    this.status = 'loading';
    this.error = null;
    this.notifyState();

    this.initPromise = (async () => {
      try {
        // Dynamic import ensures @mediapipe/tasks-vision is split into a separate bundle chunk
        const { FilesetResolver, FaceDetector, HandLandmarker } = await import('@mediapipe/tasks-vision');

        // Resolve self-hosted WASM binary and loader
        const vision = await FilesetResolver.forVisionTasks('/mediapipe/wasm');

        // 1. Try GPU delegate first for maximum performance
        try {
          this.faceDetector = await FaceDetector.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath: '/mediapipe/models/blaze_face_short_range.tflite',
              delegate: 'GPU'
            },
            runningMode: 'IMAGE',
            minDetectionConfidence: 0.25 // Base low threshold; profile applies final gating
          });

          this.handLandmarker = await HandLandmarker.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath: '/mediapipe/models/hand_landmarker.task',
              delegate: 'GPU'
            },
            runningMode: 'IMAGE',
            numHands: 2,
            minHandDetectionConfidence: 0.3,
            minHandPresenceConfidence: 0.3,
            minTrackingConfidence: 0.3
          });

          this.delegate = 'GPU';
        } catch (gpuErr: any) {
          console.warn('[PrivacyDetector] GPU delegate initialization failed, falling back to CPU:', gpuErr);

          // 2. CPU fallback if WebGL/GPU is unavailable or context lost
          this.faceDetector = await FaceDetector.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath: '/mediapipe/models/blaze_face_short_range.tflite',
              delegate: 'CPU'
            },
            runningMode: 'IMAGE',
            minDetectionConfidence: 0.25
          });

          this.handLandmarker = await HandLandmarker.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath: '/mediapipe/models/hand_landmarker.task',
              delegate: 'CPU'
            },
            runningMode: 'IMAGE',
            numHands: 2,
            minHandDetectionConfidence: 0.3,
            minHandPresenceConfidence: 0.3,
            minTrackingConfidence: 0.3
          });

          this.delegate = 'CPU';
        }

        this.status = 'ready';
        this.error = null;
        this.notifyState();
      } catch (err: any) {
        console.error('[PrivacyDetector] Fatal failure loading MediaPipe models or WASM:', err);
        this.status = 'error';
        this.error = err?.message || 'Failed to load self-hosted privacy detector models.';
        this.notifyState();
        throw err;
      } finally {
        this.initPromise = null;
      }
    })();

    return this.initPromise;
  }

  /**
   * Sets static background reference face boxes from Step 0 (empty scene calibration).
   * Detections matching these coordinates will be treated as static false positives (e.g. posters).
   */
  public setStaticReferenceBoxes(boxes: NormalizedBox[]): void {
    this.staticReferenceBoxes = [...boxes];
    console.log(`[PrivacyDetector] Configured ${boxes.length} static reference false-positive box(es) to ignore.`);
  }

  public getStaticReferenceBoxes(): NormalizedBox[] {
    return [...this.staticReferenceBoxes];
  }

  public clearStaticReferenceBoxes(): void {
    this.staticReferenceBoxes = [];
  }

  /**
   * Evaluates face and hand presence on a video frame or canvas using the chosen profile.
   * "privacy": conservative (confidence >= 0.30, 1 frame, 800ms cooldown)
   * "enrollment": robust (confidence >= 0.60, min box 6% width, 3 frames persistence, 300ms cooldown)
   */
  public detect(
    source: HTMLVideoElement | HTMLCanvasElement,
    profileName: 'privacy' | 'enrollment' = 'privacy'
  ): PrivacyDetectionResult {
    const profile = getDetectorProfile(profileName);

    if (this.status !== 'ready' || !this.faceDetector || !this.handLandmarker) {
      return {
        detector_ready: false,
        face_present: false,
        hand_present: false,
        hand_count: 0,
        face_boxes: [],
        active_face_boxes: [],
        ignored_static_boxes: [],
        hand_boxes: [],
        processing_ms: 0,
        delegate: this.delegate,
        profile: profile.name,
        error: this.error || 'Privacy detector not ready'
      };
    }

    const sourceWidth = 'videoWidth' in source ? (source.videoWidth || 640) : (source.width || 640);
    const sourceHeight = 'videoHeight' in source ? (source.videoHeight || 480) : (source.height || 480);

    if (sourceWidth === 0 || sourceHeight === 0) {
      return {
        detector_ready: true,
        face_present: false,
        hand_present: false,
        hand_count: 0,
        face_boxes: [],
        active_face_boxes: [],
        ignored_static_boxes: [],
        hand_boxes: [],
        processing_ms: 0,
        delegate: this.delegate,
        profile: profile.name
      };
    }

    const t0 = performance.now();
    const now = Date.now();

    try {
      // Downscale to ~320 px wide copy preserving aspect ratio
      const targetWidth = 320;
      const targetHeight = Math.max(120, Math.round((targetWidth * sourceHeight) / sourceWidth));

      if (!this.downscaleCanvas) {
        this.downscaleCanvas = document.createElement('canvas');
        this.downscaleCtx = this.downscaleCanvas.getContext('2d', { willReadFrequently: true });
      }

      this.downscaleCanvas.width = targetWidth;
      this.downscaleCanvas.height = targetHeight;

      if (!this.downscaleCtx) {
        throw new Error('Canvas 2D context unavailable');
      }

      this.downscaleCtx.drawImage(source, 0, 0, targetWidth, targetHeight);

      // 1. Run MediaPipe FaceDetector
      const faceResults = this.faceDetector.detect(this.downscaleCanvas);
      const rawDetections = faceResults.detections || [];

      // Extract bounding boxes and confidence scores
      const currentFrameDetections: { box: NormalizedBox; score: number }[] = rawDetections.map((d: any) => {
        const box = d.boundingBox;
        const score = (d.categories && d.categories[0] && typeof d.categories[0].score === 'number')
          ? d.categories[0].score
          : (typeof d.score === 'number' ? d.score : 0.90);

        if (!box) return { box: { x: 0, y: 0, width: 0, height: 0 }, score };

        return {
          box: {
            x: Math.max(0, Math.min(1, box.originX / targetWidth)),
            y: Math.max(0, Math.min(1, box.originY / targetHeight)),
            width: Math.max(0, Math.min(1, box.width / targetWidth)),
            height: Math.max(0, Math.min(1, box.height / targetHeight))
          },
          score: Math.round(score * 100) / 100
        };
      });

      // 2. Multi-frame persistence tracking (IoU / Center Distance matching)
      const nextTrackedFaces: TrackedFace[] = [];
      const detailedFaceBoxes: DetectedFaceBox[] = [];

      for (const cur of currentFrameDetections) {
        // Find best match in previous tracked faces
        let bestMatchIdx = -1;
        let bestMatchScore = 0;

        for (let i = 0; i < this.trackedFaces.length; i++) {
          const prev = this.trackedFaces[i];
          const iou = computeIoU(cur.box, prev.box);
          const dist = centerDistance(cur.box, prev.box);

          if (iou >= 0.20 || dist <= 0.12) {
            const matchScore = iou > 0 ? iou : (1.0 - dist);
            if (matchScore > bestMatchScore) {
              bestMatchScore = matchScore;
              bestMatchIdx = i;
            }
          }
        }

        let consecutiveFrames = 1;
        if (bestMatchIdx >= 0) {
          consecutiveFrames = this.trackedFaces[bestMatchIdx].consecutiveFrames + 1;
        }

        nextTrackedFaces.push({
          box: cur.box,
          score: cur.score,
          consecutiveFrames,
          lastSeenTimestamp: now
        });

        // Check if this detection matches any static reference box from Step 0
        let isStaticBackground = false;
        for (const refBox of this.staticReferenceBoxes) {
          const refIou = computeIoU(cur.box, refBox);
          const refDist = centerDistance(cur.box, refBox);
          const sizeDiff = Math.abs(cur.box.width - refBox.width);

          if (refIou >= 0.20 || (refDist <= 0.10 && sizeDiff <= 0.08)) {
            isStaticBackground = true;
            break;
          }
        }

        const areaFraction = cur.box.width * cur.box.height;

        detailedFaceBoxes.push({
          ...cur.box,
          score: cur.score,
          areaFraction: Math.round(areaFraction * 1000) / 1000,
          widthFraction: Math.round(cur.box.width * 1000) / 1000,
          heightFraction: Math.round(cur.box.height * 1000) / 1000,
          consecutiveFrames,
          isStaticBackground
        });
      }

      this.trackedFaces = nextTrackedFaces;

      // 3. Filter qualifying active face intrusions according to active profile
      const activeFaceBoxes: DetectedFaceBox[] = [];
      const ignoredStaticBoxes: DetectedFaceBox[] = [];

      for (const fb of detailedFaceBoxes) {
        if (fb.isStaticBackground) {
          ignoredStaticBoxes.push(fb);
          continue;
        }

        // Confidence and size gating based on active profile
        const meetsConfidence = fb.score >= profile.minFaceConfidence;
        const meetsMinSize = fb.width >= profile.minFaceBoxWidthFraction;
        const meetsConsecutive = fb.consecutiveFrames >= profile.minConsecutiveFrames;

        if (meetsConfidence && meetsMinSize && meetsConsecutive) {
          activeFaceBoxes.push(fb);
        }
      }

      // 4. Cooldown logic based on profile settings
      const rawActiveDetected = activeFaceBoxes.length > 0;

      if (rawActiveDetected) {
        this.cooldownFramesRemaining = profile.cooldownFrames;
        this.lastFaceSeenTimestamp = now;
      } else if (this.cooldownFramesRemaining > 0) {
        this.cooldownFramesRemaining--;
      }

      // Check whether still in cooldown window
      const elapsedSinceLastSeen = now - this.lastFaceSeenTimestamp;
      const inCooldown = (elapsedSinceLastSeen < profile.cooldownMs) && (this.cooldownFramesRemaining > 0);

      // In enrollment mode, flag clears promptly when consecutive frames lack detection
      const face_present = rawActiveDetected || inCooldown;

      // 5. Run MediaPipe HandLandmarker
      const handResults = this.handLandmarker.detect(this.downscaleCanvas);
      const rawHandBoxes: NormalizedBox[] = (handResults.landmarks || []).map((landmarks: any[]) => {
        let minX = 1;
        let maxX = 0;
        let minY = 1;
        let maxY = 0;
        for (const pt of landmarks) {
          if (pt.x < minX) minX = pt.x;
          if (pt.x > maxX) maxX = pt.x;
          if (pt.y < minY) minY = pt.y;
          if (pt.y > maxY) maxY = pt.y;
        }
        return {
          x: Math.max(0, Math.min(1, minX)),
          y: Math.max(0, Math.min(1, minY)),
          width: Math.max(0, Math.min(1, maxX - minX)),
          height: Math.max(0, Math.min(1, maxY - minY))
        };
      });

      const hand_present = rawHandBoxes.length > 0;
      const processing_ms = Math.round(performance.now() - t0);

      return {
        detector_ready: true,
        face_present,
        hand_present,
        hand_count: rawHandBoxes.length,
        face_boxes: detailedFaceBoxes,
        active_face_boxes: activeFaceBoxes,
        ignored_static_boxes: ignoredStaticBoxes,
        hand_boxes: rawHandBoxes,
        processing_ms,
        delegate: this.delegate,
        profile: profile.name
      };
    } catch (err: any) {
      console.warn('[PrivacyDetector] Detection error on frame:', err);
      return {
        detector_ready: false,
        face_present: false,
        hand_present: false,
        hand_count: 0,
        face_boxes: [],
        active_face_boxes: [],
        ignored_static_boxes: [],
        hand_boxes: [],
        processing_ms: Math.round(performance.now() - t0),
        delegate: this.delegate,
        profile: profile.name,
        error: err?.message || 'Frame detection failed'
      };
    }
  }

  public resetCooldown(): void {
    this.cooldownFramesRemaining = 0;
    this.lastFaceSeenTimestamp = 0;
    this.trackedFaces = [];
  }
}

export const privacyDetector = new PrivacyDetectorService();
