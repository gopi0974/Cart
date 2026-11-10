import React, { useState } from 'react';
import { Camera, Lock, AlertTriangle, ShieldAlert, RefreshCw, X, Smartphone, Globe, Laptop, HelpCircle } from 'lucide-react';
import { CameraStatus, CameraPermissionState } from '../services/cameraHelper';

interface Props {
  status: CameraStatus;
  permissionState: CameraPermissionState;
  onRequestPermission: () => void;
  onRetry: () => void;
  onClose: () => void;
  title?: string;
  description?: string;
}

export const CameraPermissionExplainer: React.FC<Props> = ({
  status,
  permissionState,
  onRequestPermission,
  onRetry,
  onClose,
  title,
  description,
}) => {
  const [activeTab, setActiveTab] = useState<'android' | 'ios' | 'desktop'>('android');

  // 1. BLOCKED / DENIED: Step-by-step browser guides
  if (status === 'BLOCKED' || permissionState === 'denied') {
    return (
      <div className="p-6 bg-white dark:bg-[#131B2E] rounded-3xl max-w-md w-full mx-auto shadow-2xl border border-red-200 dark:border-red-900/60 text-slate-800 dark:text-slate-100 flex flex-col items-center text-center animate-in fade-in zoom-in-95 duration-200">
        <div className="w-14 h-14 rounded-2xl bg-red-100 dark:bg-red-950/60 flex items-center justify-center text-red-600 dark:text-red-400 mb-4 shadow-inner">
          <Lock className="w-7 h-7" />
        </div>

        <h3 className="font-display font-bold text-lg text-red-600 dark:text-red-400 mb-1">
          Camera Access Blocked
        </h3>
        <p className="text-xs text-slate-600 dark:text-slate-400 mb-4 max-w-xs">
          Camera access was blocked by your browser. Please follow the steps below to allow access and scan barcodes:
        </p>

        {/* Browser Selector Tabs */}
        <div className="flex w-full bg-slate-100 dark:bg-slate-800/80 rounded-xl p-1 mb-4 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setActiveTab('android')}
            className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1.5 transition-all ${
              activeTab === 'android'
                ? 'bg-white dark:bg-slate-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Smartphone className="w-3.5 h-3.5" />
            <span>Android</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('ios')}
            className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1.5 transition-all ${
              activeTab === 'ios'
                ? 'bg-white dark:bg-slate-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Globe className="w-3.5 h-3.5" />
            <span>iPhone</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('desktop')}
            className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1.5 transition-all ${
              activeTab === 'desktop'
                ? 'bg-white dark:bg-slate-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Laptop className="w-3.5 h-3.5" />
            <span>Desktop</span>
          </button>
        </div>

        {/* Tab Instructions Content */}
        <div className="w-full bg-slate-50 dark:bg-slate-900/60 rounded-2xl p-4 border border-slate-200 dark:border-slate-800 text-left text-xs mb-5 space-y-2.5">
          {activeTab === 'android' && (
            <>
              <div className="font-semibold text-slate-900 dark:text-white flex items-center gap-1.5 mb-1 text-[13px]">
                <span className="w-5 h-5 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px] font-bold">1</span>
                Android (Chrome)
              </div>
              <ol className="list-decimal list-inside space-y-1.5 text-slate-600 dark:text-slate-300">
                <li>Tap the <strong>lock / tune icon</strong> 🔒 in the address bar.</li>
                <li>Tap <strong>Permissions</strong> → <strong>Camera</strong>.</li>
                <li>Select <strong>Allow</strong>, then reload this page.</li>
              </ol>
            </>
          )}

          {activeTab === 'ios' && (
            <>
              <div className="font-semibold text-slate-900 dark:text-white flex items-center gap-1.5 mb-1 text-[13px]">
                <span className="w-5 h-5 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px] font-bold">1</span>
                iPhone (Safari)
              </div>
              <ol className="list-decimal list-inside space-y-1.5 text-slate-600 dark:text-slate-300">
                <li>Tap the <strong>aA</strong> icon in the address bar.</li>
                <li>Tap <strong>Website Settings</strong>.</li>
                <li>Tap <strong>Camera</strong> and set to <strong>Allow</strong>.</li>
                <li>Tap <strong>Done</strong> and reload this page.</li>
              </ol>
            </>
          )}

          {activeTab === 'desktop' && (
            <>
              <div className="font-semibold text-slate-900 dark:text-white flex items-center gap-1.5 mb-1 text-[13px]">
                <span className="w-5 h-5 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px] font-bold">1</span>
                Desktop (Chrome / Edge)
              </div>
              <ol className="list-decimal list-inside space-y-1.5 text-slate-600 dark:text-slate-300">
                <li>Click the <strong>padlock icon</strong> 🔒 next to the website URL.</li>
                <li>Toggle <strong>Camera</strong> to <strong>Allow / On</strong>.</li>
                <li>Click <strong>Reload</strong> to apply changes.</li>
              </ol>
            </>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2 w-full">
          <button
            type="button"
            onClick={onRetry}
            className="flex-1 py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-md shadow-emerald-600/20 active:scale-95 transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Try Again
          </button>
          <button
            type="button"
            onClick={onClose}
            className="py-2.5 px-4 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs hover:bg-slate-100 dark:hover:bg-slate-800 active:scale-95 transition-all"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  // 2. CAMERA IN USE or NOT FOUND
  if (status === 'IN_USE' || status === 'NOT_FOUND' || status === 'INSECURE' || status === 'ERROR') {
    return (
      <div className="p-6 bg-white dark:bg-[#131B2E] rounded-3xl max-w-md w-full mx-auto shadow-2xl border border-amber-200 dark:border-amber-900/60 text-slate-800 dark:text-slate-100 flex flex-col items-center text-center animate-in fade-in zoom-in-95 duration-200">
        <div className="w-14 h-14 rounded-2xl bg-amber-100 dark:bg-amber-950/60 flex items-center justify-center text-amber-600 dark:text-amber-400 mb-4 shadow-inner">
          <AlertTriangle className="w-7 h-7" />
        </div>

        <h3 className="font-display font-bold text-lg text-slate-900 dark:text-white mb-1">
          {status === 'IN_USE'
            ? 'Camera Is in Use'
            : status === 'NOT_FOUND'
            ? 'No Camera Detected'
            : status === 'INSECURE'
            ? 'HTTPS Secure Connection Required'
            : 'Camera Connection Failed'}
        </h3>

        <p className="text-xs text-slate-600 dark:text-slate-400 mb-5 max-w-xs">
          {status === 'IN_USE'
            ? 'Your camera is currently in use by another app or browser tab. Please close any other camera apps and tap retry.'
            : status === 'NOT_FOUND'
            ? 'No camera was found on this device. You can still type barcodes or cart numbers manually.'
            : status === 'INSECURE'
            ? 'Camera access requires a secure HTTPS connection. Please load this site over HTTPS.'
            : 'Unable to start camera viewfinder. Please tap retry to try again.'}
        </p>

        <div className="flex gap-2 w-full">
          <button
            type="button"
            onClick={onRetry}
            className="flex-1 py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-md shadow-emerald-600/20 active:scale-95 transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
          <button
            type="button"
            onClick={onClose}
            className="py-2.5 px-4 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs hover:bg-slate-100 dark:hover:bg-slate-800 active:scale-95 transition-all"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  // 3. PRE-PERMISSION EXPLAINER (Shown before first camera access)
  return (
    <div className="p-6 bg-white dark:bg-[#131B2E] rounded-3xl max-w-md w-full mx-auto shadow-2xl border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100 flex flex-col items-center text-center animate-in fade-in zoom-in-95 duration-200">
      <div className="w-14 h-14 rounded-2xl bg-emerald-100 dark:bg-emerald-950/60 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-4 shadow-inner">
        <Camera className="w-7 h-7" />
      </div>

      <h3 className="font-display font-bold text-lg text-slate-900 dark:text-white mb-1">
        {title || 'Camera Access Needed'}
      </h3>
      <p className="text-xs text-slate-600 dark:text-slate-400 mb-5 max-w-xs leading-relaxed">
        {description || 'SmartCart needs camera access to scan cart QR codes and item barcodes in real time. Your camera feed stays on your device.'}
      </p>

      <div className="w-full bg-slate-50 dark:bg-slate-900/60 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 text-left text-xs text-slate-600 dark:text-slate-400 mb-5 space-y-1.5">
        <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span>Fast, touchless retail barcode scanning</span>
        </div>
        <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span>Camera stream is automatically closed when done</span>
        </div>
      </div>

      <div className="flex gap-2 w-full">
        <button
          type="button"
          onClick={onRequestPermission}
          className="flex-1 py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/30 active:scale-95 transition-all"
        >
          <Camera className="w-4 h-4" />
          Allow Camera
        </button>
        <button
          type="button"
          onClick={onClose}
          className="py-3 px-4 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs hover:bg-slate-100 dark:hover:bg-slate-800 active:scale-95 transition-all"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

