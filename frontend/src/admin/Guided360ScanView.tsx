import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera, Check, RefreshCw, Volume2, VolumeX, Sparkles, AlertCircle,
  ArrowLeft, X, Trash2, AlertTriangle, CheckCircle2, Plus, Zap,
  Play, Pause, SkipForward, Scan, ShieldAlert, Eye, XCircle, Circle, Loader2, Info
} from 'lucide-react';
import { Product } from '../types';
import { api } from '../services/api';
import { privacyDetector, DetectedFaceBox } from '../services/privacyDetector';

interface Props {
  product: Product;
  onComplete: () => void;
  onPreviewTest: () => void;
}

export interface ProductBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CapturedFrame {
  dataUrl: string; // Cropped to product bounding box with 5% margin (never full frame)
  blurScore: number;
  timestamp: number;
  box: ProductBoundingBox;
}

interface AngleStep {
  tag: string;
  label: string;
  prompt: string;
  speechText: string;
  degree: number;
}

// 9 Required Angles covering all packaging perspectives
const REQUIRED_ANGLES: AngleStep[] = [
  { tag: 'FRONT', label: 'Front View', prompt: 'Hold item facing directly at camera', speechText: 'Show the front packaging, hold still', degree: 0 },
  { tag: 'RIGHT', label: 'Right Side', prompt: 'Rotate slowly to the right side', speechText: 'Rotate slowly to the right', degree: 40 },
  { tag: 'BACK', label: 'Back Packaging', prompt: 'Show the back packaging', speechText: 'Show the back packaging', degree: 80 },
  { tag: 'LEFT', label: 'Left Side', prompt: 'Rotate to show the left side', speechText: 'Rotate to show the left side', degree: 120 },
  { tag: 'TOP', label: 'Top Lid', prompt: 'Tilt up to show the top lid', speechText: 'Tilt up for the top lid', degree: 160 },
  { tag: 'BOTTOM', label: 'Bottom Base', prompt: 'Tilt down to show the base', speechText: 'Tilt down for the bottom base', degree: 200 },
  { tag: 'LABEL_CLOSEUP', label: 'Label Close-up', prompt: 'Bring closer to show nutrition & barcode label, hold still', speechText: 'Bring it closer for label close-up, hold still', degree: 240 },
  { tag: 'TILT_UP', label: 'Top-Angle 45°', prompt: 'Tilt product 45° upward towards ceiling', speechText: 'Tilt forty-five degrees upward, hold still', degree: 280 },
  { tag: 'TILT_DOWN', label: 'Bottom-Angle 45°', prompt: 'Tilt product 45° downward towards desk', speechText: 'Tilt forty-five degrees downward, hold still', degree: 320 },
];

