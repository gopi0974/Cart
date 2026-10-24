import React, { useState, useEffect } from 'react';
import {
  Camera, CheckCircle2, Clock, AlertTriangle, ShieldCheck,
  LogOut, ChevronRight, ShoppingCart, RefreshCw, Tag, Trash2, X, AlertCircle
} from 'lucide-react';
import { CartSession, CartItem } from '../types';
import { WarningBanner } from './WarningBanner';
import { BarcodeScannerModal } from './BarcodeScannerModal';
import { CheckoutModal } from './CheckoutModal';
import { api, getWsBaseUrl } from '../services/api';
import { audioFeedback } from '../services/audioFeedback';
import { useTranslation } from '../services/i18n';

interface Props {
  session: CartSession;
  onDisconnect: () => void;
  onCheckoutComplete: () => void;
}

export const ActiveCartView: React.FC<Props> = ({ session: initialSession, onDisconnect, onCheckoutComplete }) => {
  const [session, setSession] = useState<CartSession>(initialSession);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scannerMode, setScannerMode] = useState<'ADD' | 'REMOVE'>('ADD');
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [couponCode, setCouponCode] = useState('');
  const [couponLoading, setCouponLoading] = useState(false);
  const [couponFeedback, setCouponFeedback] = useState<{ text: string; success: boolean } | null>(null);

  // User-Side Item Removal State
  const [activeRemovalItem, setActiveRemovalItem] = useState<CartItem | null>(null);
  const [removalStep, setRemovalStep] = useState<'TAKE_OUT' | 'AWAITING_RESCAN' | null>(null);
  const [removalStatusMsg, setRemovalStatusMsg] = useState<string>('');
  const [removalVerifying, setRemovalVerifying] = useState<boolean>(false);
  const [removalToast, setRemovalToast] = useState<string | null>(null);

  const { t } = useTranslation();

  // Restore pending removal state across page refresh
  useEffect(() => {
    if (!session.items) return;
    const pendingItem = session.items.find(
      (i) => i.status === 'REMOVING' || i.status === 'REMOVED_PENDING_RESCAN'
    );
    if (pendingItem) {
      setActiveRemovalItem(pendingItem);
      if (pendingItem.status === 'REMOVING') {
        setRemovalStep('TAKE_OUT');
        setRemovalStatusMsg('Take this item out of the cart, then rescan its barcode.');
      } else {
        setRemovalStep('AWAITING_RESCAN');
        setRemovalStatusMsg('Item removed. Please rescan its barcode to take it off your bill.');
      }
    } else if (activeRemovalItem && !session.items.some(i => i.id === activeRemovalItem.id && (i.status === 'REMOVING' || i.status === 'REMOVED_PENDING_RESCAN'))) {
      setActiveRemovalItem(null);
      setRemovalStep(null);
      setRemovalStatusMsg('');
    }
  }, [session.items]);

  // Sync state & connect to Cart WebSocket
  useEffect(() => {
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${getWsBaseUrl()}/ws/cart/${session.cart_id}`);
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const { event: evtType } = payload;

          if (evtType === 'ITEM_VERIFIED') {
            audioFeedback.playItemVerified();
            refreshSession();
          } else if (
            evtType === 'ITEM_MISMATCH' || 
            evtType === 'UNSCANNED_ITEM_DETECTED' || 
            evtType === 'ITEM_REMOVAL_DETECTED' ||
            evtType === 'ITEM_REMOVAL_INITIATED'
          ) {
            audioFeedback.playWarning();
            refreshSession();
          } else if (evtType === 'ITEM_REMOVED_AWAITING_RESCAN') {
            audioFeedback.playItemVerified();
            setRemovalStep('AWAITING_RESCAN');
            setRemovalStatusMsg('Item removed. Please rescan its barcode to take it off your bill.');
            refreshSession();
          } else if (evtType === 'WARNING_CLEARED' || evtType === 'ITEM_SCANNED_PENDING' || evtType === 'REMOVAL_CANCELLED') {
            refreshSession();
          } else if (evtType === 'CART_CAMERA_STATUS') {
            setSession((prev) => ({
              ...prev,
              camera_status: payload.camera_status,
              can_checkout: payload.camera_status === 'ONLINE' ? prev.can_checkout : false
            }));
            refreshSession();
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };
    } catch (e) {
      console.warn('WS connection error:', e);
    }

    return () => {
      if (ws) ws.close();
    };
  }, [session.cart_id]);

  const refreshSession = async () => {
    setIsRefreshing(true);
    try {
      const updated = await api.getSession(session.id);
      setSession(updated);
    } catch (e) {
      console.error('Failed to refresh session:', e);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleExitClick = () => {
    const hasItems = session.items && session.items.length > 0;
    const confirmMessage = hasItems
      ? `You have ${session.items.length} item(s) in your basket (₹${session.total_amount.toFixed(2)}). Exiting will end this session and free the cart for other shoppers. Are you sure you want to exit?`
      : 'Exit shopping session and release this cart?';

    if (window.confirm(confirmMessage)) {
      onDisconnect();
    }
  };

  // 1. Shopper clicks "Remove" on an item
  const handleInitiateRemove = async (item: CartItem) => {
    try {
      setActiveRemovalItem(item);
      setRemovalStep('TAKE_OUT');
      setRemovalStatusMsg('Take this item out of the cart, then rescan its barcode.');
      audioFeedback.playWarning();

      const updatedItem = await api.initiateItemRemove(session.id, item.id);
      await refreshSession();

      // Trigger AI camera check after giving user a moment to reach in
      setTimeout(() => {
        triggerRemovalVerification(updatedItem.id);
      }, 1600);
    } catch (err: any) {
      alert(err.message || 'Failed to initiate item removal');
    }
  };

  // 2. Cart Camera AI verification of physical item removal
  const triggerRemovalVerification = async (itemId: string) => {
    setRemovalVerifying(true);
    try {
      const res = await api.verifyItemRemoval(session.id, itemId);
      if (res.removed) {
        // AI verified item has physically departed the cart!
        setRemovalStep('AWAITING_RESCAN');
        setRemovalStatusMsg('Item removed. Please rescan its barcode to take it off your bill.');
        audioFeedback.playItemVerified();
        await refreshSession();

        // Prompt shopper with barcode scanner in REMOVE mode
        setScannerMode('REMOVE');
        setScannerOpen(true);
      } else {
        // Still in cart, hand occluded, or uncertain
        setRemovalStep('TAKE_OUT');
        setRemovalStatusMsg(res.message || 'We still see this item in the cart. Please take it out.');
        audioFeedback.playWarning();
        await refreshSession();
      }
    } catch (err: any) {
      console.error('Verification error:', err);
    } finally {
      setRemovalVerifying(false);
    }
  };

  // 3. Shopper taps "Cancel" to keep the item in cart
  const handleCancelRemove = async (itemId: string) => {
    try {
      await api.cancelItemRemove(session.id, itemId);
      setActiveRemovalItem(null);
      setRemovalStep(null);
      setRemovalStatusMsg('');
      await refreshSession();
    } catch (err: any) {
      alert(err.message || 'Failed to cancel removal');
    }
  };

  // 4. Barcode scanned during ADD or REMOVE mode
  const handleBarcodeDetected = async (barcode: string) => {
    if (scannerMode === 'REMOVE') {
      try {
        const res = await api.rescanRemove(session.id, barcode);
        const removedName = res.product_name || activeRemovalItem?.product_name || 'Item';

        // Success notification
        setRemovalToast(`${removedName} removed from cart.`);
        setTimeout(() => setRemovalToast(null), 4500);

        audioFeedback.playItemVerified();
        setActiveRemovalItem(null);
        setRemovalStep(null);
        setRemovalStatusMsg('');

        await refreshSession();
      } catch (err: any) {
        audioFeedback.playWarning();
        // Propagate error to modal for explicit mismatch message
        throw new Error(err.message || `This barcode does not match the item you are removing.`);
      }
    } else {
      try {
        await api.scanItem(session.id, barcode);
        await refreshSession();
      } catch (err: any) {
        throw new Error(err.message || `Product not found (barcode ${barcode})`);
      }
    }
  };

  const handleApplyCoupon = async () => {
    if (!couponCode.trim()) return;
    setCouponLoading(true);
    setCouponFeedback(null);
    try {
      const res = await api.applyCoupon(session.id, couponCode.trim());
      setCouponFeedback({
        text: `Coupon applied: Rs.${res.discount_amount.toFixed(2)} off! (${res.description})`,
        success: true
      });
      audioFeedback.playItemVerified();
      await refreshSession();
    } catch (err: any) {
      setCouponFeedback({
        text: err.message || 'Invalid coupon code. Try WELCOME10 or SUPER50.',
        success: false
      });
      audioFeedback.playWarning();
    } finally {
      setCouponLoading(false);
    }
  };

  const openAddScanner = () => {
    setScannerMode('ADD');
    setScannerOpen(true);
  };

  const openRemoveScanner = (barcode?: string) => {
    setScannerMode('REMOVE');
    setScannerOpen(true);
  };

  // Checkout is blocked if any removal is pending, camera is offline, or unverified items exist
  const hasPendingRemoval = session.items.some(
    (i) => i.status === 'REMOVING' || i.status === 'REMOVED_PENDING_RESCAN'
  ) || activeRemovalItem !== null;

  const checkoutBlocked = hasPendingRemoval || !session.can_checkout || session.camera_status === 'OFFLINE';

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col justify-between pb-36 animate-fade-in relative">
      {/* Floating Success Toast */}
      {removalToast && (
        <div className="fixed top-16 left-4 right-4 z-50 max-w-sm mx-auto bg-emerald-600 text-white px-4 py-3 rounded-2xl shadow-2xl flex items-center gap-2.5 animate-bounce">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span className="text-xs font-semibold">{removalToast}</span>
        </div>
      )}

      {/* Top Cart Status Header */}
      <div className="sticky top-0 z-20 glass-panel border-b border-slate-200 dark:border-slate-800 px-4 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-2.5">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></div>
          <div>
            <div className="font-display font-bold text-sm text-slate-900 dark:text-white flex items-center gap-1.5">
              <span>{session.cart_number}</span>
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                ACTIVE
              </span>
            </div>
            <div className="text-[11px] text-slate-400">
              Session #{session.id.slice(0, 8)}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refreshSession}
            className={`p-2 rounded-xl text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors ${
              isRefreshing ? 'animate-spin text-emerald-600' : ''
            }`}
            title="Refresh Cart"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={handleExitClick}
            className="text-xs text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 px-2.5 py-1.5 rounded-xl border border-red-200 dark:border-red-900/50 flex items-center gap-1 active:scale-95 transition-all"
            title="Exit session and release cart"
          >
            <LogOut className="w-3.5 h-3.5" />
            Exit
          </button>
        </div>
      </div>

      {/* Main Cart Body */}
      <div className="p-4 flex-1">
        {/* Camera Offline Warning Banner */}
        {session.camera_status === 'OFFLINE' && (
          <div className="mb-4 p-4 rounded-2xl bg-amber-500/10 border-2 border-amber-500/30 text-amber-800 dark:text-amber-200 flex items-start gap-3 shadow-sm animate-pulse">
            <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="text-xs">
              <div className="font-bold text-sm">Cart Camera Disconnected</div>
              <p className="mt-0.5 leading-relaxed font-medium text-amber-700 dark:text-amber-300">
                This cart's camera is not connected. Verification is paused. Please ask staff for assistance.
              </p>
            </div>
          </div>
        )}

        {/* Dynamic Warning Banners */}
        <WarningBanner
          warnings={session.active_warnings}
          onScanClick={openAddScanner}
          onRescanRemoveClick={openRemoveScanner}
          onCancelRemove={handleCancelRemove}
          onVerifyRemovalClick={triggerRemovalVerification}
        />

        {/* Dedicated Removal Flow Banner / Card */}
        {activeRemovalItem && (
          <div className="mb-5 p-4 rounded-2xl bg-amber-50 dark:bg-amber-950/40 border-2 border-amber-400 dark:border-amber-600/70 text-amber-950 dark:text-amber-100 shadow-xl space-y-3 animate-fade-in">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full bg-amber-500 animate-ping" />
                <span className="font-bold text-sm text-amber-950 dark:text-amber-100">
                  Removing: {activeRemovalItem.product_name}
                </span>
              </div>
              <button
                onClick={() => handleCancelRemove(activeRemovalItem.id)}
                className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-white px-2 py-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 flex items-center gap-1"
                title="Cancel removal and keep item"
              >
                <X className="w-3.5 h-3.5" />
                Cancel
              </button>
            </div>

            {removalStep === 'TAKE_OUT' && (
              <div className="space-y-2.5">
                <div className="p-3 rounded-xl bg-white/90 dark:bg-slate-900/90 border border-amber-300 dark:border-amber-700/60 text-xs">
                  <p className="font-semibold text-slate-900 dark:text-white text-sm">
                    Take this item out of the cart, then rescan its barcode.
                  </p>
                  {removalStatusMsg && (
                    <p className="mt-1 text-amber-700 dark:text-amber-300 font-medium">
                      {removalStatusMsg}
                    </p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => triggerRemovalVerification(activeRemovalItem.id)}
                    disabled={removalVerifying}
                    className="flex-1 bg-amber-600 hover:bg-amber-700 text-white font-semibold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center gap-1.5 shadow-md active:scale-95 transition-all"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${removalVerifying ? 'animate-spin' : ''}`} />
                    {removalVerifying ? 'Checking Cart Camera...' : "I've Removed It (Check Camera)"}
                  </button>
                  <button
                    onClick={() => handleCancelRemove(activeRemovalItem.id)}
                    className="px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
                  >
                    Cancel (Keep Item)
                  </button>
                </div>
              </div>
            )}

            {removalStep === 'AWAITING_RESCAN' && (
              <div className="space-y-2.5">
                <div className="p-3 rounded-xl bg-blue-50 dark:bg-blue-950/70 border border-blue-300 dark:border-blue-700/60 text-xs">
                  <p className="font-semibold text-blue-950 dark:text-blue-100 text-sm">
                    Item removed. Please rescan its barcode to take it off your bill.
                  </p>
                  <p className="mt-1 text-blue-700 dark:text-blue-300">
                    Scan the barcode on <strong>{activeRemovalItem.product_name}</strong> to confirm and drop it from your bill.
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setScannerMode('REMOVE');
                      setScannerOpen(true);
                    }}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center gap-1.5 shadow-md active:scale-95 transition-all"
                  >
                    <Camera className="w-4 h-4" />
                    Rescan Barcode to Drop from Bill
                  </button>
                  <button
                    onClick={() => handleCancelRemove(activeRemovalItem.id)}
                    className="px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
                  >
                    Cancel (Keep Item)
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Section Heading */}
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {t.cartItems} ({session.items.length})
          </h2>
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            Camera AI Monitoring
          </span>
        </div>

        {/* Items List */}
        {session.items.length === 0 ? (
          <div className="bg-white dark:bg-[#131B2E] border border-dashed border-slate-300 dark:border-slate-800 rounded-3xl p-8 text-center my-6">
            <div className="w-16 h-16 bg-slate-100 dark:bg-slate-800 rounded-2xl mx-auto flex items-center justify-center text-slate-400 mb-3">
              <ShoppingCart className="w-8 h-8" />
            </div>
            <h3 className="font-semibold text-slate-800 dark:text-slate-200 text-sm">
              {t.emptyCartTitle}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs mx-auto">
              {t.emptyCartDesc}
            </p>
            <button
              onClick={openAddScanner}
              className="mt-4 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold px-4 py-2.5 rounded-xl shadow-md shadow-emerald-600/20 inline-flex items-center gap-1.5"
            >
              <Camera className="w-4 h-4" />
              {t.scanBarcode}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {session.items.map((item: CartItem) => {
              const isItemRemoving = item.status === 'REMOVING';
              const isItemRemovedPending = item.status === 'REMOVED_PENDING_RESCAN';

              return (
                <div
                  key={item.id}
                  className={`bg-white dark:bg-[#131B2E] border rounded-2xl p-3.5 shadow-sm transition-all flex items-start gap-3 relative overflow-hidden ${
                    isItemRemoving
                      ? 'border-amber-400/90 dark:border-amber-500/80 shadow-amber-500/10 shadow-lg ring-1 ring-amber-400'
                      : isItemRemovedPending
                      ? 'border-blue-400/90 dark:border-blue-500/80 shadow-blue-500/10 shadow-lg ring-1 ring-blue-400'
                      : item.status === 'PENDING'
                      ? 'border-amber-400/80 dark:border-amber-500/70 shadow-amber-500/10 shadow-lg'
                      : item.status === 'VERIFIED'
                      ? 'border-emerald-200 dark:border-emerald-900/60'
                      : 'border-red-300 dark:border-red-900/60'
                  }`}
                >
                  {/* Product Thumbnail */}
                  <div className="w-14 h-14 bg-slate-100 dark:bg-slate-800 rounded-xl overflow-hidden flex-shrink-0 flex items-center justify-center border border-slate-100 dark:border-slate-800">
                    {item.product_image_url ? (
                      <img
                        src={item.product_image_url}
                        alt={item.product_name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <ShoppingCart className="w-6 h-6 text-slate-400" />
                    )}
                  </div>

                  {/* Info & State */}
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                      <h4 className="font-semibold text-sm text-slate-900 dark:text-white truncate pr-2">
                        {item.product_name}
                      </h4>
                      <div className="text-right flex-shrink-0">
                        <span className="font-mono font-bold text-sm text-slate-900 dark:text-white">
                          ₹{item.unit_price.toFixed(2)}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono mt-0.5">
                      <span>{item.brand} • Qty: {item.quantity}</span>
                      
                      {/* Remove Button for Verified/Pending Items */}
                      {!isItemRemoving && !isItemRemovedPending && (
                        <button
                          onClick={() => handleInitiateRemove(item)}
                          className="text-red-500 hover:text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs px-2 py-0.5 rounded-lg border border-red-200 dark:border-red-900/50 flex items-center gap-1 active:scale-95 transition-all font-sans"
                          title="Remove item from cart"
                        >
                          <Trash2 className="w-3 h-3" />
                          <span>{t.removeItem || 'Remove'}</span>
                        </button>
                      )}
                    </div>

                    {/* Dynamic Status Badges */}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {item.status === 'VERIFIED' && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/50 px-2 py-0.5 rounded-md border border-emerald-200 dark:border-emerald-800/40">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                          {t.verifiedStatus}
                          {item.confidence_score && (
                            <span className="opacity-75 font-mono text-[10px]">
                              ({(item.confidence_score * 100).toFixed(0)}%)
                            </span>
                          )}
                        </span>
                      )}

                      {isItemRemoving && (
                        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-950/60 px-2.5 py-0.5 rounded-md border border-amber-300 dark:border-amber-700 animate-pulse">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                          {t.removingStatus || 'REMOVING • Take out of cart'}
                        </span>
                      )}

                      {isItemRemovedPending && (
                        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-blue-800 dark:text-blue-300 bg-blue-100 dark:bg-blue-950/60 px-2.5 py-0.5 rounded-md border border-blue-300 dark:border-blue-700">
                          <CheckCircle2 className="w-3.5 h-3.5 text-blue-600" />
                          {t.removedPendingRescanStatus || 'REMOVED • Rescan barcode to drop'}
                        </span>
                      )}

                      {item.status === 'PENDING' && (
                        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 px-2 py-0.5 rounded-md border border-amber-300 dark:border-amber-700/60 animate-pulse">
                          <Clock className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
                          {t.pendingStatus}
                        </span>
                      )}

                      {item.status === 'WARNING_MISMATCH' && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/50 px-2 py-0.5 rounded-md border border-red-300 dark:border-red-700/60">
                          <AlertTriangle className="w-3.5 h-3.5 text-red-600" />
                          {t.mismatchStatus}
                        </span>
                      )}

                      {item.status === 'WARNING_UNSCANNED' && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/50 px-2 py-0.5 rounded-md border border-red-300 dark:border-red-700/60">
                          <AlertTriangle className="w-3.5 h-3.5 text-red-600" />
                          {t.unscannedStatus}
                        </span>
                      )}
                    </div>

                    {/* Inline actions for removing items */}
                    {isItemRemoving && (
                      <div className="flex items-center gap-2 mt-2 pt-1 border-t border-slate-100 dark:border-slate-800">
                        <button
                          onClick={() => triggerRemovalVerification(item.id)}
                          disabled={removalVerifying}
                          className="bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold px-2.5 py-1 rounded-lg flex items-center gap-1 shadow-sm"
                        >
                          <RefreshCw className={`w-3 h-3 ${removalVerifying ? 'animate-spin' : ''}`} />
                          Check Camera
                        </button>
                        <button
                          onClick={() => handleCancelRemove(item.id)}
                          className="border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 text-[11px] px-2.5 py-1 rounded-lg"
                        >
                          Cancel
                        </button>
                      </div>
                    )}

                    {isItemRemovedPending && (
                      <div className="flex items-center gap-2 mt-2 pt-1 border-t border-slate-100 dark:border-slate-800">
                        <button
                          onClick={() => {
                            setActiveRemovalItem(item);
                            setScannerMode('REMOVE');
                            setScannerOpen(true);
                          }}
                          className="bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-semibold px-2.5 py-1 rounded-lg flex items-center gap-1 shadow-sm"
                        >
                          <Camera className="w-3 h-3" />
                          Rescan Barcode
                        </button>
                        <button
                          onClick={() => handleCancelRemove(item.id)}
                          className="border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 text-[11px] px-2.5 py-1 rounded-lg"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Promo Code Application Box */}
        {session.items.length > 0 && (
          <div className="mt-4 p-3.5 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                <Tag className="w-3.5 h-3.5 text-emerald-500" />
                {t.coupons}
              </span>
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono">
                Try: WELCOME10 or SUPER50
              </span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={couponCode}
                onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                placeholder="PROMO CODE"
                className="flex-1 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono uppercase focus:ring-2 focus:ring-emerald-500 outline-none"
              />
              <button
                onClick={handleApplyCoupon}
                disabled={couponLoading || !couponCode.trim()}
                className="bg-slate-900 dark:bg-slate-800 hover:bg-emerald-600 dark:hover:bg-emerald-600 text-white text-xs font-semibold px-3 py-1.5 rounded-xl transition-all disabled:opacity-50"
              >
                {couponLoading ? '...' : t.apply}
              </button>
            </div>
            {couponFeedback && (
              <div className={`text-[11px] font-medium ${couponFeedback.success ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500'}`}>
                {couponFeedback.text}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Persistent Sticky Bottom Action Deck */}
      <div className="fixed bottom-0 left-0 right-0 z-30 max-w-md mx-auto p-4 bg-white/95 dark:bg-[#131B2E]/95 backdrop-blur-lg border-t border-slate-200 dark:border-slate-800 shadow-2xl pb-safe">
        {/* Live Running Total Summary */}
        <div className="flex items-center justify-between mb-3 px-1 text-xs">
          <div className="text-slate-500 dark:text-slate-400">
            {t.subtotal}: <span className="font-mono text-slate-800 dark:text-slate-200">₹{session.subtotal_amount.toFixed(2)}</span>
            <span className="mx-1.5">•</span>
            {t.tax}: <span className="font-mono text-slate-800 dark:text-slate-200">₹{session.total_tax.toFixed(2)}</span>
            {session.total_discount > 0 && (
              <>
                <span className="mx-1.5">•</span>
                <span className="text-emerald-600 font-mono">-₹{session.total_discount.toFixed(2)}</span>
              </>
            )}
          </div>
          <div className="font-display font-bold text-base text-slate-900 dark:text-white">
            {t.total}: <span className="font-mono text-emerald-600 dark:text-emerald-400">₹{session.total_amount.toFixed(2)}</span>
          </div>
        </div>

        {/* Dual Primary Action CTAs */}
        <div className="flex gap-2.5">
          {/* Big Barcode Scan Button */}
          <button
            onClick={openAddScanner}
            className="flex-1 bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 text-white font-semibold py-3.5 px-4 rounded-2xl shadow-lg flex items-center justify-center gap-2 active:scale-95 transition-all text-sm"
          >
            <Camera className="w-5 h-5 text-emerald-400" />
            {t.scanBarcode}
          </button>

          {/* Pay Button with Verification & Removal Guards */}
          <button
            onClick={() => setCheckoutOpen(true)}
            disabled={checkoutBlocked}
            title={
              hasPendingRemoval
                ? 'Please complete the item removal before checking out.'
                : session.camera_status === 'OFFLINE'
                ? "This cart's camera is not connected. Verification is paused. Please ask staff for assistance."
                : !session.can_checkout
                ? 'All items must be verified by camera and warnings cleared before paying'
                : 'Proceed to Payment'
            }
            className={`flex-1 font-semibold py-3.5 px-4 rounded-2xl shadow-lg flex items-center justify-center gap-1.5 transition-all text-sm ${
              !checkoutBlocked
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-600/30 active:scale-95'
                : 'bg-slate-200 dark:bg-slate-800 text-slate-400 dark:text-slate-600 cursor-not-allowed shadow-none'
            }`}
          >
            <span>{t.pay} ₹{session.total_amount.toFixed(2)}</span>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {checkoutBlocked && session.items.length > 0 && (
          <p className="text-[11px] text-center text-amber-600 dark:text-amber-400 mt-2 font-medium">
            {hasPendingRemoval
              ? 'Please complete the item removal before checking out.'
              : session.camera_status === 'OFFLINE'
              ? "This cart's camera is not connected. Verification is paused. Please ask staff for assistance."
              : "Checkout opens once all items are placed and verified in cart."}
          </p>
        )}
      </div>

      {/* Barcode Scanner Modal */}
      <BarcodeScannerModal
        isOpen={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onBarcodeDetected={handleBarcodeDetected}
        mode={scannerMode}
        targetProductName={activeRemovalItem?.product_name}
      />

      {/* Checkout Modal */}
      <CheckoutModal
        isOpen={checkoutOpen}
        onClose={() => setCheckoutOpen(false)}
        session={session}
        onPaymentSuccess={onCheckoutComplete}
      />
    </div>
  );
};
