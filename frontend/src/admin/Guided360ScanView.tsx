import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera, Check, RefreshCw, Volume2, VolumeX, Sparkles, AlertCircle,
  ArrowLeft, X, Trash2, AlertTriangle, CheckCircle2, Plus, Zap,
  Play, Pause, SkipForward, Scan, ShieldAlert, Eye
} from 'lucide-react';
import { Product } from '../types';
import { api } from '../services/api';

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
  dataUrl: string; // Cropped to product bounding box with 5% margin
  originalDataUrl: string; // Full uncropped high-resolution camera frame
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
  const [productRatio, setProductRatio] = useState<number>(0);
  const [detectedBox, setDetectedBox] = useState<ProductBoundingBox | null>(null);

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

  // Capture Crop & Original Frames
  const captureFrameInternal = useCallback((): CapturedFrame | null => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return null;

    const vw = video.videoWidth || 1280;
    const vh = video.videoHeight || 720;

    // 1. Full uncropped original frame
    const originalCanvas = document.createElement('canvas');
    originalCanvas.width = vw;
    originalCanvas.height = vh;
    const origCtx = originalCanvas.getContext('2d');
    if (!origCtx) return null;
    origCtx.drawImage(video, 0, 0, vw, vh);
    const originalDataUrl = originalCanvas.toDataURL('image/jpeg', 0.90);

    // 2. Cropped product box with 5% margin
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
      originalDataUrl,
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
        let skinPixelCount = 0;
        let minPX = gX2;
        let maxPX = gX1;
        let minPY = gY2;
        let maxPY = gY1;

        const bgRef = bgRefAverage.current;

        for (let y = gY1; y < gY2; y++) {
          const row = y * 160;
          for (let x = gX1; x < gX2; x++) {
            const idx = row + x;
            const pIdx = idx * 4;
            const r = data[pIdx];
            const g = data[pIdx + 1];
            const b = data[pIdx + 2];

            // Skin / Hand / Face color filtering in YCbCr & RGB space
            const cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128;
            const cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128;
            const isSkin = (cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173) ||
                           (r > 95 && g > 40 && b > 20 && Math.max(r, g, b) - Math.min(r, g, b) > 15 && Math.abs(r - g) > 15 && r > g && r > b);

            if (isSkin) {
              skinPixelCount++;
            } else if (bgRef) {
              const bgDiff = Math.abs(gray[idx] - bgRef[idx]);
              if (bgDiff > 24) {
                // Foreground pixel that is NOT background and NOT skin
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

        // Face & Body Intrusion Guard: If skin/face dominates >35% of guide box
        const skinRatio = skinPixelCount / totalGuidePixels;
        const isFaceIntrusion = skinRatio > 0.35;
        setFaceDetectedWarning(isFaceIntrusion);

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

        // Draw Canvas Overlay (Green box on product, red/hatched on excluded regions)
        if (overlayCanvas) {
          overlayCanvas.width = 160;
          overlayCanvas.height = 120;
          const oCtx = overlayCanvas.getContext('2d');
          if (oCtx) {
            oCtx.clearRect(0, 0, 160, 120);

            if (isFaceIntrusion) {
              // Excluded red hatched warning
              oCtx.fillStyle = 'rgba(239, 68, 68, 0.35)';
              oCtx.fillRect(gX1, gY1, gX2 - gX1, gY2 - gY1);
              oCtx.strokeStyle = '#EF4444';
              oCtx.lineWidth = 2;
              oCtx.strokeRect(gX1, gY1, gX2 - gX1, gY2 - gY1);
            } else if (computedBox && isProductBigEnough) {
              // Scale box back to overlay coordinates
              const oX = (computedBox.x / vw) * 160;
              const oY = (computedBox.y / vh) * 120;
              const oW = (computedBox.width / vw) * 160;
              const oH = (computedBox.height / vh) * 120;

              oCtx.strokeStyle = '#10B981';
              oCtx.lineWidth = 2;
              oCtx.strokeRect(oX, oY, oW, oH);

              oCtx.fillStyle = 'rgba(16, 185, 129, 0.12)';
              oCtx.fillRect(oX, oY, oW, oH);
            }
          }
        }

        // Visual HUD Feedback
        if (isFaceIntrusion) {
          setCameraFeedback('Show only the product. Keep your face out of the frame');
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
        if (!isPausedRef.current && autoCaptureEnabled && productConfirmedRef.current && !isFaceIntrusion && isProductBigEnough) {
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
            if (motionDiff > 25.0 || isFaceIntrusion) {
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
            if (now - lastCaptureTimeRef.current >= 300 && isLightingOk && !isFaceIntrusion) {
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
    if (faceDetectedWarning) {
      alert('Cannot capture while face/hands are detected in the guide box. Show only the product.');
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

  const handleRetakeInGallery = (tag: string) => {
    const idx = REQUIRED_ANGLES.findIndex((a) => a.tag === tag);
    if (idx !== -1) {
      setCurrentStepIdx(idx);
      setProductConfirmedForStep(false);
      setStepFrames([]);
      setStepPhase('WAITING_STEADY');
      setCountdown(3);
      lastCapturedGrayRef.current = null;
      stepStartTimeRef.current = Date.now();
      setIsScanning(true);
      setIsDone(false);
    }
  };

  const handleDeleteInGallery = (tag: string) => {
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[tag];
      return copy;
    });
  };

  // Coverage Rule: Target 40 to 80 good frames across all 9 angles
  const totalCapturedFrames = Object.values(captures).reduce((sum, arr) => sum + arr.length, 0);
  const completedAngles = REQUIRED_ANGLES.filter((a) => (captures[a.tag]?.length || 0) >= 4);
  const completedAnglesCount = completedAngles.length;
  const hasLabelCloseup = (captures['LABEL_CLOSEUP']?.length || 0) >= 4;
  const meetsCoverageRule = completedAnglesCount === REQUIRED_ANGLES.length && totalCapturedFrames >= 40 && hasLabelCloseup;

  // Submit Real Frames: Uploads all 40-80 cropped and original frames to backend as background job
  const handleSaveEmbeddings = async () => {
    if (!meetsCoverageRule) return;

    setIsProcessing(true);
    setJobError(null);
    setJobStage('SAVING_FRAMES');
    setJobStageMessage('Uploading cropped & original frames to cloud storage...');
    setJobDone(0);
    setJobTotal(totalCapturedFrames);

    try {
      const payload: { angle_tag: string; image_data_url: string; original_image_data_url?: string }[] = [];
      for (const [angle_tag, frameList] of Object.entries(captures)) {
        for (const frame of frameList) {
          payload.push({
            angle_tag,
            image_data_url: frame.dataUrl, // Cropped product box
            original_image_data_url: frame.originalDataUrl, // Original full frame
          });
        }
      }

      const res = await api.complete360Scan(product.id, payload);
      setActiveJobId(res.job_id);
      setJobStatus('PENDING');
      setJobStageMessage('Frames saved. Waiting for background worker...');
    } catch (e: any) {
      setJobError(e.message || 'Failed to submit 360-scan frames');
      setJobStatus('FAILED');
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
    if (!activeJobId) return;
    try {
      setJobError(null);
      setJobStatus('PENDING');
      setJobStage('QUEUED');
      setJobStageMessage('Re-enqueuing job...');
      await api.retryScanJob(activeJobId);
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

      {!isDone ? (
        /* Real Viewfinder and Circular Progress Ring */
        <div className="space-y-6">
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
                faceDetectedWarning
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

                {/* Face & Body Warning Banner: "Show only the product. Keep your face out of the frame" */}
                {faceDetectedWarning && !isCalibratingBg && (
                  <div className="absolute inset-0 bg-red-950/90 backdrop-blur-sm flex flex-col items-center justify-center p-4 text-center z-30 animate-pulse">
                    <ShieldAlert className="w-12 h-12 text-red-400 mb-2" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider text-red-200">
                      Person Detected in Guide Box
                    </span>
                    <p className="text-xs font-bold text-white mt-1 leading-snug">
                      "Show only the product. Keep your face out of the frame"
                    </p>
                    <span className="text-[10px] text-red-300 mt-1.5 font-mono">
                      Face / skin intrusion blocked from capture
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
                disabled={faceDetectedWarning}
                className={`py-3 px-2 rounded-2xl text-white font-semibold text-xs flex flex-col items-center justify-center gap-1 active:scale-95 transition-all shadow-lg ${
                  faceDetectedWarning
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
      ) : (
        /* Final 360 Review Screen (CROPPED Thumbnails, Coverage Rule Check) */
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
                <div key={i} className="space-y-1 bg-slate-900 p-2 rounded-xl border border-slate-800">
                  <div className="aspect-square bg-black rounded-lg overflow-hidden flex items-center justify-center">
                    <img src={f.dataUrl} alt={`Frame ${i + 1}`} className="w-full h-full object-contain" />
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

            {/* Real Stage Telemetry List */}
            <div className="space-y-2 text-left text-xs">
              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                jobStage === 'SAVING_FRAMES' || jobDone > 0 || jobStage === 'REMOVING_BACKGROUND' || jobStage === 'COMPUTING_VECTORS' || jobStatus === 'ENROLLED'
                  ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300'
                  : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${jobDone > 0 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Frames uploaded & saved in Supabase object storage</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                jobStage === 'REMOVING_BACKGROUND' || jobStage === 'COMPUTING_VECTORS' || jobStatus === 'ENROLLED'
                  ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300'
                  : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${jobStage === 'COMPUTING_VECTORS' || jobStatus === 'ENROLLED' ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Downscaled ~320px & GrabCut segmentation onto neutral grey (128,128,128)</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                jobStage === 'COMPUTING_VECTORS' || jobStatus === 'ENROLLED'
                  ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300'
                  : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${jobStatus === 'ENROLLED' ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Batch ONNX INT8 CLIP ViT-B/32 embedding extraction</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                jobStatus === 'ENROLLED'
                  ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 text-emerald-700 dark:text-emerald-300'
                  : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${jobStatus === 'ENROLLED' ? 'text-emerald-600' : 'text-slate-400'}`} />
                <span>Single-transaction atomic commit & quality score calculated</span>
              </div>
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
