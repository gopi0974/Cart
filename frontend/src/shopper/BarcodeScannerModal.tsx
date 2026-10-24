import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  X, Flashlight, Barcode, Volume2, VolumeX, AlertCircle, 
  CheckCircle2, ArrowRight, RefreshCw, ZoomIn, Info, HelpCircle
} from 'lucide-react';
import { BrowserMultiFormatReader, BarcodeFormat } from '@zxing/browser';
import { DecodeHintType } from '@zxing/library';
import { audioFeedback } from '../services/audioFeedback';
import { CameraHelper, CameraErrorResult } from '../services/cameraHelper';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onBarcodeDetected: (barcode: string) => Promise<void> | void;
  mode?: 'ADD' | 'REMOVE';
  targetProductName?: string;
}

type ScannerStatus = 'STARTING' | 'SCANNING' | 'DECODED' | 'ERROR';

export const BarcodeScannerModal: React.FC<Props> = ({ 
  isOpen, 
  onClose, 
  onBarcodeDetected, 
  mode = 'ADD',
  targetProductName
}) => {
  // Scanner state
  const [status, setStatus] = useState<ScannerStatus>('STARTING');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [decodedValue, setDecodedValue] = useState<string | null>(null);
  const [decodedFormat, setDecodedFormat] = useState<string | null>(null);
  const [showTips, setShowTips] = useState<boolean>(false);
  const [soundEnabled, setSoundEnabled] = useState<boolean>(true);

  // Hardware controls
  const [torchEnabled, setTorchEnabled] = useState<boolean>(false);
  const [torchSupported, setTorchSupported] = useState<boolean>(false);
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [zoomCaps, setZoomCaps] = useState<{ min: number; max: number; step: number; current: number } | null>(null);

  // Manual input fallback
  const [manualBarcode, setManualBarcode] = useState<string>('');
  const [manualSubmitting, setManualSubmitting] = useState<boolean>(false);

  // Refs for camera and decoding
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const zxingControlsRef = useRef<any>(null);
  const isStoppingRef = useRef<boolean>(false);

  // 2 consecutive identical reads debouncing & 2s cooldown
  const pendingCodeRef = useRef<string | null>(null);
  const consecutiveCountRef = useRef<number>(0);
  const lastAcceptedCodeRef = useRef<string | null>(null);
  const lastAcceptedTimeRef = useRef<number>(0);

  // 8-second tip timer
  const tipTimerRef = useRef<any>(null);

  // Process a raw decoded candidate from ZXing or native BarcodeDetector
  const handleRawCandidate = useCallback(async (candidate: string, formatName: string = '1D/2D Barcode') => {
    if (!candidate || isStoppingRef.current) return;
    const cleanCode = candidate.trim();
    if (cleanCode.length < 3) return;

    const now = Date.now();

    // 1. Ignore the same code for 2 seconds after acceptance
    if (cleanCode === lastAcceptedCodeRef.current && (now - lastAcceptedTimeRef.current) < 2000) {
      return;
    }

    // 2. Enforce 2 consecutive identical reads
    if (cleanCode === pendingCodeRef.current) {
      consecutiveCountRef.current += 1;
    } else {
      pendingCodeRef.current = cleanCode;
      consecutiveCountRef.current = 1;
      return;
    }

    if (consecutiveCountRef.current >= 2) {
      // Confirmed read!
      lastAcceptedCodeRef.current = cleanCode;
      lastAcceptedTimeRef.current = now;
      pendingCodeRef.current = null;
      consecutiveCountRef.current = 0;

      // Provide immediate sensory cues
      audioFeedback.playScanSuccess();
      if (typeof navigator !== 'undefined' && navigator.vibrate) {
        try {
          navigator.vibrate([40, 60, 40]);
        } catch {}
      }

      setStatus('DECODED');
      setDecodedValue(cleanCode);
      setDecodedFormat(formatName);

      // Submit barcode to active cart
      try {
        await onBarcodeDetected(cleanCode);
        setTimeout(() => {
          onClose();
        }, 400);
      } catch (err: any) {
        // If product lookup or rescan failed, show error in modal and resume scanning
        setStatus('ERROR');
        setErrorMessage(err?.message || `Error with barcode ${cleanCode}`);
        setTimeout(() => {
          setStatus('SCANNING');
        }, 3200);
      }
    }
  }, [onBarcodeDetected, onClose]);

  // Start real camera and ZXing reader
  const startScanner = useCallback(async () => {
    isStoppingRef.current = false;
    setStatus('STARTING');
    setErrorMessage(null);
    setDecodedValue(null);
    setShowTips(false);

    try {
      // 1. Obtain real back camera stream (1280x720 ideal, continuous focus)
      const stream = await CameraHelper.getBackCameraStream({
        idealWidth: 1280,
        idealHeight: 720,
        facingMode: 'environment',
      });
      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }

      // Check hardware capabilities (torch, zoom)
      const hasTorch = CameraHelper.isTorchSupported(stream);
      setTorchSupported(hasTorch);
      const zCaps = CameraHelper.getZoomCapabilities(stream);
      setZoomCaps(zCaps);
      if (zCaps) setZoomLevel(zCaps.current);

      // 2. Configure ZXing Multi-Format Reader with all required retail formats
      const hints = new Map<DecodeHintType, any>();
      hints.set(DecodeHintType.POSSIBLE_FORMATS, [
        BarcodeFormat.EAN_13,
        BarcodeFormat.EAN_8,
        BarcodeFormat.UPC_A,
        BarcodeFormat.UPC_E,
        BarcodeFormat.CODE_128,
        BarcodeFormat.CODE_39,
        BarcodeFormat.ITF,
        BarcodeFormat.QR_CODE,
      ]);
      hints.set(DecodeHintType.TRY_HARDER, true);

      const reader = new BrowserMultiFormatReader(hints, {
        delayBetweenScanAttempts: 100, // ~10 scans per second
      });

      // 3. Optional speedup: Native BarcodeDetector if available
      let nativeDetector: any = null;
      if (typeof window !== 'undefined' && 'BarcodeDetector' in window) {
        try {
          const supported = await (window as any).BarcodeDetector.getSupportedFormats();
          const targetFormats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']
            .filter((f) => supported.includes(f));
          if (targetFormats.length > 0) {
            nativeDetector = new (window as any).BarcodeDetector({ formats: targetFormats });
          }
        } catch (e) {
          console.warn('BarcodeDetector initialization skipped:', e);
        }
      }

      // Native detection ticker (runs alongside ZXing)
      let nativeInterval: any = null;
      if (nativeDetector && videoRef.current) {
        nativeInterval = setInterval(async () => {
          if (isStoppingRef.current || !videoRef.current || videoRef.current.readyState < 2) return;
          try {
            const barcodes = await nativeDetector.detect(videoRef.current);
            if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
              handleRawCandidate(barcodes[0].rawValue, barcodes[0].format?.toUpperCase() || 'NATIVE');
            }
          } catch {}
        }, 120);
      }

      // 4. Start ZXing continuous video stream decoding
      if (videoRef.current) {
        const controls = await reader.decodeFromVideoElement(
          videoRef.current,
          (result, error) => {
            if (isStoppingRef.current) return;
            if (result && result.getText()) {
              const formatStr = result.getBarcodeFormat() ? String(result.getBarcodeFormat()) : 'BARCODE';
              handleRawCandidate(result.getText(), formatStr);
            }
          }
        );
        zxingControlsRef.current = {
          stop: () => {
            controls.stop();
            if (nativeInterval) clearInterval(nativeInterval);
          },
        };
      }

      setStatus('SCANNING');

      // Start 8-second tip timer if no barcode is read
      tipTimerRef.current = setTimeout(() => {
        setShowTips(true);
      }, 8000);

    } catch (err: any) {
      console.error('Failed to initialize barcode camera scanner:', err);
      setStatus('ERROR');
      const parsed = err?.message ? err : CameraHelper.parseCameraError(err);
      setErrorMessage(parsed.message || 'Unable to access camera for barcode scanning.');
    }
  }, [handleRawCandidate]);

  // Teardown scanner and release hardware
  const stopScanner = useCallback(() => {
    isStoppingRef.current = true;
    if (tipTimerRef.current) {
      clearTimeout(tipTimerRef.current);
      tipTimerRef.current = null;
    }
    if (zxingControlsRef.current) {
      try {
        zxingControlsRef.current.stop();
      } catch {}
      zxingControlsRef.current = null;
    }
    if (streamRef.current) {
      CameraHelper.stopStream(streamRef.current);
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setTorchEnabled(false);
  }, []);

  // Modal open/close lifecycle
  useEffect(() => {
    if (isOpen) {
      startScanner();
    } else {
      stopScanner();
    }
    return () => {
      stopScanner();
    };
  }, [isOpen, startScanner, stopScanner]);

  // Toggle Hardware Flashlight / Torch
  const handleToggleTorch = async () => {
    if (!streamRef.current) return;
    const nextState = !torchEnabled;
    const ok = await CameraHelper.setTorch(streamRef.current, nextState);
    if (ok) setTorchEnabled(nextState);
  };

  // Toggle Zoom Level (e.g. 1x / 2x)
  const handleToggleZoom = async () => {
    if (!streamRef.current || !zoomCaps) return;
    const targetZoom = zoomLevel >= 2 ? 1 : Math.min(2, zoomCaps.max);
    const ok = await CameraHelper.setZoom(streamRef.current, targetZoom);
    if (ok) setZoomLevel(targetZoom);
  };

  // Viewfinder Tap-to-Focus
  const handleViewfinderTap = async () => {
    if (!streamRef.current) return;
    await CameraHelper.triggerFocus(streamRef.current);
  };

  // Manual fallback submission
  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const clean = manualBarcode.trim();
    if (!clean) return;

    setManualSubmitting(true);
    setErrorMessage(null);
    try {
      audioFeedback.playScanSuccess();
      await onBarcodeDetected(clean);
      setManualBarcode('');
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || `Product not found (barcode ${clean})`);
    } finally {
      setManualSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/95 backdrop-blur-md flex flex-col justify-between animate-fade-in select-none">
      {/* Top Header & Hardware Controls */}
      <div className="p-4 flex items-center justify-between text-white z-20 bg-gradient-to-b from-black/80 to-transparent">
        <button
          onClick={onClose}
          className="p-2.5 rounded-full bg-white/10 hover:bg-white/20 active:scale-95 transition-all"
          title="Close scanner"
        >
          <X className="w-6 h-6" />
        </button>

        <div className="text-center">
          <h3 className="font-semibold text-base font-display flex items-center justify-center gap-1.5">
            <Barcode className="w-5 h-5 text-emerald-400" />
            <span>{mode === 'REMOVE' ? 'Rescan Removed Item' : 'Real Barcode Scanner'}</span>
          </h3>
          <p className="text-[11px] text-white/70">
            {mode === 'REMOVE' 
              ? (targetProductName ? `Rescan barcode for ${targetProductName}` : 'Scan barcode to drop from cart')
              : 'Align retail barcode inside the frame'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Sound Toggle */}
          <button
            onClick={() => {
              const next = !soundEnabled;
              setSoundEnabled(next);
              audioFeedback.setSound(next);
            }}
            className="p-2.5 rounded-full bg-white/10 hover:bg-white/20 active:scale-95 transition-all"
            title={soundEnabled ? 'Mute beep' : 'Enable beep'}
          >
            {soundEnabled ? <Volume2 className="w-5 h-5 text-emerald-400" /> : <VolumeX className="w-5 h-5 opacity-60" />}
          </button>

          {/* Torch Toggle */}
          {torchSupported && (
            <button
              onClick={handleToggleTorch}
              className={`p-2.5 rounded-full transition-all active:scale-95 ${
                torchEnabled ? 'bg-amber-400 text-black shadow-lg shadow-amber-400/30' : 'bg-white/10 hover:bg-white/20 text-white'
              }`}
              title="Toggle flashlight"
            >
              <Flashlight className="w-5 h-5" />
            </button>
          )}

          {/* Zoom Toggle */}
          {zoomCaps && zoomCaps.max > 1 && (
            <button
              onClick={handleToggleZoom}
              className={`p-2.5 rounded-full text-xs font-bold transition-all active:scale-95 ${
                zoomLevel > 1 ? 'bg-emerald-500 text-white' : 'bg-white/10 text-white hover:bg-white/20'
              }`}
              title="Toggle Zoom"
            >
              <span>{zoomLevel.toFixed(1)}x</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Viewfinder Center */}
      <div 
        onClick={handleViewfinderTap}
        className="relative flex-1 flex flex-col items-center justify-center p-4 overflow-hidden cursor-crosshair"
      >
        {/* Real Live Video Camera Feed */}
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
        />

        {/* Viewfinder Dark Overlay Shroud */}
        <div className="absolute inset-0 bg-black/40 pointer-events-none" />

        {/* Wide & Short Scan Box (84% width, ~2.4:1 ratio for retail barcodes) */}
        <div className="relative w-[86%] max-w-sm h-36 border-2 border-emerald-400/90 rounded-2xl overflow-hidden shadow-2xl backdrop-contrast-125 z-10 flex items-center justify-center bg-black/10">
          {/* Animated Red Laser Scanning Line */}
          {status === 'SCANNING' && (
            <div className="absolute left-0 right-0 h-0.5 bg-red-500 shadow-[0_0_12px_#ef4444] animate-laser" />
          )}

          {/* High-Contrast Corner Framing Reticles */}
          <div className="absolute top-2 left-2 w-5 h-5 border-t-3 border-l-3 border-emerald-400 rounded-tl-sm pointer-events-none" />
          <div className="absolute top-2 right-2 w-5 h-5 border-t-3 border-r-3 border-emerald-400 rounded-tr-sm pointer-events-none" />
          <div className="absolute bottom-2 left-2 w-5 h-5 border-b-3 border-l-3 border-emerald-400 rounded-bl-sm pointer-events-none" />
          <div className="absolute bottom-2 right-2 w-5 h-5 border-b-3 border-r-3 border-emerald-400 rounded-br-sm pointer-events-none" />

          {/* Decoded Confirmation Banner */}
          {status === 'DECODED' && decodedValue && (
            <div className="absolute inset-0 bg-emerald-600/90 flex flex-col items-center justify-center text-white p-3 text-center animate-fade-in z-20">
              <CheckCircle2 className="w-8 h-8 text-white mb-1 animate-bounce" />
              <div className="text-xs font-mono font-bold tracking-wider">{decodedValue}</div>
              <div className="text-[10px] uppercase opacity-90">{decodedFormat}</div>
            </div>
          )}

          {/* Fallback Watermark */}
          {status !== 'DECODED' && (
            <Barcode className="w-16 h-16 text-white/15 pointer-events-none" />
          )}
        </div>

        {/* Status Indicator Pill */}
        <div className="mt-4 z-10 flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-slate-900/80 backdrop-blur-md border border-white/10 text-xs text-white">
          <span 
            className={`w-2 h-2 rounded-full ${
              status === 'SCANNING' ? 'bg-emerald-400 animate-pulse' :
              status === 'DECODED' ? 'bg-emerald-500' :
              status === 'STARTING' ? 'bg-amber-400 animate-pulse' : 'bg-red-500'
            }`} 
          />
          <span className="font-medium">
            {status === 'STARTING' && 'Starting camera engine...'}
            {status === 'SCANNING' && 'Scanning for barcode (ZXing + Native)...'}
            {status === 'DECODED' && `Decoded: ${decodedValue}`}
            {status === 'ERROR' && 'Scanner error'}
          </span>
        </div>

        {/* 8-Second Helpful Diagnostic Tips */}
        {showTips && status === 'SCANNING' && (
          <div className="mt-3 z-10 max-w-xs bg-slate-900/90 border border-emerald-500/30 rounded-2xl p-3 text-white text-xs space-y-1 animate-fade-in">
            <div className="font-bold flex items-center gap-1 text-emerald-400 text-[11px] uppercase tracking-wider">
              <HelpCircle className="w-3.5 h-3.5" />
              <span>Scanning Tips</span>
            </div>
            <ul className="text-[11px] text-slate-300 list-disc list-inside space-y-0.5">
              <li>Move camera back a little (4–8 inches away)</li>
              <li>Hold steady & avoid harsh reflections/glare</li>
              {torchSupported && !torchEnabled && (
                <li>Turn on the flashlight in low light</li>
              )}
            </ul>
          </div>
        )}

        {/* Error Notification Alert */}
        {errorMessage && (
          <div className="mt-3 z-10 max-w-xs bg-red-950/90 border border-red-500 text-red-200 text-xs px-3.5 py-2.5 rounded-2xl flex items-start gap-2 shadow-xl animate-fade-in">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-bold text-[11px]">Scan Warning</div>
              <div className="text-[11px] leading-tight mt-0.5">{errorMessage}</div>
            </div>
          </div>
        )}
      </div>

      {/* Clearly Labeled Manual Entry Fallback Deck */}
      <div className="p-4 bg-slate-900/95 border-t border-white/10 z-20 rounded-t-3xl space-y-3">
        <div className="flex items-center justify-between text-xs">
          <span className="font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
            <Barcode className="w-3.5 h-3.5 text-emerald-400" />
            <span>Manual Barcode Number Entry</span>
          </span>
          <span className="text-[10px] text-slate-500 font-medium">Fallback</span>
        </div>

        <form onSubmit={handleManualSubmit} className="flex gap-2">
          <input
            type="text"
            pattern="[0-9A-Za-z-]+"
            placeholder="Type barcode (e.g. 8901262010053)"
            value={manualBarcode}
            onChange={(e) => setManualBarcode(e.target.value)}
            className="flex-1 bg-slate-800 border border-slate-700 focus:border-emerald-500 text-white text-xs font-mono rounded-xl px-3.5 py-2.5 outline-none"
          />
          <button
            type="submit"
            disabled={manualSubmitting || !manualBarcode.trim()}
            className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl flex items-center gap-1 transition-all active:scale-95 shadow-md shadow-emerald-600/20"
          >
            <span>{manualSubmitting ? 'Verifying...' : 'Look Up'}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </form>

        <p className="text-[10px] text-center text-slate-500">
          Continuous autofocus enabled • Formats: EAN-13, EAN-8, UPC-A, UPC-E, Code 128, Code 39, ITF, QR
        </p>
      </div>
    </div>
  );
};
