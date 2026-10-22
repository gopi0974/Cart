import React, { useState, useEffect } from 'react';
import { Plus, Printer, QrCode, Battery, Camera, RefreshCw, CheckCircle2 } from 'lucide-react';
import { CartFleetItem } from '../types';
import { api } from '../services/api';

export const CartFleetView: React.FC = () => {
  const [carts, setCarts] = useState<CartFleetItem[]>([]);
  const [newCartNumber, setNewCartNumber] = useState('CART-13');
  const [loading, setLoading] = useState(false);

  const fetchCarts = async () => {
    try {
      const data = await api.getAdminCarts();
      setCarts(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchCarts();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.registerCart(newCartNumber);
      alert(`Registered smart cart ${newCartNumber}!`);
      setNewCartNumber(`CART-${carts.length + 2}`);
      fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to register cart');
    } finally {
      setLoading(false);
    }
  };

  const handlePrintQRSheet = () => {
    window.print();
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
            Smart Cart Hardware Fleet & QR Sheets
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Register new smart carts, generate printable QR stickers for handles, and monitor camera/battery health.
          </p>
        </div>

        <div className="flex items-center gap-2 print:hidden">
          <button
            onClick={handlePrintQRSheet}
            className="bg-white dark:bg-slate-800 hover:bg-slate-50 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
          >
            <Printer className="w-3.5 h-3.5 text-emerald-500" />
            Print All Handle QR Stickers
          </button>
        </div>
      </div>

      {/* Register New Cart Bar */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm print:hidden">
        <form onSubmit={handleRegister} className="flex flex-col sm:flex-row items-center gap-3">
          <div className="flex-1 w-full">
            <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
              Register New Smart Cart
            </label>
            <input
              type="text"
              required
              value={newCartNumber}
              onChange={(e) => setNewCartNumber(e.target.value)}
              placeholder="e.g. CART-13"
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white text-xs font-mono rounded-xl p-2.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs py-3 px-5 rounded-xl shadow-md shadow-emerald-600/30 flex items-center justify-center gap-1.5 active:scale-95 transition-all sm:self-end"
          >
            <Plus className="w-4 h-4" />
            <span>Register Smart Cart</span>
          </button>
        </form>
      </div>

      {/* Printable QR Code Sheet */}
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 mb-3">
          Cart Handle QR Codes ({carts.length})
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {carts.map((c) => (
            <div
              key={c.id}
              className="bg-white dark:bg-[#131B2E] border-2 border-slate-200 dark:border-slate-800 rounded-3xl p-4 text-center shadow-sm flex flex-col items-center justify-between space-y-3"
            >
              <div className="font-display font-bold text-sm text-slate-900 dark:text-white">
                {c.cart_number}
              </div>

              {/* QR Graphic with token */}
              <div className="p-3 bg-slate-900 rounded-2xl text-white inline-block shadow-inner">
                <QrCode className="w-20 h-20 text-white" />
              </div>

              <div className="text-[10px] font-mono text-slate-500 uppercase">
                {c.qr_code_token}
              </div>

              <div className="w-full pt-2 border-t border-slate-100 dark:border-slate-800 flex justify-between text-[11px] text-slate-400 print:hidden">
                <span>{c.battery_level}% 🔋</span>
                <span className="text-emerald-500 font-semibold">{c.status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
