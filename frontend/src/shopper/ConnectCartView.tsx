import React, { useState } from 'react';
import { QrCode, ShoppingCart, ShieldCheck, Zap, ArrowRight, AlertCircle } from 'lucide-react';
import { api } from '../services/api';
import { CartSession } from '../types';

interface Props {
  onConnected: (session: CartSession) => void;
}

export const ConnectCartView: React.FC<Props> = ({ onConnected }) => {
  const [cartInput, setCartInput] = useState('CART-01');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async (tokenOrNumber: string) => {
    setLoading(true);
    setError(null);
    try {
      const session = await api.pairCart(tokenOrNumber);
      onConnected(session);
    } catch (err: any) {
      setError(err.message || 'Failed to connect to cart. Please check cart number or QR.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto p-5 min-h-[90vh] flex flex-col justify-between">
      <div>
        {/* Brand Header */}
        <div className="text-center mt-6 mb-8">
          <div className="w-16 h-16 bg-emerald-600 dark:bg-emerald-500 rounded-3xl mx-auto flex items-center justify-center text-white shadow-xl shadow-emerald-500/20 mb-4 transform hover:scale-105 transition-transform">
            <ShoppingCart className="w-8 h-8" />
          </div>
          <h1 className="text-2xl font-bold font-display tracking-tight text-slate-900 dark:text-white">
            SmartCart AI
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            SuperMart Autonomous Retail • No Billing Queues
          </p>
        </div>

        {/* QR Scanner Reticle Graphic */}
        <div className="relative border-2 border-dashed border-emerald-500/60 dark:border-emerald-400/50 rounded-3xl p-8 text-center bg-emerald-50/50 dark:bg-emerald-950/20 mb-6 backdrop-blur-sm">
          <div className="w-20 h-20 mx-auto mb-3 text-emerald-600 dark:text-emerald-400 flex items-center justify-center relative">
            <QrCode className="w-16 h-16" />
            <div className="absolute inset-0 border-2 border-emerald-500 rounded-lg animate-ping opacity-25"></div>
          </div>
          <h2 className="font-semibold text-slate-800 dark:text-slate-200 text-base">
            Point camera at Cart Handle QR
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs mx-auto">
            Scan the QR code printed on your shopping cart to pair your phone instantly.
          </p>

          <button
            onClick={() => handleConnect(`QR-${cartInput}`)}
            disabled={loading}
            className="mt-5 w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 px-4 rounded-2xl shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all"
          >
            <Zap className="w-4 h-4 fill-current" />
            {loading ? 'Pairing Cart...' : `Connect to ${cartInput}`}
          </button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/50 rounded-2xl flex items-start gap-3 text-red-700 dark:text-red-400 text-sm">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Manual Cart Selection Fallback */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm">
          <label className="block text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
            Or Select Cart Number Manually
          </label>
          <div className="flex gap-2">
            <select
              value={cartInput}
              onChange={(e) => setCartInput(e.target.value)}
              className="flex-1 bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white rounded-xl px-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((num) => {
                const c = `CART-${num < 10 ? '0' : ''}${num}`;
                return (
                  <option key={c} value={c}>
                    {c} (Floor Level 1)
                  </option>
                );
              })}
            </select>
            <button
              onClick={() => handleConnect(cartInput)}
              disabled={loading}
              className="bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 text-white px-4 rounded-xl flex items-center justify-center"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Privacy Notice Banner */}
      <div className="mt-8 mb-4 p-4 bg-slate-100 dark:bg-slate-900/60 rounded-2xl flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-800">
        <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
        <div>
          <span className="font-semibold text-slate-700 dark:text-slate-300">Privacy Guaranteed: </span>
          The overhead camera strictly monitors cart interior items. No facial recording or biometric identification.
        </div>
      </div>
    </div>
  );
};
