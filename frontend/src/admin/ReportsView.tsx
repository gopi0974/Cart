import React, { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, ShieldCheck, DollarSign, Download, Clock, ShoppingCart, Calendar } from 'lucide-react';
import { api } from '../services/api';

export const ReportsView: React.FC = () => {
  const [timeRange, setTimeRange] = useState<'TODAY' | 'WEEK' | 'MONTH'>('TODAY');
  const [metrics, setMetrics] = useState<any>(null);
  const [reportStats, setReportStats] = useState<any>(null);

  useEffect(() => {
    api.getAdminOverview().then(setMetrics).catch(() => {});
    api.getReports().then(setReportStats).catch(() => {});
  }, []);

  const hourlyData = [
    { time: '09:00', trips: 14, sales: 8400, preventedLoss: 450 },
    { time: '11:00', trips: 28, sales: 16800, preventedLoss: 1200 },
    { time: '13:00', trips: 42, sales: 25200, preventedLoss: 980 },
    { time: '15:00', trips: 35, sales: 21000, preventedLoss: 620 },
    { time: '17:00', trips: 56, sales: 33600, preventedLoss: 2150 },
    { time: '19:00', trips: 48, sales: 28800, preventedLoss: 1400 },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-emerald-500" />
            Financial & Loss Prevention Reports
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Autonomous store analytics, theft interception metrics, and checkout volume reports.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-semibold flex">
            {(['TODAY', 'WEEK', 'MONTH'] as const).map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`px-3 py-1.5 rounded-lg transition-all ${
                  timeRange === r
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                {r === 'TODAY' ? 'Today' : r === 'WEEK' ? '7 Days' : '30 Days'}
              </button>
            ))}
          </div>

          <button
            onClick={() => alert('Exporting CSV financial audit report...')}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 text-slate-600 dark:text-slate-300 transition-all text-xs flex items-center gap-1.5 shadow-sm"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Summary Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase">Total Revenue</span>
            <DollarSign className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            ₹{metrics?.revenue_today?.toLocaleString() || '134,800'}
          </div>
          <div className="text-[11px] text-emerald-600 mt-1 flex items-center gap-1">
            <TrendingUp className="w-3 h-3" />
            +18.4% vs last week
          </div>
        </div>

        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase">Shrinkage Prevented</span>
            <ShieldCheck className="w-4 h-4 text-blue-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            ₹6,800
          </div>
          <div className="text-[11px] text-blue-600 mt-1">
            14 unscanned items intercepted
          </div>
        </div>

        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase">Completed Trips</span>
            <ShoppingCart className="w-4 h-4 text-purple-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            223
          </div>
          <div className="text-[11px] text-purple-600 mt-1">
            Avg. 4.2 mins per customer
          </div>
        </div>

        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase">AI Accuracy</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900 dark:text-white">
            98.6%
          </div>
          <div className="text-[11px] text-amber-600 mt-1">
            Zero queue congestion
          </div>
        </div>
      </div>

      {/* Hourly Throughput Table */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm">
        <h3 className="font-display font-bold text-sm text-slate-900 dark:text-white mb-4">
          Hourly Throughput & Security Interceptions
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 uppercase font-mono">
                <th className="py-2.5 px-3">Time Window</th>
                <th className="py-2.5 px-3">Cart Trips</th>
                <th className="py-2.5 px-3">Gross Sales</th>
                <th className="py-2.5 px-3">Shrinkage Intercepted</th>
                <th className="py-2.5 px-3">Verification Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {hourlyData.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-3 font-mono font-medium text-slate-800 dark:text-slate-200">{row.time} - {row.time.replace(/:\d\d/, ':59')}</td>
                  <td className="py-3 px-3 font-mono">{row.trips} trips</td>
                  <td className="py-3 px-3 font-mono text-emerald-600 dark:text-emerald-400 font-bold">₹{row.sales.toLocaleString()}</td>
                  <td className="py-3 px-3 font-mono text-amber-600 dark:text-amber-400">₹{row.preventedLoss.toLocaleString()}</td>
                  <td className="py-3 px-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 border border-emerald-200 dark:border-emerald-800/40">
                      98.8% Verified
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
