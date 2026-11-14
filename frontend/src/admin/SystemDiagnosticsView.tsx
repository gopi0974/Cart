import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity, Database, HardDrive, Cpu, CheckCircle2, AlertTriangle,
  XCircle, RefreshCw, Clock, Layers, Zap, AlertCircle
} from 'lucide-react';
import { api } from '../services/api';

interface Props {
  health?: any;
  status: 'CONNECTED' | 'WAKING_UP' | 'OFFLINE';
  onRefresh?: () => void;
  onSessionExpired?: () => void;
}

export const SystemDiagnosticsView: React.FC<Props> = ({
  health: initialHealth,
  status: externalStatus,
  onRefresh,
  onSessionExpired,
}) => {
  const [data, setData] = useState<any>(initialHealth || null);
  const [loading, setLoading] = useState<boolean>(!initialHealth);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [responseTimeMs, setResponseTimeMs] = useState<number | null>(
    initialHealth?._response_time_ms ?? null
  );
  const [dbQueries, setDbQueries] = useState<number | null>(
    initialHealth?._db_queries ?? null
  );

  const fetchDiagnostics = useCallback(async (fresh: boolean = false) => {
    if (fresh) {
      setRefreshing(true);
    } else if (!data) {
      setLoading(true);
    }
    setError(null);

    try {
      const resp = await api.getSystemHealth(fresh);
      setData(resp);
      setResponseTimeMs(resp._response_time_ms ?? null);
      setDbQueries(resp._db_queries ?? null);
      setError(null);
    } catch (err: any) {
      if (err?.statusCode === 401 || err?.message === 'Session expired') {
        if (onSessionExpired) {
          onSessionExpired();
        } else if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('smartcart:session-expired'));
        }
        return;
      }
      setError(err?.message || 'Could not load system diagnostics');
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
      if (onRefresh && fresh) {
        onRefresh();
      }
    }
  }, [data, onRefresh, onSessionExpired]);

  useEffect(() => {
    fetchDiagnostics(false);
  }, []);

  const handleManualRefresh = () => {
    fetchDiagnostics(true);
  };

  // Real Computation: Catalog State
  const computeCatalogState = () => {
    if (!data || data.total_products == null || data.products_enrolled == null) {
      return null;
    }
    const total = Number(data.total_products);
    const enrolled = Number(data.products_enrolled);
    const vectors = Number(data.vectors_count ?? 0);

    if (total === 0) {
      return {
        label: 'No products in catalog',
        color: 'text-slate-500 dark:text-slate-400',
        badge: 'EMPTY',
      };
    }
    if (enrolled === 0) {
      return {
        label: `0 / ${total} Enrolled (0%) - Re-enrollment needed`,
        color: 'text-amber-500 font-semibold',
        badge: 'RE-ENROLL',
      };
    }
    if (enrolled === total) {
      return {
        label: `All ${enrolled} Enrolled (100%) · ${vectors} vectors`,
        color: 'text-emerald-600 dark:text-emerald-400 font-semibold',
        badge: 'COMPLETE',
      };
    }
    const pct = Math.round((enrolled / total) * 100);
    return {
      label: `${enrolled} / ${total} Enrolled (${pct}%) · ${vectors} vectors`,
      color: 'text-emerald-600 dark:text-emerald-400 font-semibold',
      badge: `${pct}%`,
    };
  };

  // Real Computation: Peak Margin
  const computePeakMargin = () => {
    if (!data || data.memory_rss_mb == null) {
      return null;
    }
    const budget = Number(data.ram_budget_mb || 512);
    const rss = Number(data.memory_rss_mb);
    const marginMb = Math.max(0, budget - rss);
    const marginPct = Math.round((marginMb / budget) * 100);

    return {
      marginMb: marginMb.toFixed(1),
      marginPct,
      label: `${marginMb.toFixed(1)} MB Free (${marginPct}% headroom)`,
      status: marginMb > 150 ? 'GOOD' : marginMb > 80 ? 'MODERATE' : 'CRITICAL',
    };
  };

  const catalogState = computeCatalogState();
  const peakMargin = computePeakMargin();
  const workerMetrics = data?.scan_worker_metrics || {};

  return (
    <div className="space-y-6">
      {/* 1. Page Shell Header - Always renders immediately */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
            System & Infrastructure
          </span>
          <h1 className="text-xl sm:text-2xl font-bold font-display text-slate-900 dark:text-white">
            Backend Diagnostics & Health
          </h1>
        </div>

        <div className="flex items-center gap-3 self-start sm:self-auto">
          {responseTimeMs !== null && (
            <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-slate-800 text-[11px] font-mono text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
              <Zap className="w-3.5 h-3.5 text-amber-500" />
              <span>{responseTimeMs.toFixed(1)} ms</span>
              <span className="text-slate-400">·</span>
              <span>{dbQueries === 0 ? '0 DB queries (cache hit)' : `${dbQueries ?? 0} DB queries`}</span>
            </div>
          )}

          <button
            onClick={handleManualRefresh}
            disabled={refreshing || loading}
            className="flex items-center gap-2 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 px-3.5 py-2 rounded-xl text-xs font-semibold hover:border-slate-300 dark:hover:border-slate-700 transition-colors shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-emerald-500' : 'text-slate-400'}`} />
            {refreshing ? 'Refreshing...' : 'Refresh Status'}
          </button>
        </div>
      </div>

      {/* Global Error Alert Banner with Retry Button */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/60 rounded-2xl flex items-center justify-between gap-4 shadow-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
            <div>
              <h3 className="text-xs font-bold text-red-900 dark:text-red-200">
                Could not load system diagnostics
              </h3>
              <p className="text-[11px] text-red-700 dark:text-red-400 mt-0.5">
                {error}
              </p>
            </div>
          </div>
          <button
            onClick={handleManualRefresh}
            className="px-3.5 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-xl shadow-sm transition-colors shrink-0"
          >
            Retry
          </button>
        </div>
      )}

      {/* Public BASE_URL & QR Warning Banner */}
      {data?.base_url_warning && (
        <div className="p-4 rounded-2xl bg-amber-500/10 border-2 border-amber-500/30 text-amber-800 dark:text-amber-200 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
          <div className="text-xs">
            <div className="font-bold text-sm uppercase tracking-wider">{data.base_url_warning}</div>
            <p className="mt-1 leading-relaxed">
              Cart pairing QR generation is disabled because <code>BASE_URL</code> is missing or contains localhost.
              In your Render service environment variables, set <code className="bg-amber-500/20 px-1.5 py-0.5 rounded font-mono font-bold">BASE_URL=https://cart-9tds.vercel.app</code> (no trailing slash).
            </p>
          </div>
        </div>
      )}

      {/* 2. Main Status Overview Card */}
      <div className="p-5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${
            error ? 'bg-red-50 dark:bg-red-950/50 text-red-500' :
            loading ? 'bg-slate-100 dark:bg-slate-800 text-slate-400 animate-pulse' :
            data?.status === 'HEALTHY' ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400' :
            data?.status === 'DEGRADED' ? 'bg-amber-50 dark:bg-amber-950/50 text-amber-500' :
            'bg-red-50 dark:bg-red-950/50 text-red-500'
          }`}>
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-slate-900 dark:text-white">
                {error ? 'Could not load backend status' :
                 loading ? 'Checking backend connectivity...' :
                 data?.status === 'HEALTHY' ? 'Backend Fully Operational' :
                 data?.status === 'DEGRADED' ? 'Backend Degraded / Migration Required' :
                 data?.status === 'STARTING' ? 'Backend Initializing ONNX Model' :
                 'Backend Unhealthy / Disconnected'}
              </h2>
              {data?.status && !error && (
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase ${
                  data.status === 'HEALTHY' ? 'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-700 dark:text-emerald-300' :
                  data.status === 'DEGRADED' ? 'bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-300' :
                  'bg-red-100 dark:bg-red-900/60 text-red-700 dark:text-red-300'
                }`}>
                  {data.status}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Verified by live active database pre-ping (<code className="font-mono text-[11px]">SELECT 1</code>) and ONNX runtime state.
            </p>
            {data?.git_commit && (
              <div className="flex items-center gap-1.5 mt-1.5">
                <span className="text-[11px] text-slate-400 font-mono">Git Commit:</span>
                <span className="font-mono text-[11px] font-bold bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-700 dark:text-slate-300">
                  {data.git_commit}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3. Cards Grid - Renders shell for each card then populates */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Card 1: AI Vision Model (INT8) */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-500" />
              AI Vision Model (INT8)
            </span>
            {error ? (
              <span className="text-[11px] font-bold text-red-500 flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> Could not load
              </span>
            ) : loading ? (
              <span className="text-[11px] font-bold text-slate-400 animate-pulse">Loading...</span>
            ) : data?.model_loaded ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Ready
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-amber-500">
                <AlertTriangle className="w-3.5 h-3.5" /> Initializing
              </span>
            )}
          </div>

          {error ? (
            <div className="py-4 text-center">
              <p className="text-xs text-slate-400">Could not load model diagnostics.</p>
              <button onClick={handleManualRefresh} className="mt-2 text-xs text-emerald-600 hover:underline font-semibold">
                Retry
              </button>
            </div>
          ) : loading ? (
            <div className="space-y-2 py-2 animate-pulse">
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-3/4" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-2/3" />
            </div>
          ) : (
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between text-slate-500">
                <span>Model Architecture:</span>
                <span className="font-mono text-slate-800 dark:text-slate-200 text-[11px] truncate max-w-[160px]" title={data?.model_name}>
                  {data?.model_name || 'CLIP ViT-B/32 INT8'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Vector Dimension:</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">{data?.vector_dimension || 512}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Last Embedding Latency:</span>
                <span className="font-mono text-slate-800 dark:text-slate-200">
                  {data?.embed_ms_last != null ? `${data.embed_ms_last} ms` : 'No recent scans'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Avg Embedding Latency:</span>
                <span className="font-mono text-slate-800 dark:text-slate-200">
                  {data?.embed_ms_avg != null ? `${data.embed_ms_avg} ms` : 'No recent scans'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Card 2: Database & Vectors (Real Catalog State) */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-500" />
              PostgreSQL Database
            </span>
            {error ? (
              <span className="text-[11px] font-bold text-red-500 flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> Could not load
              </span>
            ) : loading ? (
              <span className="text-[11px] font-bold text-slate-400 animate-pulse">Loading...</span>
            ) : data?.database_ok ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Connected
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-red-500">
                <XCircle className="w-3.5 h-3.5" /> Disconnected
              </span>
            )}
          </div>

          {error ? (
            <div className="py-4 text-center">
              <p className="text-xs text-slate-400">Could not load database telemetry.</p>
              <button onClick={handleManualRefresh} className="mt-2 text-xs text-emerald-600 hover:underline font-semibold">
                Retry
              </button>
            </div>
          ) : loading ? (
            <div className="space-y-2 py-2 animate-pulse">
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-2/3" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-4/5" />
            </div>
          ) : (
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between text-slate-500">
                <span>Total Catalog Items:</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {data?.total_products != null ? data.total_products : 'Could not load'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Enrolled Products:</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {data?.products_enrolled != null ? data.products_enrolled : 'Could not load'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Vectors Count:</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {data?.vectors_count != null ? data.vectors_count : 'Could not load'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500 pt-1 border-t border-slate-100 dark:border-slate-800">
                <span>Catalog State:</span>
                <span className={`text-right ${catalogState?.color || 'text-slate-800 dark:text-slate-200'}`}>
                  {catalogState?.label || 'Could not load'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Card 3: Memory & Storage (Real Peak Margin) */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-emerald-500" />
              Instance Memory & Disk
            </span>
            {error ? (
              <span className="text-[11px] font-bold text-red-500 flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> Could not load
              </span>
            ) : loading ? (
              <span className="text-[11px] font-bold text-slate-400 animate-pulse">Loading...</span>
            ) : data?.storage_ok ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Storage OK
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-red-500">
                <XCircle className="w-3.5 h-3.5" /> Read-Only
              </span>
            )}
          </div>

          {error ? (
            <div className="py-4 text-center">
              <p className="text-xs text-slate-400">Could not load memory telemetry.</p>
              <button onClick={handleManualRefresh} className="mt-2 text-xs text-emerald-600 hover:underline font-semibold">
                Retry
              </button>
            </div>
          ) : loading ? (
            <div className="space-y-2 py-2 animate-pulse">
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-3/4" />
              <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-2/3" />
            </div>
          ) : (
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between text-slate-500">
                <span>Resident Memory (RSS):</span>
                <span className="font-mono text-slate-800 dark:text-slate-200">
                  {data?.memory_rss_mb != null ? `${Number(data.memory_rss_mb).toFixed(1)} MB` : 'Could not load'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>RAM Budget:</span>
                <span className="text-slate-800 dark:text-slate-200">
                  {data?.ram_budget_mb != null ? `${data.ram_budget_mb} MB (Render Free)` : '512 MB'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500 pt-1 border-t border-slate-100 dark:border-slate-800">
                <span>Peak Margin:</span>
                <span className={
                  peakMargin?.status === 'GOOD' ? 'text-emerald-600 dark:text-emerald-400 font-semibold' :
                  peakMargin?.status === 'MODERATE' ? 'text-amber-500 font-semibold' :
                  'text-red-500 font-semibold'
                }>
                  {peakMargin?.label || 'Could not load'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 4. Scan Worker & Storage Metrics Card */}
      <div className="p-5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800/80 pb-3">
          <div className="flex items-center gap-2.5">
            <Layers className="w-4 h-4 text-purple-500" />
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">
              360° Vision Scan Worker & Frame Storage
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Storage Driver:</span>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200/50 dark:border-purple-800/40">
              {error ? 'Could not load' : loading ? '...' : (data?.storage_type || 'Supabase Storage')}
            </span>
          </div>
        </div>

        {error ? (
          <div className="py-6 text-center">
            <p className="text-xs text-slate-400">Could not load scan worker telemetry.</p>
            <button onClick={handleManualRefresh} className="mt-2 text-xs text-emerald-600 hover:underline font-semibold">
              Retry
            </button>
          </div>
        ) : loading ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 animate-pulse py-2">
            <div className="h-12 bg-slate-100 dark:bg-slate-800 rounded-xl" />
            <div className="h-12 bg-slate-100 dark:bg-slate-800 rounded-xl" />
            <div className="h-12 bg-slate-100 dark:bg-slate-800 rounded-xl" />
            <div className="h-12 bg-slate-100 dark:bg-slate-800 rounded-xl" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Top Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800/60">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Last Job ID
                </span>
                <span className="text-xs font-mono font-bold text-slate-800 dark:text-slate-200 truncate block mt-0.5" title={workerMetrics.last_job_id || 'None'}>
                  {workerMetrics.last_job_id ? `${workerMetrics.last_job_id.slice(0, 13)}...` : 'None'}
                </span>
              </div>

              <div className="p-3 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800/60">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Total Job Duration
                </span>
                <span className="text-xs font-mono font-bold text-slate-800 dark:text-slate-200 block mt-0.5">
                  {workerMetrics.total_duration_ms ? `${(workerMetrics.total_duration_ms / 1000).toFixed(2)}s` : 'N/A'}
                </span>
              </div>

              <div className="p-3 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800/60">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Last Job Status
                </span>
                <span className={`text-xs font-bold block mt-0.5 ${
                  workerMetrics.last_job_status === 'ENROLLED' ? 'text-emerald-600 dark:text-emerald-400' :
                  workerMetrics.last_job_status === 'FAILED' ? 'text-red-500' :
                  'text-slate-600 dark:text-slate-300'
                }`}>
                  {workerMetrics.last_job_status || 'IDLE'}
                </span>
              </div>

              <div className="p-3 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800/60">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Frames Processed
                </span>
                <span className="text-xs font-mono font-bold text-slate-800 dark:text-slate-200 block mt-0.5">
                  {workerMetrics.frames_processed ?? 0}
                </span>
              </div>
            </div>

            {/* Per-Stage Execution Times Breakdown */}
            <div className="p-3.5 bg-slate-50/70 dark:bg-slate-900/40 rounded-xl border border-slate-100 dark:border-slate-800/60 space-y-2">
              <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300 block">
                Per-Stage Processing Times (Pipeline Benchmarks):
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-y-2 gap-x-4 text-xs">
                <div className="flex justify-between text-slate-500">
                  <span>Storage Download:</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    {workerMetrics.download_storage_ms_avg != null ? `${workerMetrics.download_storage_ms_avg} ms avg` : '0 ms'}
                  </span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Background Removal:</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    {workerMetrics.background_removal_ms_avg != null ? `${workerMetrics.background_removal_ms_avg} ms avg` : '0 ms'}
                  </span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Crop & Resize:</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    {workerMetrics.crop_resize_ms_avg != null ? `${workerMetrics.crop_resize_ms_avg} ms avg` : '0 ms'}
                  </span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Embedding Generation:</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    {workerMetrics.embedding_ms_avg != null ? `${workerMetrics.embedding_ms_avg} ms avg` : '0 ms'}
                  </span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Database Save:</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    {workerMetrics.database_save_ms_total != null ? `${workerMetrics.database_save_ms_total} ms` : '0 ms'}
                  </span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Total Duration:</span>
                  <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                    {workerMetrics.total_duration_ms != null ? `${workerMetrics.total_duration_ms} ms` : '0 ms'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 5. Alembic Database Migration Revisions Card */}
      <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
            <Database className="w-4 h-4 text-blue-500" />
            Database Schema & Migration Status
          </span>
          {error ? (
            <span className="text-[11px] font-bold text-red-500 flex items-center gap-1">
              <XCircle className="w-3.5 h-3.5" /> Could not load
            </span>
          ) : loading ? (
            <span className="text-[11px] font-bold text-slate-400 animate-pulse">Loading...</span>
          ) : data?.schema_ok ? (
            <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" /> Schema Up to Date
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[11px] font-bold text-amber-500">
              <AlertTriangle className="w-3.5 h-3.5" /> Migration Required
            </span>
          )}
        </div>

        {error ? (
          <div className="py-2 text-center">
            <p className="text-xs text-slate-400">Could not load migration state.</p>
          </div>
        ) : loading ? (
          <div className="space-y-2 py-2 animate-pulse">
            <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
            <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-2/3" />
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div className="flex justify-between text-slate-500 p-2 bg-slate-50 dark:bg-slate-900/50 rounded-xl">
              <span>Current Revision:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200 font-semibold">
                {data?.current_revision || 'None (Legacy)'}
              </span>
            </div>
            <div className="flex justify-between text-slate-500 p-2 bg-slate-50 dark:bg-slate-900/50 rounded-xl">
              <span>Head Revision:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200 font-semibold">
                {data?.head_revision || 'None'}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 6. Public Domain & QR Pairing Configuration */}
      <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
            <Zap className="w-4 h-4 text-emerald-500" />
            Public Base URL & QR Pairing Engine
          </span>
          {error ? (
            <span className="text-[11px] font-bold text-red-500 flex items-center gap-1">
              <XCircle className="w-3.5 h-3.5" /> Could not load
            </span>
          ) : loading ? (
            <span className="text-[11px] font-bold text-slate-400 animate-pulse">Loading...</span>
          ) : data?.base_url_valid ? (
            <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" /> Configured & Ready
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[11px] font-bold text-amber-500">
              <AlertTriangle className="w-3.5 h-3.5" /> Configuration Required
            </span>
          )}
        </div>

        {error ? (
          <div className="py-2 text-center">
            <p className="text-xs text-slate-400">Could not load base URL state.</p>
          </div>
        ) : loading ? (
          <div className="space-y-2 py-2 animate-pulse">
            <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
          </div>
        ) : (
          <div className="space-y-2 text-xs">
            <div className="flex justify-between items-center p-2 bg-slate-50 dark:bg-slate-900/50 rounded-xl">
              <span className="text-slate-500">Public Base URL Host:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200 font-bold">
                {data?.base_url_host ? data.base_url_host : 'None (Set BASE_URL)'}
              </span>
            </div>
            {data?.base_url_warning && (
              <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-300 text-[11px] font-medium">
                {data.base_url_warning} (e.g. <code>https://cart-9tds.vercel.app</code>)
              </div>
            )}
          </div>
        )}
      </div>

      {/* 7. Active Cart Pending Items AI Diagnostics */}
      <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-500" />
            Active Cart Pending Items & Vector Diagnostics
          </span>
          <span className="text-[11px] font-mono text-slate-400">
            {data?.pending_items_diagnostics?.length || 0} pending item(s)
          </span>
        </div>

        {error ? (
          <div className="py-2 text-center">
            <p className="text-xs text-slate-400">Could not load pending items diagnostics.</p>
          </div>
        ) : loading ? (
          <div className="space-y-2 py-2 animate-pulse">
            <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-2/3" />
            <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-1/2" />
          </div>
        ) : (data?.pending_items_diagnostics && data.pending_items_diagnostics.length > 0) ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-100 dark:border-slate-800 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
                  <th className="py-2 px-2">Cart</th>
                  <th className="py-2 px-2">Product Name</th>
                  <th className="py-2 px-2">Barcode</th>
                  <th className="py-2 px-2">Has Vectors</th>
                  <th className="py-2 px-2">Vector Count</th>
                  <th className="py-2 px-2">Version Mismatch</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono">
                {data.pending_items_diagnostics.map((item: any) => (
                  <tr key={item.item_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                    <td className="py-2 px-2 font-bold text-slate-900 dark:text-white">{item.cart_number}</td>
                    <td className="py-2 px-2 font-sans font-medium text-slate-800 dark:text-slate-200">{item.product_name}</td>
                    <td className="py-2 px-2 text-slate-500">{item.scanned_barcode}</td>
                    <td className="py-2 px-2">
                      {item.has_vectors ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800/40 font-sans">
                          <CheckCircle2 className="w-3 h-3" /> Yes
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 px-2 py-0.5 rounded-full border border-red-200 dark:border-red-800/40 font-sans">
                          <XCircle className="w-3 h-3" /> NO VECTORS
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-slate-700 dark:text-slate-300 font-semibold">{item.vector_count}</td>
                    <td className="py-2 px-2">
                      {item.preprocessing_version_mismatch_count > 0 ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-800/40 font-sans">
                          {item.preprocessing_version_mismatch_count} outdated
                        </span>
                      ) : (
                        <span className="text-slate-400 text-[11px]">0 mismatches</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-slate-400">
            No active cart items currently pending AI camera verification.
          </div>
        )}
      </div>
      <div className="p-4 bg-blue-50/70 dark:bg-blue-950/30 border border-blue-200/80 dark:border-blue-900/50 rounded-2xl space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-blue-900 dark:text-blue-300">
          <Clock className="w-4 h-4 text-blue-500 shrink-0" />
          Render Inactivity Sleep & Keepalive Architecture
        </div>
        <p className="text-xs text-blue-800/80 dark:text-blue-300/80 leading-relaxed">
          On Render Free Tier, backend web services spin down after 15 minutes of inactivity. To prevent shopper connection delays, the frontend automatically pings <code className="font-mono text-[11px] bg-blue-100 dark:bg-blue-900/60 px-1 py-0.5 rounded">/health</code> as soon as the shopper portal opens. For permanent zero-cold-start operation, configure a free HTTP monitor (e.g., UptimeRobot, Cron-Job.org) to ping <code className="font-mono text-[11px] bg-blue-100 dark:bg-blue-900/60 px-1 py-0.5 rounded">/health</code> every 10 minutes.
        </p>
      </div>
    </div>
  );
};
