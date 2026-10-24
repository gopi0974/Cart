import React, { useState, useEffect } from 'react';
import { Camera, Battery, Wifi, ShieldAlert, ShoppingCart, Eye, RefreshCw, X, RotateCcw, AlertTriangle, Trash2, CheckCircle2, ZoomIn, Package, Shield } from 'lucide-react';
import { CartFleetItem, CartItem } from '../types';
import { api } from '../services/api';

export const LiveCartMonitor: React.FC = () => {
  const [carts, setCarts] = useState<CartFleetItem[]>([]);
  const [filter, setFilter] = useState<'ALL' | 'ACTIVE' | 'ALERT' | 'IDLE'>('ALL');
  const [selectedCart, setSelectedCart] = useState<CartFleetItem | null>(null);
  const [modalTab, setModalTab] = useState<'ITEMS' | 'CAMERA'>('ITEMS');
  const [sessionItems, setSessionItems] = useState<CartItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Force removal modal state
  const [itemToForceRemove, setItemToForceRemove] = useState<CartItem | null>(null);
  const [forceReason, setForceReason] = useState('');
  const [forceLoading, setForceLoading] = useState(false);

  // Evidence snapshot full preview
  const [previewEvidenceUrl, setPreviewEvidenceUrl] = useState<string | null>(null);

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

  const fetchSessionItems = async (sessionId: string) => {
    setItemsLoading(true);
    try {
      const data = await api.getAdminSessionItems(sessionId);
      setSessionItems(data.items || []);
    } catch (e) {
      console.error('Failed to load session items:', e);
      setSessionItems([]);
    } finally {
      setItemsLoading(false);
    }
  };

  const handleResetCart = async (cart: CartFleetItem) => {
    if (!window.confirm(`Force release session and reset ${cart.cart_number} to Idle?`)) {
      return;
    }
    setActionLoading(cart.id);
    try {
      const res = await api.resetCartSession(cart.id);
      alert(res.message);
      await fetchCarts();
      if (selectedCart?.id === cart.id) {
        setSelectedCart(null);
      }
    } catch (err: any) {
      alert(err.message || 'Failed to reset cart');
    } finally {
      setActionLoading(null);
    }
  };

  const handleConfirmForceRemove = async () => {
    if (!selectedCart?.active_session_id || !itemToForceRemove) return;
    if (!forceReason.trim()) {
      alert('Please enter a mandatory reason for staff force-removal audit logging.');
      return;
    }

    setForceLoading(true);
    try {
      const res = await api.forceRemoveSessionItem(
        selectedCart.active_session_id,
        itemToForceRemove.id,
        forceReason.trim()
      );
      alert(res.message);
      setItemToForceRemove(null);
      setForceReason('');
      await fetchSessionItems(selectedCart.active_session_id);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to force remove item');
    } finally {
      setForceLoading(false);
    }
  };

  useEffect(() => {
    fetchCarts();
    const interval = setInterval(fetchCarts, 4000);
    return () => clearInterval(interval);
  }, []);

  // When selected cart changes, load items if active session exists
  useEffect(() => {
    if (selectedCart?.active_session_id) {
      fetchSessionItems(selectedCart.active_session_id);
      const interval = setInterval(() => {
        fetchSessionItems(selectedCart.active_session_id!);
      }, 3500);
      return () => clearInterval(interval);
    } else {
      setSessionItems([]);
    }
  }, [selectedCart?.active_session_id]);

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
            Real-time status, removal inspection, camera snapshots, battery telemetry, and live sessions across {carts.length} carts.
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

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => {
                    setSelectedCart(cart);
                    setModalTab(cart.active_session_id ? 'ITEMS' : 'CAMERA');
                  }}
                  className="flex-1 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 text-xs font-semibold py-2.5 rounded-2xl flex items-center justify-center gap-1.5 active:scale-95 transition-all"
                >
                  <Eye className="w-3.5 h-3.5 text-emerald-500" />
                  {cart.active_session_id ? 'Inspect Basket' : 'Live Camera'}
                </button>
                {(cart.status === 'ACTIVE' || cart.status === 'ALERT' || cart.item_count > 0 || Boolean(cart.active_session_id)) && (
                  <button
                    onClick={() => handleResetCart(cart)}
                    disabled={actionLoading === cart.id}
                    title="Force Release Session and Reset Cart to Idle"
                    className="p-2.5 rounded-2xl bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/40 dark:hover:bg-amber-900/40 text-amber-600 dark:text-amber-400 text-xs font-bold transition-all active:scale-95 border border-amber-200 dark:border-amber-800/40"
                  >
                    <RotateCcw className={`w-3.5 h-3.5 ${actionLoading === cart.id ? 'animate-spin' : ''}`} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cart Inspection / Camera Modal */}
      {selectedCart && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-3 sm:p-5 animate-fade-in">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-3xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="p-4 sm:p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="font-display font-bold text-lg text-slate-900 dark:text-white flex items-center gap-2">
                  <span>Cart {selectedCart.cart_number}</span>
                  <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full ${
                    selectedCart.status === 'ALERT'
                      ? 'bg-red-100 dark:bg-red-950 text-red-600'
                      : 'bg-emerald-100 dark:bg-emerald-950 text-emerald-600'
                  }`}>
                    {selectedCart.status}
                  </span>
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  {selectedCart.active_session_id ? `Active Session: ${selectedCart.active_session_id.substring(0, 8)}...` : 'No active session (Idle)'}
                </p>
              </div>

              {/* Tabs */}
              <div className="flex items-center gap-2">
                <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-2xl text-xs font-semibold">
                  <button
                    onClick={() => setModalTab('ITEMS')}
                    className={`px-3 py-1.5 rounded-xl transition-all flex items-center gap-1.5 ${
                      modalTab === 'ITEMS'
                        ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                        : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <Package className="w-3.5 h-3.5" />
                    Basket & Removals ({sessionItems.length})
                  </button>
                  <button
                    onClick={() => setModalTab('CAMERA')}
                    className={`px-3 py-1.5 rounded-xl transition-all flex items-center gap-1.5 ${
                      modalTab === 'CAMERA'
                        ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                        : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <Camera className="w-3.5 h-3.5" />
                    Live Feed
                  </button>
                </div>

                <button
                  onClick={() => setSelectedCart(null)}
                  className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-5">
              {modalTab === 'ITEMS' ? (
                <div className="space-y-4">
                  {/* Summary Bar */}
                  <div className="grid grid-cols-3 gap-3 bg-slate-50 dark:bg-slate-900/60 p-3.5 rounded-2xl border border-slate-100 dark:border-slate-800 text-center">
                    <div>
                      <div className="text-[11px] text-slate-400">Total Items</div>
                      <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                        {sessionItems.filter(i => i.status !== 'REMOVED').length} active
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-slate-400">In Removal Process</div>
                      <div className="text-sm font-bold text-amber-500">
                        {sessionItems.filter(i => i.status === 'REMOVING' || i.status === 'REMOVED_PENDING_RESCAN').length}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-slate-400">Cart Total</div>
                      <div className="text-sm font-bold text-emerald-500 font-mono">
                        ₹{selectedCart.total_amount.toFixed(2)}
                      </div>
                    </div>
                  </div>

                  {itemsLoading ? (
                    <div className="py-12 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                      <RefreshCw className="w-4 h-4 animate-spin text-emerald-500" />
                      Loading basket items...
                    </div>
                  ) : sessionItems.length === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-400 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
                      {selectedCart.active_session_id
                        ? 'No items currently in this cart basket.'
                        : 'Cart is currently idle. Connect a shopper session to inspect items.'}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {sessionItems.map((item) => {
                        const isRemoving = item.status === 'REMOVING';
                        const isPendingRescan = item.status === 'REMOVED_PENDING_RESCAN';
                        const isRemoved = item.status === 'REMOVED';
                        const isMismatch = item.status === 'WARNING_MISMATCH';
                        const isUnscanned = item.status === 'WARNING_UNSCANNED';

                        return (
                          <div
                            key={item.id}
                            className={`p-3.5 rounded-2xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                              isRemoving
                                ? 'bg-amber-500/10 border-amber-300 dark:border-amber-700/60'
                                : isPendingRescan
                                ? 'bg-cyan-500/10 border-cyan-300 dark:border-cyan-700/60'
                                : isRemoved
                                ? 'bg-slate-100/60 dark:bg-slate-900/30 border-slate-200 dark:border-slate-800 opacity-60'
                                : isMismatch
                                ? 'bg-red-500/10 border-red-300 dark:border-red-700/60'
                                : 'bg-white dark:bg-slate-900/60 border-slate-200 dark:border-slate-800'
                            }`}
                          >
                            {/* Product Info */}
                            <div className="flex items-start gap-3 flex-1 min-w-0">
                              {item.product_image_url ? (
                                <img
                                  src={item.product_image_url}
                                  alt={item.product_name}
                                  className="w-12 h-12 object-contain bg-white rounded-xl border border-slate-200 dark:border-slate-700 p-1 flex-shrink-0"
                                />
                              ) : (
                                <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0 text-slate-400">
                                  <Package className="w-5 h-5" />
                                </div>
                              )}

                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h4 className="font-semibold text-sm text-slate-900 dark:text-white truncate">
                                    {item.product_name}
                                  </h4>
                                  {/* Item Status Badges */}
                                  {isRemoving && (
                                    <span className="bg-amber-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full animate-pulse flex items-center gap-1">
                                      <AlertTriangle className="w-3 h-3" />
                                      REMOVING (Physical departure verified)
                                    </span>
                                  )}
                                  {isPendingRescan && (
                                    <span className="bg-cyan-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                                      <RotateCcw className="w-3 h-3" />
                                      REMOVED (Pending Barcode Rescan)
                                    </span>
                                  )}
                                  {isRemoved && (
                                    <span className="bg-slate-400 dark:bg-slate-700 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                                      REMOVED FROM BASKET
                                    </span>
                                  )}
                                  {isMismatch && (
                                    <span className="bg-red-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                                      MISMATCH WARNING
                                    </span>
                                  )}
                                  {isUnscanned && (
                                    <span className="bg-purple-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                                      UNSCANNED WARNING
                                    </span>
                                  )}
                                  {item.status === 'VERIFIED' && (
                                    <span className="bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-0.5">
                                      <CheckCircle2 className="w-3 h-3" /> VERIFIED
                                    </span>
                                  )}
                                </div>

                                <div className="text-xs text-slate-500 flex items-center gap-3 mt-1 flex-wrap">
                                  <span>Barcode: <strong className="font-mono text-slate-700 dark:text-slate-300">{item.product_barcode}</strong></span>
                                  <span>•</span>
                                  <span>Qty: <strong className="text-slate-700 dark:text-slate-300">{item.quantity}</strong></span>
                                  <span>•</span>
                                  <span>Price: <strong className="font-mono text-emerald-600 dark:text-emerald-400">₹{item.unit_price.toFixed(2)}</strong></span>
                                </div>
                              </div>
                            </div>

                            {/* Camera Removal Snapshot & Force Remove Button */}
                            <div className="flex items-center gap-2 self-end sm:self-center">
                              {/* Removal snapshot preview thumbnail */}
                              {item.verification_evidence_url && (
                                <button
                                  type="button"
                                  onClick={() => setPreviewEvidenceUrl(item.verification_evidence_url!)}
                                  title="View camera snapshot confirming physical removal"
                                  className="relative group p-1 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 hover:scale-105 transition-all"
                                >
                                  <img
                                    src={item.verification_evidence_url}
                                    alt="Removal snapshot"
                                    className="w-12 h-10 object-cover rounded-lg"
                                  />
                                  <div className="absolute inset-0 bg-black/40 rounded-lg opacity-0 group-hover:opacity-100 flex items-center justify-center text-white transition-opacity">
                                    <ZoomIn className="w-4 h-4" />
                                  </div>
                                </button>
                              )}

                              {/* Force Remove button for active/pending items */}
                              {!isRemoved && (
                                <button
                                  onClick={() => {
                                    setItemToForceRemove(item);
                                    setForceReason('');
                                  }}
                                  className="px-3 py-1.5 rounded-xl bg-red-50 hover:bg-red-100 dark:bg-red-950/40 dark:hover:bg-red-900/50 text-red-600 dark:text-red-400 text-xs font-semibold flex items-center gap-1.5 border border-red-200 dark:border-red-900/50 active:scale-95 transition-all"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                  Force Remove
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="relative aspect-video bg-black rounded-2xl flex items-center justify-center overflow-hidden border border-slate-800">
                    <img
                      src="https://images.unsplash.com/photo-1542838132-92c53300491e?w=800&auto=format&fit=crop&q=80"
                      alt="Cart Feed"
                      className="w-full h-full object-cover opacity-70"
                    />

                    {/* ROI Box */}
                    <div className="absolute inset-8 border-2 border-dashed border-emerald-400 rounded-2xl pointer-events-none flex items-center justify-center">
                      <span className="bg-black/70 font-mono text-xs text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/40">
                        Overhead Cart Basket ROI • Visual AI Active
                      </span>
                    </div>
                  </div>

                  <div className="p-3 bg-slate-50 dark:bg-slate-900/60 rounded-2xl flex items-center justify-between text-xs text-slate-400 border border-slate-100 dark:border-slate-800">
                    <div>Resolution: 1920×1080 @ 30fps • Codec: H.264 WebRTC</div>
                    <div className="font-mono text-emerald-400">Status: {selectedCart.camera_status}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Force Removal Confirmation Dialog */}
      {itemToForceRemove && selectedCart?.active_session_id && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-md p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-red-600">
                <ShieldAlert className="w-5 h-5" />
                <h3 className="font-bold text-base text-slate-900 dark:text-white">
                  Staff Force-Remove Item
                </h3>
              </div>
              <button
                onClick={() => setItemToForceRemove(null)}
                className="p-1 rounded-full text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="text-xs text-slate-600 dark:text-slate-300 space-y-2">
              <p>
                You are manually dropping this item from the active cart session and recalculating the shopper's bill:
              </p>
              <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700">
                <div className="font-bold text-slate-900 dark:text-white">{itemToForceRemove.product_name}</div>
                <div className="font-mono text-slate-400 mt-0.5">Barcode: {itemToForceRemove.product_barcode}</div>
                <div className="text-emerald-500 font-mono mt-0.5">Price: ₹{itemToForceRemove.unit_price.toFixed(2)}</div>
              </div>
            </div>

            {/* Mandatory Reason */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-200 mb-1">
                Mandatory Staff Reason (Logged to AuditLog) *
              </label>
              <textarea
                rows={3}
                value={forceReason}
                onChange={(e) => setForceReason(e.target.value)}
                placeholder="e.g. Associate verified customer returned item to shelf without rescanning barcode."
                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white text-xs rounded-xl p-3 focus:outline-none focus:ring-2 focus:ring-red-500"
              />
            </div>

            <div className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setItemToForceRemove(null)}
                disabled={forceLoading}
                className="flex-1 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-200 text-xs font-semibold py-2.5 rounded-xl transition-all"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmForceRemove}
                disabled={forceLoading || !forceReason.trim()}
                className="flex-1 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-semibold py-2.5 rounded-xl shadow-md shadow-red-600/30 transition-all flex items-center justify-center gap-1.5"
              >
                <Trash2 className="w-3.5 h-3.5" />
                {forceLoading ? 'Removing...' : 'Confirm Force Remove'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Snapshot Zoom Modal */}
      {previewEvidenceUrl && (
        <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex items-center justify-center p-4 animate-fade-in">
          <div className="max-w-2xl w-full bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between text-white">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-emerald-400" />
                <h4 className="font-bold text-sm">Cart Camera Removal Snapshot</h4>
              </div>
              <button
                onClick={() => setPreviewEvidenceUrl(null)}
                className="p-1 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 flex items-center justify-center bg-black">
              <img
                src={previewEvidenceUrl}
                alt="Removal Evidence"
                className="max-h-[65vh] w-auto object-contain rounded-xl border border-slate-800"
              />
            </div>
            <div className="p-3 bg-slate-950 text-center text-xs text-slate-400">
              Captured by overhead interior cart camera during physical item departure.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
