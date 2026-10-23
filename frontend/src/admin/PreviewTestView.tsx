import React, { useState, useEffect, useRef } from 'react';
import {
  Camera, CheckCircle2, AlertTriangle, ShieldCheck, ArrowRight, RefreshCw, Eye, Sparkles, Volume2, VolumeX,
  Layers, Award
} from 'lucide-react';
import { api } from '../services/api';
import { Product } from '../types';

interface Props {
  initialProduct?: Product | null;
  onBackToCatalog: () => void;
}

export const PreviewTestView: React.FC<Props> = ({ initialProduct, onBackToCatalog }) => {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBarcode, setSelectedBarcode] = useState<string>(initialProduct?.barcode || '');
  const [testResult, setTestResult] = useState<any>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [confirmedDeployment, setConfirmedDeployment] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let active = true;

    api.getProducts().then((prods) => {
      if (!active) return;
      setProducts(prods);
      if (initialProduct) {
        setSelectedBarcode(initialProduct.barcode);
      } else if (prods.length > 0) {
        setSelectedBarcode(prods[0].barcode);
      }
    }).catch(console.error);

    // Start real camera stream
    async function initCamera() {
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
          const fallback = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          if (!active) {
            fallback.getTracks().forEach((t) => t.stop());
            return;
          }
          streamRef.current = fallback;
          if (videoRef.current) {
            videoRef.current.srcObject = fallback;
            videoRef.current.play().catch(() => {});
          }
        } catch (e: any) {
          setCameraError('Camera access unavailable. Connect a webcam to test recognition.');
        }
      }
    }

    initCamera();

    return () => {
      active = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, [initialProduct]);

  // Run live recognition test by grabbing actual frame from video stream
  const runRecognitionTest = async () => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) {
      alert('Camera feed is not ready. Please wait a second.');
      return;
    }

    setIsTesting(true);
    setConfirmedDeployment(false);

    try {
      // Capture live high-resolution frame from webcam
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Failed to create canvas context');

      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frameDataUrl = canvas.toDataURL('image/jpeg', 0.92);

      // Call real backend preview recognition
      const res = await api.previewTest(frameDataUrl, selectedBarcode);
      setTestResult(res);

      // Voice audio announcement
      if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const speechMsg = res.matched
          ? `Matched: ${res.product_name}, ${(res.confidence * 100).toFixed(0)} percent similarity`
          : (res.top_matches && res.top_matches.length > 0)
          ? `Top match: ${res.top_matches[0].product_name}, ${(res.top_matches[0].similarity * 100).toFixed(0)} percent similarity`
          : 'No visual match detected in vector store.';
        const utterance = new SpeechSynthesisUtterance(speechMsg);
        utterance.rate = 1.0;
        window.speechSynthesis.speak(utterance);
      }
    } catch (e: any) {
      alert(e.message || 'Recognition test failed');
    } finally {
      setIsTesting(false);
    }
  };

  const handleStaffConfirm = () => {
    setConfirmedDeployment(true);
    if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.speak(new SpeechSynthesisUtterance('Product verified and confirmed for deployment.'));
    }
    setTimeout(() => {
      onBackToCatalog();
    }, 1200);
  };

  const topMatches = testResult?.top_matches || [];

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <span>AI Recognition Preview Test</span>
            <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
              REAL VECTOR MATCH
            </span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Hold your product in front of the webcam to verify live CLIP ViT-B/32 vector recognition and view top 3 candidates.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs flex items-center gap-1.5"
            title="Toggle Voice Feedback"
          >
            {voiceEnabled ? <Volume2 className="w-3.5 h-3.5 text-purple-600" /> : <VolumeX className="w-3.5 h-3.5 text-slate-400" />}
            Audio
          </button>

          <button
            onClick={onBackToCatalog}
            className="text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-emerald-600 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
          >
            ← Back to Products
          </button>
        </div>
      </div>

      {cameraError && (
        <div className="p-4 rounded-2xl bg-red-50 dark:bg-red-950/50 border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 text-xs flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{cameraError}</span>
        </div>
      )}

      {/* Camera Viewfinder and Real-Time Recognition Display */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left: Camera Feed with Center Reticle */}
        <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-xl relative aspect-square flex flex-col justify-between p-4 text-white">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="absolute inset-0 w-full h-full object-cover"
          />

          <div className="relative z-10 flex justify-between text-xs">
            <span className="bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full font-mono text-emerald-400 border border-emerald-500/30">
              Webcam: LIVE
            </span>
            <span className="bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
              CLIP ViT-B/32: ACTIVE
            </span>
          </div>

          {/* Center Targeting Reticle */}
          <div className="relative z-10 border-2 border-dashed border-emerald-400 rounded-3xl w-52 h-52 mx-auto flex flex-col items-center justify-center bg-black/40 backdrop-blur-[2px]">
            <Camera className="w-8 h-8 text-emerald-400 mb-2 animate-pulse" />
            <span className="text-[11px] font-mono text-emerald-300 text-center px-3 py-1 bg-black/70 rounded-lg">
              Hold Product in View
            </span>
          </div>

          <div className="relative z-10 text-center">
            <button
              onClick={runRecognitionTest}
              disabled={isTesting}
              className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-3 px-6 rounded-2xl shadow-lg shadow-emerald-600/30 text-xs active:scale-95 transition-all inline-flex items-center gap-2"
            >
              <Eye className="w-4 h-4" />
              {isTesting ? 'Extracting Vector & Matching...' : 'Test Recognition Now'}
            </button>
          </div>
        </div>

        {/* Right: Real-time Match Telemetry & Top-3 Candidates */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                Expected Product for Verification
              </label>
              <select
                value={selectedBarcode}
                onChange={(e) => setSelectedBarcode(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-xl p-3 focus:outline-none font-semibold font-mono"
              >
                {products.map((p) => (
                  <option key={p.barcode} value={p.barcode}>
                    {p.name} ({p.barcode})
                  </option>
                ))}
              </select>
            </div>

            {testResult ? (
              <div className="space-y-3">
                {/* Primary Match Status Banner */}
                {testResult.matched ? (
                  <div className="p-4 rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 space-y-2 animate-fade-in">
                    <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 font-bold text-sm">
                      <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                      <span>VERIFIED MATCH ({(testResult.confidence * 100).toFixed(1)}%)</span>
                    </div>
                    <div className="text-xs text-slate-600 dark:text-slate-300">
                      Product: <strong>{testResult.product_name}</strong>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 rounded-2xl bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 space-y-1 animate-fade-in">
                    <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300 font-bold text-xs">
                      <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                      <span>{testResult.message || 'No confident match detected'}</span>
                    </div>
                  </div>
                )}

                {/* Top 3 Matches Proof of Enrollment */}
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                    <Award className="w-3.5 h-3.5 text-purple-500" />
                    Top 3 Visual Matches (Cosine Similarity)
                  </h3>

                  {topMatches.length > 0 ? (
                    <div className="space-y-2">
                      {topMatches.map((m: any, idx: number) => {
                        const pct = Math.round(m.similarity * 100);
                        const isTop = idx === 0;
                        const isExpected = m.barcode === selectedBarcode;

                        return (
                          <div
                            key={idx}
                            className={`p-3 rounded-xl border text-xs space-y-1.5 ${
                              isExpected
                                ? 'bg-purple-50/60 dark:bg-purple-950/30 border-purple-300 dark:border-purple-800'
                                : 'bg-slate-50 dark:bg-slate-900 border-slate-200 dark:border-slate-800'
                            }`}
                          >
                            <div className="flex justify-between items-center">
                              <span className="font-semibold text-slate-900 dark:text-white flex items-center gap-1.5">
                                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-bold">
                                  #{idx + 1}
                                </span>
                                {m.product_name}
                              </span>
                              <span className="font-mono font-bold text-purple-600 dark:text-purple-400">
                                {pct}%
                              </span>
                            </div>

                            <div className="w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${
                                  pct >= 85 ? 'bg-emerald-500' : pct >= 65 ? 'bg-amber-500' : 'bg-blue-500'
                                }`}
                                style={{ width: `${Math.min(100, pct)}%` }}
                              />
                            </div>

                            <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                              <span>EAN: {m.barcode}</span>
                              <span>Angle: {m.matched_angle}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic p-3 text-center border border-dashed rounded-xl">
                      No vector matches returned yet.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="border border-dashed border-slate-200 dark:border-slate-700 rounded-2xl p-8 text-center text-xs text-slate-400 space-y-2">
                <Sparkles className="w-6 h-6 text-purple-400 mx-auto" />
                <p>Click "Test Recognition Now" to evaluate webcam frame against multi-angle 360 embeddings.</p>
              </div>
            )}
          </div>

          <div className="space-y-2 pt-4">
            {testResult?.matched && (
              <button
                onClick={handleStaffConfirm}
                disabled={confirmedDeployment}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-3.5 rounded-2xl text-xs active:scale-95 transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/30"
              >
                <CheckCircle2 className="w-4 h-4" />
                {confirmedDeployment
                  ? 'Confirmed! Returning to Products...'
                  : 'Staff Confirms Match • Deploy to Shelves →'}
              </button>
            )}

            <button
              onClick={onBackToCatalog}
              className="w-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 font-semibold py-3 rounded-2xl text-xs active:scale-95 transition-all"
            >
              Return to Products Catalog
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PreviewTestView;
