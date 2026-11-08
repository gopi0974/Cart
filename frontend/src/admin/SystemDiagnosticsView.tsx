import React, { useState } from 'react';
import { Activity, Database, HardDrive, Cpu, CheckCircle2, AlertTriangle, XCircle, RefreshCw, Clock } from 'lucide-react';
import { api } from '../services/api';

interface Props {
  health: any;
  status: 'CONNECTED' | 'WAKING_UP' | 'OFFLINE';
  onRefresh: () => void;
}

export const SystemDiagnosticsView: React.FC<Props> = ({ health, status, onRefresh }) => {
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setTimeout(() => setRefreshing(false), 500);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
            System & Infrastructure
          </span>
          <h1 className="text-xl sm:text-2xl font-bold font-display text-slate-900 dark:text-white">
            Backend Diagnostics & Health
          </h1>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 px-3.5 py-2 rounded-xl text-xs font-semibold hover:border-slate-300 dark:hover:border-slate-700 transition-colors shadow-sm self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-emerald-500' : 'text-slate-400'}`} />
          {refreshing ? 'Probing /health...' : 'Refresh Status'}
        </button>
      </div>

      {/* Main Status Overview Card */}
      <div className="p-5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${
            status === 'CONNECTED' ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400' :
            status === 'WAKING_UP' ? 'bg-amber-50 dark:bg-amber-950/50 text-amber-500' :
            'bg-red-50 dark:bg-red-950/50 text-red-500'
          }`}>
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-slate-900 dark:text-white">
                {status === 'CONNECTED' ? 'Backend Fully Operational' :
                 status === 'WAKING_UP' ? 'Backend Waking Up / Initializing' :
                 'Backend Unreachable'}
              </h2>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase ${
                status === 'CONNECTED' ? 'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-700 dark:text-emerald-300' :
                status === 'WAKING_UP' ? 'bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-300 animate-pulse' :
                'bg-red-100 dark:bg-red-900/60 text-red-700 dark:text-red-300'
              }`}>
                {health?.status || status}
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Verified by live active database pre-ping (<code className="font-mono text-[11px]">SELECT 1</code>) and ONNX runtime state.
            </p>
          </div>
        </div>
      </div>

      {/* Health Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* AI Vision Model Card */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-500" />
              AI Vision Model (INT8)
            </span>
            {health?.model_loaded ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Ready
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-amber-500">
                <AlertTriangle className="w-3.5 h-3.5" /> Loading
              </span>
            )}
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between text-slate-500">
              <span>Model Architecture:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200 text-[11px]">{health?.model_name || 'openai/clip-vit-base-patch32-int8'}</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Vector Dimension:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{health?.vector_dimension || 512}</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Last Embedding Latency:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200">
                {health?.embed_ms_last != null ? `${health.embed_ms_last} ms` : 'Pending real scan'}
              </span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Avg Embedding Latency:</span>
              <span className="font-mono text-slate-800 dark:text-slate-200">
                {health?.embed_ms_avg != null ? `${health.embed_ms_avg} ms` : 'Pending real scan'}
              </span>
            </div>
          </div>
        </div>

        {/* Database & Vectors Card */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-500" />
              PostgreSQL Database
            </span>
            {health?.database_ok ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Connected
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-red-500">
                <XCircle className="w-3.5 h-3.5" /> Disconnected
              </span>
            )}
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between text-slate-500">
              <span>Enrolled Products:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{health?.products_enrolled ?? 0}</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Vectors Count:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{health?.vectors_count ?? 0}</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Catalog State:</span>
              <span className="text-slate-800 dark:text-slate-200">
                {health?.vectors_count === 0 ? 'Needs re-enrollment' : 'Enrolled'}
              </span>
            </div>
          </div>
        </div>

        {/* Memory & Storage Card */}
        <div className="p-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-emerald-500" />
              Instance Memory & Disk
            </span>
            {health?.storage_ok ? (
              <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> Storage OK
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] font-bold text-red-500">
                <XCircle className="w-3.5 h-3.5" /> Read-Only
              </span>
            )}
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between text-slate-500">
              <span>Resident Memory (RSS):</span>
              <span className="font-mono text-slate-800 dark:text-slate-200">
                {health?.memory_rss_mb ? `${health.memory_rss_mb} MB` : 'N/A'}
              </span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>RAM Budget:</span>
              <span className="text-slate-800 dark:text-slate-200">512 MB (Render Free)</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Peak Margin:</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">&gt; 200 MB Free</span>
            </div>
          </div>
        </div>
      </div>

      {/* Free Tier Sleep & Keepalive Notice */}
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

