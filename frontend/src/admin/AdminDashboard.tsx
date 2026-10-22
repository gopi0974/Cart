import React, { useState, useEffect } from 'react';
import { ShoppingCart, AlertTriangle, TrendingUp, CheckCircle, ShieldAlert, ArrowUpRight, Zap, RefreshCw } from 'lucide-react';
import { api } from '../services/api';

interface Props {
  onNavigate: (tab: string) => void;
}

export const AdminDashboard: React.FC<Props> = ({ onNavigate }) => {
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      const data = await api.getAdminOverview();
      setMetrics(data);
    } catch (e) {
      console.error('Failed to load admin overview:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000); // 5s polling for live metrics
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
            Operations Executive Overview
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Real-time supermarket fleet performance, theft prevention, and AI verification telemetry.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 text-slate-600 dark:text-slate-300 transition-all text-xs flex items-center gap-1.5 shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Active Carts */}
        <div
          onClick={() => onNavigate('FLEET')}
          className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center justify-between text-slate-500 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Active Carts</span>
            <span className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 group-hover:scale-110 transition-transform">
              <ShoppingCart className="w-4 h-4" />
            </span>
          </div>
          <div className="text-3xl font-bold font-display text-slate-900 dark:text-white">
            {metrics?.active_carts || 0} <span className="text-base font-normal text-slate-400">/ {metrics?.total_carts || 12}</span>
          </div>
          <div className="mt-2 text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1 font-medium">
            <ArrowUpRight className="w-3.5 h-3.5" />
            Fleet utilization online
          </div>
        </div>

        {/* Revenue Today */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Sales Today</span>
            <span className="p-2 rounded-xl bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400">
              <TrendingUp className="w-4 h-4" />
            </span>
          </div>
          <div className="text-3xl font-bold font-display text-slate-900 dark:text-white font-mono">
            ₹{(metrics?.revenue_today || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <div className="mt-2 text-xs text-blue-600 dark:text-blue-400 flex items-center gap-1 font-medium">
            Autonomous queue-less checkouts
          </div>
        </div>

        {/* AI Accuracy */}
        <div
          onClick={() => onNavigate('MODELS')}
          className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center justify-between text-slate-500 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">AI Accuracy</span>
            <span className="p-2 rounded-xl bg-purple-50 dark:bg-purple-950/50 text-purple-600 dark:text-purple-400 group-hover:scale-110 transition-transform">
              <CheckCircle className="w-4 h-4" />
            </span>
          </div>
          <div className="text-3xl font-bold font-display text-slate-900 dark:text-white font-mono">
            {metrics?.ai_accuracy || 98.4}%
          </div>
          <div className="mt-2 text-xs text-purple-600 dark:text-purple-400 flex items-center gap-1 font-medium">
            DINOv2 + YOLOv8 Active
          </div>
        </div>

        {/* Open Alerts */}
        <div
          onClick={() => onNavigate('ALERTS')}
          className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center justify-between text-slate-500 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Open Incidents</span>
            <span className={`p-2 rounded-xl group-hover:scale-110 transition-transform ${
              (metrics?.open_incidents || 0) > 0
                ? 'bg-red-50 dark:bg-red-950/50 text-red-600 animate-pulse'
                : 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600'
            }`}>
              <ShieldAlert className="w-4 h-4" />
            </span>
          </div>
          <div className="text-3xl font-bold font-display text-slate-900 dark:text-white">
            {metrics?.open_incidents || 0}
          </div>
          <div className="mt-2 text-xs font-medium text-slate-500 flex items-center gap-1">
            {(metrics?.open_incidents || 0) > 0 ? (
              <span className="text-red-500 font-semibold">Immediate attention needed</span>
            ) : (
              <span className="text-emerald-500 font-semibold">All carts secure</span>
            )}
          </div>
        </div>
      </div>

      {/* Real-Time Live Alert Stream Feed */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            <h2 className="font-display font-bold text-base text-slate-900 dark:text-white">
              Live Security & Incident Feed
            </h2>
          </div>
          <button
            onClick={() => onNavigate('ALERTS')}
            className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline"
          >
            View All Incidents →
          </button>
        </div>

        {metrics?.recent_alerts?.length === 0 ? (
          <div className="text-center py-8 text-slate-400 text-xs">
            No active incidents. Supermarket cart operations are running normally.
          </div>
        ) : (
          <div className="space-y-2.5">
            {metrics?.recent_alerts?.map((a: any) => (
              <div
                key={a.id}
                className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-4"
              >
                <div className="flex items-center gap-3">
                  <span className={`p-2 rounded-xl ${
                    a.severity === 'HIGH' || a.severity === 'CRITICAL'
                      ? 'bg-red-100 dark:bg-red-950 text-red-600'
                      : 'bg-amber-100 dark:bg-amber-950 text-amber-600'
                  }`}>
                    <AlertTriangle className="w-4 h-4" />
                  </span>
                  <div>
                    <div className="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <span className="font-mono bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 rounded text-[10px]">
                        {a.cart_number}
                      </span>
                      <span>{a.message}</span>
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      Type: {a.alert_type} • Status: <strong className="text-slate-700 dark:text-slate-300">{a.status}</strong>
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => onNavigate('ALERTS')}
                  className="text-xs bg-white dark:bg-slate-800 hover:bg-slate-100 border border-slate-200 dark:border-slate-700 px-3 py-1.5 rounded-xl font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap active:scale-95 transition-all"
                >
                  Review
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
