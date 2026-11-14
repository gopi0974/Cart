import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Zap,
  RefreshCw,
  Camera,
  ShieldAlert,
  ShieldCheck,
  Eye,
  Sliders,
  Layers,
  Cpu,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { api } from '../services/api';

interface Props {
  cart: {
    id: string;
    cart_number: string;
    camera_status: string;
  };
  onBack: () => void;
}

export const VerificationTraceView: React.FC<Props> = ({ cart, onBack }) => {
  const [traces, setTraces] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningNow, setRunningNow] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [runMessage, setRunMessage] = useState<{ text: string; type: 'success' | 'warn' | 'error' } | null>(null);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  const fetchTraces = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getCartVerificationTrace(cart.id, 20);
      setTraces(resp.traces || []);
      if (resp.traces && resp.traces.length > 0 && !expandedTraceId) {
        setExpandedTraceId(resp.traces[0].id);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load verification traces');
    } finally {
      setLoading(false);
    }
  }, [cart.id, expandedTraceId]);

  useEffect(() => {
    fetchTraces();
  }, [cart.id]);

  const handleRunNow = async () => {
    setRunningNow(true);
    setRunMessage(null);
    try {
      const resp = await api.runCartVerificationNow(cart.id);
      if (resp.trace) {
        setTraces((prev) => [resp.trace, ...prev.filter((t) => t.id !== resp.trace.id).slice(0, 19)]);
        setExpandedTraceId(resp.trace.id);
      }
      setRunMessage({
        text: `Judgement evaluated: ${resp.decision} (${resp.message || 'Completed'})`,
        type: resp.decision === 'AUTO_APPROVE' ? 'success' : 'warn'
      });
    } catch (err: any) {
      setRunMessage({
        text: `Execution failed: ${err?.message || 'Unknown error'}`,
        type: 'error'
      });
    } finally {
      setRunningNow(false);
    }
  };

  const formatStoppedAt = (stage: string) => {
    switch (stage) {
      case 'completed':
        return { label: 'stopped at: completed', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40' };
      case 'hand_present':
        return { label: 'stopped at: hand_present', color: 'bg-amber-500/20 text-amber-300 border-amber-500/40' };
      case 'face_present':
        return { label: 'stopped at: face_present', color: 'bg-rose-500/20 text-rose-300 border-rose-500/40' };
      case 'camera_offline':
        return { label: 'stopped at: camera_offline', color: 'bg-slate-700/50 text-slate-300 border-slate-600' };
      case 'empty_reference':
        return { label: 'stopped at: empty_reference', color: 'bg-amber-500/20 text-amber-300 border-amber-500/40' };
      case 'no_product_vectors':
        return { label: 'stopped at: no_product_vectors', color: 'bg-red-500/20 text-red-400 border-red-500/40' };
      case 'low_confidence':
        return { label: 'stopped at: low_confidence', color: 'bg-rose-500/20 text-rose-300 border-rose-500/40' };
      case 'wrong_item':
        return { label: 'stopped at: wrong_item', color: 'bg-rose-500/20 text-rose-300 border-rose-500/40' };
      case 'reposition_needed':
        return { label: 'stopped at: reposition_needed', color: 'bg-amber-500/20 text-amber-300 border-amber-500/40' };
      default:
        return { label: `stopped at: ${stage || 'unknown'}`, color: 'bg-slate-800 text-slate-300 border-slate-700' };
    }
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb Navigation */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <button onClick={onBack} className="hover:text-slate-800 dark:hover:text-slate-200 transition-colors">
            Admin
          </button>
          <span>/</span>
          <button onClick={onBack} className="hover:text-slate-800 dark:hover:text-slate-200 transition-colors">
            Carts
          </button>
          <span>/</span>
          <span className="font-mono font-bold text-slate-900 dark:text-white">{cart.cart_number}</span>
          <span>/</span>
          <span className="font-semibold text-purple-600 dark:text-purple-400">Verification trace</span>
        </div>

        <button
          onClick={onBack}
          className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800 text-xs font-semibold flex items-center gap-1.5 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Carts Fleet</span>
        </button>
      </div>

      {/* Cart Status & Actions Header */}
      <div className="p-5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-600 dark:text-purple-400">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
                Verification Trace: {cart.cart_number}
              </h1>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                  cart.camera_status === 'ONLINE'
                    ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                    : 'bg-slate-500/10 text-slate-500 border border-slate-500/30'
                }`}
              >
                Camera {cart.camera_status}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Live multi-stage diagnostic timeline for the last 20 AI verification judgements on this cart.
            </p>
          </div>
        </div>

        {/* Staff Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={fetchTraces}
            disabled={loading}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition-colors"
            title="Refresh judgements trace history"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          <button
            onClick={handleRunNow}
            disabled={runningNow}
            className="py-2.5 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white font-bold text-xs flex items-center gap-2 shadow-lg shadow-purple-600/20 active:scale-95 transition-all"
            title="Judge the latest stable frame for this cart immediately"
          >
            <Zap className={`w-4 h-4 ${runningNow ? 'animate-spin' : ''}`} />
            <span>{runningNow ? 'Evaluating Frame...' : 'Run verification now'}</span>
          </button>
        </div>
      </div>

      {/* Execution Feedback Notification */}
      {runMessage && (
        <div
          className={`p-3.5 rounded-2xl border text-xs font-medium flex items-center justify-between gap-2 ${
            runMessage.type === 'success'
              ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40'
              : runMessage.type === 'warn'
              ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/40'
              : 'bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800/40'
          }`}
        >
          <div className="flex items-center gap-2">
            {runMessage.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            ) : runMessage.type === 'warn' ? (
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 text-red-600 shrink-0" />
            )}
            <span>{runMessage.text}</span>
          </div>
          <button onClick={() => setRunMessage(null)} className="text-xs font-bold opacity-60 hover:opacity-100">
            Dismiss
          </button>
        </div>
      )}

      {/* Trace History List */}
      <div className="space-y-4">
        <div className="flex items-center justify-between text-xs text-slate-500 px-1">
          <span className="font-semibold uppercase tracking-wider text-[11px]">
            Judgements History ({traces.length} of last 20)
          </span>
          <span>Click a card to inspect all 10 stages</span>
        </div>

        {error ? (
          <div className="p-8 text-center bg-white dark:bg-[#131B2E] border border-red-200 dark:border-red-900/40 rounded-3xl space-y-3">
            <XCircle className="w-8 h-8 text-red-500 mx-auto" />
            <p className="text-xs text-red-600 dark:text-red-400 font-medium">{error}</p>
            <button onClick={fetchTraces} className="text-xs text-purple-600 font-semibold hover:underline">
              Retry loading traces
            </button>
          </div>
        ) : loading && traces.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 bg-slate-100 dark:bg-slate-800/60 rounded-3xl animate-pulse" />
            ))}
          </div>
        ) : traces.length === 0 ? (
          <div className="p-12 text-center bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl space-y-3">
            <Clock className="w-10 h-10 text-slate-400 mx-auto" />
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">No Verification Judgements Yet</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              This cart has not recorded any AI verification judgements yet. Start the camera stream on{' '}
              <code className="text-purple-500 font-mono">/cart-device</code> and scan an item, or click "Run verification now".
            </p>
          </div>
        ) : (
          traces.map((trace, idx) => {
            const isExpanded = expandedTraceId === trace.id;
            const stopped = formatStoppedAt(trace.stopped_at);
            const isApproved = trace.decision === 'AUTO_APPROVE';
            const isWarning = ['REPOSITION_PROMPT', 'HAND_IN_CART'].includes(trace.decision);

            return (
              <div
                key={trace.id || idx}
                className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl shadow-sm overflow-hidden transition-all"
              >
                {/* Judgement Summary Card Header */}
                <div
                  onClick={() => setExpandedTraceId(isExpanded ? null : trace.id)}
                  className="p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-3 cursor-pointer hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors"
                >
                  <div className="flex items-start sm:items-center gap-3">
                    <span className="w-7 h-7 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-mono text-xs font-bold text-slate-500">
                      #{idx + 1}
                    </span>

                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-sm text-slate-900 dark:text-white">
                          {trace.scanned_product_name || (trace.scanned_barcode ? `Barcode ${trace.scanned_barcode}` : 'Unscanned Item Placement')}
                        </span>

                        {/* Decision Pill */}
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                            isApproved
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                              : isWarning
                              ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                              : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/30'
                          }`}
                        >
                          {trace.decision}
                        </span>

                        {/* Explicit Stopped At Pill */}
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold border ${stopped.color}`}>
                          {stopped.label}
                        </span>
                      </div>

                      <p className="text-xs text-slate-500 mt-1 line-clamp-1">{trace.reason_text}</p>
                    </div>
                  </div>

                  {/* Right Meta Info */}
                  <div className="flex items-center gap-4 text-xs font-mono shrink-0">
                    {trace.score_scanned != null && (
                      <div className="text-right">
                        <span className="text-[10px] text-slate-400 block uppercase">Match Score</span>
                        <span
                          className={`font-bold ${
                            trace.score_scanned >= 0.85
                              ? 'text-emerald-500'
                              : trace.score_scanned >= 0.65
                              ? 'text-amber-500'
                              : 'text-rose-500'
                          }`}
                        >
                          {(trace.score_scanned * 100).toFixed(1)}%
                        </span>
                      </div>
                    )}

                    <div className="text-right">
                      <span className="text-[10px] text-slate-400 block uppercase">Time</span>
                      <span className="text-slate-600 dark:text-slate-300">
                        {trace.timestamp
                          ? new Date(trace.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                          : 'Recent'}
                      </span>
                    </div>

                    <div className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>
                  </div>
                </div>

                {/* Expanded 10-Stage Pipeline Deep-Dive */}
                {isExpanded && (
                  <div className="border-t border-slate-100 dark:border-slate-800 p-5 bg-slate-50/50 dark:bg-slate-900/40 space-y-4">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400 flex items-center gap-2">
                        <Sliders className="w-3.5 h-3.5" />
                        10-Stage Pipeline Evaluation Trace
                      </h4>
                    </div>

                    {/* Cart Session & Pending Verification Context */}
                    <div className="p-3 bg-purple-500/5 dark:bg-purple-900/10 border border-purple-500/20 rounded-2xl grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div>
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Cart & Session Context
                        </span>
                        <div className="font-mono text-[11px] text-slate-700 dark:text-slate-300 truncate">
                          Cart: <span className="font-bold text-slate-900 dark:text-white">{trace.cart_number || trace.cart_id}</span>
                        </div>
                        <div className="font-mono text-[10px] text-slate-500 truncate" title={trace.session_id || 'None'}>
                          Session: {trace.session_id ? trace.session_id.slice(0, 13) + '...' : 'No active session'}
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Pending Items Found ({trace.pending_items?.length || 0})
                        </span>
                        {trace.pending_items && trace.pending_items.length > 0 ? (
                          <div className="space-y-0.5 mt-0.5">
                            {trace.pending_items.map((pi: any, idx: number) => (
                              <div key={idx} className="font-mono text-[11px] text-emerald-600 dark:text-emerald-400 font-semibold truncate" title={`${pi.product_name} (${pi.barcode})`}>
                                • {pi.product_name} <span className="text-slate-400">[{pi.barcode}]</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[11px] text-slate-500 italic block mt-0.5">0 items pending</span>
                        )}
                      </div>

                      <div>
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Unscanned Alert Evaluation
                        </span>
                        <div className="font-mono text-[11px] text-slate-700 dark:text-slate-300 mt-0.5">
                          {trace.unscanned_alert_reason || 'N/A (Pending item evaluated)'}
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs">
                      {/* Stage 1: Frame Received */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 1 • Frame Received
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          {trace.frame_received_time ? new Date(trace.frame_received_time).toLocaleTimeString() : 'N/A'}
                        </div>
                        <span className="text-[10px] text-slate-500 block">Capture sensor timestamp</span>
                      </div>

                      {/* Stage 2: Camera Online */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 2 • Camera Online
                        </span>
                        <div className="flex items-center gap-1.5 font-bold">
                          {trace.camera_online ? (
                            <span className="text-emerald-500 flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Online
                            </span>
                          ) : (
                            <span className="text-red-500 flex items-center gap-1">
                              <XCircle className="w-3.5 h-3.5" /> Offline
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] text-slate-500 block">Watchdog heartbeat status</span>
                      </div>

                      {/* Stage 3: Empty Reference */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 3 • Empty Reference
                        </span>
                        <div className="flex items-center gap-1.5 font-bold">
                          {trace.empty_reference_present ? (
                            <span className="text-emerald-500 flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Present
                            </span>
                          ) : (
                            <span className="text-amber-500 flex items-center gap-1">
                              <AlertTriangle className="w-3.5 h-3.5" /> Missing
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] text-slate-500 block">Baseline differencing map</span>
                      </div>

                      {/* Stage 4: Privacy Flags */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 4 • Privacy Flags
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          Hand: {trace.hand_present ? '✋ YES' : 'NO'} • Face: {trace.face_present ? '👤 YES' : 'NO'}
                        </div>
                        <span className="text-[10px] text-slate-500 block">MediaPipe in-browser gate</span>
                      </div>

                      {/* Stage 5: Frame Stability */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 5 • Stability
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          {trace.frame_stable ? 'Steady' : 'Motion'} ({trace.stable_seconds != null ? `${trace.stable_seconds}s` : 'N/A'})
                        </div>
                        <span className="text-[10px] text-slate-500 block">Settling window (req: ~1s)</span>
                      </div>

                      {/* Stage 6: Changed Region */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 6 • Changed Region
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200 truncate" title={trace.changed_region_size}>
                          {trace.changed_region_size || 'None'}
                        </div>
                        <span className="text-[10px] text-slate-500 block font-mono">
                          {trace.changed_region_box ? `[${trace.changed_region_box.join(', ')}]` : 'Fallback crop'}
                        </span>
                      </div>

                      {/* Stage 7: Crop & Preprocessing */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 7 • Crop & Preproc
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          Crop: <span className={trace.crop_status === 'saved' ? 'text-emerald-500' : 'text-amber-500'}>{trace.crop_status || 'saved'}</span>
                        </div>
                        <span className="text-[10px] text-slate-500 block truncate" title={trace.preprocessing_used}>
                          {trace.preprocessing_used} {trace.grabcut_applied ? '• GrabCut' : ''}
                        </span>
                      </div>

                      {/* Stage 8: Embedding Latency */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 8 • CLIP Embedding
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          {trace.embedding_ms != null ? `${trace.embedding_ms} ms` : 'N/A'}
                        </div>
                        <span className="text-[10px] text-slate-500 block">ONNX INT8 ViT-B/32 latency</span>
                      </div>

                      {/* Stage 9: Candidate Scoring */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 9 • Candidates
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          Scanned: {trace.score_scanned != null ? `${(trace.score_scanned * 100).toFixed(1)}%` : '0%'}
                        </div>
                        <span className="text-[10px] text-slate-500 block truncate" title={trace.best_other_product_name || 'No competitors'}>
                          Best other: {trace.best_other_score != null ? `${(trace.best_other_score * 100).toFixed(1)}% (${trace.best_other_product_name || 'N/A'})` : 'None'}
                        </span>
                      </div>

                      {/* Stage 10: Dispatch & Decision */}
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Stage 10 • Dispatch
                        </span>
                        <div className="font-mono text-[11px] font-bold text-slate-800 dark:text-slate-200">
                          Sent: {trace.sent_to_shopper ? '✅ Yes' : '❌ No'}
                        </div>
                        <span className="text-[10px] text-slate-500 block font-mono">
                          Thresholds: HIGH={trace.threshold_high || 0.85}, LOW={trace.threshold_low || 0.65}
                        </span>
                      </div>
                    </div>

                    {/* Evidence Crop Preview */}
                    {trace.evidence_url && (
                      <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl flex items-center gap-4">
                        <img
                          src={trace.evidence_url}
                          alt="Verification evidence crop"
                          className="w-16 h-16 rounded-xl object-cover border border-slate-200 dark:border-slate-700 shadow-sm"
                        />
                        <div>
                          <span className="text-xs font-bold text-slate-800 dark:text-slate-200 block">
                            Saved Evidence Crop (Product Only)
                          </span>
                          <span className="text-[11px] text-slate-400 font-mono block mt-0.5">
                            {trace.evidence_url}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

