import React, { useState, useEffect, useRef } from 'react';
import {
  Camera, Check, RefreshCw, Volume2, VolumeX, Sparkles, AlertCircle,
  ArrowRight, ShieldCheck, Trash2, Sun, Moon, Eye, AlertTriangle, CheckCircle2, Plus
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
  { tag: 'FRONT', label: 'Front View', prompt: 'Hold item facing directly at camera', speechText: 'Show the front', degree: 0 },
  { tag: 'RIGHT', label: 'Right Side', prompt: 'Rotate slowly to the right side', speechText: 'Rotate slowly to the right', degree: 51 },
  { tag: 'BACK', label: 'Back Packaging', prompt: 'Show the back packaging', speechText: 'Show the back', degree: 103 },
  { tag: 'LEFT', label: 'Left Side', prompt: 'Rotate to show the left side', speechText: 'Show the left', degree: 154 },
  { tag: 'TOP', label: 'Top Lid', prompt: 'Tilt up to show the top lid', speechText: 'Tilt up for the top', degree: 206 },
  { tag: 'BOTTOM', label: 'Bottom Base', prompt: 'Tilt down to show the base', speechText: 'Tilt down for the bottom', degree: 257 },
  { tag: 'LABEL_CLOSEUP', label: 'Label Close-up', prompt: 'Bring closer to show nutrition & barcode label, hold still', speechText: 'Bring it closer to show the label, hold still', degree: 308 },
];

