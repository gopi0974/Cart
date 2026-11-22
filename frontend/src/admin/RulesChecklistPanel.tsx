import React, { useState, useEffect } from 'react';
import {
  CheckCircle2,
  ShieldCheck,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Lock,
  Layers,
  Cpu,
  RefreshCw,
  EyeOff,
  ShoppingBag
} from 'lucide-react';
import { api } from '../services/api';

interface Props {
  selectedCartId?: string;
  cartNumber?: string;
}

export const RulesChecklistPanel: React.FC<Props> = ({ selectedCartId, cartNumber }) => {
  const [rules, setRules] = useState<any[]>([]);
  const [cartStatus, setCartStatus] = useState<any | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRule, setExpandedRule] = useState<string | null>(null);

  const loadChecklist = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getRulesChecklist(selectedCartId);
      setRules(resp.rules || []);
      setCartStatus(resp.cart_status || null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load rules checklist');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadChecklist();
  }, [selectedCartId]);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="p-5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold font-display text-slate-900 dark:text-white">
                Cart State Machine Rules Checklist
              </h2>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
                10 / 10 Enforced
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Strict formal verification matrix governed by <code className="text-purple-500 font-mono">cart_state_machine.py</code>
            </p>
          </div>
        </div>

        <button
          onClick={loadChecklist}
          disabled={loading}
          className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition-colors self-start sm:self-auto"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Status</span>
        </button>
      </div>

      {/* Cart Real-Time Compliance Summary (if cart selected) */}
      {cartStatus && (
        <div className="p-4 bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-2xl space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <ShoppingBag className="w-4 h-4 text-purple-500" />
              Live Cart Compliance: {cartStatus.cart_number || cartNumber}
            </span>
            <span className="text-[11px] font-mono text-slate-400">
              Camera: {cartStatus.camera_status} • Session: {cartStatus.session_id ? cartStatus.session_id.slice(0, 8) : 'None'}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
            <div className="p-2.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-400 block">R1 Empty Start</span>
              <div className="font-bold flex items-center gap-1 text-[11px]">
                {cartStatus.cart_empty_verified ? (
                  <span className="text-emerald-500 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Verified</span>
                ) : (
                  <span className="text-amber-500 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" /> Awaiting Empty</span>
                )}
              </div>
            </div>

            <div className="p-2.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-400 block">R2 Pending Item</span>
              <div className="font-bold flex items-center gap-1 text-[11px]">
                {cartStatus.pending_count === 0 ? (
                  <span className="text-slate-500 font-normal">0 pending</span>
                ) : cartStatus.pending_count === 1 ? (
                  <span className="text-purple-500">1 item pending</span>
                ) : (
                  <span className="text-red-500">Blocked ({cartStatus.pending_count})</span>
                )}
              </div>
            </div>

            <div className="p-2.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-400 block">R5 Removing</span>
              <div className="font-bold flex items-center gap-1 text-[11px]">
                {cartStatus.removing_count === 0 ? (
                  <span className="text-emerald-500">None</span>
                ) : (
                  <span className="text-amber-500 font-semibold">{cartStatus.removing_count} in progress</span>
                )}
              </div>
            </div>

            <div className="p-2.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-400 block">R6 Violations</span>
              <div className="font-bold flex items-center gap-1 text-[11px]">
                {cartStatus.open_alerts_count === 0 ? (
                  <span className="text-emerald-500 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> 0 open</span>
                ) : (
                  <span className="text-red-500 font-bold">{cartStatus.open_alerts_count} active</span>
                )}
              </div>
            </div>

            <div className="p-2.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-400 block">R9 Checkout</span>
              <div className="font-bold flex items-center gap-1 text-[11px]">
                {cartStatus.r9_passed ? (
                  <span className="text-emerald-500 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Eligible</span>
                ) : (
                  <span className="text-slate-400 font-normal">Blocked</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Rules List (R1 - R10) */}
      <div className="space-y-3">
        {loading && rules.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-16 bg-slate-100 dark:bg-slate-800/60 rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="p-6 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/40 rounded-2xl text-xs text-red-600 dark:text-red-400 text-center">
            {error}
          </div>
        ) : (
          rules.map((rule) => {
            const isExpanded = expandedRule === rule.id;
            return (
              <div
                key={rule.id}
                className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden transition-all"
              >
                <div
                  onClick={() => setExpandedRule(isExpanded ? null : rule.id)}
                  className="p-4 flex items-center justify-between gap-3 cursor-pointer hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-8 h-8 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-600 dark:text-purple-400 font-mono text-xs font-bold flex items-center justify-center shrink-0">
                      {rule.id}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-900 dark:text-white">
                          {rule.name}
                        </span>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 font-mono">
                          {rule.status}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{rule.summary}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="hidden sm:inline-block px-2 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 font-mono text-[10px] text-slate-600 dark:text-slate-300">
                      Code: {rule.reason_code}
                    </span>
                    <div className="p-1 text-slate-400 hover:text-slate-600">
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-slate-100 dark:border-slate-800 p-4 bg-slate-50/50 dark:bg-slate-900/40 text-xs space-y-3">
                    <div>
                      <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider block">
                        Full Requirement Specification
                      </span>
                      <p className="text-slate-700 dark:text-slate-300 mt-1 leading-relaxed">
                        {rule.summary}
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
                        <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider block flex items-center gap-1">
                          <Cpu className="w-3.5 h-3.5 text-purple-500" /> State Machine Enforcement
                        </span>
                        <div className="font-mono text-[11px] text-purple-600 dark:text-purple-400 font-semibold break-words">
                          {rule.enforcement}
                        </div>
                      </div>

                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
                        <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider block flex items-center gap-1">
                          <Lock className="w-3.5 h-3.5 text-amber-500" /> Scan Block Reason
                        </span>
                        <div className="font-mono text-[11px] text-slate-800 dark:text-slate-200 font-bold">
                          HTTP 409: {rule.reason_code}
                        </div>
                      </div>

                      <div className="p-3 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
                        <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider block flex items-center gap-1">
                          <EyeOff className="w-3.5 h-3.5 text-emerald-500" /> Privacy & Audit Gate
                        </span>
                        <div className="text-[11px] text-slate-600 dark:text-slate-400 leading-normal">
                          {rule.privacy_gate}
                        </div>
                      </div>
                    </div>
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
