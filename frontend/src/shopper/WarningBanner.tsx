import React from 'react';
import { AlertTriangle, AlertCircle, ArrowRight, Camera } from 'lucide-react';
import { ActiveWarning } from '../types';

interface Props {
  warnings: ActiveWarning[];
  onScanClick: () => void;
  onRescanRemoveClick: (barcode?: string) => void;
}

export const WarningBanner: React.FC<Props> = ({ warnings, onScanClick, onRescanRemoveClick }) => {
  if (!warnings || warnings.length === 0) return null;

  return (
    <div className="space-y-3 mb-5">
      {warnings.map((w, idx) => {
        const isRemoval = w.type === 'REMOVAL_WITHOUT_RESCAN';
        const isMismatch = w.type === 'MISMATCH_ITEM';

        return (
          <div
            key={idx}
            className={`p-4 rounded-2xl border flex flex-col gap-3 shadow-md animate-fade-in transition-all ${
              isRemoval
                ? 'bg-amber-50 dark:bg-amber-950/30 border-amber-300 dark:border-amber-700/60 text-amber-900 dark:text-amber-200'
                : 'bg-red-50 dark:bg-red-950/30 border-red-300 dark:border-red-700/60 text-red-900 dark:text-red-200'
            }`}
          >
            <div className="flex items-start gap-3">
              <div
                className={`p-2 rounded-xl flex-shrink-0 ${
                  isRemoval
                    ? 'bg-amber-200/70 dark:bg-amber-900/50 text-amber-800 dark:text-amber-300'
                    : 'bg-red-200/70 dark:bg-red-900/50 text-red-800 dark:text-red-300'
                }`}
              >
                {isRemoval ? <AlertCircle className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
              </div>

              <div className="flex-1">
                <div className="font-semibold text-sm">
                  {isRemoval
                    ? 'Item Removed from Cart'
                    : isMismatch
                    ? 'Item Check Needed'
                    : 'Unscanned Item Detected'}
                </div>
                <p className="text-xs mt-0.5 opacity-90 leading-relaxed">
                  {w.message}
                </p>
              </div>
            </div>

            {/* Direct Action Button */}
            <div className="flex justify-end">
              {isRemoval ? (
                <button
                  onClick={() => onRescanRemoveClick(w.target_barcode)}
                  className="bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold px-4 py-2 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Rescan to Drop from Bill
                </button>
              ) : (
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
