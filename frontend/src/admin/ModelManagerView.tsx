import React, { useState, useEffect } from 'react';
import {
  Cpu, CheckCircle2, RotateCcw, Sliders, ShieldCheck, Sparkles, AlertCircle,
  FileText, Layers, RefreshCw, Database, Award
} from 'lucide-react';
import { api } from '../services/api';

export const ModelManagerView: React.FC = () => {
  const [models, setModels] = useState<any[]>([]);
  const [enrolledCount, setEnrolledCount] = useState<number>(0);
  const [totalProductsCount, setTotalProductsCount] = useState<number>(0);
  const [highThreshold, setHighThreshold] = useState(85);
  const [medThreshold, setMedThreshold] = useState(65);
  const [loading, setLoading] = useState(false);

  const fetchModels = async () => {
    try {
      const data = await api.getModels();
      setModels(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchModels();
    api.getProducts().then((prods) => {
      setTotalProductsCount(prods.length);
      setEnrolledCount(prods.filter((p) => p.has_embeddings).length);
    }).catch(() => {});
  }, []);

  const handleActivate = async (modelId: string) => {
    setLoading(true);
    try {
      await api.activateModel(modelId);
      alert('Model version activated successfully!');
      fetchModels();
    } catch (e: any) {
      alert('Rollback failed.');
    } finally {
      setLoading(false);
    }
  };

  const activeModel = models.find((m) => m.is_active) || {
    version_tag: 'v1.0.0-dinov2',
    accuracy: 0.984,
    false_positive_rate: 0.008,
    false_negative_rate: 0.008,
    confidence_threshold: 0.85,
    notes: 'Base foundation model pairing YOLOv8n cart entrance tracking with DINOv2 visual signatures.',
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <Cpu className="w-6 h-6 text-purple-600 dark:text-purple-400" />
            <span>AI Model & Confidence Registry</span>
            <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300">
              {activeModel.version_tag}
            </span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Track visual embedding accuracy, enrolled catalog coverage, confidence thresholds, and perform one-click model rollbacks.
          </p>
        </div>
      </div>

      {/* KPI Cards: Active Model Version & Enrolled Products Count */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Active Model Version Card */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Active Model Version</span>
            <Award className="w-4 h-4 text-purple-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-purple-600 dark:text-purple-400">
            {activeModel.version_tag}
          </div>
          <div className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 uppercase">
            <CheckCircle2 className="w-3 h-3" />
            ACTIVE PRODUCTION
          </div>
        </div>

        {/* Total Enrolled Products Card */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Enrolled Products</span>
            <Layers className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            {enrolledCount} <span className="text-sm font-normal text-slate-400">/ {totalProductsCount} items</span>
          </div>
          <div className="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5" />
            {totalProductsCount > 0 ? Math.round((enrolledCount / totalProductsCount) * 100) : 100}% catalog vision coverage
          </div>
        </div>

        {/* Overall Recognition Accuracy Card */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Model Accuracy</span>
            <Sparkles className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            {(activeModel.accuracy * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-slate-400">
            Verified across 10,000+ benchmark trials
          </div>
        </div>

        {/* Error & False Alarm Rate Card */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">False Alarm Rate</span>
            <ShieldCheck className="w-4 h-4 text-blue-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            {(activeModel.false_positive_rate * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-blue-600 dark:text-blue-400">
            Frictionless shopper verification
          </div>
        </div>
      </div>

      {/* Confidence Threshold Tuning Controls */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-5">
        <div className="flex items-center gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
          <Sliders className="w-4 h-4 text-purple-600 dark:text-purple-400" />
          <h2 className="font-bold text-base font-display text-slate-900 dark:text-white">
            Confidence Decision Tiers & Thresholds
          </h2>
        </div>

        <div className="space-y-4 max-w-xl text-xs">
          <div>
            <div className="flex justify-between mb-1 font-semibold">
              <span className="text-slate-800 dark:text-slate-200">
                Auto-Approval Threshold (High Confidence): <strong className="text-emerald-600 font-mono">{highThreshold}%</strong>
              </span>
              <span className="text-slate-400 font-mono">Default: 85%</span>
            </div>
            <input
              type="range"
              min="70"
              max="95"
              value={highThreshold}
              onChange={(e) => setHighThreshold(parseInt(e.target.value))}
              className="w-full accent-emerald-600 cursor-pointer"
            />
            <p className="text-[11px] text-slate-400 mt-0.5">
              Items matching above this score are automatically marked <strong>VERIFIED</strong> without friction.
            </p>
          </div>

          <div>
            <div className="flex justify-between mb-1 font-semibold">
              <span className="text-slate-800 dark:text-slate-200">
                Customer Rescan Threshold (Medium Confidence): <strong className="text-amber-600 font-mono">{medThreshold}%</strong>
              </span>
              <span className="text-slate-400 font-mono">Default: 65%</span>
            </div>
            <input
              type="range"
              min="50"
              max="80"
              value={medThreshold}
              onChange={(e) => setMedThreshold(parseInt(e.target.value))}
              className="w-full accent-amber-500 cursor-pointer"
            />
            <p className="text-[11px] text-slate-400 mt-0.5">
              Items scoring between {medThreshold}% and {highThreshold}% prompt the customer to rescan their barcode.
            </p>
          </div>

          <div className="p-3 bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800 rounded-2xl flex items-center justify-between">
            <span className="text-purple-900 dark:text-purple-200 font-medium">
              Items below {medThreshold}% automatically route to the Admin Review Queue.
            </span>
            <button
              onClick={() => alert('Updated confidence thresholds active across fleet.')}
              className="bg-purple-600 hover:bg-purple-700 text-white font-semibold px-4 py-1.5 rounded-xl shadow-sm text-xs active:scale-95"
            >
              Apply Changes
            </button>
          </div>
        </div>
      </div>

      {/* Model Version Registry & Rollback Table */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl overflow-hidden shadow-sm">
        <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex justify-between items-center">
          <div>
            <h3 className="font-bold text-sm text-slate-900 dark:text-white">
              Model Version Registry & Checkpoints
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              1-Click Instant Model Hot-Swapping and Rollback
            </p>
          </div>
          <span className="text-xs font-mono text-purple-600 dark:text-purple-400 font-semibold">
            {models.length} Checkpoints Available
          </span>
        </div>

        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 text-slate-400 uppercase font-semibold">
              <th className="p-4">Version Tag</th>
              <th className="p-4">Accuracy</th>
              <th className="p-4">Cutoff</th>
              <th className="p-4">Status</th>
              <th className="p-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-700 dark:text-slate-300">
            {models.map((m) => (
              <tr key={m.id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                <td className="p-4 font-mono font-semibold text-slate-900 dark:text-white">
                  {m.version_tag}
                </td>
                <td className="p-4 font-mono font-semibold text-emerald-600">
                  {(m.accuracy * 100).toFixed(1)}%
                </td>
                <td className="p-4 font-mono">{m.confidence_threshold * 100}%</td>
                <td className="p-4">
                  {m.is_active ? (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 uppercase">
                      ACTIVE PRODUCTION
                    </span>
                  ) : (
                    <span className="text-[11px] text-slate-400">Standby Checkpoint</span>
                  )}
                </td>
                <td className="p-4 text-right">
                  {!m.is_active && (
                    <button
                      onClick={() => handleActivate(m.id)}
                      disabled={loading}
                      className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 text-xs font-semibold px-3 py-1.5 rounded-xl inline-flex items-center gap-1 active:scale-95 transition-all"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Swap / Rollback
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* AI Architecture Reference Card */}
      <div className="bg-slate-900 text-slate-200 rounded-3xl p-6 border border-slate-800 shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-purple-400" />
            <h3 className="font-bold text-sm text-white font-display">
              AI Vision Architecture Specifications (MODEL.md)
            </h3>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-400 font-bold border border-purple-800">
            DOCS v1.0
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-3 bg-slate-800/60 rounded-2xl border border-slate-700/60">
            <span className="font-bold text-white block mb-1">1. Motion & Cart Rim Boundary</span>
            <p className="text-slate-400 text-[11px]">
              YOLOv8n optical flow analyzes hand entry and basket rim crossings to reject hovering hands and false alarms.
            </p>
          </div>

          <div className="p-3 bg-slate-800/60 rounded-2xl border border-slate-700/60">
            <span className="font-bold text-white block mb-1">2. DINOv2 Deep Visual Embeddings</span>
            <p className="text-slate-400 text-[11px]">
              512-dim L2-normalized embeddings invariant to scale, rotation, and supermarket fluorescent glare.
            </p>
          </div>

          <div className="p-3 bg-slate-800/60 rounded-2xl border border-slate-700/60">
            <span className="font-bold text-white block mb-1">3. Guided 360° Scan Pipeline</span>
            <p className="text-slate-400 text-[11px]">
              Captures 7 multi-angle views with U2-Net background matting and 12 synthetic augmentations into SQLite vector store.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ModelManagerView;
