import React, { useState, useEffect, useRef } from 'react';
import { X, Flashlight, RefreshCw, Barcode, Volume2, VolumeX, Sparkles } from 'lucide-react';
import { audioFeedback } from '../services/audioFeedback';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onBarcodeDetected: (barcode: string) => void;
  mode?: 'ADD' | 'REMOVE';
}

export const BarcodeScannerModal: React.FC<Props> = ({ isOpen, onClose, onBarcodeDetected, mode = 'ADD' }) => {
  const [torch, setTorch] = useState(false);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Quick Demo items for instant testing without physical barcodes
  const DEMO_ITEMS = [
    { name: 'Amul Milk 1L', barcode: '8901262010053', price: '₹52.00', category: 'Dairy' },
    { name: 'Cadbury Silk 150g', barcode: '7622201745424', price: '₹165.00', category: 'Confectionery' },
    { name: 'Epigamia Yogurt 120g', barcode: '8906070430018', price: '₹60.00', category: 'Dairy' },
    { name: 'Quaker Oats 1kg', barcode: '8901491101934', price: '₹185.00', category: 'Breakfast' },
    { name: 'Nescafe Coffee 200g', barcode: '8901058852300', price: '₹389.00', category: 'Beverages' },
    { name: 'Tropicana Orange 1L', barcode: '8902080000014', price: '₹129.00', category: 'Beverages' },
  ];

  useEffect(() => {
    if (!isOpen) {
      stopCamera();
      return;
    }

    startCamera();
    return () => stopCamera();
  }, [isOpen, facingMode]);

  const startCamera = async () => {
    setCameraError(null);
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: facingMode }
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      }
    } catch (err: any) {
      console.warn('Live camera access error or desktop fallback:', err);
      setCameraError('Camera access unavailable or permission denied. Use demo barcode buttons below.');
    }
  };

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  };

  const toggleTorch = async () => {
    if (!streamRef.current) return;
    const track = streamRef.current.getVideoTracks()[0];
    const capabilities = (track.getCapabilities ? track.getCapabilities() : {}) as any;
    if (capabilities.torch) {
      try {
        await (track as any).applyConstraints({
          advanced: [{ torch: !torch }]
        });
        setTorch(!torch);
      } catch (e) {
        console.warn('Torch constraint error:', e);
      }
    } else {
      setTorch(!torch);
    }
  };

  const handleSimulatedScan = (barcode: string) => {
    audioFeedback.playScanSuccess();
    onBarcodeDetected(barcode);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex flex-col justify-between animate-fade-in">
      {/* Top Header Controls */}
      <div className="p-4 flex items-center justify-between text-white z-10">
        <button
          onClick={onClose}
          className="p-2.5 rounded-full bg-white/10 hover:bg-white/20 active:scale-95 transition-all"
        >
          <X className="w-6 h-6" />
        </button>

        <div className="text-center">
          <h3 className="font-semibold text-base font-display">
            {mode === 'REMOVE' ? 'Rescan Removed Item' : 'Scan Product Barcode'}
          </h3>
          <p className="text-xs text-white/70">
            {mode === 'REMOVE' ? 'Confirm item removal from cart' : 'Align barcode within frame'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const next = !soundEnabled;
              setSoundEnabled(next);
              audioFeedback.setSound(next);
            }}
            className="p-2.5 rounded-full bg-white/10 hover:bg-white/20 active:scale-95 transition-all"
          >
            {soundEnabled ? <Volume2 className="w-5 h-5 text-emerald-400" /> : <VolumeX className="w-5 h-5 opacity-60" />}
          </button>
          <button
            onClick={toggleTorch}
            className={`p-2.5 rounded-full ${torch ? 'bg-amber-400 text-black' : 'bg-white/10 hover:bg-white/20 text-white'} active:scale-95 transition-all`}
          >
            <Flashlight className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Main Viewfinder with Laser Alignment Reticle */}
      <div className="relative flex-1 flex items-center justify-center p-6 overflow-hidden">
        {/* Live video background */}
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover opacity-60"
        />

        {/* Framing Guide Box */}
        <div className="relative w-72 h-44 border-2 border-white/60 rounded-3xl overflow-hidden shadow-2xl backdrop-contrast-125 z-10 flex items-center justify-center">
          {/* Laser guide line */}
          <div className="absolute left-0 right-0 h-0.5 bg-red-500 shadow-[0_0_12px_#ef4444] animate-laser"></div>

          {/* Corner brackets */}
          <div className="absolute top-3 left-3 w-4 h-4 border-t-2 border-l-2 border-emerald-400 rounded-tl-sm"></div>
          <div className="absolute top-3 right-3 w-4 h-4 border-t-2 border-r-2 border-emerald-400 rounded-tr-sm"></div>
          <div className="absolute bottom-3 left-3 w-4 h-4 border-b-2 border-l-2 border-emerald-400 rounded-bl-sm"></div>
          <div className="absolute bottom-3 right-3 w-4 h-4 border-b-2 border-r-2 border-emerald-400 rounded-br-sm"></div>

          <Barcode className="w-16 h-16 text-white/20" />
        </div>

        {cameraError && (
          <div className="absolute bottom-4 bg-slate-900/90 text-amber-300 text-xs px-4 py-2 rounded-xl border border-amber-500/30 z-20">
            {cameraError}
          </div>
        )}
      </div>

      {/* Quick Interactive Demo Barcode Chips */}
      <div className="p-4 bg-slate-900/95 border-t border-white/10 z-10 rounded-t-3xl">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            Quick Test Barcode Samples
          </span>
          <button
            onClick={() => setFacingMode(facingMode === 'environment' ? 'user' : 'environment')}
            className="text-xs text-emerald-400 flex items-center gap-1 hover:underline"
          >
            <RefreshCw className="w-3 h-3" />
            Flip Cam
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto pr-1">
          {DEMO_ITEMS.map((item) => (
            <button
              key={item.barcode}
              onClick={() => handleSimulatedScan(item.barcode)}
              className="text-left bg-white/5 hover:bg-emerald-600/20 hover:border-emerald-500/50 border border-white/10 p-2.5 rounded-xl transition-all active:scale-95 group"
            >
              <div className="text-xs font-medium text-white truncate group-hover:text-emerald-300">
                {item.name}
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400 mt-0.5">
                <span className="font-mono text-emerald-400">{item.price}</span>
                <span className="font-mono text-[10px] opacity-75">{item.barcode.slice(-4)}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
