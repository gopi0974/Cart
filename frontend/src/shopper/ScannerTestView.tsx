import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Barcode, Camera, Flashlight, Volume2, VolumeX, CheckCircle2, 
  AlertCircle, RefreshCw, ZoomIn, Clock, ShieldCheck, Database, ArrowLeft
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { BrowserMultiFormatReader, BarcodeFormat } from '@zxing/browser';
import { DecodeHintType } from '@zxing/library';
import { CameraHelper } from '../services/cameraHelper';
import { audioFeedback } from '../services/audioFeedback';
import { api } from '../services/api';
import { Product } from '../types';

interface ScanHistoryItem {
  id: string;
  time: string;
  value: string;
  format: string;
  decodeTimeMs: number;
  productName?: string;
  productFound?: boolean;
}

export const ScannerTestView: React.FC = () => {
  const [status, setStatus] = useState<'STARTING' | 'SCANNING' | 'DECODED' | 'ERROR'>('STARTING');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);

  // Decoded info
  const [lastValue, setLastValue] = useState<string | null>(null);
  const [lastFormat, setLastFormat] = useState<string | null>(null);
  const [lastDecodeTime, setLastDecodeTime] = useState<number | null>(null);
  const [matchedProduct, setMatchedProduct] = useState<Product | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);

  // Hardware controls & telemetry
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [torchSupported, setTorchSupported] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [zoomCaps, setZoomCaps] = useState<any>(null);
  const [streamResolution, setStreamResolution] = useState<{ width: number; height: number } | null>(null);
  const [hasNativeDetector, setHasNativeDetector] = useState<boolean>(false);

  // History log
  const [history, setHistory] = useState<ScanHistoryItem[]>([]);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const zxingControlsRef = useRef<any>(null);
  const isStoppingRef = useRef(false);
  const scanStartTimestampRef = useRef<number>(Date.now());

  // Debouncing refs
  const pendingCodeRef = useRef<string | null>(null);
  const consecutiveCountRef = useRef<number>(0);
  const lastAcceptedCodeRef = useRef<string | null>(null);
  const lastAcceptedTimeRef = useRef<number>(0);

  const lookupProductInDb = async (barcode: string): Promise<Product | null> => {
    try {
      const products = await api.getProducts(barcode);
      const found = products.find((p) => p.barcode === barcode);
      return found || null;
    } catch {
      return null;
    }
  };

  const handleDecodedCandidate = useCallback(async (candidate: string, format: string) => {
    if (!candidate || isStoppingRef.current) return;
    const clean = candidate.trim();
    if (clean.length < 3) return;

    const now = Date.now();
    // 2-second cooldown on identical code
    if (clean === lastAcceptedCodeRef.current && (now - lastAcceptedTimeRef.current) < 2000) {
      return;
    }

    // 2 consecutive reads required
    if (clean === pendingCodeRef.current) {
      consecutiveCountRef.current += 1;
    } else {
      pendingCodeRef.current = clean;
      consecutiveCountRef.current = 1;
      return;
    }

    if (consecutiveCountRef.current >= 2) {
      const elapsed = Math.max(12, now - scanStartTimestampRef.current);
      lastAcceptedCodeRef.current = clean;
      lastAcceptedTimeRef.current = now;
      pendingCodeRef.current = null;
      consecutiveCountRef.current = 0;
      scanStartTimestampRef.current = now;

      audioFeedback.playScanSuccess();
      if (typeof navigator !== 'undefined' && navigator.vibrate) {
        try {
          navigator.vibrate([40, 60, 40]);
        } catch {}
      }

      setStatus('DECODED');
      setLastValue(clean);
      setLastFormat(format);
      setLastDecodeTime(elapsed);
      setErrorMessage(null);

      // Perform real database catalog lookup
      setLookupLoading(true);
      const prod = await lookupProductInDb(clean);
      setMatchedProduct(prod);
      setLookupLoading(false);

      // Add to session history
      setHistory((prev) => [
        {
          id: `${clean}-${now}`,
          time: new Date().toLocaleTimeString(),
          value: clean,
          format: format,
          decodeTimeMs: elapsed,
          productName: prod ? prod.name : undefined,
          productFound: Boolean(prod),
        },
        ...prev.slice(0, 19),
      ]);

      // Resume scanning display state after brief flash
      setTimeout(() => {
        if (!isStoppingRef.current) {
          setStatus('SCANNING');
        }
      }, 900);
    }
  }, []);

  const startScanner = useCallback(async () => {
    isStoppingRef.current = false;
    setStatus('STARTING');
    setErrorMessage(null);
    scanStartTimestampRef.current = Date.now();

    try {
      const stream = await CameraHelper.getBackCameraStream({
        idealWidth: 1280,
        idealHeight: 720,
        facingMode,
      });
      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
        const track = stream.getVideoTracks()[0];
        const settings = track.getSettings ? track.getSettings() : {};
        if (settings.width && settings.height) {
          setStreamResolution({ width: settings.width, height: settings.height });
        }
      }

      const hasTorch = CameraHelper.isTorchSupported(stream);
      setTorchSupported(hasTorch);
      const zCaps = CameraHelper.getZoomCapabilities(stream);
      setZoomCaps(zCaps);
      if (zCaps) setZoomLevel(zCaps.current);

      // Configure ZXing
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
        delayBetweenScanAttempts: 100,
      });

      // Optional Native BarcodeDetector
      let nativeDetector: any = null;
      if (typeof window !== 'undefined' && 'BarcodeDetector' in window) {
        try {
          const supported = await (window as any).BarcodeDetector.getSupportedFormats();
          const targetFormats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']
            .filter((f) => supported.includes(f));
          if (targetFormats.length > 0) {
            nativeDetector = new (window as any).BarcodeDetector({ formats: targetFormats });
            setHasNativeDetector(true);
          }
        } catch {}
      }

      let nativeInterval: any = null;
      if (nativeDetector && videoRef.current) {
        nativeInterval = setInterval(async () => {
          if (isStoppingRef.current || !videoRef.current || videoRef.current.readyState < 2) return;
          try {
            const detected = await nativeDetector.detect(videoRef.current);
            if (detected && detected.length > 0 && detected[0].rawValue) {
              handleDecodedCandidate(detected[0].rawValue, detected[0].format?.toUpperCase() || 'NATIVE');
            }
          } catch {}
        }, 120);
      }

      // Start ZXing
      if (videoRef.current) {
        const controls = await reader.decodeFromVideoElement(videoRef.current, (result) => {
          if (isStoppingRef.current) return;
          if (result && result.getText()) {
            const fmt = result.getBarcodeFormat() ? String(result.getBarcodeFormat()) : 'BARCODE';
            handleDecodedCandidate(result.getText(), fmt);
          }
        });
        zxingControlsRef.current = {
          stop: () => {
            controls.stop();
            if (nativeInterval) clearInterval(nativeInterval);
          },
        };
      }

      setStatus('SCANNING');
    } catch (err: any) {
      console.error('Scanner test camera initialization failed:', err);
      setStatus('ERROR');
      const parsed = CameraHelper.parseCameraError(err);
      setErrorMessage(parsed.message);
    }
  }, [facingMode, handleDecodedCandidate]);

  const stopScanner = useCallback(() => {
    isStoppingRef.current = true;
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

  useEffect(() => {
    startScanner();
    return () => stopScanner();
  }, [startScanner, stopScanner]);

  const handleToggleTorch = async () => {
    if (!streamRef.current) return;
    const next = !torchEnabled;
    const ok = await CameraHelper.setTorch(streamRef.current, next);
    if (ok) setTorchEnabled(next);
  };

  const handleToggleZoom = async () => {
    if (!streamRef.current || !zoomCaps) return;
    const targetZoom = zoomLevel >= 2 ? 1 : Math.min(2, zoomCaps.max);
    const ok = await CameraHelper.setZoom(streamRef.current, targetZoom);
    if (ok) setZoomLevel(targetZoom);
  };

  const handleFlipCamera = () => {
    stopScanner();
    setFacingMode((prev) => (prev === 'environment' ? 'user' : 'environment'));
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Navigation */}
      <header className="p-4 border-b border-slate-800 bg-slate-900/80 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/user"
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-all"
            title="Back to Shopper App"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="font-display font-bold text-lg text-white flex items-center gap-2">
              <Barcode className="w-5 h-5 text-emerald-400" />
              <span>Real Barcode Scanner Test Bench</span>
            </h1>
            <p className="text-xs text-slate-400">
              Diagnostic verification tool for live camera barcode decoding & real catalog lookup
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const next = !soundEnabled;
              setSoundEnabled(next);
              audioFeedback.setSound(next);
            }}
            className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white transition-all"
            title="Toggle audio beep"
          >
            {soundEnabled ? <Volume2 className="w-4 h-4 text-emerald-400" /> : <VolumeX className="w-4 h-4 opacity-50" />}
          </button>
          <button
            onClick={handleFlipCamera}
            className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white transition-all flex items-center gap-1.5 text-xs font-semibold"
            title="Switch facing mode"
          >
            <RefreshCw className="w-4 h-4 text-emerald-400" />
            <span className="hidden sm:inline">{facingMode === 'environment' ? 'Rear Cam' : 'Front Cam'}</span>
          </button>
        </div>
      </header>

      {/* Main Grid View */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Live Camera Viewfinder */}
        <div className="lg:col-span-7 flex flex-col gap-4">
          <div className="relative aspect-[4/3] sm:aspect-[16/9] w-full bg-black rounded-3xl overflow-hidden border border-slate-800 shadow-2xl flex items-center justify-center">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover"
            />

            {/* Shroud */}
            <div className="absolute inset-0 bg-black/40 pointer-events-none" />

            {/* Wide 84% Scanning Box */}
            <div className="relative w-[84%] max-w-sm h-36 border-2 border-emerald-400 rounded-2xl overflow-hidden shadow-2xl backdrop-contrast-125 z-10 flex items-center justify-center bg-black/10">
              {status === 'SCANNING' && (
                <div className="absolute left-0 right-0 h-0.5 bg-red-500 shadow-[0_0_12px_#ef4444] animate-laser" />
              )}
              <div className="absolute top-2 left-2 w-5 h-5 border-t-3 border-l-3 border-emerald-400 rounded-tl-sm pointer-events-none" />
              <div className="absolute top-2 right-2 w-5 h-5 border-t-3 border-r-3 border-emerald-400 rounded-tr-sm pointer-events-none" />
              <div className="absolute bottom-2 left-2 w-5 h-5 border-b-3 border-l-3 border-emerald-400 rounded-bl-sm pointer-events-none" />
              <div className="absolute bottom-2 right-2 w-5 h-5 border-b-3 border-r-3 border-emerald-400 rounded-br-sm pointer-events-none" />

              {status === 'DECODED' && lastValue && (
                <div className="absolute inset-0 bg-emerald-600/90 flex flex-col items-center justify-center text-white p-3 text-center animate-fade-in z-20">
                  <CheckCircle2 className="w-8 h-8 text-white mb-1 animate-bounce" />
                  <div className="text-sm font-mono font-bold tracking-wider">{lastValue}</div>
                  <div className="text-[10px] uppercase opacity-90">{lastFormat}</div>
                </div>
              )}
            </div>

            {/* Hardware Controls Overlay */}
            <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between z-20 pointer-events-auto">
              <div className="flex items-center gap-2 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded-full border border-white/10 text-xs">
                <span
                  className={`w-2 h-2 rounded-full ${
                    status === 'SCANNING' ? 'bg-emerald-400 animate-pulse' :
                    status === 'DECODED' ? 'bg-emerald-500' :
                    status === 'STARTING' ? 'bg-amber-400 animate-pulse' : 'bg-red-500'
                  }`}
                />
                <span className="font-semibold text-white">{status}</span>
              </div>

              <div className="flex items-center gap-2">
                {torchSupported && (
                  <button
                    onClick={handleToggleTorch}
                    className={`p-2.5 rounded-full transition-all active:scale-95 ${
                      torchEnabled ? 'bg-amber-400 text-black shadow-lg shadow-amber-400/30' : 'bg-slate-900/80 text-white hover:bg-slate-800'
                    }`}
                    title="Toggle Flashlight"
                  >
                    <Flashlight className="w-4 h-4" />
                  </button>
                )}
                {zoomCaps && zoomCaps.max > 1 && (
                  <button
                    onClick={handleToggleZoom}
                    className={`px-3 py-1.5 rounded-full text-xs font-bold transition-all active:scale-95 ${
                      zoomLevel > 1 ? 'bg-emerald-500 text-white' : 'bg-slate-900/80 text-white hover:bg-slate-800'
                    }`}
                    title="Toggle Zoom"
                  >
                    {zoomLevel.toFixed(1)}x
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Telemetry Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-slate-900 p-3 rounded-2xl border border-slate-800">
              <div className="text-slate-400 text-[10px] uppercase font-bold">Decoder Engine</div>
              <div className="font-semibold text-emerald-400 mt-0.5 truncate">
                ZXing {hasNativeDetector ? '+ Native' : 'Wasm'}
              </div>
            </div>
            <div className="bg-slate-900 p-3 rounded-2xl border border-slate-800">
              <div className="text-slate-400 text-[10px] uppercase font-bold">Camera Resolution</div>
              <div className="font-mono font-semibold text-white mt-0.5">
                {streamResolution ? `${streamResolution.width}x${streamResolution.height}` : '720p Ideal'}
              </div>
            </div>
            <div className="bg-slate-900 p-3 rounded-2xl border border-slate-800">
              <div className="text-slate-400 text-[10px] uppercase font-bold">Scan Rate</div>
              <div className="font-mono font-semibold text-white mt-0.5">~10 Scans / sec</div>
            </div>
            <div className="bg-slate-900 p-3 rounded-2xl border border-slate-800">
              <div className="text-slate-400 text-[10px] uppercase font-bold">Decode Latency</div>
              <div className="font-mono font-semibold text-emerald-400 mt-0.5">
                {lastDecodeTime ? `${lastDecodeTime}ms` : '—'}
              </div>
            </div>
          </div>

          {errorMessage && (
            <div className="bg-red-950/80 border border-red-500/50 p-4 rounded-2xl flex items-start gap-3 text-red-200 text-xs">
              <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
              <div>
                <div className="font-bold text-sm">Camera Hardware Alert</div>
                <div className="mt-0.5">{errorMessage}</div>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Real-Time Diagnostic Feed & History */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          {/* Latest Decoded Card */}
          <div className="bg-slate-900 rounded-3xl p-5 border border-slate-800 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <h2 className="font-bold text-sm text-white">Latest Decoded Barcode</h2>
              </div>
              <span className="text-[10px] font-mono text-slate-500">2 Consecutive Reads</span>
            </div>

            {lastValue ? (
              <div className="space-y-3">
                <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800/80 flex items-center justify-between">
                  <div>
                    <div className="text-xs text-slate-400 font-medium">Decoded Value</div>
                    <div className="text-xl font-mono font-black text-emerald-400 tracking-wider mt-0.5">
                      {lastValue}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-400 font-medium">Format</div>
                    <div className="text-xs font-mono font-bold text-slate-200 mt-0.5">
                      {lastFormat || '1D'}
                    </div>
                  </div>
                </div>

                {/* Catalog Match Indicator */}
                <div className="p-3.5 rounded-2xl border text-xs flex items-start gap-2.5 bg-slate-950/50 border-slate-800">
                  <Database className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div className="text-[10px] font-bold text-slate-400 uppercase">Supermarket Catalog Status</div>
                    {lookupLoading ? (
                      <div className="text-slate-400 text-xs mt-0.5">Querying PostgreSQL catalog...</div>
                    ) : matchedProduct ? (
                      <div className="mt-0.5 space-y-0.5">
                        <div className="font-bold text-emerald-400 text-sm">{matchedProduct.name}</div>
                        <div className="text-slate-300 font-mono text-xs">
                          Price: ₹{matchedProduct.price.toFixed(2)} • {matchedProduct.category}
                        </div>
                      </div>
                    ) : (
                      <div className="text-amber-400 font-medium text-xs mt-0.5">
                        Product not found in catalog (Barcode: {lastValue})
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-slate-500 text-xs">
                <Barcode className="w-12 h-12 mx-auto text-slate-700 mb-2 opacity-50" />
                <span>Hold a retail barcode (EAN-13, UPC, Code 128, QR) inside the viewfinder</span>
              </div>
            )}
          </div>

          {/* Session Scan History Table */}
          <div className="bg-slate-900 rounded-3xl p-5 border border-slate-800 shadow-xl flex-1 flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
              <h2 className="font-bold text-sm text-white flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-400" />
                <span>Session Scan Log</span>
              </h2>
              <span className="text-xs text-slate-500 font-mono">{history.length} scans</span>
            </div>

            <div className="flex-1 overflow-y-auto max-h-72 space-y-2 pr-1">
              {history.length > 0 ? (
                history.map((h) => (
                  <div
                    key={h.id}
                    className="p-2.5 rounded-xl bg-slate-950 border border-slate-800/80 flex items-center justify-between text-xs hover:border-slate-700 transition-colors"
                  >
                    <div>
                      <div className="font-mono font-bold text-white flex items-center gap-1.5">
                        <span>{h.value}</span>
                        <span className="text-[10px] font-normal px-1.5 py-0.2 rounded bg-slate-800 text-slate-300">
                          {h.format}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 truncate max-w-[200px] mt-0.5">
                        {h.productName ? (
                          <span className="text-emerald-400 font-medium">{h.productName}</span>
                        ) : (
                          <span className="text-slate-500">Uncataloged Item</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-slate-400 text-[10px]">{h.time}</div>
                      <div className="font-mono text-emerald-400 text-[10px] mt-0.5">{h.decodeTimeMs}ms</div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-6 text-slate-600 text-xs">
                  No barcodes scanned yet during this test session.
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};
