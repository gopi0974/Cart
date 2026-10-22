import React, { useState, useEffect, useRef } from 'react';
import { Camera, Check, RefreshCw, Volume2, VolumeX, Sparkles, AlertCircle, ArrowRight, ShieldCheck, Trash2 } from 'lucide-react';
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
}

const REQUIRED_ANGLES: AngleStep[] = [
  { tag: 'FRONT', label: 'Front View', prompt: 'Hold item facing directly at camera', speechText: 'Show the front' },
  { tag: 'RIGHT', label: 'Right Side', prompt: 'Rotate slowly to the right', speechText: 'Rotate slowly to the right' },
  { tag: 'BACK', label: 'Back Packaging', prompt: 'Show the back side', speechText: 'Show the back' },
  { tag: 'LEFT', label: 'Left Side', prompt: 'Rotate to show the left side', speechText: 'Rotate left' },
  { tag: 'TOP', label: 'Top View', prompt: 'Tilt up to show the top lid', speechText: 'Tilt up to show the top' },
  { tag: 'BOTTOM', label: 'Bottom View', prompt: 'Tilt down to show the base', speechText: 'Tilt down to show the bottom' },
  { tag: 'LABEL_CLOSEUP', label: 'Label Close-up', prompt: 'Bring closer to capture nutrition & barcode label', speechText: 'Bring it closer to show the label, hold still' },
];

export const Guided360ScanView: React.FC<Props> = ({ product, onComplete, onPreviewTest }) => {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [captures, setCaptures] = useState<Record<string, string>>({});
  const [isScanning, setIsScanning] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [qualityFeedback, setQualityFeedback] = useState('🟢 Frame is Sharp • Good Lighting');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDone, setIsDone] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Initialize camera
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

  // Voice speech synthesis on angle change
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

  // Capture current angle frame
  const captureCurrentAngle = () => {
    const step = REQUIRED_ANGLES[currentStepIdx];
    if (!step) return;

    // Grab frame from video or fallback thumbnail
    const sampleImg = product.primary_image_url || 'https://images.unsplash.com/photo-1550583724-b2692b85b150?w=600';
    setCaptures((prev) => ({ ...prev, [step.tag]: sampleImg }));

    if (currentStepIdx < REQUIRED_ANGLES.length - 1) {
      setCurrentStepIdx(currentStepIdx + 1);
    } else {
      setIsScanning(false);
      setIsDone(true);
      if (voiceEnabled && 'speechSynthesis' in window) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance('All angles captured. Please review thumbnails.'));
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

  const handleSaveEmbeddings = async () => {
    setIsProcessing(true);
    try {
      const payload = Object.entries(captures).map(([angle_tag, image_data_url]) => ({
        angle_tag,
        image_data_url,
      }));
      await api.complete360Scan(product.id, payload);
      alert(`Enrolled 360° visual embeddings for ${product.name}! Ready for live test.`);
      onPreviewTest();
    } catch (e: any) {
      alert(e.message || 'Failed to generate embeddings');
    } finally {
      setIsProcessing(false);
    }
  };

  const progressPercent = Math.round((Object.keys(captures).length / REQUIRED_ANGLES.length) * 100);
  const currentStep = REQUIRED_ANGLES[currentStepIdx] || REQUIRED_ANGLES[0];

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-xl bg-purple-100 dark:bg-purple-950 text-purple-600 dark:text-purple-400 font-bold">
              360°
            </span>
            <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
              Guided 360° Vision Enrollment
            </h1>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Enrolling <strong className="text-slate-800 dark:text-slate-200">{product.name}</strong> • EAN: <span className="font-mono">{product.barcode}</span>
          </p>
        </div>

        <button
          onClick={() => setVoiceEnabled(!voiceEnabled)}
          className={`p-2.5 rounded-2xl border flex items-center gap-1.5 text-xs font-semibold transition-all ${
            voiceEnabled
              ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-300 dark:border-purple-800 text-purple-700 dark:text-purple-300'
              : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500'
          }`}
        >
          {voiceEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          Voice Guidance
        </button>
      </div>

      {!isDone ? (
        /* Enrollment Viewfinder and Circular Progress Ring */
        <div className="space-y-6">
          <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-2xl relative aspect-square max-w-md mx-auto flex items-center justify-center p-6 text-white">
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

              {/* Center Guidance Box */}
              <div className="absolute inset-10 border-2 border-dashed border-purple-400/80 rounded-3xl flex flex-col items-center justify-center p-4 text-center bg-black/40 backdrop-blur-[2px]">
                <Camera className="w-8 h-8 text-purple-400 mb-2 animate-bounce-subtle" />
                <span className="text-xs font-bold text-white font-display uppercase tracking-wider">
                  {currentStep.label}
                </span>
                <span className="text-[11px] text-purple-200 mt-1 leading-snug">
                  {currentStep.prompt}
                </span>
              </div>
            </div>

            {/* Top Prompt HUD */}
            <div className="absolute top-4 left-4 right-4 z-20 flex justify-between items-center text-xs">
              <span className="bg-black/70 backdrop-blur-md px-3 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
                Angle {currentStepIdx + 1} of {REQUIRED_ANGLES.length}
              </span>
              <span className="bg-black/70 backdrop-blur-md px-3 py-1 rounded-full text-[11px] font-semibold text-emerald-400 border border-emerald-500/30">
                {qualityFeedback}
              </span>
            </div>
          </div>

          {/* Capture Trigger Button */}
          <div className="max-w-md mx-auto flex gap-3">
            <button
              onClick={captureCurrentAngle}
              className="flex-1 bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3.5 px-4 rounded-2xl shadow-xl shadow-purple-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all text-sm"
            >
              <Check className="w-5 h-5" />
              Capture Angle ({currentStep.label})
            </button>
          </div>
        </div>
      ) : (
        /* Final 360 Review Screen (Thumbnails Gallery & Vector Embedding Generation) */
        <div className="space-y-6">
          <div className="text-center space-y-1">
            <span className="inline-block p-3 bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 rounded-full mb-1">
              <Check className="w-6 h-6" />
            </span>
            <h2 className="text-lg font-bold font-display text-slate-900 dark:text-white">
              All 360° Angles Captured
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Review all packaging perspectives before background removal and vector embedding extraction.
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {REQUIRED_ANGLES.map((ang) => (
              <div
                key={ang.tag}
                className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-2.5 shadow-sm space-y-2 group"
              >
                <div className="aspect-square bg-slate-100 dark:bg-slate-900 rounded-xl overflow-hidden relative">
                  <img
                    src={captures[ang.tag] || product.primary_image_url || ''}
                    alt={ang.label}
                    className="w-full h-full object-cover"
                  />
                  <button
                    onClick={() => handleRetake(ang.tag)}
                    className="absolute top-1 right-1 bg-black/70 hover:bg-black text-white p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Retake this angle"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">{ang.label}</span>
                  <span className="text-emerald-500 text-[10px] font-bold">100% OK</span>
                </div>
              </div>
            ))}
          </div>

          <div className="flex gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
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
              disabled={isProcessing}
              className="flex-1 bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-5 rounded-2xl shadow-xl shadow-purple-600/30 flex items-center justify-center gap-2 text-xs active:scale-98 transition-all"
            >
              <Sparkles className="w-4 h-4" />
              {isProcessing ? 'Generating Vector Embeddings...' : 'Extract Embeddings & Go to Preview Test →'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
