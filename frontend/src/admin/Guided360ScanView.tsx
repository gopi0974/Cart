import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera, Check, RefreshCw, Volume2, VolumeX, Sparkles, AlertCircle,
  ArrowRight, ShieldCheck, Trash2, Sun, Moon, Eye, AlertTriangle, CheckCircle2, Plus, Zap
} from 'lucide-react';
import { Product } from '../types';
import { api } from '../services/api';

interface Props {
  product: Product;
  onComplete: () => void;
  onPreviewTest: () => void;
}

interface AngleStep {
  tag: string;
  label: string;
  prompt: string;
  speechText: string;
  degree: number;
}

const REQUIRED_ANGLES: AngleStep[] = [
  { tag: 'FRONT', label: 'Front View', prompt: 'Hold item facing directly at camera', speechText: 'Show the front packaging, hold still', degree: 0 },
  { tag: 'RIGHT', label: 'Right Side', prompt: 'Rotate slowly to the right side', speechText: 'Rotate slowly to the right', degree: 51 },
  { tag: 'BACK', label: 'Back Packaging', prompt: 'Show the back packaging', speechText: 'Show the back packaging', degree: 103 },
  { tag: 'LEFT', label: 'Left Side', prompt: 'Rotate to show the left side', speechText: 'Rotate to show the left side', degree: 154 },
  { tag: 'TOP', label: 'Top Lid', prompt: 'Tilt up to show the top lid', speechText: 'Tilt up for the top lid', degree: 206 },
  { tag: 'BOTTOM', label: 'Bottom Base', prompt: 'Tilt down to show the base', speechText: 'Tilt down for the bottom base', degree: 257 },
  { tag: 'LABEL_CLOSEUP', label: 'Label Close-up', prompt: 'Bring closer to show nutrition & barcode label, hold still', speechText: 'Bring it closer for label close-up, hold still', degree: 308 },
];

