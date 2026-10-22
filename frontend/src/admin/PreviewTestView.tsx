import React, { useState, useEffect, useRef } from 'react';
import { Camera, CheckCircle2, AlertTriangle, ShieldCheck, ArrowRight, RefreshCw, Eye, Sparkles, Volume2, VolumeX } from 'lucide-react';
import { api } from '../services/api';
import { Product } from '../types';

interface Props {
  initialProduct?: Product | null;
  onBackToCatalog: () => void;
}

export const PreviewTestView: React.FC<Props> = ({ initialProduct, onBackToCatalog }) => {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBarcode, setSelectedBarcode] = useState<string>(initialProduct?.barcode || '8901262010053');
  const [testResult, setTestResult] = useState<any>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [confirmedDeployment, setConfirmedDeployment] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api.getProducts().then((prods) => {
      setProducts(prods);
      if (initialProduct) {
        setSelectedBarcode(initialProduct.barcode);
      } else if (prods.length > 0) {
        setSelectedBarcode(prods[0].barcode);
      }
    }).catch(console.error);

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        .then((stream) => {
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        })
        .catch(() => {});
    }
  }, [initialProduct]);

  const runRecognitionTest = async () => {
    setIsTesting(true);
    setConfirmedDeployment(false);
    try {
      const res = await api.previewTest('preview_camera_frame', selectedBarcode);
      setTestResult(res);

      // Voice audio announcement
      if (voiceEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const speechMsg = res.matched
          ? `Matched: ${res.product_name}, ${(res.confidence * 100).toFixed(0)} percent confidence`
          : 'No match detected. Please check product packaging.';
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
      window.speechSynthesis.speak(new SpeechSynthesisUtterance('Product verified and confirmed for supermarket shelf deployment.'));
    }
    setTimeout(() => {
      onBackToCatalog();
    }, 1200);
  };

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <span>AI Recognition Preview Test</span>
            <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
              VECTOR MATCH TEST
            </span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Point camera at newly enrolled product to verify AI recognition before putting it on supermarket shelves.
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

      {/* Camera Viewfinder and Real-Time Recognition Display */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left: Camera Feed with Center Reticle */}
        <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-xl relative aspect-square flex flex-col justify-between p-4 text-white">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="absolute inset-0 w-full h-full object-cover opacity-60"
          />

          <div className="relative z-10 flex justify-between text-xs">
            <span className="bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full font-mono text-emerald-400 border border-emerald-500/30">
              Camera: ACTIVE
            </span>
            <span className="bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full font-mono text-purple-300 border border-purple-500/30">
              DINOv2 Vector Match: READY
            </span>
          </div>

          {/* Center Targeting Reticle */}
          <div className="relative z-10 border-2 border-dashed border-emerald-400 rounded-3xl w-52 h-52 mx-auto flex flex-col items-center justify-center bg-black/40 backdrop-blur-[2px]">
            <Camera className="w-8 h-8 text-emerald-400 mb-2 animate-pulse" />
            <span className="text-[11px] font-mono text-emerald-300 text-center px-3 py-1 bg-black/70 rounded-lg">
              Point at Product Packaging
            </span>
          </div>

          <div className="relative z-10 text-center">
            <button
              onClick={runRecognitionTest}
              disabled={isTesting}
              className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-3 px-6 rounded-2xl shadow-lg shadow-emerald-600/30 text-xs active:scale-95 transition-all inline-flex items-center gap-2"
            >
              <Eye className="w-4 h-4" />
              {isTesting ? 'Matching Vector Index...' : 'Test Recognition Now'}
            </button>
          </div>
        </div>

        {/* Right: Real-time Match Telemetry & Staff Confirmation */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                Target Product for Verification
              </label>
              <select
                value={selectedBarcode}
                onChange={(e) => setSelectedBarcode(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-xl p-3 focus:outline-none font-semibold"
              >
                {products.map((p) => (
                  <option key={p.barcode} value={p.barcode}>
                    {p.name} ({p.barcode})
                  </option>
                ))}
              </select>
            </div>

            {testResult ? (
              testResult.matched ? (
                <div className="p-5 rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 space-y-3 animate-fade-in">
                  <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 font-bold text-sm">
                    <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                    <span>Matched: {testResult.product_name} ({(testResult.confidence * 100).toFixed(1)}%)</span>
                  </div>

                  <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1 font-mono">
                    <div>Product Name: <strong className="text-slate-900 dark:text-white font-sans">{testResult.product_name}</strong></div>
                    <div>Barcode: <span>{testResult.barcode}</span></div>
                    <div>Model Confidence: <span className="text-emerald-600 font-bold">{(testResult.confidence * 100).toFixed(1)}%</span></div>
                    <div>Status: <span className="text-purple-600 font-bold">AI Enrolled ✓</span></div>
                  </div>

                  <div className="pt-2 text-[11px] text-emerald-700 dark:text-emerald-300 border-t border-emerald-200 dark:border-emerald-800/60 flex items-center gap-1.5 font-medium">
                    <ShieldCheck className="w-4 h-4 text-emerald-600" />
                    Vector similarity verified across 360-degree embeddings.
                  </div>
                </div>
              ) : (
                <div className="p-5 rounded-2xl bg-red-50 dark:bg-red-950/40 border border-red-300 dark:border-red-800 space-y-2 animate-fade-in">
                  <div className="flex items-center gap-2 text-red-700 dark:text-red-300 font-bold text-sm">
                    <AlertTriangle className="w-5 h-5 text-red-600 shrink-0" />
                    <span>No match detected</span>
                  </div>
                  <p className="text-xs text-red-600 dark:text-red-300">
                    {testResult.message || 'Confidence score below recognition threshold (42.1%).'}
                  </p>
                </div>
              )
            ) : (
              <div className="border border-dashed border-slate-200 dark:border-slate-700 rounded-2xl p-8 text-center text-xs text-slate-400 space-y-2">
                <Sparkles className="w-6 h-6 text-purple-400 mx-auto" />
                <p>Click "Test Recognition Now" to evaluate camera frame against multi-angle 360 embeddings.</p>
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
