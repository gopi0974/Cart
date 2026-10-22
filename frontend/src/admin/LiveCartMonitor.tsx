import React, { useState, useEffect } from 'react';
import { Camera, Battery, Wifi, ShieldAlert, ShoppingCart, Eye, RefreshCw, X } from 'lucide-react';
import { CartFleetItem } from '../types';
import { api } from '../services/api';

export const LiveCartMonitor: React.FC = () => {
  const [carts, setCarts] = useState<CartFleetItem[]>([]);
  const [filter, setFilter] = useState<'ALL' | 'ACTIVE' | 'ALERT' | 'IDLE'>('ALL');
  const [selectedCart, setSelectedCart] = useState<CartFleetItem | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCarts = async () => {
    try {
      const data = await api.getAdminCarts();
      setCarts(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCarts();
    const interval = setInterval(fetchCarts, 4000);
    return () => clearInterval(interval);
  }, []);

  const filteredCarts = carts.filter((c) => {
    if (filter === 'ACTIVE') return c.status === 'ACTIVE';
    if (filter === 'ALERT') return c.status === 'ALERT';
    if (filter === 'IDLE') return c.status === 'IDLE';
    return true;
  });

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header and Filter Chips */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
            Fleet Live Monitoring
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Real-time status, interior camera feeds, battery levels, and active sessions across all {carts.length} carts.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex bg-slate-100 dark:bg-slate-900 p-1 rounded-2xl border border-slate-200 dark:border-slate-800 text-xs font-semibold">
          {(['ALL', 'ACTIVE', 'ALERT', 'IDLE'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setFilter(tab)}
              className={`px-3 py-1.5 rounded-xl transition-all ${
                filter === tab
                  ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Cart Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filteredCarts.map((cart) => {
          const isAlert = cart.status === 'ALERT';
          const isActive = cart.status === 'ACTIVE';

          return (
            <div
              key={cart.id}
              className={`bg-white dark:bg-[#131B2E] rounded-3xl p-5 border shadow-sm transition-all hover:shadow-md flex flex-col justify-between ${
                isAlert
                  ? 'border-red-300 dark:border-red-900/60 shadow-red-500/10'
                  : isActive
                  ? 'border-emerald-300 dark:border-emerald-900/60'
                  : 'border-slate-200 dark:border-slate-800 opacity-80'
              }`}
            >
              <div>
                {/* Top Row: Cart Number & Status Chip */}
                <div className="flex items-center justify-between mb-3">
                  <div className="font-display font-bold text-lg text-slate-900 dark:text-white flex items-center gap-2">
                    <span className="font-mono">{cart.cart_number}</span>
                  </div>

                  <span
                    className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                      isAlert
                        ? 'bg-red-100 dark:bg-red-950 text-red-600 animate-pulse'
                        : isActive
                        ? 'bg-emerald-100 dark:bg-emerald-950 text-emerald-600'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
                    }`}
                  >
                    {cart.status}
                  </span>
                </div>

                {/* Session Telemetry */}
                <div className="space-y-1.5 text-xs text-slate-600 dark:text-slate-300 mb-4 bg-slate-50 dark:bg-slate-900/50 p-3 rounded-2xl border border-slate-100 dark:border-slate-800/60">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Current Basket:</span>
                    <span className="font-semibold">{cart.item_count} items</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Running Bill:</span>
                    <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">
                      ₹{cart.total_amount.toFixed(2)}
                    </span>
                  </div>
                </div>

                {/* Hardware Diagnostics */}
                <div className="flex items-center justify-between text-xs text-slate-500 mb-4 px-1">
                  <span className="flex items-center gap-1">
                    <Battery className={`w-3.5 h-3.5 ${cart.battery_level < 20 ? 'text-red-500' : 'text-emerald-500'}`} />
                    {cart.battery_level}%
                  </span>
                  <span className="flex items-center gap-1">
                    <Camera className="w-3.5 h-3.5 text-blue-500" />
                    {cart.camera_status}
                  </span>
                </div>
              </div>

              {/* Action: Open Live Camera Modal */}
              <button
                onClick={() => setSelectedCart(cart)}
                className="w-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 text-xs font-semibold py-2.5 rounded-2xl flex items-center justify-center gap-1.5 active:scale-95 transition-all"
              >
                <Eye className="w-3.5 h-3.5 text-emerald-500" />
                Live Camera Feed
              </button>
            </div>
          );
        })}
      </div>

      {/* Live Cart Camera Modal */}
      {selectedCart && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl text-white">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="font-display font-bold text-base flex items-center gap-2">
                  <span>{selectedCart.cart_number}</span>
                  <span className="text-xs font-mono font-normal bg-slate-800 px-2 py-0.5 rounded text-emerald-400">
                    {selectedCart.status}
                  </span>
                </h3>
                <p className="text-xs text-slate-400">Overhead Wide-Angle Cart Interior Camera</p>
              </div>
              <button
                onClick={() => setSelectedCart(null)}
                className="p-2 rounded-full bg-slate-800 hover:bg-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="relative aspect-video bg-black flex items-center justify-center overflow-hidden">
              <img
                src="https://images.unsplash.com/photo-1542838132-92c53300491e?w=800&auto=format&fit=crop&q=80"
                alt="Cart Feed"
                className="w-full h-full object-cover opacity-70"
              />

              {/* Real-time bounding box overlay */}
              <div className="absolute inset-8 border-2 border-dashed border-emerald-400 rounded-2xl pointer-events-none flex items-center justify-center">
                <span className="bg-black/70 font-mono text-xs text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/40">
                  Cart Basket ROI • AI Monitoring Active
                </span>
              </div>
            </div>

            <div className="p-4 bg-slate-950 flex items-center justify-between text-xs text-slate-400">
              <div>Resolution: 1920×1080 @ 30fps • Codec: H.264 WebRTC</div>
              <div className="font-mono text-emerald-400">FPS: 30 • Latency: 42ms</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
