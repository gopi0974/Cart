/**
 * Real In-Browser Privacy & Feature Detector using @mediapipe/tasks-vision.
 * Self-hosted WASM and Models loaded from local /mediapipe/wasm and /mediapipe/models.
 * Lazily loaded on /cart-device, /detector-test and 360 Scan, never in shopper bundle.
 */

export interface NormalizedBox {
  x: number;      // 0..1 (top-left)
  y: number;      // 0..1 (top-left)
  width: number;  // 0..1
  height: number; // 0..1
}

export type DetectorStatus = 'uninitialized' | 'loading' | 'ready' | 'error';

export interface DetectorState {
  status: DetectorStatus;
  error: string | null;
  delegate: 'GPU' | 'CPU' | null;
}

export interface PrivacyDetectionResult {
  detector_ready: boolean;
  face_present: boolean;
  hand_present: boolean;
  hand_count: number;
  face_boxes: NormalizedBox[];
  hand_boxes: NormalizedBox[];
  processing_ms: number;
  delegate: 'GPU' | 'CPU' | null;
  error?: string;
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

  // Privacy rules state: 5 frame cooldown and 1-second retention
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
            minDetectionConfidence: 0.25 // Low threshold to catch small / side-on faces
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
   * Evaluates face and hand presence on a video frame or canvas.
   * Runs on a downscaled 320px wide copy to maintain minimal CPU usage.
   * If detector is not ready or fails, returns safe failure (detector_ready=false).
   */
  public detect(source: HTMLVideoElement | HTMLCanvasElement): PrivacyDetectionResult {
    if (this.status !== 'ready' || !this.faceDetector || !this.handLandmarker) {
      return {
        detector_ready: false,
        face_present: false,
        hand_present: false,
        hand_count: 0,
        face_boxes: [],
        hand_boxes: [],
        processing_ms: 0,
        delegate: this.delegate,
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
        hand_boxes: [],
        processing_ms: 0,
        delegate: this.delegate
      };
    }

    const t0 = performance.now();

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

      // Run MediaPipe FaceDetector
      const faceResults = this.faceDetector.detect(this.downscaleCanvas);
      const rawFaceBoxes: NormalizedBox[] = (faceResults.detections || []).map((d: any) => {
        const box = d.boundingBox;
        if (!box) return { x: 0, y: 0, width: 0, height: 0 };
        return {
          x: Math.max(0, Math.min(1, box.originX / targetWidth)),
          y: Math.max(0, Math.min(1, box.originY / targetHeight)),
          width: Math.max(0, Math.min(1, box.width / targetWidth)),
          height: Math.max(0, Math.min(1, box.height / targetHeight))
        };
      });

      // Run MediaPipe HandLandmarker
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

      const now = Date.now();
      const rawFaceDetected = rawFaceBoxes.length > 0;

      // Settings: Cooldown of 5 frames + treat "face found in the last second" as face_present
      if (rawFaceDetected) {
        this.cooldownFramesRemaining = 5;
        this.lastFaceSeenTimestamp = now;
      } else if (this.cooldownFramesRemaining > 0) {
        this.cooldownFramesRemaining--;
      }

      const faceInLastSecond = (now - this.lastFaceSeenTimestamp) < 1000;
      const face_present = rawFaceDetected || (this.cooldownFramesRemaining > 0) || faceInLastSecond;
      const hand_present = rawHandBoxes.length > 0;
      const processing_ms = Math.round(performance.now() - t0);

      return {
        detector_ready: true,
        face_present,
        hand_present,
        hand_count: rawHandBoxes.length,
        face_boxes: rawFaceBoxes,
        hand_boxes: rawHandBoxes,
        processing_ms,
        delegate: this.delegate
      };
    } catch (err: any) {
      console.warn('[PrivacyDetector] Detection error on frame:', err);
      return {
        detector_ready: false,
        face_present: false,
        hand_present: false,
        hand_count: 0,
        face_boxes: [],
        hand_boxes: [],
        processing_ms: Math.round(performance.now() - t0),
        delegate: this.delegate,
        error: err?.message || 'Frame detection failed'
      };
    }
  }

  public resetCooldown(): void {
    this.cooldownFramesRemaining = 0;
    this.lastFaceSeenTimestamp = 0;
  }
}

export const privacyDetector = new PrivacyDetectorService();

