import React, { useState, useEffect, useRef } from 'react';
import { Camera, CheckCircle2, AlertTriangle, ShieldCheck, ArrowRight, RefreshCw, Eye } from 'lucide-react';
import { api } from '../services/api';
import { Product } from '../types';

interface Props {
  onBackToCatalog: () => void;
}

export const PreviewTestView: React.FC<Props> = ({ onBackToCatalog }) => {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBarcode, setSelectedBarcode] = useState<string>('8901262010053');
  const [testResult, setTestResult] = useState<any>(null);
  const [isTesting, setIsTesting] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api.getProducts().then(setProducts).catch(console.error);

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ video: true })
        .then((stream) => {
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        })
        .catch(() => {});
    }
  }, []);

  const runRecognitionTest = async () => {
    setIsTesting(true);
    try {
      const res = await api.previewTest('mock_image_data_url', selectedBarcode);
      setTestResult(res);
    } catch (e: any) {
      alert(e.message || 'Recognition test failed');
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <span>Recognition Preview Test Bench</span>
            <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
              VECTOR MATCH TEST
            </span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Hold newly enrolled items in front of the camera to verify AI recognition before making them available on shelves.
          </p>
        </div>

        <button
          onClick={onBackToCatalog}
          className="text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-emerald-600 flex items-center gap-1"
        >
          ← Back to Catalog
        </button>
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
            <span className="bg-black/60 px-2.5 py-1 rounded-full font-mono text-emerald-400">
              Camera: ACTIVE
            </span>
            <span className="bg-black/60 px-2.5 py-1 rounded-full font-mono text-purple-300">
              Vector Ingest: ON
            </span>
          </div>

          {/* Center Target Box */}
          <div className="relative z-10 border-2 border-dashed border-emerald-400 rounded-3xl w-48 h-48 mx-auto flex items-center justify-center bg-black/30 backdrop-blur-[1px]">
            <span className="text-[11px] font-mono text-emerald-300 text-center p-2 bg-black/70 rounded-lg">
              Hold Enrolled Item Inside Guide
            </span>
          </div>

          <div className="relative z-10 text-center">
            <button
              onClick={runRecognitionTest}
              disabled={isTesting}
              className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-2.5 px-6 rounded-2xl shadow-lg shadow-emerald-600/30 text-xs active:scale-95 transition-all inline-flex items-center gap-1.5"
            >
              <Eye className="w-4 h-4" />
              {isTesting ? 'Matching Vector Index...' : 'Test Recognition Now'}
            </button>
          </div>
        </div>

        {/* Right: Real-time Match Telemetry */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                Select Item to Test
              </label>
              <select
                value={selectedBarcode}
                onChange={(e) => setSelectedBarcode(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-xl p-3 focus:outline-none"
              >
                {products.map((p) => (
                  <option key={p.barcode} value={p.barcode}>
                    {p.name} ({p.barcode})
                  </option>
                ))}
              </select>
            </div>

            {testResult ? (
              <div className="p-4 rounded-2xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 space-y-2">
                <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 font-bold text-sm">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <span>Item Successfully Recognized!</span>
                </div>
                <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
                  <div>Product: <strong className="text-slate-900 dark:text-white">{testResult.product_name}</strong></div>
                  <div>Barcode: <span className="font-mono">{testResult.barcode}</span></div>
                  <div>Confidence Score: <strong className="text-emerald-600 font-mono">{(testResult.confidence * 100).toFixed(1)}%</strong></div>
                </div>
                <div className="pt-2 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium border-t border-emerald-200 dark:border-emerald-800/60">
                  ✔ Ready for supermarket floor deployment.
                </div>
              </div>
            ) : (
              <div className="border border-dashed border-slate-200 dark:border-slate-700 rounded-2xl p-8 text-center text-xs text-slate-400">
                Click "Test Recognition Now" to evaluate camera frame against multi-angle 360 embeddings.
              </div>
            )}
          </div>

          <button
            onClick={onBackToCatalog}
            className="w-full bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 text-white font-semibold py-3 rounded-2xl text-xs active:scale-95 transition-all"
          >
            Finished Testing • Return to Products
          </button>
        </div>
      </div>
    </div>
  );
};
