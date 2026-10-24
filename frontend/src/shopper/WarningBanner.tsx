import React from 'react';
import { AlertTriangle, AlertCircle, ArrowRight, Camera, X } from 'lucide-react';
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
        const isMismatch = w.type === 'MISMATCH_ITEM';

        return (
          <div
            key={idx}
            className={`p-4 rounded-2xl border flex flex-col gap-3 shadow-md animate-fade-in transition-all ${
              isRemoving
                ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-400 dark:border-amber-600/70 text-amber-950 dark:text-amber-100 shadow-amber-500/10'
                : isRemovedPending
                ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-300 dark:border-blue-700/60 text-blue-950 dark:text-blue-100 shadow-blue-500/10'
                : isRemoval
                ? 'bg-amber-50 dark:bg-amber-950/30 border-amber-300 dark:border-amber-700/60 text-amber-900 dark:text-amber-200'
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
                    : isRemoval
                    ? 'bg-amber-200/70 dark:bg-amber-900/50 text-amber-800 dark:text-amber-300'
                    : 'bg-red-200/70 dark:bg-red-900/50 text-red-800 dark:text-red-300'
                }`}
              >
                {isRemoval ? <AlertCircle className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
              </div>

              <div className="flex-1">
                <div className="font-semibold text-sm">
                  {isRemoving
                    ? 'Item Removal in Progress'
                    : isRemovedPending
                    ? 'Item Removed from Cart'
                    : isRemoval
                    ? 'Item Removed from Cart'
                    : isMismatch
                    ? 'Item Check Needed'
                    : 'Unscanned Item Detected'}
                </div>
                <p className="text-xs mt-0.5 opacity-90 leading-relaxed font-medium">
                  {w.message}
                </p>
              </div>
            </div>

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

              {!isRemoving && !isRemovedPending && isRemoval && (
                <button
                  onClick={() => onRescanRemoveClick(w.target_barcode)}
                  className="bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Rescan to Drop from Bill
                </button>
              )}

              {!isRemoval && (
                <button
                  onClick={onScanClick}
                  className="bg-red-600 hover:bg-red-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Scan Barcode Now
                  <ArrowRight className="w-3 h-3 ml-0.5" />
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