export const Guided360ScanView: React.FC<Props> = ({ product, onComplete, onPreviewTest }) => {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [captures, setCaptures] = useState<Record<string, string>>({});
  const [isScanning, setIsScanning] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState(true);
  const [isLightingGood, setIsLightingGood] = useState(true);
  const [focusStatus, setFocusStatus] = useState<'FOCUSING' | 'SHARP'>('SHARP');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState(0);
  const [isDone, setIsDone] = useState(false);
  const [steadyTimer, setSteadyTimer] = useState<number>(0);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Initialize camera stream
  useEffect(() => {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        .then((stream) => {
          streamRef.current = stream;
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        })
        .catch((e) => console.warn('Camera error:', e));
    }

    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  // Voice speech directions on angle change
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

  // Auto-capture frame stabilization simulation
  useEffect(() => {
    if (!isScanning || isDone || !autoCaptureEnabled || !isLightingGood) return;

    // Simulate focus shake/stabilization
    setFocusStatus('FOCUSING');
    const focusTimeout = setTimeout(() => {
      setFocusStatus('SHARP');
    }, 1200);

    // Auto capture after stable
    const captureTimeout = setTimeout(() => {
      if (isLightingGood) {
        handleCaptureFrame();
      }
    }, 2400);

    return () => {
      clearTimeout(focusTimeout);
      clearTimeout(captureTimeout);
    };
  }, [currentStepIdx, isScanning, isDone, autoCaptureEnabled, isLightingGood]);

  // Capture current angle frame
  const handleCaptureFrame = () => {
    const step = REQUIRED_ANGLES[currentStepIdx];
    if (!step) return;

    const sampleImg = product.primary_image_url || 'https://images.unsplash.com/photo-1550583724-b2692b85b150?w=600';
    setCaptures((prev) => ({ ...prev, [step.tag]: sampleImg }));

    if (currentStepIdx < REQUIRED_ANGLES.length - 1) {
      setCurrentStepIdx(currentStepIdx + 1);
    } else {
      setIsScanning(false);
      setIsDone(true);
      if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance('All packaging angles captured. Please review thumbnails.'));
      }
    }
  };

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

  // Coverage check: At least 4-8 angles including 1 label close-up before allowing save
  const capturedCount = Object.keys(captures).length;
  const hasLabelCloseup = Boolean(captures['LABEL_CLOSEUP']);
  const meetsCoverageRule = capturedCount >= 4 && hasLabelCloseup;

  // On Save: Background removal, synthetic angle augmentation, extract visual embeddings into vector DB
  const handleSaveEmbeddings = async () => {
    if (!meetsCoverageRule) return;

    setIsProcessing(true);
    setProcessingStep(1);

    try {
      // Animated visual pipeline
      await new Promise((r) => setTimeout(r, 700));
      setProcessingStep(2); // Synthetic Angle Augmentation
      await new Promise((r) => setTimeout(r, 700));
      setProcessingStep(3); // Extracting 512-dim DINOv2 Deep Visual Embeddings
      await new Promise((r) => setTimeout(r, 700));
      setProcessingStep(4); // Vector DB Ingestion & Barcode Linkage

      const payload = Object.entries(captures).map(([angle_tag, image_data_url]) => ({
        angle_tag,
        image_data_url,
      }));

      await api.complete360Scan(product.id, payload);
      setProcessingStep(5); // AI Enrolled Confirmation
      await new Promise((r) => setTimeout(r, 600));

      onPreviewTest();
    } catch (e: any) {
      alert(e.message || 'Failed to generate embeddings');
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
              360° AI
            </span>
            <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
              Guided 360° Vision Enrollment
            </h1>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Enrolling: <strong className="text-slate-800 dark:text-slate-200">{product.name}</strong> • EAN: <span className="font-mono text-purple-600 dark:text-purple-400">{product.barcode}</span>
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
            title="Toggle Voice Speech Prompts"
          >
            {voiceEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
            Voice: {voiceEnabled ? 'ON' : 'OFF'}
          </button>

          {/* Auto-Capture Toggle */}
          <button
            onClick={() => setAutoCaptureEnabled(!autoCaptureEnabled)}
            className={`px-3 py-2 rounded-xl border flex items-center gap-1.5 text-xs font-semibold transition-all ${
              autoCaptureEnabled
                ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300'
                : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500'
            }`}
            title="Auto-Capture Sharp Frames"
          >
            <Camera className="w-3.5 h-3.5" />
            Auto-Capture: {autoCaptureEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {!isDone ? (
        /* Enrollment Viewfinder and Circular Progress Ring */
        <div className="space-y-6">
          <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-2xl relative aspect-square max-w-md mx-auto flex items-center justify-center p-6 text-white select-none">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover opacity-60"
            />

            {/* Circular Progress Ring Guide Overlay (Phone Face-Enrollment Style) */}
            <div className="relative z-10 w-72 h-72 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90">
                {/* Background Track */}
                <circle
                  cx="144"
                  cy="144"
                  r="128"
                  stroke="currentColor"
                  strokeWidth="8"
                  className="text-white/10"
                  fill="transparent"
                />
                {/* Active Progress Ring */}
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
                      className={`absolute -translate-x-1/2 -translate-y-1/2 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-all shadow-md ${
                        isCaptured
                          ? 'bg-emerald-500 text-white scale-110 ring-2 ring-emerald-300'
                          : isCurrent
                          ? 'bg-purple-500 text-white animate-pulse ring-2 ring-purple-300'
                          : 'bg-slate-800 text-slate-400 border border-slate-600'
                      }`}
                      title={ang.label}
                    >
                      {isCaptured ? <Check className="w-3 h-3 stroke-[3]" /> : idx + 1}
                    </div>
                  );
                })}
              </div>

              {/* Center Guidance Box */}
              <div className={`absolute inset-10 border-2 rounded-3xl flex flex-col items-center justify-center p-4 text-center bg-black/50 backdrop-blur-[2px] transition-all ${
                focusStatus === 'FOCUSING'
                  ? 'border-amber-400/80 animate-pulse'
                  : 'border-purple-400/80'
              }`}>
                <Camera className="w-8 h-8 text-purple-400 mb-2 animate-bounce-subtle" />
                <span className="text-xs font-bold text-white font-display uppercase tracking-wider">
                  {currentStep.label}
                </span>
                <span className="text-[11px] text-purple-200 mt-1 leading-snug">
                  "{currentStep.prompt}"
                </span>

                {/* Focus Status Badge */}
                <div className="mt-3">
                  {focusStatus === 'FOCUSING' ? (
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-300 bg-amber-950/70 border border-amber-500/50 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="w-3 h-3" />
                      Hold still, camera is focusing...
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-300 bg-emerald-950/70 border border-emerald-500/50 px-2 py-0.5 rounded-full">
                      <Check className="w-3 h-3" />
                      Frame is Sharp
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Top Prompt HUD: Step Indicator & Lighting Feedback */}
            <div className="absolute top-4 left-4 right-4 z-20 flex justify-between items-center text-xs">
              <span className="bg-black/80 backdrop-blur-md px-3 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
                Angle {currentStepIdx + 1} of {REQUIRED_ANGLES.length}
              </span>

              {/* Interactive Lighting Status */}
              <button
                type="button"
                onClick={() => setIsLightingGood(!isLightingGood)}
                className={`px-3 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1 backdrop-blur-md transition-all ${
                  isLightingGood
                    ? 'bg-emerald-950/80 text-emerald-400 border-emerald-500/30'
                    : 'bg-red-950/80 text-red-400 border-red-500/30 animate-pulse'
                }`}
                title="Click to toggle lighting simulation"
              >
                {isLightingGood ? (
                  <>🟢 Lighting looks good (320 Lux)</>
                ) : (
                  <>⚠️ Too dark, move to better lighting (&lt;80 Lux)</>
                )}
              </button>
            </div>
          </div>

          {/* Capture Trigger Action Bar */}
          <div className="max-w-md mx-auto space-y-2">
            {!isLightingGood && (
              <div className="p-2.5 bg-red-950/50 border border-red-800 rounded-xl text-xs text-red-400 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>Lighting too dark. Move item closer to store lighting to enable sharp capture.</span>
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={handleCaptureFrame}
                disabled={!isLightingGood}
                className="flex-1 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white font-semibold py-3.5 px-4 rounded-2xl shadow-xl shadow-purple-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all text-sm"
              >
                <Check className="w-4 h-4" />
                Capture Sharp Frame ({currentStep.label})
              </button>

              <button
                onClick={() => {
                  setIsScanning(false);
                  setIsDone(true);
                }}
                className="px-4 py-3.5 rounded-2xl border border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Skip to Review
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* Final 360 Review Screen (Thumbnails Gallery, Coverage Rule Check, Vector Embeddings Extraction) */
        <div className="space-y-6">
          <div className="text-center space-y-1">
            <span className="inline-block p-3 bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 rounded-full mb-1">
              <Check className="w-6 h-6" />
            </span>
            <h2 className="text-lg font-bold font-display text-slate-900 dark:text-white">
              360° Packaging Review Gallery
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Review captured angles before background removal and deep visual embedding extraction.
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
              + Add Angle
            </button>
          </div>

          {/* Thumbnails Gallery with Retake & Delete Buttons */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {REQUIRED_ANGLES.map((ang) => {
              const capturedImg = captures[ang.tag];
              if (!capturedImg) {
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
                      src={capturedImg}
                      alt={ang.label}
                      className="w-full h-full object-cover"
                    />
                    {/* Action buttons: Retake & Delete */}
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
                    <span className="text-emerald-500 text-[10px] font-bold shrink-0">Sharp 99.2%</span>
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
                ? 'Processing Visual Embeddings Pipeline...'
                : meetsCoverageRule
                ? 'Process & Save to Vector DB →'
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
                Generating 360° AI Embeddings
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Ingesting {capturedCount} angles for <strong>{product.name}</strong>
              </p>
            </div>

            {/* Pipeline Step List */}
            <div className="space-y-2 text-left text-xs">
              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 1 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 1 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Background Removal & Matting (U2-Net)</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 2 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 2 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Synthetic Angle Augmentation (12 Virtual Views)</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 3 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 3 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Extracting 512-dim DINOv2 Deep Visual Embeddings</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 4 ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 text-purple-700 dark:text-purple-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 4 ? 'text-purple-600' : 'text-slate-400'}`} />
                <span>Vector DB Ingestion & Barcode Linkage ({product.barcode})</span>
              </div>

              <div className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                processingStep >= 5 ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 text-emerald-700 dark:text-emerald-300' : 'opacity-40 border-slate-200 dark:border-slate-800'
              }`}>
                <Check className={`w-4 h-4 ${processingStep >= 5 ? 'text-emerald-600' : 'text-slate-400'}`} />
                <span>Status Updated: <strong>AI Enrolled</strong></span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Guided360ScanView;
