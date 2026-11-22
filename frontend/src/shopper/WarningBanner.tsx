import React from 'react';
import { AlertTriangle, AlertCircle, ArrowRight, Camera, X, ShieldAlert, ShoppingCart, RefreshCw, Image as ImageIcon } from 'lucide-react';
import { ActiveWarning } from '../types';

interface Props {
  warnings: ActiveWarning[];
  onScanClick: () => void;
  onRescanRemoveClick: (barcode?: string) => void;
  onCancelRemove?: (itemId: string) => void;
  onVerifyRemovalClick?: (itemId: string) => void;
}

export const WarningBanner: React.FC<Props> = ({ 
  warnings, 
  onScanClick, 
  onRescanRemoveClick,
  onCancelRemove,
  onVerifyRemovalClick
}) => {
  if (!warnings || warnings.length === 0) return null;

  return (
    <div className="space-y-3 mb-5">
      {warnings.map((w, idx) => {
        const isRemoving = w.type === 'ITEM_REMOVING';
        const isRemovedPending = w.type === 'REMOVED_PENDING_RESCAN';
        const isRemoval = w.type === 'REMOVAL_WITHOUT_RESCAN' || isRemovedPending || isRemoving;
        const isUnauthorizedRemove = w.type === 'UNAUTHORIZED_REMOVE';
        const isCartNotEmpty = w.type === 'CART_NOT_EMPTY_AT_START';
        const isMotionUnstable = w.type === 'MOTION_UNSTABLE';
        const isUnscanned = w.type === 'UNSCANNED_ADD' || w.type === 'UNSCANNED_ITEM';
        const isMismatch = w.type === 'WRONG_ITEM_REMOVED' || w.type === 'MISMATCH_ITEM';
        const isNeedsStaffCheck = w.type === 'NEEDS_STAFF_CHECK' || w.type === 'FACE_IN_PACKAGING_WITHHELD';

        return (
          <div
            key={idx}
            className={`p-4 rounded-2xl border flex flex-col gap-3 shadow-md animate-fade-in transition-all ${
              isRemoving
                ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-400 dark:border-amber-600/70 text-amber-950 dark:text-amber-100 shadow-amber-500/10'
                : isRemovedPending
                ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-300 dark:border-blue-700/60 text-blue-950 dark:text-blue-100 shadow-blue-500/10'
                : isUnauthorizedRemove
                ? 'bg-rose-50 dark:bg-rose-950/40 border-rose-300 dark:border-rose-700/70 text-rose-950 dark:text-rose-100 shadow-rose-500/10'
                : isCartNotEmpty
                ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-300 dark:border-amber-700/70 text-amber-950 dark:text-amber-100 shadow-amber-500/10'
                : isMotionUnstable
                ? 'bg-sky-50 dark:bg-sky-950/40 border-sky-300 dark:border-sky-700/70 text-sky-950 dark:text-sky-100 shadow-sky-500/10'
                : isRemoval || isNeedsStaffCheck
                ? 'bg-amber-50 dark:bg-amber-950/35 border-amber-300 dark:border-amber-700/60 text-amber-900 dark:text-amber-200 shadow-amber-500/5'
                : 'bg-red-50 dark:bg-red-950/30 border-red-300 dark:border-red-700/60 text-red-900 dark:text-red-200'
            }`}
          >
            <div className="flex items-start gap-3">
              <div
                className={`p-2 rounded-xl flex-shrink-0 ${
                  isRemoving
                    ? 'bg-amber-200/80 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200 animate-pulse'
                    : isRemovedPending
                    ? 'bg-blue-200/80 dark:bg-blue-900/60 text-blue-900 dark:text-blue-200'
                    : isUnauthorizedRemove
                    ? 'bg-rose-200/80 dark:bg-rose-900/60 text-rose-900 dark:text-rose-200'
                    : isCartNotEmpty
                    ? 'bg-amber-200/80 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200'
                    : isMotionUnstable
                    ? 'bg-sky-200/80 dark:bg-sky-900/60 text-sky-900 dark:text-sky-200 animate-pulse'
                    : isRemoval || isNeedsStaffCheck
                    ? 'bg-amber-200/70 dark:bg-amber-900/50 text-amber-800 dark:text-amber-300'
                    : 'bg-red-200/70 dark:bg-red-900/50 text-red-800 dark:text-red-300'
                }`}
              >
                {isCartNotEmpty ? (
                  <ShoppingCart className="w-5 h-5" />
                ) : isMotionUnstable ? (
                  <RefreshCw className="w-5 h-5 animate-spin" />
                ) : isRemoval || isUnauthorizedRemove ? (
                  <AlertCircle className="w-5 h-5" />
                ) : (
                  <AlertTriangle className="w-5 h-5" />
                )}
              </div>

              <div className="flex-1">
                <div className="font-semibold text-sm">
                  {isNeedsStaffCheck
                    ? 'Staff Check Needed'
                    : isCartNotEmpty
                    ? 'Cart Not Empty'
                    : isMotionUnstable
                    ? 'Cart In Motion'
                    : isUnauthorizedRemove
                    ? 'Item Removal Detected'
                    : isRemoving
                    ? 'Item Removal in Progress'
                    : isRemovedPending
                    ? 'Item Removed from Cart'
                    : isRemoval
                    ? 'Item Removed from Cart'
                    : isMismatch
                    ? 'Wrong Item Detected'
                    : isUnscanned
                    ? 'Unscanned Item Detected'
                    : 'Item Check Needed'}
                </div>
                <p className="text-xs mt-0.5 opacity-90 leading-relaxed font-medium">
                  {w.message}
                </p>
              </div>
            </div>

            {/* R7: Last-known crop beside current evidence for UNAUTHORIZED_REMOVE */}
            {isUnauthorizedRemove && (w.last_known_image || w.current_evidence || w.evidence_url) && (
              <div className="p-3 rounded-xl bg-white/70 dark:bg-slate-900/70 border border-rose-200 dark:border-rose-900/50 space-y-2">
                <div className="flex items-center justify-between text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                  <span className="flex items-center gap-1.5">
                    <ImageIcon className="w-3.5 h-3.5 text-rose-500" />
                    Missing Item Visual Evidence
                  </span>
                  {w.confidence !== undefined && (
                    <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-rose-100 dark:bg-rose-950 text-rose-800 dark:text-rose-300 font-bold">
                      {(w.confidence * 100).toFixed(0)}% confidence
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider block font-bold">
                      Last-known in cart
                    </span>
                    <div className="h-24 bg-slate-100 dark:bg-slate-800 rounded-lg overflow-hidden flex items-center justify-center border border-slate-200 dark:border-slate-700">
                      {w.last_known_image ? (
                        <img src={w.last_known_image} alt="Last known in cart" className="w-full h-full object-cover" />
                      ) : (
                        <span className="text-[10px] text-slate-400">Snapshot missing</span>
                      )}
                    </div>
                  </div>
                  <div className="space-y-1">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider block font-bold">
                      Current camera frame
                    </span>
                    <div className="h-24 bg-slate-100 dark:bg-slate-800 rounded-lg overflow-hidden flex items-center justify-center border border-slate-200 dark:border-slate-700">
                      {w.current_evidence || w.evidence_url ? (
                        <img src={w.current_evidence || w.evidence_url} alt="Current frame" className="w-full h-full object-cover" />
                      ) : (
                        <span className="text-[10px] text-slate-400">Current frame</span>
                      )}
                    </div>
                  </div>
                </div>
                {w.top_candidates && w.top_candidates.length > 0 && (
                  <div className="text-[11px] text-rose-800 dark:text-rose-300 pt-1 border-t border-rose-200/60 dark:border-rose-900/40">
                    <span className="font-semibold">Top candidates sent to staff: </span>
                    <span>{w.top_candidates.map(c => c.product_name).join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            {/* Direct Action Buttons */}
            <div className="flex items-center justify-end gap-2 pt-1 border-t border-black/5 dark:border-white/5">
              {isRemoving && w.item_id && onCancelRemove && (
                <button
                  onClick={() => onCancelRemove(w.item_id!)}
                  className="px-3 py-1.5 rounded-xl border border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-200 text-xs font-medium hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors flex items-center gap-1"
                >
                  <X className="w-3.5 h-3.5" />
                  Cancel (Keep Item)
                </button>
              )}

              {isRemoving && w.item_id && onVerifyRemovalClick && (
                <button
                  onClick={() => onVerifyRemovalClick(w.item_id!)}
                  className="bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  I've Removed It
                </button>
              )}

              {isRemovedPending && (
                <>
                  {w.item_id && onCancelRemove && (
                    <button
                      onClick={() => onCancelRemove(w.item_id!)}
                      className="px-3 py-1.5 rounded-xl border border-blue-300 dark:border-blue-700 text-blue-800 dark:text-blue-200 text-xs font-medium hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors flex items-center gap-1"
                    >
                      <X className="w-3.5 h-3.5" />
                      Cancel (Keep Item)
                    </button>
                  )}
                  <button
                    onClick={() => onRescanRemoveClick(w.target_barcode)}
                    className="bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                  >
                    <Camera className="w-3.5 h-3.5" />
                    Rescan Barcode to Drop from Bill
                  </button>
                </>
              )}

              {!isRemoving && !isRemovedPending && isRemoval && !isUnauthorizedRemove && (
                <button
                  onClick={() => onRescanRemoveClick(w.target_barcode)}
                  className="bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Rescan to Drop from Bill
                </button>
              )}

              {isUnauthorizedRemove && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-rose-700 dark:text-rose-300 font-medium">
                    Put item back or notify attendant
                  </span>
                </div>
              )}

              {isCartNotEmpty && (
                <div className="flex items-center gap-1.5 text-xs text-amber-800 dark:text-amber-300 font-semibold px-2 py-1">
                  <span>Empty cart to start scanning</span>
                </div>
              )}

              {isMotionUnstable && (
                <div className="flex items-center gap-1.5 text-xs text-sky-800 dark:text-sky-300 font-medium px-2 py-1">
                  <span>Keep cart still for ~2 seconds</span>
                </div>
              )}

              {isNeedsStaffCheck ? (
                <div className="flex items-center gap-1.5 text-xs text-amber-800 dark:text-amber-300 font-medium px-2 py-1">
                  <ShieldAlert className="w-3.5 h-3.5 text-amber-600" />
                  <span>Attendant alerted • Please show item to staff</span>
                </div>
              ) : isUnscanned ? (
                <button
                  onClick={onScanClick}
                  className="bg-red-600 hover:bg-red-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Scan Barcode Now
                  <ArrowRight className="w-3 h-3 ml-0.5" />
                </button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};