export const Guided360ScanView: React.FC<Props> = ({ product, onComplete, onPreviewTest }) => {
  // Step 0: Background Reference Calibration States
  const [bgCalibrated, setBgCalibrated] = useState(false);
  const [isCalibratingBg, setIsCalibratingBg] = useState(true);
  const [bgFramesCaptured, setBgFramesCaptured] = useState<number>(0);

  // Guided Steps (1 through 9)
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [productConfirmedForStep, setProductConfirmedForStep] = useState(false);
  const [captures, setCaptures] = useState<Record<string, CapturedFrame[]>>({});
  const [stepFrames, setStepFrames] = useState<CapturedFrame[]>([]);
  const [isScanning, setIsScanning] = useState(true);
  const [isPaused, setIsPaused] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState(true);

  // Guided Step Progress & Timing States
  const [stepPhase, setStepPhase] = useState<'WAITING_STEADY' | 'COUNTDOWN' | 'CAPTURING' | 'STEP_COMPLETED'>('WAITING_STEADY');
  const [countdown, setCountdown] = useState<number>(3);
  const [stepElapsedTime, setStepElapsedTime] = useState<number>(0);

  // Real Frame Analysis Telemetry & Isolation
  const [liveBlurScore, setLiveBlurScore] = useState<number>(0);
  const [liveBrightness, setLiveBrightness] = useState<number>(120);
  const [cameraFeedback, setCameraFeedback] = useState<string>('Step 0: Clear background of all items');
  const [focusStatus, setFocusStatus] = useState<'BLURRY' | 'STEADY' | 'SHARP'>('BLURRY');
  const [cameraError, setCameraError] = useState<string | null>(null);

  // Product Detection & Exclusion Warnings
  const [faceDetectedWarning, setFaceDetectedWarning] = useState(false);
  const [handDetectedWarning, setHandDetectedWarning] = useState(false);
  const [detectorStatus, setDetectorStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [detectorError, setDetectorError] = useState<string | null>(null);
  const [productRatio, setProductRatio] = useState<number>(0);
  const [detectedBox, setDetectedBox] = useState<ProductBoundingBox | null>(null);

  // Face Detection Telemetry, Reasons, Static Background & Admin Override States
  const [blockingFaces, setBlockingFaces] = useState<DetectedFaceBox[]>([]);
  const [outsideFaces, setOutsideFaces] = useState<DetectedFaceBox[]>([]);
  const [allDetectedFaces, setAllDetectedFaces] = useState<DetectedFaceBox[]>([]);
  const [staticRefFacesCount, setStaticRefFacesCount] = useState<number>(0);
  const [captureBlockedReason, setCaptureBlockedReason] = useState<string | null>(null);
  const [blockedAttemptsCount, setBlockedAttemptsCount] = useState<number>(0);
  const [adminConfirmNoFace, setAdminConfirmNoFace] = useState<boolean>(false);

  // Load real in-browser MediaPipe Privacy Detector
  useEffect(() => {
    let mounted = true;
    privacyDetector.load()
      .then(() => {
        if (mounted) {
          setDetectorStatus('ready');
        }
      })
      .catch((err) => {
        if (mounted) {
          setDetectorStatus('error');
          setDetectorError(err?.message || 'Failed to initialize privacy detector');
        }
      });
    return () => { mounted = false; };
  }, []);

  // Submission & Pipeline State (Real Background Job)
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<'PENDING' | 'PROCESSING' | 'ENROLLED' | 'FAILED' | 'CANCELLED' | null>(null);
  const [jobStage, setJobStage] = useState<string>('QUEUED');
  const [jobStageMessage, setJobStageMessage] = useState<string>('');
  const [jobDone, setJobDone] = useState<number>(0);
  const [jobTotal, setJobTotal] = useState<number>(0);
  const [jobError, setJobError] = useState<string | null>(null);
  const [enrollmentStats, setEnrollmentStats] = useState<any>(null);
  const [isDone, setIsDone] = useState(false);

  // Upload verification & retry states
  const [failedUploads, setFailedUploads] = useState<any[]>([]);
  const [cachedCompressedFrames, setCachedCompressedFrames] = useState<any[]>([]);
  const [cachedUploadItems, setCachedUploadItems] = useState<any[]>([]);
  const [cachedUploadedRefs, setCachedUploadedRefs] = useState<any[]>([]);
  const [partialConfirmation, setPartialConfirmation] = useState<{ surviving: number; total: number; missingAngles: string[] } | null>(null);

  // Selected angle for expanded review gallery
  const [selectedGalleryAngle, setSelectedGalleryAngle] = useState<string | null>(null);

  // Cancellation and Exit Confirmation Dialogs
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [showCancelProcessingConfirm, setShowCancelProcessingConfirm] = useState(false);
  const [bgProcessingNotice, setBgProcessingNotice] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Background Reference Storage
  const bgRefAccumulator = useRef<Float32Array[]>([]);
  const bgRefAverage = useRef<Float32Array | null>(null);

  // Refs for precise timing, motion detection, and duplicate skipping
  const stepStartTimeRef = useRef<number>(Date.now());
  const scanStartTimeRef = useRef<number>(Date.now());
  const lastCaptureTimeRef = useRef<number>(0);
  const prevGrayRef = useRef<Float32Array | null>(null);
  const lastCapturedGrayRef = useRef<Float32Array | null>(null);
  const steadyCounterRef = useRef<number>(0);
  const phaseRef = useRef<'WAITING_STEADY' | 'COUNTDOWN' | 'CAPTURING' | 'STEP_COMPLETED'>('WAITING_STEADY');
  const isPausedRef = useRef<boolean>(false);
  const currentStepIdxRef = useRef<number>(0);
  const retakeTargetAngleRef = useRef<string | null>(null);
  const productConfirmedRef = useRef<boolean>(false);
  const detectedBoxRef = useRef<ProductBoundingBox | null>(null);
  const faceDetectedRef = useRef<boolean>(false);
  const productRatioRef = useRef<number>(0);

  phaseRef.current = stepPhase;
  isPausedRef.current = isPaused;
  currentStepIdxRef.current = currentStepIdx;
  productConfirmedRef.current = productConfirmedForStep;
  detectedBoxRef.current = detectedBox;
  faceDetectedRef.current = faceDetectedWarning;
  productRatioRef.current = productRatio;

  // Stop camera tracks immediately
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  // Check if this product already has an active background job
  useEffect(() => {
    let mounted = true;
    async function checkActive() {
      try {
        const res = await api.getProductActiveJob(product.id);
        if (mounted && res.has_active_job && res.job) {
          setActiveJobId(res.job.job_id);
          setJobStatus(res.job.status);
          setJobStage(res.job.stage);
          setJobStageMessage(res.job.stage_message || '');
          setJobDone(res.job.done);
          setJobTotal(res.job.total);
          setIsProcessing(true);
        }
      } catch (e) {
        // ignore
      }
    }
    checkActive();
    return () => {
      mounted = false;
    };
  }, [product.id]);

  // 1. Initialize real webcam stream
  useEffect(() => {
    let active = true;

    async function startCamera() {
      try {
        setCameraError(null);
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1280 },
            height: { ideal: 720 },
            facingMode: 'user',
          },
          audio: false,
        });

        if (!active) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      } catch (err: any) {
        console.error('Camera access failed:', err);
        try {
          const fallbackStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          if (!active) {
            fallbackStream.getTracks().forEach((t) => t.stop());
            return;
          }
          streamRef.current = fallbackStream;
          if (videoRef.current) {
            videoRef.current.srcObject = fallbackStream;
            videoRef.current.play().catch(() => {});
          }
        } catch (e: any) {
          setCameraError('Webcam access was denied or not found. Please connect a webcam.');
        }
      }
    }

    startCamera();

    return () => {
      active = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, []);

  // 2. Speak voice directions on step transition
  useEffect(() => {
    if (!voiceEnabled || !isScanning || isDone) return;
    if (isCalibratingBg) {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance('Step zero: Please show the empty background without hands or product.');
        utterance.rate = 1.0;
        window.speechSynthesis.speak(utterance);
      }
      return;
    }

    const step = REQUIRED_ANGLES[currentStepIdx];
    if (step && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(step.speechText);
      utterance.rate = 1.0;
      utterance.pitch = 1.05;
      window.speechSynthesis.speak(utterance);
    }
  }, [currentStepIdx, voiceEnabled, isScanning, isDone, isCalibratingBg]);

  // Capture Cropped Product Frame (Never Full Frame)
  const captureFrameInternal = useCallback((): CapturedFrame | null => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return null;

    const vw = video.videoWidth || 1280;
    const vh = video.videoHeight || 720;

    // Cropped product box with 5% margin (Strict privacy protection: only crop is captured)
    const box = detectedBoxRef.current || {
      x: Math.round(vw * 0.20),
      y: Math.round(vh * 0.15),
      width: Math.round(vw * 0.60),
      height: Math.round(vh * 0.70),
    };

    const cropCanvas = document.createElement('canvas');
    cropCanvas.width = Math.max(50, box.width);
    cropCanvas.height = Math.max(50, box.height);
    const cropCtx = cropCanvas.getContext('2d');
    if (!cropCtx) return null;

    cropCtx.drawImage(
      video,
      box.x, box.y, box.width, box.height,
      0, 0, box.width, box.height
    );
    const croppedDataUrl = cropCanvas.toDataURL('image/jpeg', 0.90);

    return {
      dataUrl: croppedDataUrl,
      blurScore: liveBlurScore,
      timestamp: Date.now(),
      box,
    };
  }, [liveBlurScore]);

  // Finish a step when minimum good frames (>= 5) and duration (>= 3.0s) are met
  const finishStep = useCallback((completedFrames: CapturedFrame[]) => {
    const step = REQUIRED_ANGLES[currentStepIdxRef.current];
    const durationSec = ((Date.now() - stepStartTimeRef.current) / 1000).toFixed(2);
    console.log(`[Guided360] Step ${currentStepIdxRef.current + 1}/9 (${step.tag}) completed in ${durationSec}s, captured ${completedFrames.length} frames.`);

    setCaptures((prev) => ({ ...prev, [step.tag]: completedFrames }));
    setStepPhase('STEP_COMPLETED');

    setTimeout(() => {
      // If user was retaking a specific angle from gallery:
      if (retakeTargetAngleRef.current) {
        retakeTargetAngleRef.current = null;
        setCaptures((latestCaptures) => {
          const completedCount = REQUIRED_ANGLES.filter((a) => (latestCaptures[a.tag]?.length || 0) >= 4).length;
          if (completedCount === REQUIRED_ANGLES.length) {
            setIsScanning(false);
            setIsDone(true);
          } else {
            const missing = REQUIRED_ANGLES.find((a) => (latestCaptures[a.tag]?.length || 0) < 4);
            if (missing) {
              const nextIdx = REQUIRED_ANGLES.findIndex((a) => a.tag === missing.tag);
              setCurrentStepIdx(nextIdx);
              currentStepIdxRef.current = nextIdx;
              setProductConfirmedForStep(false);
              setStepFrames([]);
              setStepPhase('WAITING_STEADY');
              setCountdown(3);
              lastCapturedGrayRef.current = null;
              steadyCounterRef.current = 0;
              stepStartTimeRef.current = Date.now();
            } else {
              setIsScanning(false);
              setIsDone(true);
            }
          }
          return latestCaptures;
        });
        return;
      }

      if (currentStepIdxRef.current < REQUIRED_ANGLES.length - 1) {
        const nextIdx = currentStepIdxRef.current + 1;
        setCurrentStepIdx(nextIdx);
        setProductConfirmedForStep(false);
        setStepFrames([]);
        setStepPhase('WAITING_STEADY');
        setCountdown(3);
        lastCapturedGrayRef.current = null;
        steadyCounterRef.current = 0;
        stepStartTimeRef.current = Date.now();
        console.log(`[Guided360] Step ${nextIdx + 1}/9 (${REQUIRED_ANGLES[nextIdx].tag}) started at ${new Date().toISOString()}`);
      } else {
        const totalScanSec = ((Date.now() - scanStartTimeRef.current) / 1000).toFixed(2);
        console.log(`[Guided360] Full 360 scan finished in ${totalScanSec}s across all 9 angles.`);
        setIsScanning(false);
        setIsDone(true);
        if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
          window.speechSynthesis.speak(new SpeechSynthesisUtterance('All 9 packaging angles captured with product isolation. Please review your cropped thumbnails.'));
        }
      }
    }, 700);
  }, [voiceEnabled]);

  // Step 0: Manual / Auto Calibration Trigger
  const handleCalibrateBackground = () => {
    if (bgRefAccumulator.current.length < 5) {
      setCameraFeedback('Hold camera completely still while recording empty scene...');
    }
  };

  // 3. Real-time Frame Analysis & Product Isolation Loop
  useEffect(() => {
    if (!isScanning || isDone) return;

    const analysisCanvas = document.createElement('canvas');
    analysisCanvas.width = 160;
    analysisCanvas.height = 120;
    const ctx = analysisCanvas.getContext('2d', { willReadFrequently: true });

    let isRunning = true;

    const analyzeLoop = () => {
      if (!isRunning) return;

      const video = videoRef.current;
      const overlayCanvas = overlayCanvasRef.current;
      if (video && video.readyState >= 2 && ctx) {
        const vw = video.videoWidth || 1280;
        const vh = video.videoHeight || 720;

        ctx.drawImage(video, 0, 0, 160, 120);
        const imgData = ctx.getImageData(0, 0, 160, 120);
        const data = imgData.data;

        // Grayscale conversion & Brightness calculation
        const gray = new Float32Array(160 * 120);
        let totalBrightness = 0;
        for (let i = 0, j = 0; i < data.length; i += 4, j++) {
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          gray[j] = lum;
          totalBrightness += lum;
        }

        const avgBrightness = Math.round(totalBrightness / (160 * 120));
        setLiveBrightness(avgBrightness);

        // Motion Detection: compute mean pixel difference against previous frame
        let motionDiff = 0;
        if (prevGrayRef.current) {
          let diffSum = 0;
          for (let i = 0; i < gray.length; i += 2) {
            diffSum += Math.abs(gray[i] - prevGrayRef.current[i]);
          }
          motionDiff = diffSum / (gray.length / 2);
        }
        prevGrayRef.current = new Float32Array(gray);

        // --- STEP 0: Background Reference Calibration ---
        if (isCalibratingBg) {
          if (motionDiff < 8.0 && avgBrightness >= 35) {
            if (bgRefAccumulator.current.length < 5) {
              bgRefAccumulator.current.push(new Float32Array(gray));
              setBgFramesCaptured(bgRefAccumulator.current.length);
              setCameraFeedback(`Recording empty background: ${bgRefAccumulator.current.length}/5 frames...`);
            } else {
              // Compute average background frame
              const avgBg = new Float32Array(160 * 120);
              for (let p = 0; p < 160 * 120; p++) {
                let sum = 0;
                for (let f = 0; f < 5; f++) {
                  sum += bgRefAccumulator.current[f][p];
                }
                avgBg[p] = sum / 5.0;
              }
              bgRefAverage.current = avgBg;

              // Step 0 Static Reference Calibration:
              // If the detector flags the same spot in the empty-scene reference, treat it as a static
              // false positive (e.g. poster, packaging artwork on wall, high-contrast texture) and ignore it.
              const emptySceneDet = privacyDetector.detect(video, 'privacy');
              if (emptySceneDet.face_boxes.length > 0) {
                privacyDetector.setStaticReferenceBoxes(emptySceneDet.face_boxes);
                setStaticRefFacesCount(emptySceneDet.face_boxes.length);
                console.log(`[Guided360] Step 0 empty scene: ${emptySceneDet.face_boxes.length} static reference false-positive spot(s) registered and will be ignored for this session.`);
              } else {
                privacyDetector.clearStaticReferenceBoxes();
                setStaticRefFacesCount(0);
              }

              setBgCalibrated(true);
              setIsCalibratingBg(false);
              setCameraFeedback('Background calibrated! Place product in center guide box.');
              console.log('[Guided360] Step 0: Background reference calibrated successfully from 5 empty frames.');
              if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
                window.speechSynthesis.speak(new SpeechSynthesisUtterance('Background calibrated. Place product in the guide box.'));
              }
            }
          } else {
            setCameraFeedback('Step 0: Keep camera steady and clear of all objects...');
          }

          animFrameRef.current = requestAnimationFrame(analyzeLoop);
          return;
        }

        // --- STEPS 1-9: Product Isolation & Person/Face Exclusion ---
        // Guide Box Region: central 60% of frame (x: 32..128, y: 20..100)
        const gX1 = 32;
        const gX2 = 128;
        const gY1 = 20;
        const gY2 = 100;
        const totalGuidePixels = (gX2 - gX1) * (gY2 - gY1);

        let productPixelCount = 0;
        let minPX = gX2;
        let maxPX = gX1;
        let minPY = gY2;
        let maxPY = gY1;

        const bgRef = bgRefAverage.current;

        for (let y = gY1; y < gY2; y++) {
          const row = y * 160;
          for (let x = gX1; x < gX2; x++) {
            const idx = row + x;
            if (bgRef) {
              const bgDiff = Math.abs(gray[idx] - bgRef[idx]);
              if (bgDiff > 24) {
                // Foreground pixel that is NOT background
                productPixelCount++;
                if (x < minPX) minPX = x;
                if (x > maxPX) maxPX = x;
                if (y < minPY) minPY = y;
                if (y > maxPY) maxPY = y;
              }
            } else {
              // Fallback before bgRef: use contrast
              if (Math.abs(gray[idx] - 120) > 30) {
                productPixelCount++;
                if (x < minPX) minPX = x;
                if (x > maxPX) maxPX = x;
                if (y < minPY) minPY = y;
                if (y > maxPY) maxPY = y;
              }
            }
          }
        }

        // Real in-browser MediaPipe Detection using 'enrollment' profile
        // - Min confidence >= 0.60 (ignores package logos, cartoon characters, folds)
        // - Min box width >= 6% frame width (ignores distant background specks)
        // - Requires 3 consecutive frames persistence before flag is raised
        // - Short 0.3s cooldown with immediate clear on clean frames
        const det = privacyDetector.detect(video, 'enrollment');

        // Product ratio inside guide box
        const currentProdRatio = productPixelCount / totalGuidePixels;
        setProductRatio(Math.round(currentProdRatio * 100));

        // Bounding Box Calculation with 5% margin
        let computedBox: ProductBoundingBox | null = null;
        if (productPixelCount > 50 && maxPX > minPX && maxPY > minPY) {
          const rawW = maxPX - minPX;
          const rawH = maxPY - minPY;
          const marginX = rawW * 0.05;
          const marginY = rawH * 0.05;

          const normX1 = Math.max(0, (minPX - marginX) / 160);
          const normY1 = Math.max(0, (minPY - marginY) / 120);
          const normX2 = Math.min(1.0, (maxPX + marginX) / 160);
          const normY2 = Math.min(1.0, (maxPY + marginY) / 120);

          computedBox = {
            x: Math.round(normX1 * vw),
            y: Math.round(normY1 * vh),
            width: Math.round((normX2 - normX1) * vw),
            height: Math.round((normY2 - normY1) * vh),
          };
        }
        setDetectedBox(computedBox);

        // Classify Active Faces: Blocking vs Outside Guide Box (Gentle Hint)
        // Guide box normalized coordinates
        const guideNorm = { x: 32 / 160, y: 20 / 120, width: (128 - 32) / 160, height: (100 - 20) / 120 };
        const cropTargetNorm = computedBox ? {
          x: computedBox.x / vw,
          y: computedBox.y / vh,
          width: computedBox.width / vw,
          height: computedBox.height / vh,
        } : guideNorm;

        const activeBlockingFaces: DetectedFaceBox[] = [];
        const activeOutsideFaces: DetectedFaceBox[] = [];

        for (const fb of det.active_face_boxes) {
          // Large face threshold (>15% of frame area or >38% of frame width)
          const isLargeFace = (fb.areaFraction >= 0.15) || (fb.widthFraction >= 0.38);

          // Check overlap with guide box or product crop
          const interX1 = Math.max(fb.x, cropTargetNorm.x);
          const interY1 = Math.max(fb.y, cropTargetNorm.y);
          const interX2 = Math.min(fb.x + fb.width, cropTargetNorm.x + cropTargetNorm.width);
          const interY2 = Math.min(fb.y + fb.height, cropTargetNorm.y + cropTargetNorm.height);
          const hasOverlap = (interX2 > interX1 && interY2 > interY1);

          if (isLargeFace || hasOverlap) {
            activeBlockingFaces.push(fb);
          } else {
            activeOutsideFaces.push(fb);
          }
        }

        const isFaceBlocking = activeBlockingFaces.length > 0;
        const hasOutsideHint = activeOutsideFaces.length > 0;
        setFaceDetectedWarning(isFaceBlocking);
        setBlockingFaces(activeBlockingFaces);
        setOutsideFaces(activeOutsideFaces);
        setAllDetectedFaces(det.face_boxes);

        // Hand occlusion / covering guard: reject hands covering the product
        let isHandCoveringProduct = false;
        let handOverlapRatio = 0;
        if (computedBox && det.hand_boxes.length > 0) {
          const prodNormX1 = computedBox.x / vw;
          const prodNormY1 = computedBox.y / vh;
          const prodNormX2 = (computedBox.x + computedBox.width) / vw;
          const prodNormY2 = (computedBox.y + computedBox.height) / vh;

          for (const hBox of det.hand_boxes) {
            const hX1 = hBox.x;
            const hY1 = hBox.y;
            const hX2 = hBox.x + hBox.width;
            const hY2 = hBox.y + hBox.height;

            const interX1 = Math.max(prodNormX1, hX1);
            const interY1 = Math.max(prodNormY1, hY1);
            const interX2 = Math.min(prodNormX2, hX2);
            const interY2 = Math.min(prodNormY2, hY2);

            if (interX2 > interX1 && interY2 > interY1) {
              const interArea = (interX2 - interX1) * (interY2 - interY1);
              const prodArea = (prodNormX2 - prodNormX1) * (prodNormY2 - prodNormY1);
              if (prodArea > 0) {
                const ratio = interArea / prodArea;
                if (ratio > handOverlapRatio) handOverlapRatio = ratio;
                if (ratio > 0.08) {
                  isHandCoveringProduct = true;
                  break;
                }
              }
            }
          }
        }
        setHandDetectedWarning(isHandCoveringProduct);

        // Discrete Laplacian Sharpness on Product Region
        let laplacianSum = 0;
        let count = 0;
        const laplacianVals: number[] = [];
        const lX1 = Math.max(minPX, gX1 + 10);
        const lX2 = Math.min(maxPX, gX2 - 10);
        const lY1 = Math.max(minPY, gY1 + 10);
        const lY2 = Math.min(maxPY, gY2 - 10);

        if (lX2 > lX1 && lY2 > lY1) {
          for (let y = lY1; y < lY2; y += 2) {
            const row = y * 160;
            for (let x = lX1; x < lX2; x += 2) {
              const center = gray[row + x];
              const up = gray[(y - 1) * 160 + x];
              const down = gray[(y + 1) * 160 + x];
              const left = gray[row + x - 1];
              const right = gray[row + x + 1];
              const val = 4 * center - up - down - left - right;
              laplacianVals.push(val);
              laplacianSum += val;
              count++;
            }
          }
        }

        let blurScore = 0;
        if (count > 0) {
          const mean = laplacianSum / count;
          let varSum = 0;
          for (let i = 0; i < count; i++) {
            const diff = laplacianVals[i] - mean;
            varSum += diff * diff;
          }
          blurScore = Math.round(varSum / count);
        }
        setLiveBlurScore(blurScore);

        const isSharp = blurScore >= 45;
        const isSteady = motionDiff < 10.0;
        const isLightingOk = avgBrightness >= 35;
        const isProductBigEnough = currentProdRatio >= 0.15; // At least ~15% of guide box

        // Draw Canvas Overlay: Product Box, Hand Boxes, Face Boxes with Exact Telemetry
        if (overlayCanvas) {
          if (overlayCanvas.width !== vw || overlayCanvas.height !== vh) {
            overlayCanvas.width = vw;
            overlayCanvas.height = vh;
          }
          const oCtx = overlayCanvas.getContext('2d');
          if (oCtx) {
            oCtx.clearRect(0, 0, vw, vh);

            // 1. Draw Product Bounding Box
            if (computedBox && isProductBigEnough) {
              oCtx.strokeStyle = '#10B981';
              oCtx.lineWidth = 2.5;
              oCtx.strokeRect(computedBox.x, computedBox.y, computedBox.width, computedBox.height);
              oCtx.fillStyle = 'rgba(16, 185, 129, 0.12)';
              oCtx.fillRect(computedBox.x, computedBox.y, computedBox.width, computedBox.height);

              // Product label tag
              oCtx.fillStyle = '#10B981';
              oCtx.fillRect(computedBox.x, Math.max(0, computedBox.y - 20), 130, 20);
              oCtx.fillStyle = '#FFFFFF';
              oCtx.font = 'bold 11px monospace';
              oCtx.fillText(`PRODUCT (${blurScore} shp)`, computedBox.x + 6, Math.max(14, computedBox.y - 5));
            }

            // 2. Draw Hand Bounding Boxes
            det.hand_boxes.forEach((hBox, idx) => {
              const bx = hBox.x * vw;
              const by = hBox.y * vh;
              const bw = hBox.width * vw;
              const bh = hBox.height * vh;
              oCtx.strokeStyle = '#06B6D4';
              oCtx.lineWidth = 2;
              oCtx.strokeRect(bx, by, bw, bh);
              oCtx.fillStyle = '#06B6D4';
              oCtx.fillRect(bx, Math.max(0, by - 18), 70, 18);
              oCtx.fillStyle = '#070A12';
              oCtx.font = 'bold 10px monospace';
              oCtx.fillText(`HAND #${idx + 1}`, bx + 4, Math.max(13, by - 4));
            });

            // 3. Draw Face Bounding Boxes with Detailed Telemetry
            det.face_boxes.forEach((fb, idx) => {
              const bx = fb.x * vw;
              const by = fb.y * vh;
              const bw = fb.width * vw;
              const bh = fb.height * vh;

              const isBlocking = activeBlockingFaces.some(
                (ab) => Math.abs(ab.x - fb.x) < 0.02 && Math.abs(ab.y - fb.y) < 0.02
              );

              let strokeColor = '#F59E0B'; // Amber: Outside guide box (allowed)
              let fillColor = 'rgba(245, 158, 11, 0.15)';
              let labelText = `FACE #${idx + 1}: ${Math.round(fb.score * 100)}% (${(fb.widthFraction * 100).toFixed(1)}%w) [OUTSIDE - ALLOWED]`;

              if (fb.isStaticBackground) {
                strokeColor = '#64748B'; // Slate: Static poster ignored
                fillColor = 'rgba(100, 116, 139, 0.15)';
                labelText = `POSTER / STATIC REF (IGNORED)`;
              } else if (isBlocking) {
                strokeColor = '#EF4444'; // Red: Blocking
                fillColor = 'rgba(239, 68, 68, 0.25)';
                labelText = `FACE #${idx + 1}: ${Math.round(fb.score * 100)}% | ${(fb.widthFraction * 100).toFixed(1)}%w x ${(fb.heightFraction * 100).toFixed(1)}%h (${(fb.areaFraction * 100).toFixed(1)}%a) | ${fb.consecutiveFrames}f [BLOCKING]`;
              }

              oCtx.strokeStyle = strokeColor;
              oCtx.lineWidth = isBlocking ? 3.5 : 2;
              oCtx.strokeRect(bx, by, bw, bh);
              oCtx.fillStyle = fillColor;
              oCtx.fillRect(bx, by, bw, bh);

              oCtx.font = 'bold 11px monospace';
              const textWidth = oCtx.measureText(labelText).width;
              oCtx.fillStyle = strokeColor;
              const tagY = Math.max(0, by - 22);
              oCtx.fillRect(bx, tagY, textWidth + 12, 22);
              oCtx.fillStyle = '#FFFFFF';
              oCtx.fillText(labelText, bx + 6, tagY + 15);
            });
          }
        }

        // Determine Exact Reason "Why is capture blocked?"
        let blockedReason: string | null = null;
        if (detectorStatus !== 'ready') {
          blockedReason = detectorStatus === 'loading'
            ? 'Privacy detector loading self-hosted models...'
            : 'Privacy detector offline (error loading models)';
        } else if (isFaceBlocking) {
          const topF = activeBlockingFaces[0];
          const overlapMsg = (topF.areaFraction >= 0.15 || topF.widthFraction >= 0.38)
            ? 'covers >15% of frame'
            : 'overlaps guide box / product crop';
          blockedReason = `Face detected in frame (${overlapMsg}, Confidence: ${Math.round(topF.score * 100)}%, Size: ${(topF.widthFraction * 100).toFixed(1)}%w x ${(topF.heightFraction * 100).toFixed(1)}%h, Persisted: ${topF.consecutiveFrames}f). Move face away.`;
        } else if (isHandCoveringProduct) {
          blockedReason = `Hand covering product by ${Math.round(handOverlapRatio * 100)}% (max 8% allowed). Remove hands from product.`;
        } else if (!productConfirmedRef.current) {
          blockedReason = 'Confirm product placement in guide box to begin.';
        } else if (!isLightingOk) {
          blockedReason = `Lighting too dim (Brightness: ${avgBrightness} / min 35). Move into better lighting.`;
        } else if (!isProductBigEnough) {
          blockedReason = `Product occupies ${Math.round(currentProdRatio * 100)}% of guide box (needs ≥15%). Bring product closer.`;
        } else if (!isSteady) {
          blockedReason = `Camera or item moving (Motion: ${motionDiff.toFixed(1)} / max 10.0). Hold still.`;
        } else if (!isSharp) {
          blockedReason = `Image slightly blurry (Sharpness: ${blurScore} / required 45). Hold steady.`;
        }
        setCaptureBlockedReason(blockedReason);

        // Visual HUD Feedback
        if (detectorStatus !== 'ready') {
          setCameraFeedback(detectorStatus === 'loading' ? 'Loading privacy detector...' : 'Privacy detector error — capture disabled');
          setFocusStatus('BLURRY');
        } else if (isFaceBlocking) {
          setCameraFeedback('Face detected in capture region — move face away');
          setFocusStatus('BLURRY');
        } else if (hasOutsideHint) {
          setCameraFeedback('Product isolated & sharp! (Background face in room ignored)');
          setFocusStatus(isSharp && isSteady ? 'SHARP' : 'STEADY');
        } else if (isHandCoveringProduct) {
          setCameraFeedback('Keep hands clear of the product');
          setFocusStatus('BLURRY');
        } else if (!isLightingOk) {
          setCameraFeedback('Too dark — bring item into better lighting');
          setFocusStatus('BLURRY');
        } else if (!isProductBigEnough) {
          setCameraFeedback('Bring product closer (needs ≥15% of guide box)');
          setFocusStatus('BLURRY');
        } else if (!isSteady) {
          setCameraFeedback('Holding unsteady — please hold still');
          setFocusStatus('BLURRY');
        } else if (!isSharp) {
          setCameraFeedback('Slightly blurry — hold still');
          setFocusStatus('STEADY');
        } else {
          setCameraFeedback('Product isolated & sharp! Hold steady...');
          setFocusStatus('SHARP');
        }

        // Automatic Guided Capture Execution
        // Captures only when capture is NOT blocked by face or hand and criteria are satisfied
        if (!isPausedRef.current && autoCaptureEnabled && productConfirmedRef.current && !isFaceBlocking && !isHandCoveringProduct && detectorStatus === 'ready' && isProductBigEnough) {
          const currentPhase = phaseRef.current;
          const now = Date.now();
          const stepElapsed = now - stepStartTimeRef.current;
          setStepElapsedTime(Math.round(stepElapsed / 1000));

          // Phase 1: Waiting for Steady & Sharp
          if (currentPhase === 'WAITING_STEADY') {
            if (isSharp && isSteady && isLightingOk) {
              steadyCounterRef.current += 1;
              if (steadyCounterRef.current >= 4) {
                steadyCounterRef.current = 0;
                stepStartTimeRef.current = now;
                setStepPhase('COUNTDOWN');
                setCountdown(3);
                console.log(`[Guided360] Step ${currentStepIdxRef.current + 1}/9 steady confirmed. Starting 3s countdown.`);
              }
            } else {
              steadyCounterRef.current = 0;
            }
          }

          // Phase 2: Countdown "Hold still... 3, 2, 1" (at least 3 seconds)
          else if (currentPhase === 'COUNTDOWN') {
            if (motionDiff > 25.0 || isFaceBlocking || isHandCoveringProduct || detectorStatus !== 'ready') {
              setStepPhase('WAITING_STEADY');
              steadyCounterRef.current = 0;
              setCountdown(3);
            } else {
              if (stepElapsed < 1000) {
                setCountdown(3);
              } else if (stepElapsed < 2000) {
                setCountdown(2);
              } else if (stepElapsed < 3000) {
                setCountdown(1);
              } else {
                setStepPhase('CAPTURING');
                lastCaptureTimeRef.current = 0;
              }
            }
          }

          // Phase 3: Capturing 5 to 8 frames spaced >= 300ms apart with near-duplicate skip
          else if (currentPhase === 'CAPTURING') {
            if (now - lastCaptureTimeRef.current >= 300 && isLightingOk && !isFaceBlocking && !isHandCoveringProduct && detectorStatus === 'ready') {
              let isDuplicate = false;
              if (lastCapturedGrayRef.current) {
                let dupSum = 0;
                for (let i = 0; i < gray.length; i += 4) {
                  dupSum += Math.abs(gray[i] - lastCapturedGrayRef.current[i]);
                }
                const meanDupDiff = dupSum / (gray.length / 4);
                if (meanDupDiff < 3.0) {
                  isDuplicate = true;
                }
              }

              if (!isDuplicate && blurScore >= 35) {
                const newFrame = captureFrameInternal();
                if (newFrame) {
                  lastCaptureTimeRef.current = now;
                  lastCapturedGrayRef.current = new Float32Array(gray);

                  setStepFrames((prev) => {
                    const updated = [...prev, newFrame];
                    const step = REQUIRED_ANGLES[currentStepIdxRef.current];
                    console.log(`[Guided360] Step ${currentStepIdxRef.current + 1}/9 (${step.tag}) frame ${updated.length}/6 cropped at +${((now - stepStartTimeRef.current)/1000).toFixed(2)}s (Sharpness: ${blurScore})`);

                    if (updated.length >= 6 && (now - stepStartTimeRef.current) >= 3000) {
                      finishStep(updated);
                    }
                    return updated;
                  });
                }
              }
            }
          }
        }
      }

      animFrameRef.current = requestAnimationFrame(analyzeLoop);
    };

    animFrameRef.current = requestAnimationFrame(analyzeLoop);

    return () => {
      isRunning = false;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [isScanning, isDone, autoCaptureEnabled, isCalibratingBg, captureFrameInternal, finishStep]);

  // Step Controls: Pause / Resume
  const handleTogglePause = () => {
    setIsPaused((prev) => !prev);
  };

  // Step Controls: Skip Angle
  const handleSkipAngle = () => {
    const step = REQUIRED_ANGLES[currentStepIdx];
    const durationSec = ((Date.now() - stepStartTimeRef.current) / 1000).toFixed(2);
    console.log(`[Guided360] Step ${currentStepIdx + 1}/9 (${step.tag}) skipped by user after ${durationSec}s.`);

    if (currentStepIdx < REQUIRED_ANGLES.length - 1) {
      const next = currentStepIdx + 1;
      setCurrentStepIdx(next);
      setProductConfirmedForStep(false);
      setStepFrames([]);
      setStepPhase('WAITING_STEADY');
      setCountdown(3);
      lastCapturedGrayRef.current = null;
      stepStartTimeRef.current = Date.now();
    } else {
      setIsScanning(false);
      setIsDone(true);
    }
  };

  // Step Controls: Retry Angle
  const handleRetryAngle = () => {
    const step = REQUIRED_ANGLES[currentStepIdx];
    console.log(`[Guided360] Retrying Step ${currentStepIdx + 1}/9 (${step.tag}). Resetting frame list.`);
    setProductConfirmedForStep(false);
    setStepFrames([]);
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[step.tag];
      return copy;
    });
    setStepPhase('WAITING_STEADY');
    setCountdown(3);
    lastCapturedGrayRef.current = null;
    stepStartTimeRef.current = Date.now();
  };

  // Step Controls: Capture Now (immediately snaps a frame)
  const handleCaptureNow = () => {
    if (detectorStatus !== 'ready') {
      alert('Cannot capture: Privacy detector is still initializing.');
      return;
    }
    if (faceDetectedWarning) {
      setBlockedAttemptsCount((prev) => prev + 1);
      alert('Cannot capture: Face detected overlapping product crop or covering >15% of frame. Keep your face clear of the capture area.');
      return;
    }
    if (handDetectedWarning) {
      alert('Cannot capture while hands are covering the product. Keep hands clear.');
      return;
    }

    const newFrame = captureFrameInternal();
    if (!newFrame) return;

    setStepFrames((prev) => {
      const updated = [...prev, newFrame];
      lastCaptureTimeRef.current = Date.now();
      const step = REQUIRED_ANGLES[currentStepIdx];
      console.log(`[Guided360] Manual Capture Now on Step ${currentStepIdx + 1}/9 (${step.tag}): total ${updated.length} frames.`);
      if (updated.length >= 5 && (Date.now() - stepStartTimeRef.current) >= 2000) {
        finishStep(updated);
      }
      return updated;
    });
  };

  // Admin Override: Capture anyway after 3 blocked attempts with explicit confirmation
  const handleAdminOverrideCapture = async () => {
    if (detectorStatus !== 'ready') return;
    if (!adminConfirmNoFace) {
      alert('Please check the confirmation box: "I confirm there is no face in the saved crop"');
      return;
    }

    const newFrame = captureFrameInternal();
    if (!newFrame) return;

    // Send audit log to backend
    try {
      await api.logAuditOverride({
        product_id: product.id,
        angle_tag: REQUIRED_ANGLES[currentStepIdx].tag,
        reason: 'Admin verified no face in cropped product region after 3 blocked attempts.',
        confirmed_by: 'admin',
        face_details: blockingFaces
      });
      console.log('[Guided360] Admin override audit log recorded on server.');
    } catch (err) {
      console.warn('[Guided360] Failed to send audit log to server:', err);
    }

    setStepFrames((prev) => {
      const updated = [...prev, newFrame];
      lastCaptureTimeRef.current = Date.now();
      const step = REQUIRED_ANGLES[currentStepIdx];
      console.log(`[Guided360] Admin Override Capture Now on Step ${currentStepIdx + 1}/9 (${step.tag}): total ${updated.length} frames.`);
      if (updated.length >= 5 && (Date.now() - stepStartTimeRef.current) >= 2000) {
        finishStep(updated);
      }
      return updated;
    });

    // Reset override states
    setBlockedAttemptsCount(0);
    setAdminConfirmNoFace(false);
  };

  const handleRetakeInGallery = (tag: string) => {
    const idx = REQUIRED_ANGLES.findIndex((a) => a.tag === tag);
    if (idx !== -1) {
      retakeTargetAngleRef.current = tag;
      setCurrentStepIdx(idx);
      currentStepIdxRef.current = idx;
      setProductConfirmedForStep(false);
      setStepFrames([]);
      setStepPhase('WAITING_STEADY');
      setCountdown(3);
      steadyCounterRef.current = 0;
      lastCapturedGrayRef.current = null;
      stepStartTimeRef.current = Date.now();
      setIsScanning(true);
      setIsDone(false);

      // Reconnect video stream to prevent freeze
      if (videoRef.current && streamRef.current) {
        if (videoRef.current.srcObject !== streamRef.current) {
          videoRef.current.srcObject = streamRef.current;
        }
        videoRef.current.play().catch(() => {});
      }
    }
  };

  const handleDeleteInGallery = (tag: string) => {
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[tag];
      return copy;
    });
  };

  const handleDeleteSingleFrame = (tag: string, index: number) => {
    setCaptures((prev) => {
      const list = prev[tag] || [];
      const updated = list.filter((_, idx) => idx !== index);
      const copy = { ...prev };
      if (updated.length === 0) {
        delete copy[tag];
        setSelectedGalleryAngle(null);
      } else {
        copy[tag] = updated;
      }
      return copy;
    });
  };

  // Helper to downsample captured frame to ~640px JPEG quality 80%
  const downsampleTo640Jpeg = (dataUrl: string): Promise<{ blob: Blob; jpegDataUrl: string }> => {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1.0, 640 / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.drawImage(img, 0, 0, w, h);
        }
        const jpegDataUrl = canvas.toDataURL('image/jpeg', 0.8);
        canvas.toBlob((blob) => {
          resolve({ blob: blob || new Blob(), jpegDataUrl });
        }, 'image/jpeg', 0.8);
      };
      img.onerror = () => {
        resolve({ blob: new Blob(), jpegDataUrl: dataUrl });
      };
      img.src = dataUrl;
    });
  };

  // Coverage Rule: Target 40 to 80 good frames across all 9 angles
  const totalCapturedFrames = Object.values(captures).reduce((sum, arr) => sum + arr.length, 0);
  const completedAngles = REQUIRED_ANGLES.filter((a) => (captures[a.tag]?.length || 0) >= 4);
  const completedAnglesCount = completedAngles.length;
  const hasLabelCloseup = (captures['LABEL_CLOSEUP']?.length || 0) >= 4;
  const meetsCoverageRule = completedAnglesCount === REQUIRED_ANGLES.length && totalCapturedFrames >= 36 && hasLabelCloseup;

  // Submit Real Frames: Uploads smaller ~640px JPEGs (quality 80) directly to Supabase Storage via signed URLs
  const handleSaveEmbeddings = async () => {
    if (!meetsCoverageRule) return;

    setIsProcessing(true);
    setJobError(null);
    setJobStage('SAVING_FRAMES');
    setJobStageMessage('Optimizing frames to 640px JPEGs (quality 80)...');
    setJobDone(0);

    try {
      // 1. Gather all frames across angles, capped at max 40 frames total
      const allFrames: { angle_tag: string; dataUrl: string; poor_crop: boolean }[] = [];
      for (const [angle_tag, frameList] of Object.entries(captures)) {
        for (const frame of frameList.slice(0, 5)) {
          allFrames.push({
            angle_tag,
            dataUrl: frame.dataUrl,
            poor_crop: frame.blurScore < 40,
          });
          if (allFrames.length >= 40) break;
        }
        if (allFrames.length >= 40) break;
      }

      setJobTotal(allFrames.length);

      // 2. Downsample all frames to ~640px JPEG quality 80%
      const compressedFrames: { angle_tag: string; blob: Blob; jpegDataUrl: string; filename: string; poor_crop: boolean }[] = [];
      for (let i = 0; i < allFrames.length; i++) {
        const f = allFrames[i];
        const { blob, jpegDataUrl } = await downsampleTo640Jpeg(f.dataUrl);
        compressedFrames.push({
          angle_tag: f.angle_tag,
          blob,
          jpegDataUrl,
          filename: `${product.barcode}_${f.angle_tag}_${i}_${Math.random().toString(36).substring(2, 8)}.jpg`,
          poor_crop: f.poor_crop,
        });
      }

      // 3. Request signed upload URLs from backend
      setJobStageMessage('Requesting signed cloud storage upload URLs...');
      const initResp = await api.init360ScanUpload(
        product.id,
        compressedFrames.map((cf) => ({
          angle_tag: cf.angle_tag,
          filename: cf.filename,
          poor_crop: cf.poor_crop,
        }))
      );

      setActiveJobId(initResp.job_id);
      setCachedCompressedFrames(compressedFrames);
      setCachedUploadItems(initResp.upload_items);

      // Path A: Direct upload directly to Supabase Storage
      if (initResp.direct_upload && initResp.upload_items.length === compressedFrames.length) {
        setJobStageMessage('Uploading frames directly to Supabase Storage...');
        const uploadedRefs: { angle_tag: string; frame_ref: string; poor_crop: boolean }[] = [];
        const failed: { index: number; item: any; cf: any; error: string }[] = [];

        for (let i = 0; i < compressedFrames.length; i++) {
          const item = initResp.upload_items[i];
          const cf = compressedFrames[i];
          setJobStageMessage(`Uploading frame ${i + 1}/${compressedFrames.length} directly to cloud storage...`);
          setJobDone(i);

          try {
            const putRes = await fetch(item.upload_url, {
              method: 'PUT',
              body: cf.blob,
              headers: {
                'Content-Type': 'image/jpeg',
              },
            });

            if (putRes.ok) {
              uploadedRefs.push({
                angle_tag: item.angle_tag,
                frame_ref: item.frame_ref,
                poor_crop: item.poor_crop,
              });
            } else {
              failed.push({
                index: i,
                item,
                cf,
                error: `HTTP ${putRes.status}`,
              });
            }
          } catch (err: any) {
            failed.push({
              index: i,
              item,
              cf,
              error: err.message || 'Network error',
            });
          }
        }

        setCachedUploadedRefs(uploadedRefs);

        if (failed.length > 0) {
          setFailedUploads(failed);
          setJobError(`Upload failed for ${failed.length} frame(s). Please retry the failed uploads.`);
          setJobStatus('FAILED');
          return;
        }

        // All uploaded successfully
        setFailedUploads([]);
        setJobStageMessage('Frames saved & verified. Starting background recognition worker...');
        await api.complete360Scan(product.id, {
          job_id: initResp.job_id,
          frames: uploadedRefs,
        });
        setJobStatus('PENDING');
        setJobStageMessage('Direct upload complete. Waiting for background worker...');
      } else {
        // Path B: Fallback base64 upload
        setJobStageMessage('Sending frames to backend...');
        const payload = compressedFrames.map((cf) => ({
          angle_tag: cf.angle_tag,
          image_data_url: cf.jpegDataUrl,
          poor_crop: cf.poor_crop,
        }));
        const res = await api.complete360Scan(product.id, {
          job_id: initResp.job_id,
          captures: payload,
        } as any);
        setActiveJobId(res.job_id);
        setJobStatus('PENDING');
        setJobStageMessage('Frames saved. Waiting for background worker...');
      }
    } catch (e: any) {
      setJobError(e.message || 'Failed to submit 360-scan frames');
      setJobStatus('FAILED');
    }
  };

  const handleRetryFailedUploads = async () => {
    if (!failedUploads.length || !activeJobId) return;

    setJobError(null);
    setJobStatus('PENDING');
    setJobStage('SAVING_FRAMES');
    setJobStageMessage(`Retrying ${failedUploads.length} failed upload(s)...`);

    const currentUploaded = [...cachedUploadedRefs];
    const stillFailed: { index: number; item: any; cf: any; error: string }[] = [];

    for (let i = 0; i < failedUploads.length; i++) {
      const { index, item, cf } = failedUploads[i];
      setJobStageMessage(`Retrying upload ${i + 1}/${failedUploads.length}...`);

      try {
        const putRes = await fetch(item.upload_url, {
          method: 'PUT',
          body: cf.blob,
          headers: {
            'Content-Type': 'image/jpeg',
          },
        });

        if (putRes.ok) {
          currentUploaded.push({
            angle_tag: item.angle_tag,
            frame_ref: item.frame_ref,
            poor_crop: item.poor_crop,
          });
        } else {
          stillFailed.push({ index, item, cf, error: `HTTP ${putRes.status}` });
        }
      } catch (err: any) {
        stillFailed.push({ index, item, cf, error: err.message || 'Network error' });
      }
    }

    setCachedUploadedRefs(currentUploaded);

    if (stillFailed.length > 0) {
      setFailedUploads(stillFailed);
      setJobError(`Upload failed for ${stillFailed.length} frame(s). Please retry or upload to server.`);
      setJobStatus('FAILED');
      return;
    }

    // All succeeded!
    setFailedUploads([]);
    try {
      setJobStageMessage('All frames verified. Enqueueing background recognition worker...');
      await api.complete360Scan(product.id, {
        job_id: activeJobId,
        frames: currentUploaded,
      });
      setJobStatus('PENDING');
      setJobStageMessage('Direct upload complete. Waiting for background worker...');
    } catch (e: any) {
      setJobError(e.message || 'Failed to complete 360-scan');
      setJobStatus('FAILED');
    }
  };

  const handleFallbackServerUpload = async () => {
    if (!cachedCompressedFrames.length) return;
    setJobError(null);
    setJobStatus('PENDING');
    setJobStage('SAVING_FRAMES');
    setJobStageMessage('Uploading frames via backend server...');

    try {
      const payload = cachedCompressedFrames.map((cf) => ({
        angle_tag: cf.angle_tag,
        image_data_url: cf.jpegDataUrl,
        poor_crop: cf.poor_crop,
      }));
      const res = await api.complete360Scan(product.id, {
        job_id: activeJobId || undefined,
        captures: payload,
      } as any);
      setActiveJobId(res.job_id);
      setJobStatus('PENDING');
      setJobStageMessage('Frames saved. Waiting for background worker...');
      setFailedUploads([]);
    } catch (e: any) {
      setJobError(e.message || 'Failed to upload frames to server');
      setJobStatus('FAILED');
    }
  };

  const handleScanAgain = () => {
    setIsProcessing(false);
    setJobError(null);
    setJobStatus(null);
    setActiveJobId(null);
    setFailedUploads([]);
    setCachedCompressedFrames([]);
    setCachedUploadItems([]);
    setCachedUploadedRefs([]);
    setIsDone(false);
    setIsScanning(true);
    setCurrentStepIdx(0);
    currentStepIdxRef.current = 0;
    setCaptures({});
    setStepFrames([]);
    setStepPhase('WAITING_STEADY');
    setCountdown(3);
    stepStartTimeRef.current = Date.now();
    if (videoRef.current && streamRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
      }
      videoRef.current.play().catch(() => {});
    }
  };

  // Real-time polling without fake timers or simulated steps
  useEffect(() => {
    if (!isProcessing || !activeJobId) return;
    if (jobStatus === 'ENROLLED' || jobStatus === 'FAILED' || jobStatus === 'CANCELLED') return;

    let isMounted = true;
    const interval = setInterval(async () => {
      try {
        const job = await api.getScanJob(activeJobId);
        if (!isMounted) return;

        setJobStatus(job.status);
        setJobStage(job.stage);
        setJobStageMessage(job.stage_message || '');
        setJobDone(job.done);
        setJobTotal(job.total);

        if (job.status === 'ENROLLED') {
          clearInterval(interval);
          setEnrollmentStats({
            real_frames_saved: job.total,
            total_embeddings_stored: job.done,
            model_name: 'CLIP ViT-B/32 INT8',
            vector_dim: 512,
          });
        } else if (job.status === 'FAILED') {
          clearInterval(interval);
          setJobError(job.error || 'Background processing failed. Please retry.');
        } else if (job.status === 'CANCELLED') {
          clearInterval(interval);
          setJobError('Scan processing was cancelled by user.');
        }
      } catch (err: any) {
        console.warn('Scan job polling warning:', err);
      }
    }, 1000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isProcessing, activeJobId, jobStatus]);

  // Request Cancel / Exit Flow
  const handleRequestCancel = () => {
    if (isProcessing) {
      if (jobStatus === 'PENDING' || jobStatus === 'PROCESSING') {
        setShowCancelProcessingConfirm(true);
      } else {
        handleDiscardScan();
      }
    } else {
      if (totalCapturedFrames > 0) {
        setShowDiscardConfirm(true);
      } else {
        handleDiscardScan();
      }
    }
  };

  const handleDiscardScan = () => {
    stopCamera();
    setCaptures({});
    setStepFrames([]);
    setShowDiscardConfirm(false);
    setIsProcessing(false);
    onComplete();
  };

  const handleCancelProcessing = async () => {
    if (!activeJobId) return;
    try {
      await api.cancelScanJob(activeJobId);
      setJobStatus('CANCELLED');
      setJobStage('CANCELLED');
      setJobStageMessage('Scan processing cancelled by user.');
    } catch (e: any) {
      console.error('Failed to cancel job:', e);
    } finally {
      setShowCancelProcessingConfirm(false);
    }
  };

  const handleMinimizeProcessing = () => {
    setIsProcessing(false);
    setBgProcessingNotice('Background 360 enrollment is still running. You can check progress anytime from the product catalog.');
    setTimeout(() => setBgProcessingNotice(null), 5000);
  };

  // Keyboard shortcut: Esc key triggers cancel/discard dialog
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleRequestCancel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isProcessing, jobStatus, totalCapturedFrames]);

  // Retry job without re-uploading frames
  const handleRetryJob = async () => {
    if (
      (jobError || '').toUpperCase().includes('ERR_NO_FRAMES') ||
      (jobError || '').toLowerCase().includes('no saved frames')
    ) {
      handleScanAgain();
      return;
    }
    if (!activeJobId) {
      handleSaveEmbeddings();
      return;
    }
    try {
      setJobError(null);
      const resp = await api.retryScanJob(activeJobId);
      if (resp.requires_confirmation) {
        setPartialConfirmation({
          surviving: resp.surviving_count || 0,
          total: resp.total_count || 0,
          missingAngles: resp.missing_angles || [],
        });
        return;
      }
      setJobStatus('PENDING');
      setJobStage('QUEUED');
      setJobStageMessage('Resuming enrollment from last completed frame...');
    } catch (e: any) {
      setJobError(e.message || 'Failed to retry job.');
    }
  };

  const progressPercent = Math.round((completedAnglesCount / REQUIRED_ANGLES.length) * 100);
  const currentStep = REQUIRED_ANGLES[currentStepIdx] || REQUIRED_ANGLES[0];

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleRequestCancel}
              className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 flex items-center gap-1 text-xs font-semibold transition-all active:scale-95"
              title="Return to Product List"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </button>
            <div className="flex items-center gap-2">
              <span className="p-2 rounded-xl bg-purple-100 dark:bg-purple-950 text-purple-600 dark:text-purple-400 font-bold font-mono text-sm">
                ISOLATED 360°
              </span>
              <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
                Guided 360° Vision Enrollment
              </h1>
            </div>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Product: <strong className="text-slate-800 dark:text-slate-200">{product.name}</strong> • Barcode: <span className="font-mono text-purple-600 dark:text-purple-400">{product.barcode}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Voice Guidance Toggle */}
          <button
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            className={`px-3 py-2 rounded-xl border flex items-center gap-1.5 text-xs font-semibold transition-all ${
              voiceEnabled
                ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 dark:border-purple-800 text-purple-700 dark:text-purple-300'
                : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500'
            }`}
            title="Toggle Voice Directions"
          >
            {voiceEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
            Voice: {voiceEnabled ? 'ON' : 'OFF'}
          </button>

          {/* Auto-Capture Sharp Frames Toggle */}
          <button
            onClick={() => setAutoCaptureEnabled(!autoCaptureEnabled)}
            className={`px-3 py-2 rounded-xl border flex items-center gap-1.5 text-xs font-semibold transition-all ${
              autoCaptureEnabled
                ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300'
                : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500'
            }`}
            title="Auto-capture when frame is sharp"
          >
            <Camera className="w-3.5 h-3.5" />
            Auto-Snap: {autoCaptureEnabled ? 'ON' : 'OFF'}
          </button>

          {/* Visible Cancel Scan / Close Button */}
          <button
            onClick={handleRequestCancel}
            className="px-3 py-2 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 hover:bg-red-100 dark:bg-red-950/30 text-red-600 dark:text-red-400 flex items-center gap-1 text-xs font-semibold transition-all active:scale-95"
            title="Cancel Scan (Esc)"
          >
            <X className="w-3.5 h-3.5" />
            <span>Cancel Scan</span>
          </button>
        </div>
      </div>

      {/* Notice if processing in background */}
      {bgProcessingNotice && (
        <div className="p-3.5 rounded-2xl bg-purple-50 dark:bg-purple-950/50 border border-purple-200 dark:border-purple-800 text-purple-800 dark:text-purple-300 text-xs flex items-center justify-between gap-3 animate-fade-in">
          <span>{bgProcessingNotice}</span>
          <button
            onClick={() => setIsProcessing(true)}
            className="text-xs font-bold underline hover:opacity-80 shrink-0"
          >
            Reopen Progress
          </button>
        </div>
      )}

      {cameraError && (
        <div className="p-4 rounded-2xl bg-red-50 dark:bg-red-950/50 border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 text-xs flex items-center gap-3">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>{cameraError}</span>
        </div>
      )}

      {/* Real Viewfinder and Circular Progress Ring (Always kept mounted in DOM to prevent video stream freeze) */}
      <div className={isDone ? 'hidden' : 'space-y-6'}>
          <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-2xl relative aspect-square max-w-md mx-auto flex items-center justify-center p-6 text-white select-none">
            {/* Real Webcam Live Feed */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover"
            />

            {/* Live Canvas Overlay (Green product box, Red hatched exclusions) */}
            <canvas
              ref={overlayCanvasRef}
              className="absolute inset-0 w-full h-full object-cover pointer-events-none z-10"
            />

            {/* Circular Progress Ring Guide Overlay */}
            <div className="relative z-10 w-72 h-72 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90 pointer-events-none">
                <circle
                  cx="144"
                  cy="144"
                  r="128"
                  stroke="currentColor"
                  strokeWidth="8"
                  className="text-white/20"
                  fill="transparent"
                />
                <circle
                  cx="144"
                  cy="144"
                  r="128"
                  stroke="currentColor"
                  strokeWidth="8"
                  className="text-purple-500 transition-all duration-500"
                  fill="transparent"
                  strokeDasharray={2 * Math.PI * 128}
                  strokeDashoffset={2 * Math.PI * 128 * (1 - progressPercent / 100)}
                  strokeLinecap="round"
                />
              </svg>

              {/* Angle Tick Marks Around the Ring for 9 Required Angles */}
              <div className="absolute inset-0 pointer-events-none">
                {REQUIRED_ANGLES.map((ang, idx) => {
                  const isCaptured = (captures[ang.tag]?.length || 0) >= 4;
                  const isCurrent = idx === currentStepIdx && !isCalibratingBg;
                  const rad = (ang.degree * Math.PI) / 180;
                  const radius = 128;
                  const x = 144 + radius * Math.cos(rad);
                  const y = 144 + radius * Math.sin(rad);

                  return (
                    <div
                      key={ang.tag}
                      style={{ left: `${x}px`, top: `${y}px` }}
                      className={`absolute -translate-x-1/2 -translate-y-1/2 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold transition-all shadow-md ${
                        isCaptured
                          ? 'bg-emerald-500 text-white scale-110 ring-2 ring-emerald-300'
                          : isCurrent
                          ? 'bg-purple-500 text-white animate-pulse ring-2 ring-purple-300 scale-105'
                          : 'bg-slate-900/90 text-slate-400 border border-slate-700'
                      }`}
                      title={ang.label}
                    >
                      {isCaptured ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : idx + 1}
                    </div>
                  );
                })}
              </div>

              {/* Center Guidance Box with Blur-Score Feedback & Countdown Overlay */}
              <div className={`absolute inset-10 border-2 rounded-3xl flex flex-col items-center justify-center p-4 text-center bg-black/50 backdrop-blur-[2px] transition-all relative overflow-hidden ${
                faceDetectedWarning || handDetectedWarning
                  ? 'border-red-500 bg-red-950/70 ring-4 ring-red-500/50'
                  : stepPhase === 'STEP_COMPLETED'
                  ? 'border-emerald-400 bg-emerald-950/60 ring-4 ring-emerald-400/40'
                  : focusStatus === 'SHARP'
                  ? 'border-emerald-400 ring-2 ring-emerald-400/30'
                  : focusStatus === 'STEADY'
                  ? 'border-amber-400'
                  : 'border-purple-400/70 border-dashed'
              }`}>
                {/* Step 0: Background Reference Calibration Overlay */}
                {isCalibratingBg && (
                  <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm flex flex-col items-center justify-center p-4 text-center z-30">
                    <Scan className="w-10 h-10 text-purple-400 animate-pulse mb-1.5" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider">
                      Step 0: Background Calibration
                    </span>
                    <p className="text-[11px] text-purple-200 mt-1 leading-snug">
                      Clear scene completely of product, hands & faces.
                    </p>
                    <span className="text-lg font-mono font-bold text-emerald-400 mt-2">
                      {bgFramesCaptured} / 5 reference frames
                    </span>
                    <button
                      onClick={handleCalibrateBackground}
                      className="mt-3 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold rounded-xl active:scale-95 transition-all shadow-md"
                    >
                      Calibrate Empty Scene
                    </button>
                  </div>
                )}

                {/* Face Warning Top Pill (Never blackouts viewfinder so box is visible) */}
                {faceDetectedWarning && !isCalibratingBg && (
                  <div className="absolute top-2 left-2 right-2 bg-red-950/90 border border-red-500/80 rounded-xl p-2 flex items-center justify-center gap-2 z-30 animate-pulse shadow-lg">
                    <ShieldAlert className="w-4 h-4 text-red-400 shrink-0" />
                    <span className="text-[11px] font-bold text-white leading-tight font-mono">
                      Face blocking crop ({blockingFaces.length > 0 ? `${Math.round(blockingFaces[0].score*100)}% conf, ${(blockingFaces[0].widthFraction*100).toFixed(1)}%w` : 'detected'}) — keep face clear
                    </span>
                  </div>
                )}

                {/* Hand Obstruction Warning Banner */}
                {handDetectedWarning && !faceDetectedWarning && !isCalibratingBg && (
                  <div className="absolute inset-0 bg-amber-950/90 backdrop-blur-sm flex flex-col items-center justify-center p-4 text-center z-30 animate-pulse">
                    <ShieldAlert className="w-12 h-12 text-amber-400 mb-2" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider text-amber-200">
                      Hand Obstructing Product
                    </span>
                    <p className="text-xs font-bold text-white mt-1 leading-snug">
                      Keep hands clear of the product during capture
                    </p>
                    <span className="text-[10px] text-amber-300 mt-1.5 font-mono">
                      Hand coverage blocked by MediaPipe detector
                    </span>
                  </div>
                )}

                {/* "Is this the product? Yes / Retry" confirmation prompt before starting angle */}
                {!isCalibratingBg && !productConfirmedForStep && !faceDetectedWarning && (
                  <div className="absolute inset-0 bg-slate-950/85 backdrop-blur-sm flex flex-col items-center justify-center p-4 text-center z-25 animate-fade-in">
                    <Scan className="w-8 h-8 text-emerald-400 mb-1" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider">
                      Is this the product?
                    </span>
                    <p className="text-[11px] text-slate-300 mt-1 leading-tight">
                      Product detected: <strong className="text-emerald-400">{productRatio}%</strong> of guide box.
                    </p>
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => {
                          setProductConfirmedForStep(true);
                          stepStartTimeRef.current = Date.now();
                        }}
                        className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-xl active:scale-95 transition-all flex items-center gap-1 shadow-md shadow-emerald-600/30"
                      >
                        <Check className="w-3.5 h-3.5" />
                        Yes, Start Angle
                      </button>
                      <button
                        onClick={handleRetryAngle}
                        className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl active:scale-95 transition-all"
                      >
                        Retry Box
                      </button>
                    </div>
                  </div>
                )}

                {/* 1. Countdown Phase ("Hold still... 3, 2, 1") */}
                {stepPhase === 'COUNTDOWN' && !isCalibratingBg && (
                  <div className="absolute inset-0 bg-purple-950/80 backdrop-blur-sm flex flex-col items-center justify-center animate-fade-in z-20">
                    <span className="text-xs font-semibold text-purple-200 uppercase tracking-widest">
                      Hold still...
                    </span>
                    <span className="text-5xl font-black font-mono text-white mt-1 drop-shadow-lg scale-110 animate-pulse">
                      {countdown}
                    </span>
                    <span className="text-[10px] text-purple-300 mt-2 font-mono">
                      Step timer: {stepElapsedTime}s (Min 3s)
                    </span>
                  </div>
                )}

                {/* 2. Capturing Phase (Frames 1-6) */}
                {stepPhase === 'CAPTURING' && !isCalibratingBg && (
                  <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center animate-fade-in z-20">
                    <Sparkles className="w-7 h-7 text-amber-300 animate-spin mb-1" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider">
                      Capturing Isolated Product
                    </span>
                    <span className="text-xl font-bold font-mono text-emerald-400 mt-1">
                      {stepFrames.length} / 6 frames
                    </span>
                    <span className="text-[10px] text-slate-300 mt-1">
                      Cropping to box (+5% margin) • Skipping near-duplicates
                    </span>
                  </div>
                )}

                {/* 3. Step Completed Phase (Green Tick Mark Overlay) */}
                {stepPhase === 'STEP_COMPLETED' && !isCalibratingBg && (
                  <div className="absolute inset-0 bg-emerald-950/85 backdrop-blur-sm flex flex-col items-center justify-center animate-fade-in z-20">
                    <CheckCircle2 className="w-14 h-14 text-emerald-400 animate-bounce" />
                    <span className="text-sm font-bold text-white mt-2">
                      Angle Captured! ✓
                    </span>
                    <span className="text-[10px] font-mono text-emerald-200 mt-0.5">
                      {stepFrames.length} cropped frames stored
                    </span>
                  </div>
                )}

                {/* 4. Paused State Overlay */}
                {isPaused && (
                  <div className="absolute inset-0 bg-black/85 backdrop-blur-sm flex flex-col items-center justify-center animate-fade-in z-30">
                    <Pause className="w-10 h-10 text-amber-400 mb-1" />
                    <span className="text-sm font-bold text-white uppercase tracking-wider">
                      Scan Paused
                    </span>
                    <button
                      onClick={handleTogglePause}
                      className="mt-3 px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold flex items-center gap-1.5"
                    >
                      <Play className="w-3.5 h-3.5" />
                      Resume
                    </button>
                  </div>
                )}

                {/* Regular Searching Viewfinder HUD */}
                <Camera className={`w-8 h-8 mb-1.5 ${focusStatus === 'SHARP' ? 'text-emerald-400 animate-pulse' : 'text-purple-300'}`} />
                <span className="text-xs font-bold text-white font-display uppercase tracking-wider">
                  {currentStep.label}
                </span>
                <span className="text-[11px] text-purple-200 mt-0.5 leading-snug">
                  "{currentStep.prompt}"
                </span>

                {/* Real Laplacian Sharpness Feedback Badge */}
                <div className="mt-2 space-y-1">
                  <div className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2.5 py-0.5 rounded-full ${
                    faceDetectedWarning
                      ? 'text-red-300 bg-red-950/80 border border-red-500/50'
                      : focusStatus === 'SHARP'
                      ? 'text-emerald-300 bg-emerald-950/80 border border-emerald-500/50'
                      : focusStatus === 'STEADY'
                      ? 'text-amber-300 bg-amber-950/80 border border-amber-500/50'
                      : 'text-purple-300 bg-purple-950/80 border border-purple-500/50'
                  }`}>
                    {faceDetectedWarning ? (
                      <AlertTriangle className="w-3 h-3 text-red-400" />
                    ) : focusStatus === 'SHARP' ? (
                      <Check className="w-3 h-3 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="w-3 h-3" />
                    )}
                    <span>{cameraFeedback}</span>
                  </div>
                  <div className="text-[9px] font-mono text-slate-300">
                    Sharpness: <strong className={focusStatus === 'SHARP' ? 'text-emerald-400' : 'text-slate-400'}>{liveBlurScore}</strong> (Min 45) • Product: {productRatio}%
                  </div>
                </div>
              </div>
            </div>

            {/* Top Prompt HUD */}
            <div className="absolute top-4 left-4 right-4 z-20 flex justify-between items-center text-xs">
              <span className="bg-black/80 backdrop-blur-md px-3 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
                Angle {currentStepIdx + 1} of {REQUIRED_ANGLES.length} ({currentStep.label})
              </span>

              <span className="bg-black/80 backdrop-blur-md px-3 py-1 rounded-full font-mono text-emerald-300 border border-emerald-500/30">
                Frames: {totalCapturedFrames} / 54 (Target: 40-80)
              </span>
            </div>
          </div>

          {/* Exact Reason Line: Why is capture blocked? */}
          <div className="max-w-md mx-auto space-y-2">
            <div className={`p-3 rounded-2xl border font-mono text-xs flex items-start gap-2.5 transition-all shadow-md ${
              captureBlockedReason
                ? 'bg-amber-950/40 border-amber-500/50 text-amber-200'
                : 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300'
            }`}>
              {captureBlockedReason ? (
                <>
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                  <div className="space-y-0.5 leading-snug">
                    <span className="font-bold text-amber-300 mr-1.5 uppercase text-[11px]">Why is capture blocked?</span>
                    <span className="text-amber-100">{captureBlockedReason}</span>
                  </div>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-400" />
                  <div className="space-y-0.5 leading-snug">
                    <span className="font-bold text-emerald-300 mr-1.5 uppercase text-[11px]">Capture Ready:</span>
                    <span className="text-emerald-100">Product isolated, sharp ({liveBlurScore} ≥ 45) and steady. Auto-capture armed.</span>
                  </div>
                </>
              )}
            </div>

            {/* Non-blocking background face gentle hint */}
            {outsideFaces.length > 0 && !faceDetectedWarning && (
              <div className="px-3 py-1.5 rounded-xl bg-cyan-950/30 border border-cyan-500/30 text-cyan-200 text-[11px] font-mono flex items-center gap-2">
                <Info className="w-3.5 h-3.5 shrink-0 text-cyan-400" />
                <span>Notice: Background face in room ({outsideFaces.length}) is outside the capture box — capture is allowed.</span>
              </div>
            )}

            {/* Step 0 static reference note */}
            {staticRefFacesCount > 0 && (
              <div className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-slate-300 text-[11px] font-mono flex items-center gap-2">
                <Check className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
                <span>Ignoring {staticRefFacesCount} static background detection(s) (poster/texture) calibrated in Step 0.</span>
              </div>
            )}

            {/* Admin Override: "Capture anyway" button after 3 blocked attempts */}
            {blockedAttemptsCount >= 3 && faceDetectedWarning && detectorStatus === 'ready' && (
              <div className="p-4 rounded-2xl bg-red-950/40 border border-red-500/60 text-xs font-mono space-y-3 shadow-xl animate-fade-in">
                <div className="flex items-center gap-2 text-red-300 font-bold uppercase tracking-wider text-xs">
                  <ShieldAlert className="w-4 h-4 text-red-400" />
                  <span>Admin Override ({blockedAttemptsCount} Blocked Attempts Recorded)</span>
                </div>
                <p className="text-[11px] text-red-200 leading-relaxed">
                  A face is detected overlapping the crop region or covering &gt;15% of the frame. If this detection is a false positive on product artwork or packaging graphics, you may confirm and capture the product crop.
                </p>
                {blockingFaces.length > 0 && (
                  <div className="p-2.5 rounded-xl bg-black/60 border border-red-500/30 text-[10px] text-red-300 space-y-1">
                    <div>Box Telemetry: <strong>Score: {Math.round(blockingFaces[0].score * 100)}%</strong> | Size: {(blockingFaces[0].widthFraction * 100).toFixed(1)}%w x {(blockingFaces[0].heightFraction * 100).toFixed(1)}%h ({(blockingFaces[0].areaFraction * 100).toFixed(1)}% area)</div>
                    <div>Location: ({(blockingFaces[0].x * 100).toFixed(1)}%, {(blockingFaces[0].y * 100).toFixed(1)}%) | Persisted: {blockingFaces[0].consecutiveFrames} consecutive frames</div>
                  </div>
                )}
                <label className="flex items-center gap-2.5 text-white font-medium cursor-pointer text-xs">
                  <input
                    type="checkbox"
                    checked={adminConfirmNoFace}
                    onChange={(e) => setAdminConfirmNoFace(e.target.checked)}
                    className="w-4 h-4 rounded text-red-600 focus:ring-red-500 border-slate-700 bg-slate-900 cursor-pointer"
                  />
                  <span>I confirm there is no face in the saved crop</span>
                </label>
                <button
                  onClick={handleAdminOverrideCapture}
                  disabled={!adminConfirmNoFace}
                  className={`w-full py-2.5 px-4 rounded-xl font-bold text-xs flex items-center justify-center gap-2 transition-all ${
                    adminConfirmNoFace
                      ? 'bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-600/30 active:scale-95'
                      : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
                  }`}
                >
                  <Zap className="w-3.5 h-3.5" />
                  <span>Capture anyway (Save Product Crop Only)</span>
                </button>
              </div>
            )}
          </div>

          {/* Action Deck: Pause, Capture Now, Retry Angle, Skip Angle */}
          <div className="max-w-md mx-auto space-y-2">
            <div className="grid grid-cols-4 gap-2">
              <button
                onClick={handleTogglePause}
                className="py-3 px-2 rounded-2xl border border-slate-700 bg-slate-800 hover:bg-slate-700 text-white font-semibold text-xs flex flex-col items-center justify-center gap-1 active:scale-95 transition-all"
                title={isPaused ? 'Resume Scan' : 'Pause Scan'}
              >
                {isPaused ? <Play className="w-4 h-4 text-emerald-400" /> : <Pause className="w-4 h-4 text-amber-400" />}
                <span>{isPaused ? 'Resume' : 'Pause'}</span>
              </button>

              <button
                onClick={handleCaptureNow}
                disabled={faceDetectedWarning || handDetectedWarning || detectorStatus !== 'ready'}
                className={`py-3 px-2 rounded-2xl text-white font-semibold text-xs flex flex-col items-center justify-center gap-1 active:scale-95 transition-all shadow-lg ${
                  faceDetectedWarning || handDetectedWarning || detectorStatus !== 'ready'
                    ? 'bg-slate-600 opacity-50 cursor-not-allowed shadow-none'
                    : 'bg-purple-600 hover:bg-purple-700 shadow-purple-600/30'
                }`}
                title="Capture frame immediately"
              >
                <Zap className="w-4 h-4 text-amber-300" />
                <span>Capture Now</span>
              </button>

              <button
                onClick={handleRetryAngle}
                className="py-3 px-2 rounded-2xl border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs flex flex-col items-center justify-center gap-1 active:scale-95 transition-all"
                title="Clear current angle and retry"
              >
                <RefreshCw className="w-4 h-4 text-blue-400" />
                <span>Retry Angle</span>
              </button>

              <button
                onClick={handleSkipAngle}
                className="py-3 px-2 rounded-2xl border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs flex flex-col items-center justify-center gap-1 active:scale-95 transition-all"
                title="Skip to next angle"
              >
                <SkipForward className="w-4 h-4 text-slate-400" />
                <span>Skip Angle</span>
              </button>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => {
                  setIsScanning(false);
                  setIsDone(true);
                }}
                className="flex-1 py-3 px-4 rounded-2xl border border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Review Cropped Gallery ({totalCapturedFrames} Frames)
              </button>

              <button
                onClick={handleRequestCancel}
                className="px-4 py-3 rounded-2xl border border-red-200 dark:border-red-900/40 bg-red-50 hover:bg-red-100 dark:bg-red-950/30 text-xs font-semibold text-red-600 dark:text-red-400 transition-colors active:scale-95 flex items-center gap-1"
                title="Cancel scan and discard captures"
              >
                <X className="w-4 h-4" />
                <span>Cancel</span>
              </button>
            </div>
          </div>
        </div>

      {/* Final 360 Review Screen (CROPPED Thumbnails, Coverage Rule Check) */}
      {isDone && (
        <div className="space-y-6">
          <div className="text-center space-y-1">
            <span className="inline-block p-3 bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 rounded-full mb-1">
              <Check className="w-6 h-6" />
            </span>
            <h2 className="text-lg font-bold font-display text-slate-900 dark:text-white">
              360° Cropped Product Gallery (Isolated Foreground)
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Review isolated, cropped product frames before GrabCut background replacement and deep vector embedding.
            </p>
          </div>

          {/* Coverage Rule Status Banner */}
          <div className={`p-4 rounded-2xl border flex items-center justify-between text-xs ${
            meetsCoverageRule
              ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
              : 'bg-amber-50 dark:bg-amber-950/40 border-amber-300 dark:border-amber-800 text-amber-800 dark:text-amber-300'
          }`}>
            <div className="flex items-center gap-2.5">
              {meetsCoverageRule ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
              ) : (
                <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
              )}
              <div>
                <span className="font-bold">
                  Coverage Rule: {meetsCoverageRule ? 'All Requirements Satisfied ✓' : 'Additional Frames Required'}
                </span>
                <p className="text-[11px] opacity-90 mt-0.5">
                  Requires all 9 angles with ≥4 frames each (target 40-80 frames) including Label Close-up. Currently: <strong>{totalCapturedFrames} frames</strong> across <strong>{completedAnglesCount}/9 angles</strong>.
                </p>
              </div>
            </div>

            <button
              onClick={() => {
                setIsScanning(true);
                setIsDone(false);
              }}
              className="text-xs font-semibold px-3 py-1.5 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-sm hover:bg-slate-50 dark:hover:bg-slate-800 shrink-0"
            >
              + Add / Retake Angle
            </button>
          </div>

          {/* Real CROPPED Thumbnails Gallery for 9 Angles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {REQUIRED_ANGLES.map((ang) => {
              const frameList = captures[ang.tag] || [];
              const primaryFrame = frameList[0];
              const avgSharpness = frameList.length > 0
                ? Math.round(frameList.reduce((acc, f) => acc + f.blurScore, 0) / frameList.length)
                : 0;

              if (!primaryFrame) {
                return (
                  <div
                    key={ang.tag}
                    onClick={() => handleRetakeInGallery(ang.tag)}
                    className="border-2 border-dashed border-slate-200 dark:border-slate-800 rounded-2xl p-4 flex flex-col items-center justify-center text-center cursor-pointer hover:border-purple-500 transition-colors aspect-square"
                  >
                    <Plus className="w-6 h-6 text-slate-400 mb-1" />
                    <span className="text-[11px] font-semibold text-slate-500">{ang.label}</span>
                    <span className="text-[10px] text-purple-600 mt-1">Tap to capture</span>
                  </div>
                );
              }

              return (
                <div
                  key={ang.tag}
                  className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-2.5 shadow-sm space-y-2 group relative"
                >
                  <div className="aspect-square bg-slate-950 rounded-xl overflow-hidden relative border border-slate-800 flex items-center justify-center">
                    <img
                      src={primaryFrame.dataUrl}
                      alt={ang.label}
                      className="w-full h-full object-contain"
                    />
                    <div className="absolute top-1.5 right-1.5 flex gap-1">
                      <button
                        onClick={() => setSelectedGalleryAngle(ang.tag)}
                        className="bg-black/70 hover:bg-black text-white p-1.5 rounded-lg transition-colors"
                        title="View all frames in this angle"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleRetakeInGallery(ang.tag)}
                        className="bg-black/70 hover:bg-black text-white p-1.5 rounded-lg transition-colors"
                        title="Retake this angle"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDeleteInGallery(ang.tag)}
                        className="bg-black/70 hover:bg-red-600 text-white p-1.5 rounded-lg transition-colors"
                        title="Delete this capture"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    <div className="absolute bottom-1.5 left-1.5 bg-black/80 px-2 py-0.5 rounded-md text-[10px] font-mono text-emerald-400 border border-emerald-500/30">
                      Cropped • {frameList.length} frames
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">{ang.label}</span>
                    <span className="text-emerald-500 text-[10px] font-mono font-bold shrink-0">Sharp: {avgSharpness}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Action Deck */}
          <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
            <button
              onClick={() => {
                setCaptures({});
                setStepFrames([]);
                setCurrentStepIdx(0);
                setProductConfirmedForStep(false);
                setIsScanning(true);
                setIsDone(false);
              }}
              className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-200 text-xs font-semibold py-3 px-5 rounded-2xl active:scale-95 transition-all"
            >
              Retake All
            </button>

            <button
              onClick={handleRequestCancel}
              className="bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/50 text-xs font-semibold py-3 px-5 rounded-2xl active:scale-95 transition-all flex items-center justify-center gap-1.5"
              title="Discard scan and return to products"
            >
              <X className="w-4 h-4" />
              <span>Cancel Scan</span>
            </button>

            <button
              onClick={handleSaveEmbeddings}
              disabled={!meetsCoverageRule || isProcessing}
              className={`flex-1 text-white font-semibold py-3 px-5 rounded-2xl shadow-xl flex items-center justify-center gap-2 text-xs active:scale-98 transition-all ${
                meetsCoverageRule
                  ? 'bg-purple-600 hover:bg-purple-700 shadow-purple-600/30'
                  : 'bg-slate-400 cursor-not-allowed shadow-none'
              }`}
            >
              <Sparkles className="w-4 h-4" />
              {isProcessing
                ? 'Processing Real Embeddings Pipeline...'
                : meetsCoverageRule
                ? `Confirm & Enroll Real Embeddings (${totalCapturedFrames} Frames Across 9 Angles) →`
                : `Need all 9 angles with ≥4 frames (Currently: ${totalCapturedFrames}/40 frames)`}
            </button>
          </div>
        </div>
      )}

      {/* Expanded Angle Frame Gallery Modal */}
      {selectedGalleryAngle && captures[selectedGalleryAngle] && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-2xl w-full shadow-2xl space-y-4 animate-fade-in">
            <div className="flex justify-between items-center pb-2 border-b border-slate-200 dark:border-slate-800">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                All Cropped Frames for {selectedGalleryAngle} ({captures[selectedGalleryAngle].length} frames)
              </h3>
              <button
                onClick={() => setSelectedGalleryAngle(null)}
                className="p-1.5 text-slate-400 hover:text-white rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-3 gap-2.5 max-h-96 overflow-y-auto p-1">
              {captures[selectedGalleryAngle].map((f, i) => (
                <div key={i} className="space-y-1 bg-slate-900 p-2 rounded-xl border border-slate-800 relative group">
                  <div className="aspect-square bg-black rounded-lg overflow-hidden flex items-center justify-center relative">
                    <img src={f.dataUrl} alt={`Frame ${i + 1}`} className="w-full h-full object-contain" />
                    <button
                      onClick={() => handleDeleteSingleFrame(selectedGalleryAngle, i)}
                      className="absolute top-1 right-1 bg-red-600/90 hover:bg-red-600 text-white p-1 rounded-md opacity-80 hover:opacity-100 transition-opacity"
                      title="Delete this frame"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                    <span>Frame #{i + 1}</span>
                    <span className="text-emerald-400">Sharp: {f.blurScore}</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedGalleryAngle(null)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Background Processing Pipeline Modal (Real Telemetry, No Fake Timers) */}
      {isProcessing && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-md w-full shadow-2xl space-y-5 text-center relative animate-fade-in">
            {/* Top Close / Minimize X Button */}
            <button
              onClick={() => {
                if (jobStatus === 'PENDING' || jobStatus === 'PROCESSING') {
                  handleMinimizeProcessing();
                } else {
                  setIsProcessing(false);
                }
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-2 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title={jobStatus === 'PENDING' || jobStatus === 'PROCESSING' ? 'Minimize to Background' : 'Close'}
            >
              <X className="w-4 h-4" />
            </button>

            <div className={`w-14 h-14 rounded-2xl mx-auto flex items-center justify-center ${
              jobStatus === 'FAILED'
                ? 'bg-rose-600/20 text-rose-600 dark:text-rose-400'
                : jobStatus === 'CANCELLED'
                ? 'bg-amber-600/20 text-amber-600 dark:text-amber-400'
                : jobStatus === 'ENROLLED'
                ? 'bg-emerald-600/20 text-emerald-600 dark:text-emerald-400'
                : 'bg-purple-600/20 text-purple-600 dark:text-purple-400'
            }`}>
              {jobStatus === 'FAILED' ? (
                <AlertTriangle className="w-7 h-7" />
              ) : jobStatus === 'CANCELLED' ? (
                <AlertCircle className="w-7 h-7" />
              ) : jobStatus === 'ENROLLED' ? (
                <CheckCircle2 className="w-7 h-7" />
              ) : (
                <Sparkles className="w-7 h-7 animate-spin" />
              )}
            </div>

            <div>
              <h3 className="text-base font-bold font-display text-slate-900 dark:text-white">
                {jobStatus === 'FAILED'
                  ? 'Background Processing Failed'
                  : jobStatus === 'CANCELLED'
                  ? 'Scan Processing Cancelled'
                  : jobStatus === 'ENROLLED'
                  ? 'AI Vision Enrollment Complete!'
                  : 'Processing 360° Vision Enrollment'}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {jobStatus === 'CANCELLED'
                  ? 'Processing was stopped. Uploaded frames are preserved so you can retry.'
                  : jobStageMessage || `Processing 360 captures for ${product.name}...`}
              </p>
            </div>

            {/* Real Progress Bar */}
            {jobTotal > 0 && jobStatus !== 'FAILED' && jobStatus !== 'CANCELLED' && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-[11px] font-mono text-slate-500 dark:text-slate-400">
                  <span>Progress</span>
                  <span>{jobDone} / {jobTotal} ({Math.min(100, Math.round((jobDone / Math.max(1, jobTotal)) * 100))}%)</span>
                </div>
                <div className="w-full bg-slate-100 dark:bg-slate-800 h-2.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-300 rounded-full ${
                      jobStatus === 'ENROLLED' ? 'bg-emerald-500' : 'bg-purple-600'
                    }`}
                    style={{
                      width: `${Math.min(100, Math.round((jobDone / Math.max(1, jobTotal)) * 100))}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Real Stage Telemetry List with Exact State Icons */}
            <div className="space-y-2 text-left text-xs">
              {[
                {
                  id: 'UPLOAD',
                  label: 'Frames uploaded & verified in cloud storage',
                  status: (() => {
                    if (jobStatus === 'ENROLLED') return 'DONE';
                    if (jobStatus === 'FAILED') {
                      const err = (jobError || '').toUpperCase();
                      if (
                        jobStage === 'SAVING_FRAMES' ||
                        jobStage === 'AWAITING_UPLOAD' ||
                        err.includes('ERR_NO_FRAMES') ||
                        err.includes('ERR_MISSING_FRAMES') ||
                        err.includes('UPLOAD FAILED') ||
                        failedUploads.length > 0
                      ) {
                        return 'FAILED';
                      }
                      return 'DONE';
                    }
                    if (jobStage === 'SAVING_FRAMES' || jobStage === 'AWAITING_UPLOAD' || jobStage === 'QUEUED') {
                      return 'IN_PROGRESS';
                    }
                    return 'DONE';
                  })(),
                },
                {
                  id: 'PREPROCESS',
                  label: 'Downscaled ~320px & product crop isolation',
                  status: (() => {
                    if (jobStatus === 'ENROLLED') return 'DONE';
                    if (jobStatus === 'FAILED') {
                      const err = (jobError || '').toUpperCase();
                      if (
                        jobStage === 'SAVING_FRAMES' ||
                        jobStage === 'AWAITING_UPLOAD' ||
                        err.includes('ERR_NO_FRAMES') ||
                        err.includes('ERR_MISSING_FRAMES') ||
                        err.includes('UPLOAD FAILED') ||
                        failedUploads.length > 0
                      ) {
                        return 'PENDING';
                      }
                      if (jobStage === 'REMOVING_BACKGROUND' || (jobStage === 'PROCESSING_FRAMES' && jobDone === 0)) {
                        return 'FAILED';
                      }
                      return 'DONE';
                    }
                    if (jobStage === 'SAVING_FRAMES' || jobStage === 'AWAITING_UPLOAD' || jobStage === 'QUEUED') {
                      return 'PENDING';
                    }
                    if (jobStage === 'REMOVING_BACKGROUND') {
                      return 'IN_PROGRESS';
                    }
                    return 'DONE';
                  })(),
                },
                {
                  id: 'EMBED',
                  label: 'Batch ONNX INT8 CLIP ViT-B/32 embedding extraction',
                  status: (() => {
                    if (jobStatus === 'ENROLLED') return 'DONE';
                    if (jobStatus === 'FAILED') {
                      const err = (jobError || '').toUpperCase();
                      if (
                        jobStage === 'SAVING_FRAMES' ||
                        jobStage === 'AWAITING_UPLOAD' ||
                        err.includes('ERR_NO_FRAMES') ||
                        err.includes('ERR_MISSING_FRAMES') ||
                        err.includes('UPLOAD FAILED') ||
                        failedUploads.length > 0 ||
                        jobStage === 'REMOVING_BACKGROUND' ||
                        (jobStage === 'PROCESSING_FRAMES' && jobDone === 0)
                      ) {
                        return 'PENDING';
                      }
                      if (jobStage === 'COMPUTING_VECTORS' || (jobStage === 'PROCESSING_FRAMES' && jobDone > 0)) {
                        return 'FAILED';
                      }
                      return 'DONE';
                    }
                    if (jobStage === 'COMPUTING_VECTORS' || (jobStage === 'PROCESSING_FRAMES' && jobDone > 0)) {
                      return 'IN_PROGRESS';
                    }
                    if (jobStage === 'SAVING_TO_DATABASE' || jobStage === 'COMPLETED') {
                      return 'DONE';
                    }
                    return 'PENDING';
                  })(),
                },
                {
                  id: 'DATABASE',
                  label: 'Single-transaction atomic commit & quality score calculated',
                  status: (() => {
                    if (jobStatus === 'ENROLLED') return 'DONE';
                    if (jobStatus === 'FAILED') {
                      if (jobStage === 'SAVING_TO_DATABASE') {
                        return 'FAILED';
                      }
                      return 'PENDING';
                    }
                    if (jobStage === 'SAVING_TO_DATABASE') {
                      return 'IN_PROGRESS';
                    }
                    return 'PENDING';
                  })(),
                },
              ].map((step) => (
                <div
                  key={step.id}
                  className={`p-2.5 rounded-xl border flex items-center gap-2.5 transition-all ${
                    step.status === 'DONE'
                      ? 'bg-emerald-50/60 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800/60 text-emerald-800 dark:text-emerald-300'
                      : step.status === 'FAILED'
                      ? 'bg-red-50 dark:bg-red-950/40 border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 font-medium'
                      : step.status === 'IN_PROGRESS'
                      ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 dark:border-purple-800 text-purple-700 dark:text-purple-300 shadow-sm'
                      : 'opacity-40 border-slate-200 dark:border-slate-800 text-slate-400'
                  }`}
                >
                  {step.status === 'DONE' && <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />}
                  {step.status === 'FAILED' && <XCircle className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0" />}
                  {step.status === 'IN_PROGRESS' && <Loader2 className="w-4 h-4 text-purple-600 dark:text-purple-400 animate-spin shrink-0" />}
                  {step.status === 'PENDING' && <Circle className="w-4 h-4 text-slate-300 dark:text-slate-600 shrink-0" />}
                  <span>{step.label}</span>
                </div>
              ))}
            </div>

            {/* Error Message if Failed */}
            {jobStatus === 'FAILED' && (
              <div className="p-3 bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 rounded-xl text-left text-xs text-rose-700 dark:text-rose-300">
                <div className="font-semibold mb-1 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Error Details
                </div>
                <p className="font-mono text-[11px] break-words">{jobError || 'Unknown processing error.'}</p>
              </div>
            )}

            {/* Success Summary */}
            {enrollmentStats && jobStatus === 'ENROLLED' && (
              <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-[11px] font-mono text-slate-600 dark:text-slate-300 text-left">
                <div>Enrolled Vectors: <strong>{enrollmentStats.total_embeddings_stored}</strong> (capped at 100)</div>
                <div>Model: <strong>{enrollmentStats.model_name}</strong> ({enrollmentStats.vector_dim}-dim)</div>
                <div>Status: <strong className="text-emerald-600 dark:text-emerald-400">ACTIVE & READY</strong></div>
              </div>
            )}

            {/* Action Buttons Depending on State */}
            {/* 1. When Active (PENDING or PROCESSING) */}
            {(jobStatus === 'PENDING' || jobStatus === 'PROCESSING') && (
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => setShowCancelProcessingConfirm(true)}
                  className="flex-1 py-2.5 px-4 bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/40 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all"
                >
                  <X className="w-3.5 h-3.5" />
                  Cancel Scan
                </button>
                <button
                  onClick={handleMinimizeProcessing}
                  className="flex-1 py-2.5 px-4 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-md shadow-purple-600/20"
                >
                  Run in Background
                </button>
              </div>
            )}

            {/* 2. When Failed */}
            {jobStatus === 'FAILED' && (
              <div className="space-y-2 pt-1">
                {((jobError || '').toUpperCase().includes('ERR_NO_FRAMES') ||
                  (jobError || '').toLowerCase().includes('no saved frames') ||
                  (jobTotal === 0 && jobDone === 0)) ? (
                  <div className="space-y-2">
                    <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl text-center space-y-2">
                      <p className="text-xs text-red-700 dark:text-red-300 font-medium">
                        This scan has no saved frames. Please scan again.
                      </p>
                      <button
                        onClick={handleScanAgain}
                        className="w-full py-2.5 px-4 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-md shadow-purple-600/20"
                      >
                        <Camera className="w-3.5 h-3.5" />
                        Scan again
                      </button>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={onComplete}
                        className="flex-1 py-2 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
                      >
                        Done
                      </button>
                      <button
                        onClick={() => setIsProcessing(false)}
                        className="py-2 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-500 rounded-xl text-xs font-semibold transition-all"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                ) : partialConfirmation ? (
                  <div className="space-y-3">
                    <div className="p-3.5 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-xl space-y-2.5 text-left">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                        <div>
                          <p className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                            Partial Frames Warning
                          </p>
                          <p className="text-[11px] text-amber-800 dark:text-amber-300 mt-0.5">
                            Only {partialConfirmation.surviving} of {partialConfirmation.total} frames found in storage. Some angles will be missing:
                          </p>
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {partialConfirmation.missingAngles.map(ang => (
                              <span key={ang} className="px-1.5 py-0.5 bg-amber-200/70 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200 rounded text-[10px] font-mono border border-amber-300 dark:border-amber-700">
                                {ang}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-2 pt-1">
                        <button
                          onClick={async () => {
                            if (!activeJobId) return;
                            try {
                              setPartialConfirmation(null);
                              setJobError(null);
                              setJobStatus('PENDING');
                              setJobStage('QUEUED');
                              setJobStageMessage('Enrolling with surviving frames...');
                              await api.retryScanJob(activeJobId, { confirm_partial: true });
                            } catch (e: any) {
                              setJobError(e.message || 'Failed to retry job.');
                            }
                          }}
                          className="flex-1 py-2 px-3 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-xs font-semibold shadow-sm"
                        >
                          Confirm &amp; Enroll Partial
                        </button>
                        <button
                          onClick={() => setPartialConfirmation(null)}
                          className="py-2 px-3 bg-slate-200 hover:bg-slate-300 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                ) : failedUploads.length > 0 ? (
                  <div className="space-y-2">
                    <div className="p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 rounded-xl text-center space-y-2">
                      <p className="text-xs text-amber-800 dark:text-amber-200 font-medium">
                        Upload failed for {failedUploads.length} frame(s).
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={handleRetryFailedUploads}
                          className="flex-1 py-2 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 shadow-md"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                          Retry Failed ({failedUploads.length})
                        </button>
                        <button
                          onClick={handleFallbackServerUpload}
                          className="flex-1 py-2 px-3 bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-xl text-xs font-semibold"
                        >
                          Upload via Server
                        </button>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={onComplete}
                        className="flex-1 py-2 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
                      >
                        Done
                      </button>
                      <button
                        onClick={() => setIsProcessing(false)}
                        className="py-2 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-500 rounded-xl text-xs font-semibold transition-all"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <button
                      onClick={handleRetryJob}
                      className="flex-1 py-2.5 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-md shadow-purple-600/20"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      Retry
                    </button>
                    <button
                      onClick={onComplete}
                      className="flex-1 py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
                    >
                      Done
                    </button>
                    <button
                      onClick={() => setIsProcessing(false)}
                      className="py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-500 rounded-xl text-xs font-semibold transition-all"
                    >
                      Close
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 3. When Cancelled */}
            {jobStatus === 'CANCELLED' && (
              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleRetryJob}
                  className="flex-1 py-2.5 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-md shadow-purple-600/20"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Retry
                </button>
                <button
                  onClick={onComplete}
                  className="flex-1 py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
                >
                  Done
                </button>
                <button
                  onClick={() => setIsProcessing(false)}
                  className="py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-500 rounded-xl text-xs font-semibold transition-all"
                >
                  Close
                </button>
              </div>
            )}

            {/* 4. When Enrolled (Success) */}
            {jobStatus === 'ENROLLED' && (
              <div className="flex gap-2 pt-1">
                {onPreviewTest && (
                  <button
                    onClick={() => {
                      setIsProcessing(false);
                      onPreviewTest();
                    }}
                    className="flex-1 py-2.5 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-md shadow-purple-600/20"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Run Preview Test
                  </button>
                )}
                <button
                  onClick={onComplete}
                  className="flex-1 py-2.5 px-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold transition-all shadow-md shadow-emerald-600/20"
                >
                  Done
                </button>
                <button
                  onClick={() => setIsProcessing(false)}
                  className="py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
                >
                  Close
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Discard Scan Confirmation Dialog */}
      {showDiscardConfirm && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-sm w-full shadow-2xl space-y-4 text-center animate-fade-in">
            <div className="w-12 h-12 rounded-2xl bg-red-100 dark:bg-red-950/60 text-red-600 dark:text-red-400 mx-auto flex items-center justify-center">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">Discard this scan?</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Any captured frames will be deleted from memory and camera tracks will be stopped.
              </p>
            </div>
            <div className="flex gap-2.5 pt-2">
              <button
                onClick={handleDiscardScan}
                className="flex-1 py-2.5 px-4 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold transition-all shadow-md shadow-red-600/20"
              >
                Discard
              </button>
              <button
                onClick={() => setShowDiscardConfirm(false)}
                className="flex-1 py-2.5 px-4 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
              >
                Keep scanning
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stop Processing Confirmation Dialog */}
      {showCancelProcessingConfirm && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-sm w-full shadow-2xl space-y-4 text-center animate-fade-in">
            <div className="w-12 h-12 rounded-2xl bg-amber-100 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 mx-auto flex items-center justify-center">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">Stop processing?</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                The background AI worker will be stopped. Saved frames are preserved so you can retry or resume later.
              </p>
            </div>
            <div className="flex gap-2.5 pt-2">
              <button
                onClick={handleCancelProcessing}
                className="flex-1 py-2.5 px-4 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold transition-all shadow-md shadow-red-600/20"
              >
                Stop Processing
              </button>
              <button
                onClick={() => setShowCancelProcessingConfirm(false)}
                className="flex-1 py-2.5 px-4 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all"
              >
                Keep Running
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Guided360ScanView;
