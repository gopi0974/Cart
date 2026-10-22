import React, { useState, useEffect } from 'react';
import { Check, X, ShieldQuestion, ArrowRight, Sparkles, RefreshCw, Layers } from 'lucide-react';
import { ReviewCase } from '../types';
import { api } from '../services/api';

export const ReviewQueueView: React.FC = () => {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCaseIdx, setActiveCaseIdx] = useState(0);

  const fetchQueue = async () => {
    try {
      const data = await api.getReviewQueue();
      setCases(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  // Keyboard shortcuts [A] Approve, [R] Reject
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (cases.length === 0) return;
      const current = cases[activeCaseIdx];
      if (!current) return;

      if (e.key === 'a' || e.key === 'A') {
        handleDecision(current.id, 'APPROVE');
      } else if (e.key === 'r' || e.key === 'R') {
        handleDecision(current.id, 'REJECT');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [cases, activeCaseIdx]);

  const handleDecision = async (caseId: string, decision: 'APPROVE' | 'REJECT') => {
    try {
      await api.submitReviewDecision(caseId, decision, 'Staff hotkey decision.');
      await fetchQueue();
      setActiveCaseIdx(0);
    } catch (e) {
      alert('Failed to submit decision.');
    }
  };

  const currentCase = cases[activeCaseIdx];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <span>Human-In-The-Loop Review Queue</span>
            {cases.length > 0 && (
              <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300">
                {cases.length} PENDING
              </span>
            )}
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Cases where AI visual confidence fell below auto-approval cutoff. Staff decisions retrain model embeddings.
          </p>
        </div>

        {/* Keyboard shortcut hint */}
        <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-100 dark:bg-slate-900 px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800">
          <span>Shortcuts:</span>
          <kbd className="px-1.5 py-0.5 bg-white dark:bg-slate-800 rounded border border-slate-300 dark:border-slate-700 font-bold text-emerald-600">A</kbd> Approve
          <kbd className="px-1.5 py-0.5 bg-white dark:bg-slate-800 rounded border border-slate-300 dark:border-slate-700 font-bold text-red-500 ml-1">R</kbd> Reject
        </div>
      </div>

      {cases.length === 0 ? (
        <div className="bg-white dark:bg-[#131B2E] border border-dashed border-slate-200 dark:border-slate-800 rounded-3xl p-16 text-center text-slate-400 text-xs space-y-3">
          <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 rounded-2xl mx-auto flex items-center justify-center">
            <Check className="w-6 h-6" />
          </div>
          <h3 className="font-semibold text-slate-700 dark:text-slate-300 text-sm">
            Review Queue is Clear!
          </h3>
          <p className="max-w-xs mx-auto">
            All AI item matches are currently verified above confidence thresholds.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-6">
          {/* Case Header */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 dark:border-slate-800 pb-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-700 dark:text-slate-300">
                  {currentCase.cart_number}
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-white">
                  Case #{currentCase.id.slice(0, 8)}
                </span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5">
                Observed: {new Date(currentCase.created_at).toLocaleTimeString()}
              </div>
            </div>

            {/* Confidence Score Pill */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">Match Confidence:</span>
              <span className="font-mono text-sm font-bold px-3 py-1 bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 rounded-xl border border-amber-300 dark:border-amber-800/40">
                {(currentCase.confidence * 100).toFixed(1)}% (Threshold: 85.0%)
              </span>
            </div>
          </div>

          {/* Side-by-Side Visual Inspection Comparison */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: Cart Camera Evidence */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span>1. Overhead Cart Camera Capture</span>
                <span className="text-red-500">Live Frame</span>
              </div>
              <div className="aspect-video bg-black rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700 relative shadow-inner">
                <img
                  src={currentCase.evidence_image_url}
                  alt="Cart Camera Evidence"
                  className="w-full h-full object-cover"
                />
                <div className="absolute bottom-2 left-2 bg-black/70 px-2.5 py-1 rounded-lg text-[11px] font-mono text-white">
                  Hand Occlusion Detected
                </div>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                Customer placed item into cart basket. Hand partially masked the label causing lower visual match confidence.
              </p>
            </div>

            {/* Right: Catalog Product Reference */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span>2. Registered Catalog Reference</span>
                <span className="text-emerald-500">Claimed Barcode</span>
              </div>
              <div className="aspect-video bg-slate-100 dark:bg-slate-900 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700 relative shadow-inner flex items-center justify-center">
                {currentCase.scanned_product_image ? (
                  <img
                    src={currentCase.scanned_product_image}
                    alt="Catalog Reference"
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <Layers className="w-12 h-12 text-slate-400" />
                )}
                <div className="absolute bottom-2 left-2 bg-black/70 px-2.5 py-1 rounded-lg text-[11px] font-mono text-white">
                  360° Enrolled Embedding Model
                </div>
              </div>
              <div className="text-xs">
                <strong className="text-slate-800 dark:text-slate-200 block text-sm">
                  {currentCase.scanned_product_name || 'Item'}
                </strong>
                <span className="font-mono text-slate-400">Barcode: {currentCase.scanned_barcode}</span>
              </div>
            </div>
          </div>

          {/* Decision Bar */}
          <div className="border-t border-slate-100 dark:border-slate-800 pt-5 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
              <Sparkles className="w-4 h-4" />
              <span>Decisions automatically save positive & negative feedback to fine-tune vector embeddings.</span>
            </div>

            <div className="flex gap-3 w-full sm:w-auto">
              <button
                onClick={() => handleDecision(currentCase.id, 'REJECT')}
                className="flex-1 sm:flex-initial bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 border border-red-200 dark:border-red-900/60 font-semibold px-5 py-2.5 rounded-2xl flex items-center justify-center gap-2 text-xs active:scale-95 transition-all"
              >
                <X className="w-4 h-4" />
                Reject Match (R)
              </button>

              <button
                onClick={() => handleDecision(currentCase.id, 'APPROVE')}
                className="flex-1 sm:flex-initial bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-6 py-2.5 rounded-2xl shadow-md shadow-emerald-600/30 flex items-center justify-center gap-2 text-xs active:scale-95 transition-all"
              >
                <Check className="w-4 h-4" />
                Approve Match (A)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
