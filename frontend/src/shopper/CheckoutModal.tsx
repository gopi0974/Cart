import React, { useState } from 'react';
import { X, CreditCard, Smartphone, ShieldCheck, CheckCircle2, Lock } from 'lucide-react';
import { CartSession } from '../types';
import { api } from '../services/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  session: CartSession;
  onPaymentSuccess: () => void;
}

export const CheckoutModal: React.FC<Props> = ({ isOpen, onClose, session, onPaymentSuccess }) => {
  const [method, setMethod] = useState<'UPI' | 'CARD'>('UPI');
  const [upiId, setUpiId] = useState('shopper@okaxis');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handlePay = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.checkout(session.id, method, method === 'UPI' ? upiId : undefined);
      onPaymentSuccess();
    } catch (err: any) {
      setError(err.message || 'Payment processing failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4 animate-fade-in">
      <div className="bg-white dark:bg-[#131B2E] w-full max-w-lg rounded-t-3xl sm:rounded-3xl border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div>
            <h3 className="font-display font-bold text-lg text-slate-900 dark:text-white">
              Checkout & Payment
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {session.cart_number} • {session.item_count} Verified Items
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-5">
          {/* Bill Summary Card */}
          <div className="bg-slate-50 dark:bg-slate-900/60 p-4 rounded-2xl border border-slate-200 dark:border-slate-800">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
              Order Summary
            </div>
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between text-slate-600 dark:text-slate-300">
                <span>Items Subtotal</span>
                <span className="font-mono">₹{session.subtotal_amount.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-slate-600 dark:text-slate-300">
                <span>Estimated GST Tax (5-18%)</span>
                <span className="font-mono">₹{session.total_tax.toFixed(2)}</span>
              </div>
              {session.total_discount > 0 && (
                <div className="flex justify-between text-emerald-600 dark:text-emerald-400">
                  <span>Store Discounts</span>
                  <span className="font-mono">-₹{session.total_discount.toFixed(2)}</span>
                </div>
              )}
              <div className="border-t border-slate-200 dark:border-slate-700 pt-2 mt-2 flex justify-between font-bold text-base text-slate-900 dark:text-white">
                <span>Total Amount</span>
                <span className="font-mono text-emerald-600 dark:text-emerald-400">
                  ₹{session.total_amount.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          {/* Payment Method Selector */}
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2.5">
              Select Payment Method
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setMethod('UPI')}
                className={`p-3.5 rounded-2xl border flex flex-col items-center gap-2 transition-all ${
                  method === 'UPI'
                    ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 shadow-sm'
                    : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 text-slate-700 dark:text-slate-300'
                }`}
              >
                <Smartphone className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                <span className="text-xs font-semibold">UPI Apps (Sandbox)</span>
              </button>

              <button
                onClick={() => setMethod('CARD')}
                className={`p-3.5 rounded-2xl border flex flex-col items-center gap-2 transition-all ${
                  method === 'CARD'
                    ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 shadow-sm'
                    : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 text-slate-700 dark:text-slate-300'
                }`}
              >
                <CreditCard className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                <span className="text-xs font-semibold">Card / NetBanking</span>
              </button>
            </div>
          </div>

          {/* Method Input Details */}
          {method === 'UPI' ? (
            <div className="bg-slate-50 dark:bg-slate-900/60 p-4 rounded-2xl border border-slate-200 dark:border-slate-800 space-y-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
                UPI ID (Virtual Payment Address)
              </label>
              <input
                type="text"
                value={upiId}
                onChange={(e) => setUpiId(e.target.value)}
                className="w-full bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-slate-900 dark:text-white font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500"
                placeholder="username@bank"
              />
              <div className="flex gap-2">
                {['@okaxis', '@oksbi', '@paytm'].map((suf) => (
                  <button
                    key={suf}
                    type="button"
                    onClick={() => setUpiId(`shopper${suf}`)}
                    className="text-[11px] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 px-2.5 py-1 rounded-lg text-slate-600 dark:text-slate-400 hover:text-emerald-600 font-mono"
                  >
                    {suf}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-slate-50 dark:bg-slate-900/60 p-4 rounded-2xl border border-slate-200 dark:border-slate-800 space-y-2.5">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>Test Sandbox Card</span>
                <span className="font-mono text-emerald-600">Auto-Authorized</span>
              </div>
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-3 flex items-center justify-between">
                <span className="font-mono text-sm text-slate-800 dark:text-slate-200">
                  •••• •••• •••• 4242
                </span>
                <span className="text-xs font-semibold text-slate-500">08/29</span>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-600 dark:text-red-400">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <Lock className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>256-bit encrypted checkout. PCI-DSS Level 1 compliant gateway.</span>
          </div>
        </div>

        {/* Footer CTA */}
        <div className="p-5 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-[#131B2E]">
          <button
            onClick={handlePay}
            disabled={loading}
            className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-semibold py-3.5 px-4 rounded-2xl shadow-xl shadow-emerald-600/30 flex items-center justify-center gap-2 text-base active:scale-98 transition-all"
          >
            {loading ? (
              <span>Authorizing Payment...</span>
            ) : (
              <>
                <CheckCircle2 className="w-5 h-5" />
                Pay ₹{session.total_amount.toFixed(2)} & Get Exit QR
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
