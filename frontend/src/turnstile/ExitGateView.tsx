import React, { useState, useEffect } from 'react';
import { QrCode, CheckCircle2, Lock, Unlock, ShieldCheck, ArrowRight, RefreshCw, AlertCircle } from 'lucide-react';
import { api } from '../services/api';
import { audioFeedback } from '../services/audioFeedback';

export const ExitGateView: React.FC = () => {
  const [tokenInput, setTokenInput] = useState('');
  const [gateUnlocked, setGateUnlocked] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleVerify = async (tokenToTest?: string) => {
    const token = tokenToTest || tokenInput;
    if (!token) return;

    setLoading(true);
    setError(null);
    try {
      const res = await api.verifyExitGate(token);
      setResult(res);
      if (res.gate_unlocked) {
        setGateUnlocked(true);
        audioFeedback.playItemVerified();
        setTimeout(() => {
          setGateUnlocked(false);
        }, 8000); // Re-locks gate after 8 seconds
      } else {
        audioFeedback.playWarning();
        setError(res.message);
      }
    } catch (err: any) {
      setError(err.message || 'Verification failed');
      audioFeedback.playWarning();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="text-center space-y-1 pb-4 border-b border-slate-200 dark:border-slate-800">
        <div className="inline-flex items-center gap-2 p-2 px-3 rounded-full bg-slate-900 text-white text-xs font-mono mb-1">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>SUPERMARKET TURNSTILE BARRIER GATE #01</span>
        </div>
        <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
          Store Exit Gate Scanner
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Scans shopper's digital receipt exit QR pass to confirm payment and unlock the automatic turnstile.
        </p>
      </div>

      {/* Turnstile Physical Gate State Simulator */}
      <div className={`p-8 rounded-3xl border-2 transition-all flex flex-col items-center justify-center text-center space-y-4 shadow-xl ${
        gateUnlocked
          ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500 shadow-emerald-500/20'
          : 'bg-slate-900 border-slate-800 text-white shadow-slate-950/50'
      }`}>
        <div className={`w-24 h-24 rounded-full flex items-center justify-center transition-all shadow-inner ${
          gateUnlocked
            ? 'bg-emerald-500 text-white animate-bounce-subtle'
            : 'bg-red-500/20 text-red-500 border-2 border-red-500/40'
        }`}>
          {gateUnlocked ? <Unlock className="w-12 h-12" /> : <Lock className="w-12 h-12" />}
        </div>

        <div>
          <div className="text-xl font-bold font-display uppercase tracking-wider">
            {gateUnlocked ? '🟢 TURNSTILE UNLOCKED • PROCEED' : '🔴 GATE LOCKED • SCAN RECEIPT'}
          </div>
          <p className={`text-xs mt-1 ${gateUnlocked ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-400'}`}>
            {gateUnlocked
              ? 'Paid status verified! Optical gate barrier open for departure.'
              : 'Optical gate barrier locked. Present your digital receipt QR to exit.'}
          </p>
        </div>

        {/* Turnstile Physical Barrier Graphic */}
        <div className="w-full max-w-sm flex items-center justify-between gap-2 pt-2">
          <div className={`h-3 flex-1 rounded-full transition-all ${gateUnlocked ? 'bg-emerald-500 -rotate-45' : 'bg-red-500'}`} />
          <div className="w-4 h-4 rounded-full bg-slate-700" />
          <div className={`h-3 flex-1 rounded-full transition-all ${gateUnlocked ? 'bg-emerald-500 rotate-45' : 'bg-red-500'}`} />
        </div>
      </div>

      {/* Verification Scanner Input */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
        <label className="block text-xs font-semibold text-slate-500 uppercase">
          Enter or Scan Receipt Exit Token
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="e.g. EXIT-REC-20261020-XXXX-..."
            className="flex-1 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-xs font-mono text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button
            onClick={() => handleVerify()}
            disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-6 rounded-xl text-xs flex items-center gap-1.5 shadow-md shadow-emerald-600/30 active:scale-95 transition-all"
          >
            <QrCode className="w-4 h-4" />
            Verify Gate
          </button>
        </div>

        {error && (
          <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 rounded-xl text-xs text-red-600 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {result && result.gate_unlocked && (
          <div className="p-4 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-2xl text-xs space-y-1 text-slate-700 dark:text-slate-300">
            <div className="font-bold text-emerald-700 dark:text-emerald-300 flex items-center gap-1.5 text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span>{result.message}</span>
            </div>
            <div>Receipt Number: <strong className="font-mono text-slate-900 dark:text-white">{result.receipt_number}</strong></div>
            <div>Cart: <strong className="font-mono text-slate-900 dark:text-white">{result.cart_number}</strong> • Paid Amount: <strong className="text-emerald-600 font-mono">₹{result.amount_paid.toFixed(2)}</strong></div>
          </div>
        )}
      </div>
    </div>
  );
};