export const Guided360ScanView: React.FC<Props> = ({ product, onComplete, onPreviewTest }) => {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [captures, setCaptures] = useState<Record<string, { dataUrl: string; blurScore: number }>>({});
  const [isScanning, setIsScanning] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState(true);
  
  // Real Frame Analysis Telemetry
  const [liveBlurScore, setLiveBlurScore] = useState<number>(0);
  const [liveBrightness, setLiveBrightness] = useState<number>(120);
  const [cameraFeedback, setCameraFeedback] = useState<string>('Hold item in center outline');
  const [focusStatus, setFocusStatus] = useState<'BLURRY' | 'STEADY' | 'SHARP'>('BLURRY');
  const [cameraError, setCameraError] = useState<string | null>(null);

  // Submission & Pipeline State
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState(0);
  const [enrollmentStats, setEnrollmentStats] = useState<any>(null);
  const [isDone, setIsDone] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const steadyFramesRef = useRef<number>(0);
  const animFrameRef = useRef<number | null>(null);

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
        // Fallback to basic video constraint
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
    const step = REQUIRED_ANGLES[currentStepIdx];
    if (step && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(step.speechText);
      utterance.rate = 1.0;
      utterance.pitch = 1.05;
      window.speechSynthesis.speak(utterance);
    }
  }, [currentStepIdx, voiceEnabled, isScanning, isDone]);

  // 3. Real-time Frame Analysis (Variance of Laplacian + Brightness + Centering)
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
      if (video && video.readyState >= 2 && ctx) {
        ctx.drawImage(video, 0, 0, 160, 120);
        const imgData = ctx.getImageData(0, 0, 160, 120);
        const data = imgData.data;

        // Grayscale conversion
        const gray = new Float32Array(160 * 120);
        let totalBrightness = 0;
        for (let i = 0, j = 0; i < data.length; i += 4, j++) {
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          gray[j] = lum;
          totalBrightness += lum;
        }

        const avgBrightness = Math.round(totalBrightness / (160 * 120));
        setLiveBrightness(avgBrightness);

        // Center ROI (crop 25% to 75% region where user holds item)
        const startX = 35;
        const endX = 125;
        const startY = 25;
        const endY = 95;

        let laplacianSum = 0;
        let count = 0;
        const laplacianVals: number[] = [];

        // Discrete Laplacian: 4 * center - up - down - left - right
        for (let y = startY; y < endY; y += 2) {
          const row = y * 160;
          for (let x = startX; x < endX; x += 2) {
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

        // Frame quality logic
        if (avgBrightness < 35) {
          setCameraFeedback('Too dark — bring item into better lighting');
          setFocusStatus('BLURRY');
          steadyFramesRef.current = 0;
        } else if (blurScore < 25) {
          setCameraFeedback('Move slower — holding still reduces motion blur');
          setFocusStatus('BLURRY');
          steadyFramesRef.current = 0;
        } else if (blurScore < 45) {
          setCameraFeedback('Bring the item closer to the camera');
          setFocusStatus('STEADY');
          steadyFramesRef.current = 0;
        } else {
          // Frame is sharp and item is centered!
          setCameraFeedback('Sharp frame! Hold steady for auto-capture...');
          setFocusStatus('SHARP');
          steadyFramesRef.current += 1;

          // Auto-capture when held steady for ~6 frames (~400-600ms)
          if (autoCaptureEnabled && steadyFramesRef.current >= 6) {
            steadyFramesRef.current = 0;
            handleCaptureRealFrame(blurScore);
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
  }, [isScanning, isDone, autoCaptureEnabled, currentStepIdx]);

  // 4. Capture REAL High-Resolution Frame from Live Video
  const handleCaptureRealFrame = useCallback((blurScoreOverride?: number) => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return;

    const step = REQUIRED_ANGLES[currentStepIdx];
    if (!step) return;

    // Use full natural video dimensions
    const captureCanvas = document.createElement('canvas');
    captureCanvas.width = video.videoWidth || 1280;
    captureCanvas.height = video.videoHeight || 720;
    const ctx = captureCanvas.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
    const realImageDataUrl = captureCanvas.toDataURL('image/jpeg', 0.92);

    const score = blurScoreOverride ?? liveBlurScore;
    setCaptures((prev) => ({
      ...prev,
      [step.tag]: { dataUrl: realImageDataUrl, blurScore: score },
    }));

    // Advance to next angle or finish
    if (currentStepIdx < REQUIRED_ANGLES.length - 1) {
      setCurrentStepIdx((prev) => prev + 1);
    } else {
      setIsScanning(false);
      setIsDone(true);
      if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance('All packaging angles captured. Please review your real thumbnails.'));
      }
    }
  }, [currentStepIdx, liveBlurScore, voiceEnabled]);

  const handleRetake = (tag: string) => {
    const idx = REQUIRED_ANGLES.findIndex((a) => a.tag === tag);
    if (idx !== -1) {
      setCurrentStepIdx(idx);
      setIsScanning(true);
      setIsDone(false);
    }
  };

  const handleDelete = (tag: string) => {
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[tag];
      return copy;
    });
  };

  const capturedCount = Object.keys(captures).length;
  const hasLabelCloseup = Boolean(captures['LABEL_CLOSEUP']);
  const meetsCoverageRule = capturedCount >= 4 && hasLabelCloseup;

  // 5. Submit Real Frames: Uploads to backend, removes background, augments, extracts embeddings
  const handleSaveEmbeddings = async () => {
    if (!meetsCoverageRule) return;

    setIsProcessing(true);
    setProcessingStep(1);

    try {
      const payload = Object.entries(captures).map(([angle_tag, cap]) => ({
        angle_tag,
        image_data_url: cap.dataUrl,
      }));

      setProcessingStep(2); // Background removal & realistic augmentations
      const result = await api.complete360Scan(product.id, payload);
      setEnrollmentStats(result);

      setProcessingStep(3); // Real CLIP ViT-B/32 embedding extraction
      await new Promise((r) => setTimeout(r, 400));
      setProcessingStep(4); // Vector DB ingestion & disk sync

      // Finish and move to preview test
      setTimeout(() => {
        onPreviewTest();
      }, 1000);
    } catch (e: any) {
      alert(`Enrollment failed: ${e.message || 'Unknown error'}`);
      setIsProcessing(false);
    }
  };

  const progressPercent = Math.round((capturedCount / REQUIRED_ANGLES.length) * 100);
  const currentStep = REQUIRED_ANGLES[currentStepIdx] || REQUIRED_ANGLES[0];

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-xl bg-purple-100 dark:bg-purple-950 text-purple-600 dark:text-purple-400 font-bold font-mono text-sm">
              REAL 360°
            </span>
            <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
              Guided 360° Vision Enrollment
            </h1>
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
        </div>
      </div>

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

              {/* Angle Tick Marks Around the Ring */}
              <div className="absolute inset-0 pointer-events-none">
                {REQUIRED_ANGLES.map((ang, idx) => {
                  const isCaptured = Boolean(captures[ang.tag]);
                  const isCurrent = idx === currentStepIdx;
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

              {/* Center Guidance Box with Blur-Score Feedback */}
              <div className={`absolute inset-10 border-2 rounded-3xl flex flex-col items-center justify-center p-4 text-center bg-black/40 backdrop-blur-[2px] transition-all ${
                focusStatus === 'SHARP'
                  ? 'border-emerald-400 ring-2 ring-emerald-400/30'
                  : focusStatus === 'STEADY'
                  ? 'border-amber-400'
                  : 'border-purple-400/70 border-dashed'
              }`}>
                <Camera className={`w-8 h-8 mb-2 ${focusStatus === 'SHARP' ? 'text-emerald-400 animate-pulse' : 'text-purple-300'}`} />
                <span className="text-xs font-bold text-white font-display uppercase tracking-wider">
                  {currentStep.label}
                </span>
                <span className="text-[11px] text-purple-200 mt-1 leading-snug">
                  "{currentStep.prompt}"
                </span>

                {/* Real Laplacian Sharpness Feedback Badge */}
                <div className="mt-3 space-y-1">
                  <div className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2.5 py-0.5 rounded-full ${
                    focusStatus === 'SHARP'
                      ? 'text-emerald-300 bg-emerald-950/80 border border-emerald-500/50'
                      : focusStatus === 'STEADY'
                      ? 'text-amber-300 bg-amber-950/80 border border-amber-500/50'
                      : 'text-purple-300 bg-purple-950/80 border border-purple-500/50'
                  }`}>
                    {focusStatus === 'SHARP' ? (
                      <Check className="w-3 h-3 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="w-3 h-3" />
                    )}
                    <span>{cameraFeedback}</span>
                  </div>
                  <div className="text-[9px] font-mono text-slate-300">
                    Sharpness: <strong className={focusStatus === 'SHARP' ? 'text-emerald-400' : 'text-slate-400'}>{liveBlurScore}</strong> (Min 45) • Brightness: {liveBrightness}
                  </div>
                </div>
              </div>
            </div>

            {/* Top Prompt HUD */}
            <div className="absolute top-4 left-4 right-4 z-20 flex justify-between items-center text-xs">
              <span className="bg-black/80 backdrop-blur-md px-3 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
                Angle {currentStepIdx + 1} of {REQUIRED_ANGLES.length}
              </span>

              <span className={`px-3 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1 backdrop-blur-md ${
                liveBrightness >= 35
                  ? 'bg-emerald-950/80 text-emerald-400 border-emerald-500/30'
                  : 'bg-red-950/80 text-red-400 border-red-500/30 animate-pulse'
              }`}>
                {liveBrightness >= 35 ? '🟢 Lighting OK' : '⚠️ Too Dark'}
              </span>
            </div>
          </div>

          {/* Action Deck: Manual Snap & Skip Buttons */}
          <div className="max-w-md mx-auto flex gap-2">
            <button
              onClick={() => handleCaptureRealFrame()}
              className="flex-1 bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3.5 px-4 rounded-2xl shadow-xl shadow-purple-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all text-sm"
            >
              <Zap className="w-4 h-4 text-amber-300" />
              Snap Real Frame ({currentStep.label})
            </button>

            <button
              onClick={() => {
                setIsScanning(false);
                setIsDone(true);
              }}
              className="px-4 py-3.5 rounded-2xl border border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              Review Gallery ({capturedCount})
            </button>
          </div>
        </div>
      ) : (
        /* Final 360 Review Screen (Real Thumbnails, Coverage Rule Check) */
        <div className="space-y-6">
          <div className="text-center space-y-1">
            <span className="inline-block p-3 bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 rounded-full mb-1">
              <Check className="w-6 h-6" />
            </span>
            <h2 className="text-lg font-bold font-display text-slate-900 dark:text-white">
              360° Real Packaging Review Gallery
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Confirm real webcam captures before background removal and deep visual embedding extraction.
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
                  Coverage Rule: {meetsCoverageRule ? 'Requirements Satisfied' : 'Action Required'}
                </span>
                <p className="text-[11px] opacity-90 mt-0.5">
                  Rule requires at least 4 angles including 1 label close-up. Currently: <strong>{capturedCount} angles</strong>, Label Close-up: <strong>{hasLabelCloseup ? 'Captured ✓' : 'Missing ✗'}</strong>.
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

          {/* Real Thumbnails Gallery */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {REQUIRED_ANGLES.map((ang) => {
              const cap = captures[ang.tag];
              if (!cap) {
                return (
                  <div
                    key={ang.tag}
                    onClick={() => handleRetake(ang.tag)}
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
                  <div className="aspect-square bg-slate-100 dark:bg-slate-900 rounded-xl overflow-hidden relative">
                    <img
                      src={cap.dataUrl}
                      alt={ang.label}
                      className="w-full h-full object-cover"
                    />
                    {/* Retake & Delete Buttons */}
                    <div className="absolute top-1.5 right-1.5 flex gap-1">
                      <button
                        onClick={() => handleRetake(ang.tag)}
                        className="bg-black/70 hover:bg-black text-white p-1.5 rounded-lg transition-colors"
                        title="Retake this angle"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(ang.tag)}
                        className="bg-black/70 hover:bg-red-600 text-white p-1.5 rounded-lg transition-colors"
                        title="Delete this capture"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">{ang.label}</span>
                    <span className="text-emerald-500 text-[10px] font-mono font-bold shrink-0">Sharp: {cap.blurScore}</span>
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
                setCurrentStepIdx(0);
                setIsScanning(true);
                setIsDone(false);
              }}
              className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-200 text-xs font-semibold py-3 px-5 rounded-2xl active:scale-95 transition-all"
            >
              Retake All
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
                ? `Confirm & Enroll Real Embeddings (${capturedCount} Real Angles) →`
                : 'Need at least 4 angles + Label Close-up to Save'}
            </button>
          </div>
        </div>
      )}

      {/* Multi-Step Processing Pipeline Modal */}
      {isProcessing && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-md w-full shadow-2xl space-y-5 text-center">
            <div className="w-14 h-14 rounded-2xl bg-purple-600/20 text-purple-600 dark:text-purple-400 mx-auto flex items-center justify-center">
              <Sparkles className="w-7 h-7 animate-spin" />
            </div>

            <div>
              <h3 className="text-base font-bold font-display text-slate-900 dark:text-white">
                Generating Real AI Embeddings
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Saving real frames & extracting CLIP ViT-B/32 representations for <strong>{product.name}</strong>
              </p>
            </div>

            <div className="space-y-2 text-left text-xs">
              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 1 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 1 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Writing real JPEG frames to image storage</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 2 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 2 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Background removal (GrabCut) & light augmentations</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 3 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 3 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Computing real 512-dim CLIP ViT-B/32 normalized vectors</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 4 ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 text-emerald-700 dark:text-emerald-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 4 ? 'text-emerald-600' : 'text-slate-400'}`} />
                <span>Persisting to PostgreSQL pgvector & vector disk cache</span>
              </div>
            </div>

            {enrollmentStats && (
              <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-xl text-[11px] font-mono text-slate-600 dark:text-slate-300 text-left">
                <div>Saved Real Images: <strong>{enrollmentStats.real_frames_saved}</strong></div>
                <div>Stored Vectors: <strong>{enrollmentStats.total_embeddings_stored}</strong></div>
                <div>Model: <strong>{enrollmentStats.model_name}</strong> ({enrollmentStats.vector_dim}-dim)</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Guided360ScanView;
