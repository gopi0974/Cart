import React, { useState, useEffect, useRef } from 'react';
import { Camera, CheckCircle2, AlertTriangle, AlertCircle, ShoppingBag, Eye, RefreshCw, Cpu, Activity, ShieldAlert } from 'lucide-react';
import { api } from '../services/api';
import { Product } from '../types';

export const CartSimulatorView: React.FC = () => {
  const [cartId, setCartId] = useState('CART-01');
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>('8901262010053');
  const [wrongProduct, setWrongProduct] = useState<string>('8902080000014');
  const [confidence, setConfidence] = useState(0.95);
  const [log, setLog] = useState<{ time: string; text: string; type: 'info' | 'success' | 'warn' | 'error' }[]>([]);
  const [isSimulating, setIsSimulating] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api.getProducts().then(setProducts).catch(console.error);

    // Initialize local webcam for virtual overhead cart camera view
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ video: true })
        .then((stream) => {
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        })
        .catch(() => {});
    }
  }, []);

  const addLog = (text: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const time = new Date().toLocaleTimeString();
    setLog((prev) => [{ time, text, type }, ...prev.slice(0, 19)]);
  };

  const handleAction = async (actionType: 'PLACE_CORRECT' | 'PLACE_WRONG' | 'PLACE_UNSCANNED' | 'REMOVE_ITEM') => {
    setIsSimulating(true);
    try {
      addLog(`Sending vision frame event [${actionType}] to Cart ${cartId}...`, 'info');
      const res = await api.simulateAction({
        cart_id: cartId,
        action_type: actionType,
        barcode: selectedProduct,
        detected_barcode: actionType === 'PLACE_WRONG' ? wrongProduct : selectedProduct,
        confidence: confidence,
        evidence_url: 'https://images.unsplash.com/photo-1542838132-92c53300491e?w=600&auto=format&fit=crop&q=80',
      });
      addLog(`Result: ${res.event} (${res.status})`, actionType === 'PLACE_CORRECT' ? 'success' : 'warn');
    } catch (err: any) {
      addLog(`Action failed: ${err.message}`, 'error');
    } finally {
      setIsSimulating(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6">
      {/* Deck Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-xl bg-purple-100 dark:bg-purple-950/50 text-purple-600 dark:text-purple-400">
              <Cpu className="w-5 h-5" />
            </span>
            <h1 className="text-xl font-bold font-display text-slate-900 dark:text-white">
              Virtual Cart Camera & AI Hardware Simulator
            </h1>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Simulate cart overhead camera streams, object detections, hand entries, and security anomalies in real time.
          </p>
        </div>

        {/* Cart Target Selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-500 uppercase">Target Cart:</span>
          <select
            value={cartId}
            onChange={(e) => setCartId(e.target.value)}
            className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white text-xs font-mono rounded-xl px-3 py-2 focus:ring-2 focus:ring-purple-500"
          >
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((n) => {
              const c = `CART-${n < 10 ? '0' : ''}${n}`;
              return <option key={c} value={c}>{c}</option>;
            })}
          </select>
        </div>
      </div>

      {/* Grid: Camera View + Action Controls */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left Column: Virtual Cart Interior Camera */}
        <div className="bg-slate-900 rounded-3xl overflow-hidden border border-slate-800 shadow-xl relative aspect-video flex flex-col justify-between p-4 text-white">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="absolute inset-0 w-full h-full object-cover opacity-40"
          />

          {/* Top Camera HUD Overlay */}
          <div className="relative z-10 flex justify-between items-center text-xs">
            <div className="flex items-center gap-1.5 bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full border border-white/10">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-ping"></span>
              <span className="font-mono">LIVE • 1080p @ 30fps</span>
            </div>
            <div className="bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full font-mono text-[11px] border border-white/10">
              YOLOv8 + DINOv2 Tracking
            </div>
          </div>

          {/* Center Bounding Box Detection Guide */}
          <div className="relative z-10 border-2 border-emerald-400/80 rounded-2xl w-48 h-32 mx-auto flex items-center justify-center bg-emerald-500/10 backdrop-blur-[1px]">
            <div className="text-[11px] font-mono text-emerald-300 text-center p-2 bg-black/70 rounded-lg">
              CART BASKET ROI<br />
              Confidence: {(confidence * 100).toFixed(0)}%
            </div>
          </div>

          {/* Bottom Telemetry */}
          <div className="relative z-10 flex justify-between text-[11px] text-slate-400 bg-black/60 backdrop-blur-md p-2 rounded-xl">
            <span>Camera: 🟢 ONLINE</span>
            <span>Battery: 94%</span>
            <span>Cart: {cartId}</span>
          </div>
        </div>

        {/* Right Column: Interactive Hardware Triggers */}
        <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-4">
          <h2 className="font-semibold text-sm text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <Activity className="w-4 h-4 text-purple-600 dark:text-purple-400" />
            Trigger Cart Events & AI Detections
          </h2>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">
                Active Scanned Product
              </label>
              <select
                value={selectedProduct}
                onChange={(e) => setSelectedProduct(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-xl p-2.5 focus:outline-none"
              >
                {products.map((p) => (
                  <option key={p.barcode} value={p.barcode}>
                    {p.name} (₹{p.price.toFixed(2)})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">
                Different Mismatch Product (For Mismatch Test)
              </label>
              <select
                value={wrongProduct}
                onChange={(e) => setWrongProduct(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-xl p-2.5 focus:outline-none"
              >
                {products.map((p) => (
                  <option key={p.barcode} value={p.barcode}>
                    {p.name} (₹{p.price.toFixed(2)})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Action Trigger Buttons */}
          <div className="grid grid-cols-2 gap-2.5 pt-2">
            <button
              onClick={() => handleAction('PLACE_CORRECT')}
              disabled={isSimulating}
              className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold p-3 rounded-2xl flex flex-col items-center justify-center gap-1 shadow-md shadow-emerald-600/20 active:scale-95 transition-all text-center"
            >
              <CheckCircle2 className="w-5 h-5" />
              <span>1. Item Placed</span>
              <span className="text-[10px] font-normal opacity-80">(Auto Verify)</span>
            </button>

            <button
              onClick={() => handleAction('PLACE_WRONG')}
              disabled={isSimulating}
              className="bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold p-3 rounded-2xl flex flex-col items-center justify-center gap-1 shadow-md shadow-amber-600/20 active:scale-95 transition-all text-center"
            >
              <AlertTriangle className="w-5 h-5" />
              <span>2. Wrong Item Placed</span>
              <span className="text-[10px] font-normal opacity-80">(Mismatch Alert)</span>
            </button>

            <button
              onClick={() => handleAction('PLACE_UNSCANNED')}
              disabled={isSimulating}
              className="bg-red-600 hover:bg-red-700 text-white text-xs font-semibold p-3 rounded-2xl flex flex-col items-center justify-center gap-1 shadow-md shadow-red-600/20 active:scale-95 transition-all text-center"
            >
              <ShieldAlert className="w-5 h-5" />
              <span>3. Unscanned Item</span>
              <span className="text-[10px] font-normal opacity-80">(Theft Warning)</span>
            </button>

            <button
              onClick={() => handleAction('REMOVE_ITEM')}
              disabled={isSimulating}
              className="bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold p-3 rounded-2xl flex flex-col items-center justify-center gap-1 shadow-md active:scale-95 transition-all text-center"
            >
              <ShoppingBag className="w-5 h-5" />
              <span>4. Item Removed</span>
              <span className="text-[10px] font-normal opacity-80">(Prompt Rescan)</span>
            </button>
          </div>
        </div>
      </div>

      {/* Live Event Stream Terminal */}
      <div className="bg-slate-900 border border-slate-800 rounded-3xl p-4 shadow-xl">
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800 text-xs font-mono text-slate-400">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            Real-Time Vision & WebSocket Event Logger
          </span>
          <button onClick={() => setLog([])} className="hover:text-white">Clear</button>
        </div>
        <div className="font-mono text-xs space-y-1.5 max-h-36 overflow-y-auto pr-1">
          {log.length === 0 ? (
            <div className="text-slate-600 text-center py-4">No events triggered yet. Tap any trigger button above.</div>
          ) : (
            log.map((item, i) => (
              <div key={i} className="flex gap-2 leading-relaxed">
                <span className="text-slate-500 flex-shrink-0">[{item.time}]</span>
                <span className={
                  item.type === 'success' ? 'text-emerald-400 font-semibold' :
                  item.type === 'warn' ? 'text-amber-400 font-semibold' :
                  item.type === 'error' ? 'text-red-400 font-semibold' :
                  'text-slate-300'
                }>
                  {item.text}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
