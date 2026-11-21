import React, { useState, useEffect, useRef } from 'react';
import {
  FlaskConical, Upload, Camera, RefreshCw, Trash2, CheckCircle2,
  AlertTriangle, XCircle, BarChart3, HelpCircle, Layers, Sliders, ChevronDown, Check, ArrowRight
} from 'lucide-react';
import { api } from '../services/api';
import { Product } from '../types';
import { CameraHelper } from '../services/cameraHelper';

export const RecognitionLabView: React.FC = () => {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBarcode, setSelectedBarcode] = useState<string>('');
  const [angleLabel, setAngleLabel] = useState<string>('OVERHEAD');
  const [loading, setLoading] = useState<boolean>(false);
  const [evaluating, setEvaluating] = useState<boolean>(false);
  const [results, setResults] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'SENSITIVITY' | 'CONFUSION' | 'PHOTOS'>('OVERVIEW');
  const [selectedMarginFilter, setSelectedMarginFilter] = useState<number>(0.10);
  const [feedbackMsg, setFeedbackMsg] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Webcam capture state
  const [webcamActive, setWebcamActive] = useState<boolean>(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    fetchProducts();
    fetchResults();
    return () => {
      CameraHelper.stopAllStreams();
    };
  }, []);

  const fetchProducts = async () => {
    try {
      const prods = await api.getProducts();
      setProducts(prods);
      if (prods.length > 0 && !selectedBarcode) {
        setSelectedBarcode(prods[0].barcode);
      }
    } catch (e: any) {
      console.error('Failed to load products:', e);
    }
  };

  const fetchResults = async () => {
    setLoading(true);
    try {
      const data = await api.getRecognitionLabResults();
      setResults(data);
    } catch (e: any) {
      console.error('Failed to fetch Recognition Lab results:', e);
    } finally {
      setLoading(false);
    }
  };

  // Start webcam
  const handleStartWebcam = async () => {
    try {
      setWebcamActive(true);
      const stream = await CameraHelper.openCamera();
      if (videoRef.current) {
        CameraHelper.attachStreamToVideo(videoRef.current, stream);
      }
    } catch (e: any) {
      setFeedbackMsg({ text: `Camera access failed: ${e.message}`, type: 'error' });
      setWebcamActive(false);
    }
  };

  const handleStopWebcam = () => {
    CameraHelper.stopAllStreams();
    setWebcamActive(false);
  };

  // Capture frame from webcam
  const handleCaptureWebcam = async () => {
    if (!videoRef.current || !selectedBarcode) return;
    setEvaluating(true);
    try {
      const video = videoRef.current;
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Could not get canvas context');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);

      const resp = await api.recordRecognitionLabSample({
        expected_barcode: selectedBarcode,
        image_data_url: dataUrl,
        angle_label: angleLabel,
        source: 'webcam',
        filename: `webcam_${angleLabel.toLowerCase()}_${Date.now()}.jpg`
      });

      setFeedbackMsg({ text: resp.message || 'Sample recorded successfully!', type: 'success' });
      fetchResults();
    } catch (e: any) {
      setFeedbackMsg({ text: `Evaluation failed: ${e.message}`, type: 'error' });
    } finally {
      setEvaluating(false);
    }
  };

  // Upload local photos
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !selectedBarcode) return;

    setEvaluating(true);
    let successCount = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const reader = new FileReader();
        await new Promise<void>((resolve, reject) => {
          reader.onload = async () => {
            try {
              const dataUrl = reader.result as string;
              await api.recordRecognitionLabSample({
                expected_barcode: selectedBarcode,
                image_data_url: dataUrl,
                angle_label: angleLabel,
                source: 'upload',
                filename: file.name
              });
              successCount++;
              resolve();
            } catch (err) {
              reject(err);
            }
          };
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
      }

      setFeedbackMsg({
        text: `Successfully processed ${successCount} photo${successCount === 1 ? '' : 's'} for ${selectedProduct?.name || selectedBarcode}.`,
        type: 'success'
      });
      fetchResults();
    } catch (e: any) {
      setFeedbackMsg({ text: `Upload evaluation error: ${e.message}`, type: 'error' });
    } finally {
      setEvaluating(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDeleteSample = async (id: string) => {
    try {
      await api.deleteRecognitionLabSample(id);
      fetchResults();
    } catch (e: any) {
      setFeedbackMsg({ text: `Delete failed: ${e.message}`, type: 'error' });
    }
  };

  const handleResetAll = async () => {
    if (!window.confirm('Reset Recognition Lab? All recorded test samples will be cleared.')) return;
    try {
      const resp = await api.resetRecognitionLab();
      setFeedbackMsg({ text: resp.message, type: 'info' });
      fetchResults();
    } catch (e: any) {
      setFeedbackMsg({ text: `Reset failed: ${e.message}`, type: 'error' });
    }
  };

  const selectedProduct = products.find((p) => p.barcode === selectedBarcode);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white dark:bg-[#131B2E] p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-cyan-600/10 border border-cyan-500/20 flex items-center justify-center text-cyan-600 dark:text-cyan-400">
            <FlaskConical className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
                Recognition Lab
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-cyan-100 dark:bg-cyan-950/60 text-cyan-700 dark:text-cyan-300 border border-cyan-300 dark:border-cyan-800">
                Phase 0 • Empirical Measurement
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Evaluate real test photos through the cart camera ONNX CLIP pipeline to measure true accuracy, margins, and confusion rates.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchResults}
            disabled={loading || evaluating}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition-colors"
            title="Refresh Evaluation Analysis"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          {results && results.total_samples > 0 && (
            <button
              onClick={handleResetAll}
              disabled={loading || evaluating}
              className="p-2.5 rounded-xl border border-red-200 dark:border-red-900/40 hover:bg-red-50 dark:hover:bg-red-950/40 text-red-600 dark:text-red-400 text-xs font-semibold flex items-center gap-1.5 transition-colors"
              title="Reset All Test Samples"
            >
              <Trash2 className="w-4 h-4" />
              <span className="hidden sm:inline">Reset Lab</span>
            </button>
          )}
        </div>
      </div>

      {/* Strict Empirical Data Origin Banner */}
      <div className="p-3.5 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900/60 rounded-2xl text-xs text-blue-900 dark:text-blue-200 flex items-start gap-2.5">
        <HelpCircle className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          <strong className="font-semibold">Empirical Guarantee:</strong> {results?.data_origin_statement || 'All metrics, margins, and threshold sensitivity curves reflect strictly real captured or uploaded photos evaluated through the ONNX ViT-B/32 pipeline. No synthetic data is used.'}
        </div>
      </div>

      {/* Notification Feedback Banner */}
      {feedbackMsg && (
        <div
          className={`p-3.5 rounded-2xl border text-xs font-medium flex items-center justify-between gap-2 ${
            feedbackMsg.type === 'success'
              ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40'
              : feedbackMsg.type === 'error'
              ? 'bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800/40'
              : 'bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-300 border-blue-200 dark:border-blue-800/40'
          }`}
        >
          <span>{feedbackMsg.text}</span>
          <button onClick={() => setFeedbackMsg(null)} className="font-bold opacity-60 hover:opacity-100 text-xs">
            Dismiss
          </button>
        </div>
      )}

      {/* Ingestion & Photo Input Controls Card */}
      <div className="bg-white dark:bg-[#131B2E] p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Sliders className="w-4 h-4 text-cyan-600" />
            1. Select Test Product & Angle
          </h2>
          <span className="text-xs text-slate-400">Step 1 of 2</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Product Picker */}
          <div className="sm:col-span-2">
            <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Expected Product (Ground Truth Label)
            </label>
            <select
              value={selectedBarcode}
              onChange={(e) => setSelectedBarcode(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 text-xs font-medium focus:ring-2 focus:ring-cyan-500 focus:outline-none"
            >
              {products.map((p) => (
                <option key={p.barcode} value={p.barcode}>
                  {p.name} ({p.barcode}) • ₹{p.price}
                </option>
              ))}
            </select>
          </div>

          {/* Angle / Perspective Tag */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Perspective Angle
            </label>
            <select
              value={angleLabel}
              onChange={(e) => setAngleLabel(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-3 py-2 text-xs font-medium focus:ring-2 focus:ring-cyan-500 focus:outline-none"
            >
              <option value="OVERHEAD">Overhead (Standard Cart View)</option>
              <option value="FRONT">Front Face Up</option>
              <option value="SIDE">Side Angle</option>
              <option value="TILTED">Tilted / Diagonal 45°</option>
              <option value="CORNER">Basket Corner</option>
              <option value="LABEL_CLOSEUP">Label Facing Camera</option>
            </select>
          </div>
        </div>

        {/* Input Methods: File Upload vs Live Webcam */}
        <div className="pt-2 border-t border-slate-100 dark:border-slate-800 grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Method A: Upload Photos */}
          <div className="p-4 rounded-2xl border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-cyan-500 transition-colors flex flex-col items-center justify-center text-center space-y-2">
            <Upload className="w-8 h-8 text-cyan-600" />
            <div>
              <p className="text-xs font-bold text-slate-900 dark:text-white">
                Upload Real Test Photos
              </p>
              <p className="text-[11px] text-slate-500">
                Select one or multiple photos of {selectedProduct?.name || 'the product'}.
              </p>
            </div>
            <input
              type="file"
              ref={fileInputRef}
              multiple
              accept="image/*"
              onChange={handleFileUpload}
              className="hidden"
              id="recognition-lab-file-input"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={evaluating}
              className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 text-white text-xs font-semibold shadow-md active:scale-95 transition-all"
            >
              {evaluating ? 'Processing Photos...' : 'Choose Photo Files'}
            </button>
          </div>

          {/* Method B: Webcam Capture */}
          <div className="p-4 rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-purple-600" />
                <span className="text-xs font-bold text-slate-900 dark:text-white">
                  Live Webcam Crop Capture
                </span>
              </div>
              {!webcamActive ? (
                <button
                  onClick={handleStartWebcam}
                  className="px-3 py-1.5 rounded-xl border border-purple-300 dark:border-purple-800 text-purple-700 dark:text-purple-300 text-xs font-semibold hover:bg-purple-50 dark:hover:bg-purple-950/40"
                >
                  Start Camera
                </button>
              ) : (
                <button
                  onClick={handleStopWebcam}
                  className="px-3 py-1.5 rounded-xl border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 text-xs font-semibold"
                >
                  Stop Camera
                </button>
              )}
            </div>

            {webcamActive ? (
              <div className="space-y-2">
                <div className="w-full h-44 bg-black rounded-xl overflow-hidden relative">
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute inset-0 border-2 border-cyan-400/50 rounded-xl pointer-events-none" />
                </div>
                <button
                  onClick={handleCaptureWebcam}
                  disabled={evaluating}
                  className="w-full py-2.5 rounded-xl bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-xs font-bold shadow-md active:scale-95 transition-all"
                >
                  {evaluating ? 'Evaluating Crop...' : `Capture Photo as '${selectedProduct?.name || selectedBarcode}'`}
                </button>
              </div>
            ) : (
              <div className="h-32 flex flex-col items-center justify-center text-center text-xs text-slate-400">
                <p>Webcam preview inactive.</p>
                <p className="text-[11px] mt-0.5">Click 'Start Camera' to capture live crops.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* KPI Overview Metrics */}
      {results && results.total_samples > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm">
            <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Total Test Photos</span>
            <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white mt-1">
              {results.total_samples}
            </div>
            <span className="text-[11px] text-slate-500 mt-0.5 block">Evaluated through ONNX</span>
          </div>

          <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm">
            <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Catalog Items Tested</span>
            <div className="text-2xl font-bold font-mono text-cyan-600 dark:text-cyan-400 mt-1">
              {results.unique_products_count}
            </div>
            <span className="text-[11px] text-slate-500 mt-0.5 block">Unique products</span>
          </div>

          <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm">
            <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Top-1 Accuracy</span>
            <div className="text-2xl font-bold font-mono text-emerald-600 dark:text-emerald-400 mt-1">
              {results.overall_top1_accuracy}%
            </div>
            <span className="text-[11px] text-emerald-600 dark:text-emerald-400 mt-0.5 block">Rank #1 correct</span>
          </div>

          <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm">
            <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Avg Margin</span>
            <div className="text-2xl font-bold font-mono text-purple-600 dark:text-purple-400 mt-1">
              {results.samples.length > 0
                ? (results.samples.reduce((acc: number, s: any) => acc + s.margin, 0) / results.samples.length).toFixed(3)
                : '0.000'}
            </div>
            <span className="text-[11px] text-purple-600 dark:text-purple-400 mt-0.5 block">Score - Best Other</span>
          </div>
        </div>
      )}

      {/* Tabs Navigation for Analysis Reports */}
      {results && results.total_samples > 0 && (
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl shadow-sm overflow-hidden">
          <div className="flex border-b border-slate-200 dark:border-slate-800 px-6 pt-4 gap-6 text-xs font-bold overflow-x-auto">
            <button
              onClick={() => setActiveTab('OVERVIEW')}
              className={`pb-3 border-b-2 transition-all flex items-center gap-2 ${
                activeTab === 'OVERVIEW'
                  ? 'border-cyan-600 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              Per-Product Accuracy ({results.unique_products_count})
            </button>

            <button
              onClick={() => setActiveTab('SENSITIVITY')}
              className={`pb-3 border-b-2 transition-all flex items-center gap-2 ${
                activeTab === 'SENSITIVITY'
                  ? 'border-cyan-600 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <Sliders className="w-4 h-4" />
              Threshold & Margin Matrix (0.50 – 0.90)
            </button>

            <button
              onClick={() => setActiveTab('CONFUSION')}
              className={`pb-3 border-b-2 transition-all flex items-center gap-2 ${
                activeTab === 'CONFUSION'
                  ? 'border-cyan-600 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <Layers className="w-4 h-4" />
              Empirical Confusion Table
            </button>

            <button
              onClick={() => setActiveTab('PHOTOS')}
              className={`pb-3 border-b-2 transition-all flex items-center gap-2 ${
                activeTab === 'PHOTOS'
                  ? 'border-cyan-600 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <Camera className="w-4 h-4" />
              All Evaluated Photos ({results.total_samples})
            </button>
          </div>

          <div className="p-6">
            {/* Tab 1: Per-Product Accuracy Summary */}
            {activeTab === 'OVERVIEW' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Class-level top-1 identification accuracy and average margins.</span>
                  <span className="font-mono text-[11px]">Strict One-to-One Match</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-100 dark:border-slate-800 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
                        <th className="py-2.5 px-3">Product Name</th>
                        <th className="py-2.5 px-3">Barcode</th>
                        <th className="py-2.5 px-3 text-right">Samples</th>
                        <th className="py-2.5 px-3 text-right">Top-1 Correct</th>
                        <th className="py-2.5 px-3 text-right">Accuracy</th>
                        <th className="py-2.5 px-3 text-right">Avg Score Scanned</th>
                        <th className="py-2.5 px-3 text-right">Avg Margin</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-[11px]">
                      {results.per_product_accuracy.map((p: any) => (
                        <tr key={p.barcode} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                          <td className="py-2.5 px-3 font-sans font-bold text-slate-900 dark:text-white">
                            {p.product_name}
                          </td>
                          <td className="py-2.5 px-3 text-slate-500">{p.barcode}</td>
                          <td className="py-2.5 px-3 text-right text-slate-700 dark:text-slate-300">{p.sample_count}</td>
                          <td className="py-2.5 px-3 text-right text-emerald-600 font-bold">{p.correct_top1_count}</td>
                          <td className="py-2.5 px-3 text-right font-bold">
                            <span
                              className={`px-2 py-0.5 rounded-md text-[10px] ${
                                p.accuracy_percent >= 90
                                  ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                                  : p.accuracy_percent >= 70
                                  ? 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300'
                                  : 'bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300'
                              }`}
                            >
                              {p.accuracy_percent.toFixed(1)}%
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right text-slate-700 dark:text-slate-300">
                            {p.avg_score_scanned.toFixed(3)}
                          </td>
                          <td className="py-2.5 px-3 text-right font-bold text-purple-600 dark:text-purple-400">
                            +{p.avg_margin.toFixed(3)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Tab 2: Threshold & Margin Matrix (0.50 to 0.90, Margins 0.05 to 0.15) */}
            {activeTab === 'SENSITIVITY' && (
              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                  <div>
                    <span className="font-semibold text-slate-800 dark:text-slate-200">
                      False Accepts (FA) and False Rejects (FR) vs. Thresholds & Margins
                    </span>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      Shows error trade-offs when requiring Score ≥ Threshold AND Margin ≥ Margin Threshold.
                    </p>
                  </div>

                  {/* Margin Filter Selector */}
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-slate-400 font-semibold uppercase">Filter Margin:</span>
                    <div className="flex gap-1">
                      {[0.05, 0.08, 0.10, 0.12, 0.15].map((m) => (
                        <button
                          key={m}
                          onClick={() => setSelectedMarginFilter(m)}
                          className={`px-2 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                            selectedMarginFilter === m
                              ? 'bg-cyan-600 text-white'
                              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                          }`}
                        >
                          +{m.toFixed(2)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-100 dark:border-slate-800 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
                        <th className="py-2.5 px-3">Threshold</th>
                        <th className="py-2.5 px-3">Min Margin</th>
                        <th className="py-2.5 px-3 text-right">True Accepts</th>
                        <th className="py-2.5 px-3 text-right">False Rejects (FR)</th>
                        <th className="py-2.5 px-3 text-right">FR Rate</th>
                        <th className="py-2.5 px-3 text-right">False Accepts (FA)</th>
                        <th className="py-2.5 px-3 text-right">FA Rate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-[11px]">
                      {results.sensitivity_matrix
                        .filter((s: any) => s.margin === selectedMarginFilter)
                        .map((row: any) => (
                          <tr key={`${row.threshold}_${row.margin}`} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                            <td className="py-2.5 px-3 font-bold text-slate-900 dark:text-white">
                              {row.threshold.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-3 font-bold text-purple-600 dark:text-purple-400">
                              +{row.margin.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-3 text-right text-emerald-600 font-bold">{row.true_accepts}</td>
                            <td className="py-2.5 px-3 text-right text-amber-600">{row.false_rejects}</td>
                            <td className="py-2.5 px-3 text-right">
                              <span className={row.false_reject_rate > 20 ? 'text-amber-500 font-bold' : 'text-slate-500'}>
                                {row.false_reject_rate.toFixed(1)}%
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-right text-red-600 font-bold">{row.false_accepts}</td>
                            <td className="py-2.5 px-3 text-right">
                              <span className={row.false_accept_rate > 0 ? 'text-red-500 font-bold' : 'text-emerald-500'}>
                                {row.false_accept_rate.toFixed(1)}%
                              </span>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Tab 3: Empirical Confusion Table */}
            {activeTab === 'CONFUSION' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Rows = Expected True Product. Columns = Predicted Top-1 Match.</span>
                  <span className="text-[11px] font-mono text-emerald-600">Green diagonal = Correct</span>
                </div>

                {results.confusion_matrix.labels.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400">No predictions recorded yet.</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-center text-xs border border-slate-200 dark:border-slate-800">
                      <thead>
                        <tr className="bg-slate-50 dark:bg-slate-900 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
                          <th className="py-2 px-3 text-left border-r border-slate-200 dark:border-slate-800">Expected \ Predicted</th>
                          {results.confusion_matrix.labels.map((lbl: string) => (
                            <th key={lbl} className="py-2 px-3 truncate max-w-[120px]" title={lbl}>
                              {lbl}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-[11px]">
                        {results.confusion_matrix.matrix.map((row: any) => (
                          <tr key={row.expected} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                            <td className="py-2 px-3 font-sans font-bold text-left text-slate-900 dark:text-white border-r border-slate-200 dark:border-slate-800 truncate max-w-[150px]" title={row.expected}>
                              {row.expected}
                            </td>
                            {row.predictions.map((count: number, cIdx: number) => {
                              const predName = results.confusion_matrix.labels[cIdx];
                              const isDiagonal = predName === row.expected;
                              return (
                                <td
                                  key={cIdx}
                                  className={`py-2 px-3 font-bold ${
                                    isDiagonal && count > 0
                                      ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400'
                                      : !isDiagonal && count > 0
                                      ? 'bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400'
                                      : 'text-slate-300 dark:text-slate-700'
                                  }`}
                                >
                                  {count}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Tab 4: All Evaluated Photos Detailed List */}
            {activeTab === 'PHOTOS' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Every individual photo evaluated through the cart camera ONNX INT8 ViT-B/32 pipeline.</span>
                  <span className="font-mono text-[11px]">{results.samples.length} total entries</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-100 dark:border-slate-800 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
                        <th className="py-2.5 px-2">Crop</th>
                        <th className="py-2.5 px-3">Expected Product</th>
                        <th className="py-2.5 px-2">Angle</th>
                        <th className="py-2.5 px-3">Top-1 Match</th>
                        <th className="py-2.5 px-2 text-right">Top-1 Score</th>
                        <th className="py-2.5 px-3">Top-2 Match</th>
                        <th className="py-2.5 px-2 text-right">Top-2 Score</th>
                        <th className="py-2.5 px-2 text-right">Score Scanned</th>
                        <th className="py-2.5 px-3">Best Other</th>
                        <th className="py-2.5 px-2 text-right">Margin</th>
                        <th className="py-2.5 px-2 text-center">Result</th>
                        <th className="py-2.5 px-2 text-center">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-[11px]">
                      {results.samples.map((s: any) => (
                        <tr key={s.id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                          {/* Thumbnail */}
                          <td className="py-2 px-2">
                            <div className="w-9 h-9 rounded-lg overflow-hidden bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                              {s.thumbnail_url ? (
                                <img src={s.thumbnail_url} alt="crop" className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-slate-400 text-[9px]">N/A</div>
                              )}
                            </div>
                          </td>

                          {/* Expected Product */}
                          <td className="py-2 px-3 font-sans">
                            <div className="font-bold text-slate-900 dark:text-white truncate max-w-[130px]" title={s.expected_product_name}>
                              {s.expected_product_name}
                            </div>
                            <span className="text-[10px] text-slate-400 font-mono">{s.expected_barcode}</span>
                          </td>

                          {/* Angle */}
                          <td className="py-2 px-2 text-[10px] text-slate-500 font-sans">{s.angle_label}</td>

                          {/* Top-1 */}
                          <td className="py-2 px-3 font-sans truncate max-w-[120px]" title={s.top1_product_name}>
                            <span className={s.is_correct_top1 ? 'text-emerald-600 font-bold' : 'text-red-500 font-bold'}>
                              {s.top1_product_name}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-right font-bold text-slate-700 dark:text-slate-300">
                            {(s.top1_score * 100).toFixed(1)}%
                          </td>

                          {/* Top-2 */}
                          <td className="py-2 px-3 font-sans truncate max-w-[110px] text-slate-500" title={s.top2_product_name}>
                            {s.top2_product_name}
                          </td>
                          <td className="py-2 px-2 text-right text-slate-500">
                            {(s.top2_score * 100).toFixed(1)}%
                          </td>

                          {/* Score Scanned */}
                          <td className="py-2 px-2 text-right font-bold text-cyan-600 dark:text-cyan-400">
                            {s.score_scanned.toFixed(3)}
                          </td>

                          {/* Best Other */}
                          <td className="py-2 px-3 font-sans truncate max-w-[110px] text-slate-400" title={`${s.best_other_product_name} (${s.best_other.toFixed(3)})`}>
                            {s.best_other_product_name}
                          </td>

                          {/* Margin */}
                          <td className="py-2 px-2 text-right font-bold">
                            <span className={s.margin >= 0.10 ? 'text-emerald-600' : s.margin >= 0.05 ? 'text-amber-600' : 'text-red-500'}>
                              {s.margin >= 0 ? `+${s.margin.toFixed(3)}` : s.margin.toFixed(3)}
                            </span>
                          </td>

                          {/* Result Badge */}
                          <td className="py-2 px-2 text-center">
                            {s.is_correct_top1 ? (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
                                Match
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300">
                                Mismatch
                              </span>
                            )}
                          </td>

                          {/* Delete Action */}
                          <td className="py-2 px-2 text-center">
                            <button
                              onClick={() => handleDeleteSample(s.id)}
                              className="p-1 hover:text-red-600 text-slate-400 transition-colors"
                              title="Delete this sample"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty State when no photos recorded yet */}
      {(!results || results.total_samples === 0) && (
        <div className="bg-white dark:bg-[#131B2E] border border-dashed border-slate-300 dark:border-slate-800 rounded-3xl p-12 text-center space-y-3">
          <div className="w-14 h-14 bg-cyan-600/10 rounded-2xl mx-auto flex items-center justify-center text-cyan-600">
            <FlaskConical className="w-7 h-7" />
          </div>
          <h3 className="font-bold text-slate-800 dark:text-slate-200 text-sm">
            No Test Photos Evaluated Yet
          </h3>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Upload test photos or use the live webcam above to capture crops under different angles and lighting.
            The Recognition Lab will immediately generate the confusion matrix and sensitivity tables from your photos.
          </p>
        </div>
      )}
    </div>
  );
};
export default RecognitionLabView;
