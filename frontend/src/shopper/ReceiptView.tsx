import React, { useEffect } from 'react';
import { CheckCircle2, Download, Printer, Share2, ShoppingBag, ArrowRight, ShieldCheck, QrCode } from 'lucide-react';
import confetti from 'canvas-confetti';
import { ReceiptData } from '../types';

interface Props {
  receipt: ReceiptData;
  onNewSession: () => void;
}

export const ReceiptView: React.FC<Props> = ({ receipt, onNewSession }) => {
  useEffect(() => {
    // Joyful celebration burst on payment completion
    try {
      confetti({
        particleCount: 90,
        spread: 70,
        origin: { y: 0.6 },
        colors: ['#10b981', '#3b82f6', '#f59e0b', '#ec4899']
      });
    } catch {
      // Confetti fallback
    }
  }, []);

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="max-w-md mx-auto p-4 sm:p-6 pb-20 animate-fade-in">
      {/* Success Badge */}
      <div className="text-center my-6">
        <div className="w-16 h-16 bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 rounded-full mx-auto flex items-center justify-center mb-3 shadow-inner">
          <CheckCircle2 className="w-10 h-10" />
        </div>
        <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
          Payment Successful!
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Thank you for shopping autonomously at {receipt.store_name}
        </p>
      </div>

      {/* Official Digital Invoice Card */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-xl relative overflow-hidden print:shadow-none print:border-none">
        {/* Invoice Top Details */}
        <div className="border-b border-dashed border-slate-200 dark:border-slate-700 pb-4 mb-4">
          <div className="flex justify-between items-start">
            <div>
              <div className="font-display font-bold text-base text-slate-900 dark:text-white">
                TAX INVOICE
              </div>
              <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                {receipt.receipt_number}
              </div>
            </div>
            <div className="text-right">
              <span className="text-[10px] font-bold px-2 py-0.5 bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 rounded-full uppercase">
                PAID IN FULL
              </span>
              <div className="text-[11px] text-slate-400 mt-1">
                {new Date(receipt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mt-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <span>Cart: <strong className="font-mono text-slate-800 dark:text-slate-200">{receipt.cart_number}</strong></span>
            <span>Tax ID: <strong className="font-mono text-slate-800 dark:text-slate-200">{receipt.store_tax_id}</strong></span>
          </div>
        </div>

        {/* Itemized Table */}
        <div className="space-y-2.5 mb-5">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Purchased Items ({receipt.items.length})
          </div>
          {receipt.items.map((item, idx) => (
            <div key={idx} className="flex justify-between items-center text-sm">
              <div className="flex-1 pr-3">
                <div className="font-medium text-slate-800 dark:text-slate-200 truncate">
                  {item.name}
                </div>
                <div className="text-xs text-slate-400">
                  {item.quantity} × ₹{item.unit_price.toFixed(2)}
                </div>
              </div>
              <div className="font-mono font-medium text-slate-900 dark:text-white">
                ₹{item.total_price.toFixed(2)}
              </div>
            </div>
          ))}
        </div>

        {/* Total Calculations */}
        <div className="border-t border-dashed border-slate-200 dark:border-slate-700 pt-3 space-y-1.5 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex justify-between">
            <span>Subtotal</span>
            <span className="font-mono">₹{receipt.subtotal.toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span>GST Tax Included</span>
            <span className="font-mono">₹{receipt.tax_amount.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-base font-bold text-slate-900 dark:text-white pt-2 border-t border-slate-100 dark:border-slate-800">
            <span>Total Paid ({receipt.payment_method})</span>
            <span className="font-mono text-emerald-600 dark:text-emerald-400">
              ₹{receipt.total_paid.toFixed(2)}
            </span>
          </div>
        </div>

        {/* Store Exit Gate QR Pass */}
        <div className="mt-6 pt-5 border-t border-slate-200 dark:border-slate-700 text-center">
          <div className="inline-block p-4 bg-white rounded-2xl border-2 border-emerald-500 shadow-md">
            {/* High Contrast Exit QR Code Representation */}
            <div className="w-36 h-36 bg-slate-900 rounded-xl flex flex-col items-center justify-center p-3 text-white">
              <QrCode className="w-24 h-24 text-white" />
              <div className="text-[10px] font-mono tracking-widest text-emerald-400 mt-1 uppercase">
                {receipt.exit_gate_token.slice(-8)}
              </div>
            </div>
          </div>
          <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 mt-2">
            Scan at Turnstile Gate to Exit Supermarket
          </div>
          <div className="mt-1 flex items-center justify-center gap-2">
            <span className="text-[10px] font-mono text-slate-400 max-w-[220px] truncate">
              {receipt.exit_gate_token}
            </span>
            <button
              onClick={() => {
                navigator.clipboard.writeText(receipt.exit_gate_token);
                alert('Exit token copied! Paste into Turnstile Gate tab to unlock.');
              }}
              className="text-[10px] bg-slate-100 dark:bg-slate-800 hover:bg-emerald-50 dark:hover:bg-emerald-950 text-slate-600 dark:text-slate-300 hover:text-emerald-600 px-2 py-0.5 rounded-md border border-slate-200 dark:border-slate-700 transition-colors"
            >
              Copy Token
            </button>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            This QR code unlocks the automatic exit gate. Valid for 30 minutes.
          </p>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-6 space-y-3 print:hidden">
        <div className="flex gap-2">
          <button
            onClick={handlePrint}
            className="flex-1 bg-white dark:bg-slate-800 hover:bg-slate-50 border border-slate-200 dark:border-slate-700 py-3 rounded-2xl text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center justify-center gap-2 shadow-sm active:scale-95 transition-all"
          >
            <Printer className="w-4 h-4" />
            Print / PDF Invoice
          </button>
          <button
            onClick={() => {
              if (navigator.share) {
                navigator.share({
                  title: 'SmartCart Receipt',
                  text: `Receipt #${receipt.receipt_number} from SuperMart. Total: ₹${receipt.total_paid}`,
                }).catch(() => {});
              }
            }}
            className="flex-1 bg-white dark:bg-slate-800 hover:bg-slate-50 border border-slate-200 dark:border-slate-700 py-3 rounded-2xl text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center justify-center gap-2 shadow-sm active:scale-95 transition-all"
          >
            <Share2 className="w-4 h-4" />
            Share Receipt
          </button>
        </div>

        <button
          onClick={onNewSession}
          className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-3.5 rounded-2xl shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2 text-sm active:scale-98 transition-all"
        >
          <ShoppingBag className="w-4 h-4" />
          Finish & Return Cart
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
