import React, { useState, useEffect } from 'react';
import { ShieldAlert, AlertTriangle, CheckCircle, Clock, Search, X, Check, Eye } from 'lucide-react';
import { AdminAlert } from '../types';
import { api } from '../services/api';

export const AlertFeedView: React.FC = () => {
  const [alerts, setAlerts] = useState<AdminAlert[]>([]);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'OPEN' | 'RESOLVED'>('OPEN');
  const [selectedAlert, setSelectedAlert] = useState<AdminAlert | null>(null);
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchAlerts = async () => {
    try {
      const data = await api.getAdminAlerts(statusFilter === 'ALL' ? undefined : statusFilter);
      setAlerts(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 4000);
    return () => clearInterval(interval);
  }, [statusFilter]);

  const handleResolve = async (action: 'RESOLVED' | 'DISMISSED') => {
    if (!selectedAlert) return;
    setLoading(true);
    try {
      await api.resolveAlert(selectedAlert.id, resolutionNotes || 'Resolved by floor manager.', action);
      setSelectedAlert(null);
      setResolutionNotes('');
      fetchAlerts();
    } catch (e) {
      alert('Failed to update alert');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
            Incident & Alert Triage
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Real-time theft prevention alerts, unscanned items, mismatches, and camera occlusion incidents.
          </p>
        </div>

        {/* Status Filter */}
        <div className="flex bg-slate-100 dark:bg-slate-900 p-1 rounded-2xl border border-slate-200 dark:border-slate-800 text-xs font-semibold">
          {(['OPEN', 'RESOLVED', 'ALL'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-xl transition-all ${
                statusFilter === s
                  ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Alert Feed Table / Cards */}
      {alerts.length === 0 ? (
        <div className="bg-white dark:bg-[#131B2E] border border-dashed border-slate-200 dark:border-slate-800 rounded-3xl p-12 text-center text-slate-400 text-xs">
          No {statusFilter.toLowerCase()} alerts found. All shopping sessions operating with high integrity.
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => (
            <div
              key={alert.id}
              className={`bg-white dark:bg-[#131B2E] border rounded-2xl p-4 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${
                alert.status === 'OPEN'
                  ? 'border-red-200 dark:border-red-900/60 shadow-red-500/5'
                  : 'border-slate-200 dark:border-slate-800 opacity-75'
              }`}
            >
              <div className="flex items-start gap-3.5">
                {/* Severity Badge */}
                <div
                  className={`p-2.5 rounded-2xl flex-shrink-0 ${
                    alert.severity === 'HIGH' || alert.severity === 'CRITICAL'
                      ? 'bg-red-100 dark:bg-red-950/60 text-red-600'
                      : 'bg-amber-100 dark:bg-amber-950/60 text-amber-600'
                  }`}
                >
                  <AlertTriangle className="w-5 h-5" />
                </div>

                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-xs bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2 py-0.5 rounded-lg border border-slate-200 dark:border-slate-700">
                      {alert.cart_number}
                    </span>
                    <h3 className="font-semibold text-sm text-slate-900 dark:text-white">
                      {alert.message}
                    </h3>
                  </div>

                  <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 mt-1.5">
                    <span>Type: <strong className="text-slate-600 dark:text-slate-300">{alert.alert_type}</strong></span>
                    <span>•</span>
                    <span>Severity: <strong className={alert.severity === 'HIGH' ? 'text-red-500' : 'text-amber-500'}>{alert.severity}</strong></span>
                    <span>•</span>
                    <span>{new Date(alert.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 self-end sm:self-center">
                {alert.status === 'OPEN' ? (
                  <button
                    onClick={() => setSelectedAlert(alert)}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-sm flex items-center gap-1.5 active:scale-95 transition-all"
                  >
                    <Check className="w-3.5 h-3.5" />
                    Review & Resolve
                  </button>
                ) : (
                  <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                    <CheckCircle className="w-4 h-4" />
                    Resolved
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Resolve Incident Dialog Modal */}
      {selectedAlert && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-lg p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <div>
                <h3 className="font-bold text-base font-display text-slate-900 dark:text-white">
                  Resolve Incident: {selectedAlert.cart_number}
                </h3>
                <p className="text-xs text-slate-400">{selectedAlert.alert_type}</p>
              </div>
              <button
                onClick={() => setSelectedAlert(null)}
                className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="p-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/40 rounded-2xl text-xs text-red-700 dark:text-red-300">
                {selectedAlert.message}
              </div>

              {selectedAlert.evidence_snapshot_url && (
                <div>
                  <label className="block text-xs font-semibold text-slate-400 uppercase mb-1">
                    Cart Camera Evidence Snapshot
                  </label>
                  <img
                    src={selectedAlert.evidence_snapshot_url}
                    alt="Evidence"
                    className="w-full h-40 object-cover rounded-2xl border border-slate-200 dark:border-slate-700"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">
                  Staff Resolution Notes
                </label>
                <textarea
                  rows={3}
                  value={resolutionNotes}
                  onChange={(e) => setResolutionNotes(e.target.value)}
                  placeholder="e.g. Associate assisted customer to scan item barcode on shelf."
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white text-xs rounded-xl p-3 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={() => handleResolve('DISMISSED')}
                disabled={loading}
                className="flex-1 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-200 text-xs font-semibold py-2.5 rounded-xl transition-all"
              >
                Dismiss (False Alarm)
              </button>
              <button
                onClick={() => handleResolve('RESOLVED')}
                disabled={loading}
                className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold py-2.5 rounded-xl shadow-md shadow-emerald-600/30 transition-all"
              >
                Confirm Resolution
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
