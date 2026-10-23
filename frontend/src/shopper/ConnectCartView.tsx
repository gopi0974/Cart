import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { QrCode, ShoppingCart, ShieldCheck, Zap, ArrowRight, AlertTriangle, ShieldAlert, CheckCircle2, Lock } from 'lucide-react';
import { api } from '../services/api';
import { CartSession } from '../types';
import { useTranslation } from '../services/i18n';

interface Props {
  onConnected: (session: CartSession) => void;
}

export const ConnectCartView: React.FC<Props> = ({ onConnected }) => {
  const [searchParams] = useSearchParams();
  const [cartInput, setCartInput] = useState('CART-001');
  const [phoneInput, setPhoneInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ title?: string; message: string; type?: 'security' | 'disabled' | 'occupied' | 'generic' } | null>(null);
  const { t } = useTranslation();
  const hasAutoAttempted = useRef(false);

  // Check URL search parameters (from scanned QR code: /user/connect?cart=CART-001&token=...&sig=...)
  useEffect(() => {
    const cartParam = searchParams.get('cart');
    const tokenParam = searchParams.get('token');
    const sigParam = searchParams.get('sig');
    const phoneParam = searchParams.get('phone') || undefined;

    if (cartParam && tokenParam && !hasAutoAttempted.current) {
      hasAutoAttempted.current = true;
      setLoading(true);
      setError(null);
      
      api.connectViaQR(cartParam, tokenParam, sigParam || undefined, phoneParam)
        .then((session) => {
          // Clean URL params cleanly
          window.history.replaceState({}, '', window.location.pathname);
          onConnected(session);
        })
        .catch((err: any) => {
          const msg: string = err.message || 'Failed to connect to cart.';
          let type: 'security' | 'disabled' | 'occupied' | 'generic' = 'generic';
          let title = 'Connection Failed';

          if (msg.toLowerCase().includes('signature') || msg.toLowerCase().includes('security') || msg.toLowerCase().includes('tamper')) {
            type = 'security';
            title = 'Security Verification Failed';
          } else if (msg.toLowerCase().includes('disabled')) {
            type = 'disabled';
            title = 'Cart Temporarily Disabled';
          } else if (msg.toLowerCase().includes('occupied') || msg.toLowerCase().includes('active shopper')) {
            type = 'occupied';
            title = 'Cart In Use';
          }

          setError({ title, message: msg, type });
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [searchParams, onConnected]);

  const handleConnect = async (tokenOrNumber: string) => {
    setLoading(true);
    setError(null);
    try {
      const session = await api.pairCart(tokenOrNumber, phoneInput || undefined);
      onConnected(session);
    } catch (err: any) {
      const msg: string = err.message || 'Failed to connect to cart. Please check cart number or QR.';
      let type: 'security' | 'disabled' | 'occupied' | 'generic' = 'generic';
      let title = 'Connection Failed';

      if (msg.toLowerCase().includes('signature') || msg.toLowerCase().includes('security') || msg.toLowerCase().includes('tamper')) {
        type = 'security';
        title = 'Security Verification Failed';
      } else if (msg.toLowerCase().includes('disabled')) {
        type = 'disabled';
        title = 'Cart Temporarily Disabled';
      } else if (msg.toLowerCase().includes('occupied') || msg.toLowerCase().includes('active shopper')) {
        type = 'occupied';
        title = 'Cart In Use';
      }

      setError({ title, message: msg, type });
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
            {t.appName}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t.tagline}
          </p>
        </div>

        {/* Status / Error Banner */}
        {error && (
          <div className={`mb-6 p-4 rounded-2xl border flex items-start gap-3.5 text-sm transition-all animate-fadeIn ${
            error.type === 'security'
              ? 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-300'
              : error.type === 'occupied'
              ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/60 text-amber-800 dark:text-amber-300'
              : error.type === 'disabled'
              ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-200 dark:border-purple-900/60 text-purple-800 dark:text-purple-300'
              : 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900/60 text-red-800 dark:text-red-300'
          }`}>
            <div className="flex-shrink-0 mt-0.5">
              {error.type === 'security' ? (
                <ShieldAlert className="w-5 h-5 text-rose-600 dark:text-rose-400" />
              ) : error.type === 'occupied' ? (
                <Lock className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              ) : (
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              )}
            </div>
            <div className="flex-1">
              {error.title && <div className="font-semibold text-xs uppercase tracking-wider mb-1">{error.title}</div>}
              <div className="leading-relaxed">{error.message}</div>
            </div>
          </div>
        )}

        {/* QR Scanner Reticle Graphic / Auto-Pairing Notice */}
        <div className="relative border-2 border-dashed border-emerald-500/60 dark:border-emerald-400/50 rounded-3xl p-8 text-center bg-emerald-50/50 dark:bg-emerald-950/20 mb-6 backdrop-blur-sm">
          <div className="w-20 h-20 mx-auto mb-3 text-emerald-600 dark:text-emerald-400 flex items-center justify-center relative">
            <QrCode className="w-16 h-16" />
            <div className="absolute inset-0 border-2 border-emerald-500 rounded-lg animate-ping opacity-25"></div>
          </div>
          <h2 className="font-semibold text-slate-800 dark:text-slate-200 text-base">
            {loading ? 'Verifying Cart Signature...' : t.connectTitle}
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs mx-auto">
            {loading 
              ? 'Validating cryptographic HMAC signature with live store fleet server...' 
              : t.connectDesc}
          </p>

          <button
            onClick={() => handleConnect(`QR-${cartInput}`)}
            disabled={loading}
            className="mt-5 w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 px-4 rounded-2xl shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all disabled:opacity-50"
          >
            <Zap className="w-4 h-4 fill-current" />
            {loading ? 'Authenticating Cart...' : `${t.connectBtn} (${cartInput})`}
          </button>
        </div>

        {/* Optional Mobile Phone for SMS / Receipt */}
        <div className="mb-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-4 shadow-sm">
          <label className="block text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
            Mobile Number (Optional for Receipt SMS)
          </label>
          <input
            type="tel"
            value={phoneInput}
            onChange={(e) => setPhoneInput(e.target.value)}
            placeholder="+91 98765 43210"
            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>

        {/* Manual Cart Selection Fallback */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm">
          <label className="block text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
            Or Pick Cart Manually
          </label>
          <div className="flex gap-2">
            <select
              value={cartInput}
              onChange={(e) => setCartInput(e.target.value)}
              className="flex-1 bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white rounded-xl px-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {[1, 2, 3, 4, 5, 6, 7, 8].map((num) => {
                const c = `CART-${num < 10 ? '00' : '0'}${num}`;
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
              className="bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 text-white px-4 rounded-xl flex items-center justify-center disabled:opacity-50"
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
          {t.privacyNote}
        </div>
      </div>
    </div>
  );
};
