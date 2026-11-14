import React, { useState, useEffect } from 'react';
import { Check, X, ShieldQuestion, ArrowRight, Sparkles, RefreshCw, Layers, Tag, Eye } from 'lucide-react';
import { ReviewCase } from '../types';
import { api } from '../services/api';

type FeedbackReason = 'true match' | 'wrong item' | 'bad crop' | 'lighting';

export const ReviewQueueView: React.FC = () => {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCaseIdx, setActiveCaseIdx] = useState(0);
  const [staffFeedback, setStaffFeedback] = useState<FeedbackReason>('true match');
  const [isSubmitting, setIsSubmitting] = useState(false);

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
      if (cases.length === 0 || isSubmitting) return;
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
  }, [cases, activeCaseIdx, staffFeedback, isSubmitting]);

  const handleDecision = async (caseId: string, decision: 'APPROVE' | 'REJECT', customFeedback?: FeedbackReason) => {
    const feedback = customFeedback || (decision === 'APPROVE' && staffFeedback === 'wrong item' ? 'true match' : staffFeedback);
    setIsSubmitting(true);
    try {
      await api.submitReviewDecision(caseId, decision, `Staff feedback: ${feedback}`);
      await fetchQueue();
      setActiveCaseIdx(0);
      setStaffFeedback('true match');
    } catch (e) {
      alert('Failed to submit decision.');
    } finally {
      setIsSubmitting(false);
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
            Visual inspection cases requiring staff validation. Top 3 embedding matches and crops presented below.
          </p>
        </div>

        {/* Keyboard shortcut hint */}
        <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-100 dark:bg-slate-900 px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800">
          <span>Shortcuts:</span>
          <kbd className="bg-white dark:bg-slate-800 px-1.5 py-0.5 rounded border border-slate-300 dark:border-slate-700 font-bold text-slate-700 dark:text-slate-300">[A]</kbd>
          <span>Approve</span>
          <kbd className="bg-white dark:bg-slate-800 px-1.5 py-0.5 rounded border border-slate-300 dark:border-slate-700 font-bold text-slate-700 dark:text-slate-300">[R]</kbd>
          <span>Reject</span>
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
              <span className={`font-mono text-sm font-bold px-3 py-1 rounded-xl border ${
                currentCase.confidence >= 0.85
                  ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-800/40'
                  : currentCase.confidence >= 0.70
                  ? 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 border-amber-300 dark:border-amber-800/40'
                  : 'bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-400 border-red-300 dark:border-red-800/40'
              }`}>
                {(currentCase.confidence * 100).toFixed(1)}%
              </span>
            </div>
          </div>

          {/* Side-by-Side Visual Inspection Comparison */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: Cart Camera Evidence (Crop of Product Area) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span>1. Overhead Evidence Crop</span>
                <span className="text-red-500 font-mono text-[11px]">Product Area Crop</span>
              </div>
              <div className="aspect-video bg-black rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700 relative shadow-inner flex items-center justify-center">
                {currentCase.evidence_status === 'frame withheld (face detected)' || currentCase.confidence === 0.0 ? (
                  <div className="p-6 text-center space-y-2">
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/40 font-mono">
                      Frame withheld (face detected)
                    </span>
                    <p className="text-[11px] text-slate-400 max-w-xs mx-auto">
                      In-camera face detection withheld this frame to protect shopper privacy. Staff visual verification required.
                    </p>
                  </div>
                ) : currentCase.evidence_image_url ? (
                  <img
                    src={currentCase.evidence_image_url}
                    alt="Cart Camera Evidence Crop"
                    className="w-full h-full object-contain bg-slate-950"
                  />
                ) : (
                  <div className="text-slate-500 text-xs flex items-center gap-1.5">
                    <Eye className="w-4 h-4" />
                    <span>No evidence crop recorded</span>
                  </div>
                )}
                <div className="absolute bottom-2 left-2 bg-black/70 px-2.5 py-1 rounded-lg text-[10px] font-mono text-white">
                  {currentCase.evidence_status === 'frame withheld (face detected)' || currentCase.confidence === 0.0 ? 'Privacy Withheld' : 'Cropped Target Region'}
                </div>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                Privacy-preserving snapshot: cropped strictly to item bounding box. Full camera frames and faces are never stored.
              </p>
            </div>

            {/* Right: Scanned Product Reference */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span>2. Scanned Product (Claimed)</span>
                <span className="text-emerald-500 font-mono text-[11px]">Barcode Match</span>
              </div>
              <div className="aspect-video bg-slate-100 dark:bg-slate-900 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700 relative shadow-inner flex items-center justify-center">
                {currentCase.scanned_product_image ? (
                  <img
                    src={currentCase.scanned_product_image}
                    alt="Catalog Reference"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <Layers className="w-12 h-12 text-slate-400" />
                )}
                <div className="absolute bottom-2 left-2 bg-black/70 px-2.5 py-1 rounded-lg text-[10px] font-mono text-white">
                  Catalog Reference
                </div>
              </div>
              <div className="text-xs">
                <strong className="text-slate-800 dark:text-slate-200 block text-sm">
                  {currentCase.scanned_product_name || 'Unregistered Product'}
                </strong>
                <span className="font-mono text-slate-400">Barcode: {currentCase.scanned_barcode || 'N/A'}</span>
              </div>
            </div>
          </div>

          {/* Top 3 Product Matches with Similarity Scores */}
          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
                <Layers className="w-4 h-4 text-primary-500" />
                <span>Top 3 Visual Embedding Matches (CLIP ViT-B/32)</span>
              </h4>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {currentCase.top_candidates && currentCase.top_candidates.length > 0 ? (
                currentCase.top_candidates.slice(0, 3).map((candidate, idx) => {
                  const score = candidate.similarity;
                  const isTop = idx === 0;
                  return (
                    <div
                      key={candidate.id || idx}
                      className={`p-3 rounded-2xl border transition-all ${
                        isTop
                          ? 'bg-primary-50/50 dark:bg-primary-950/20 border-primary-200 dark:border-primary-800'
                          : 'bg-slate-50 dark:bg-slate-900/40 border-slate-200 dark:border-slate-800'
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <span className="font-bold text-[11px] text-slate-500 font-mono">
                          Rank #{idx + 1} {isTop && '• Top Candidate'}
                        </span>
                        <span className={`font-mono font-bold text-xs px-2 py-0.5 rounded-md ${
                          score >= 0.85
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
                            : score >= 0.70
                            ? 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
                            : 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'
                        }`}>
                          {(score * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="font-semibold text-xs text-slate-800 dark:text-slate-200 truncate" title={candidate.product_name}>
                        {candidate.product_name || 'Unknown Product'}
                      </div>
                      <div className="text-[10px] font-mono text-slate-400 mt-0.5">
                        {candidate.barcode ? `Barcode: ${candidate.barcode}` : 'ID: ' + (candidate.id?.slice(0, 8) || 'N/A')}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="col-span-3 text-xs text-slate-400 italic py-2">
                  No top candidate list recorded for this decision. (Confidence: {(currentCase.confidence * 100).toFixed(1)}%)
                </div>
              )}
            </div>
          </div>

          {/* Staff Feedback Selection Bar */}
          <div className="pt-2 border-t border-slate-100 dark:border-slate-800 space-y-2">
            <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <Tag className="w-3.5 h-3.5" />
              <span>Select Staff Feedback Reason:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(['true match', 'wrong item', 'bad crop', 'lighting'] as FeedbackReason[]).map((reason) => (
                <button
                  key={reason}
                  type="button"
                  onClick={() => setStaffFeedback(reason)}
                  className={`text-xs px-3 py-1.5 rounded-xl border capitalize font-medium transition-all ${
                    staffFeedback === reason
                      ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 border-transparent shadow-sm'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700 hover:border-slate-400'
                  }`}
                >
                  {reason}
                </button>
              ))}
            </div>
          </div>

          {/* Decision Action Buttons */}
          <div className="border-t border-slate-100 dark:border-slate-800 pt-5 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
              <Sparkles className="w-4 h-4 shrink-0" />
              <span>Decisions automatically save staff feedback reason into audit records.</span>
            </div>

            <div className="flex gap-3 w-full sm:w-auto">
              <button
                disabled={isSubmitting}
                onClick={() => handleDecision(currentCase.id, 'REJECT')}
                className="flex-1 sm:flex-initial bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 border border-red-200 dark:border-red-900/60 font-semibold px-5 py-2.5 rounded-2xl flex items-center justify-center gap-2 text-xs active:scale-95 transition-all disabled:opacity-50"
              >
                <X className="w-4 h-4" />
                Reject Match (R)
              </button>

              <button
                disabled={isSubmitting}
                onClick={() => handleDecision(currentCase.id, 'APPROVE')}
                className="flex-1 sm:flex-initial bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-6 py-2.5 rounded-2xl shadow-md shadow-emerald-600/30 flex items-center justify-center gap-2 text-xs active:scale-95 transition-all disabled:opacity-50"
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
