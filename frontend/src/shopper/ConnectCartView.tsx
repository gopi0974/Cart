import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  QrCode, ShoppingCart, ShieldCheck, Zap, ArrowRight, AlertTriangle,
  ShieldAlert, Lock, RefreshCw, Loader2, Camera, X, Flashlight
} from 'lucide-react';
import { BrowserMultiFormatReader, BarcodeFormat } from '@zxing/browser';
import { DecodeHintType } from '@zxing/library';
import { api } from '../services/api';
import { CartSession } from '../types';
import { useTranslation } from '../services/i18n';
import { CameraHelper, CameraStatus, CameraPermissionState } from '../services/cameraHelper';
import { CameraPermissionExplainer } from './CameraPermissionExplainer';

interface Props {
  onConnected: (session: CartSession) => void;
}

interface ConnectionError {
  title?: string;
  message: string;
  type?: 'security' | 'disabled' | 'occupied' | 'not_found' | 'waking_up' | 'server_error' | 'camera_denied' | 'generic';
  canRetry?: boolean;
}

export const ConnectCartView: React.FC<Props> = ({ onConnected }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [cartInput, setCartInput] = useState('CART-001');
  const [phoneInput, setPhoneInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ConnectionError | null>(null);
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [serverBaseUrl, setServerBaseUrl] = useState<string | null>(null);

  // In-App QR Camera Scanner State
  const [scannerOpen, setScannerOpen] = useState(false);
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>('IDLE');
  const [permissionState, setPermissionState] = useState<CameraPermissionState>('prompt');
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [torchSupported, setTorchSupported] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const controlsRef = useRef<any>(null);
  const unregisterStreamRef = useRef<(() => void) | null>(null);

  const { t } = useTranslation();
  const hasAutoAttempted = useRef(false);

  // Fetch shopper config on mount to strictly gate demo mode & obtain official BASE_URL
  useEffect(() => {
    api.getShopperConfig()
      .then((cfg) => {
        setIsDemoMode(Boolean(cfg?.demo_mode));
        if (cfg?.base_url) {
          setServerBaseUrl(cfg.base_url);
        }
      })
      .catch(() => {
        setIsDemoMode(false);
      });
  }, []);

  // Cleanup camera streams on unmount
  useEffect(() => {
    return () => {
      stopScanner();
    };
  }, []);

  const categorizeError = (err: any): ConnectionError => {
    const statusCode = err?.statusCode || err?.status;

    // 1. Camera permission denied
    if (err?.code === 'PERMISSION_DENIED' || err?.name === 'NotAllowedError') {
      return {
        title: 'Camera Permission Denied',
        message: 'Camera access was denied. Please allow camera permissions in your browser settings to scan the cart QR.',
        type: 'camera_denied',
        canRetry: true,
      };
    }

    if (err?.code === 'INSECURE_CONTEXT') {
      return {
        title: 'Insecure Context',
        message: 'Camera access requires a secure HTTPS connection. Please load this page over HTTPS.',
        type: 'camera_denied',
        canRetry: false,
      };
    }

    // 2. Genuine wake-up situations ONLY: network offline/error, timeout, 502, 503, 504
    const isWaking = Boolean(
      err?.isWakingUp ||
      statusCode === 502 ||
      statusCode === 503 ||
      statusCode === 504 ||
      (typeof err?.message === 'string' && (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')))
    );

    if (isWaking) {
      return {
        title: 'Starting Cart Server',
        message: 'Starting the cart server, this can take up to a minute... Please hold on while the cloud instance spins up.',
        type: 'waking_up',
        canRetry: true,
      };
    }

    // 3. HTTP 500: Internal server error
    if (statusCode === 500 || (typeof err?.message === 'string' && err.message.includes('Something went wrong on our side'))) {
      return {
        title: 'Server Error',
        message: 'Something went wrong on our side. Please try again.',
        type: 'server_error',
        canRetry: true,
      };
    }

    let msg: string = (err?.message || '').trim().toLowerCase();

    // Invalid or expired QR
    if (msg.includes('invalid') || msg.includes('expired') || msg.includes('signature') || msg.includes('security') || msg.includes('tamper')) {
      return {
        title: 'Invalid or Expired QR',
        message: 'This cart QR code is invalid or has expired. Please scan the current code on the cart.',
        type: 'security',
        canRetry: true,
      };
    }

    // Cart already in use
    if (msg.includes('occupied') || msg.includes('active shopper') || msg.includes('in use')) {
      return {
        title: 'Cart Already in Use',
        message: 'This cart is currently in use by another shopper. Please choose an available cart.',
        type: 'occupied',
        canRetry: false,
      };
    }

    // Cart disabled
    if (msg.includes('disabled')) {
      return {
        title: 'Cart Disabled',
        message: 'This cart is currently disabled. Please use another cart.',
        type: 'disabled',
        canRetry: false,
      };
    }

    // Cart not found
    if (msg.includes('not found') || msg.includes('verify the cart number')) {
      return {
        title: 'Cart Not Found',
        message: 'Cart not found. Please verify the cart number.',
        type: 'not_found',
        canRetry: true,
      };
    }

    return {
      title: 'Connection Failed',
      message: err?.message || 'Could not connect to cart. Please scan the QR code on the cart handle.',
      type: 'generic',
      canRetry: true,
    };
  };

  // Check URL search parameters (from scanned QR code: /user/connect?cart=CART-001&sig=...)
  useEffect(() => {
    const cartParam = searchParams.get('cart');
    const sigParam = searchParams.get('sig');
    const tokenParam = searchParams.get('token');
    const phoneParam = searchParams.get('phone') || undefined;

    if (cartParam && (sigParam || tokenParam) && !hasAutoAttempted.current) {
      hasAutoAttempted.current = true;
      setLoading(true);
      setError(null);

      api.pairCart({
        cart_number: cartParam,
        qr_token: tokenParam || undefined,
        signature: sigParam || undefined,
        customer_phone: phoneParam,
      })
      .then((session) => {
        setSearchParams({});
        navigate('/user', { replace: true });
        if (typeof window !== 'undefined' && window.history) {
          window.history.replaceState({}, '', '/user');
        }
        onConnected(session);
      })
      .catch((err: any) => {
        setError(categorizeError(err));
      })
      .finally(() => {
        setLoading(false);
      });
    }
  }, [searchParams, setSearchParams, navigate, onConnected]);

  // Start in-app camera scanner for cart QR (respecting browser permissions)
  const startScanner = async () => {
    setError(null);
    setTorchEnabled(false);
    setTorchSupported(false);

    const perm = await CameraHelper.checkPermission();
    setPermissionState(perm);

    if (perm === 'granted') {
      setCameraStatus('REQUESTING');
      setScannerOpen(true);
      await startRealCamera();
    } else if (perm === 'denied') {
      setCameraStatus('BLOCKED');
      setScannerOpen(true);
    } else {
      // 'prompt' or 'unsupported' -> show pre-permission explainer first!
      setCameraStatus('IDLE');
      setScannerOpen(true);
    }
  };

  const startRealCamera = async () => {
    setCameraStatus('REQUESTING');
    try {
      const stream = await CameraHelper.openCamera({
        facingMode: 'environment',
        idealWidth: 1280,
        idealHeight: 720,
      });
      streamRef.current = stream;
      unregisterStreamRef.current = CameraHelper.registerStream(stream);

      // Check torch support
      const videoTrack = stream.getVideoTracks()[0];
      if (videoTrack && typeof videoTrack.getCapabilities === 'function') {
        const caps: any = videoTrack.getCapabilities();
        if (caps.torch) {
          setTorchSupported(true);
        }
      }

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }

      // Initialize ZXing reader for QR Codes
      const hints = new Map();
      hints.set(DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.QR_CODE]);
      const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 80 });

      if (videoRef.current) {
        controlsRef.current = await reader.decodeFromVideoElement(
          videoRef.current,
          (result) => {
            if (result && !loading) {
              const text = result.getText();
              handleScannedQrResult(text);
            }
          }
        );
      }
      setCameraStatus('ACTIVE');
    } catch (err: any) {
      console.error('[ConnectCartView] Scanner start error:', err);
      const parsed = CameraHelper.parseCameraError(err);
      setCameraStatus(parsed.status);
      if (parsed.status === 'BLOCKED') {
        setPermissionState('denied');
      }
    }
  };

  const stopScanner = () => {
    if (controlsRef.current) {
      try {
        controlsRef.current.stop();
      } catch {}
      controlsRef.current = null;
    }
    if (unregisterStreamRef.current) {
      unregisterStreamRef.current();
      unregisterStreamRef.current = null;
    }
    if (streamRef.current) {
      CameraHelper.stopStream(streamRef.current);
      streamRef.current = null;
    }
    CameraHelper.stopAllStreams();
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setScannerOpen(false);
    setCameraStatus('IDLE');
  };

  const toggleTorch = async () => {
    if (!streamRef.current) return;
    const track = streamRef.current.getVideoTracks()[0];
    if (track && typeof track.applyConstraints === 'function') {
      try {
        const nextState = !torchEnabled;
        await track.applyConstraints({
          advanced: [{ torch: nextState } as any],
        });
        setTorchEnabled(nextState);
      } catch (err) {
        console.warn('Torch constraint error:', err);
      }
    }
  };

  const handleScannedQrResult = (decodedText: string) => {
    if (!decodedText || !decodedText.trim()) return;

    let parsedUrl: URL;
    try {
      parsedUrl = new URL(decodedText.trim());
    } catch {
      stopScanner();
      setError({
        title: 'Invalid QR Code',
        message: 'This is not a valid SmartCart QR code. Please scan the official QR code located on your cart handle.',
        type: 'security',
        canRetry: true,
      });
      return;
    }

    // Link domain validation: accept only domain matching current app origin or BASE_URL
    const currentHost = window.location.hostname.toLowerCase();
    const scannedHost = parsedUrl.hostname.toLowerCase();
    const allowedServerHost = serverBaseUrl ? new URL(serverBaseUrl).hostname.toLowerCase() : null;

    const isDomainAllowed =
      scannedHost === currentHost ||
      (allowedServerHost && scannedHost === allowedServerHost) ||
      (currentHost.endsWith('.vercel.app') && scannedHost.endsWith('.vercel.app')) ||
      (currentHost.endsWith('.onrender.com') && scannedHost.endsWith('.onrender.com'));

    if (!isDomainAllowed) {
      stopScanner();
      setError({
        title: 'Unrecognized Domain',
        message: `This QR code points to ${parsedUrl.hostname}, which does not match this SmartCart store.`,
        type: 'security',
        canRetry: true,
      });
      return;
    }

    const cartParam = parsedUrl.searchParams.get('cart');
    const sigParam = parsedUrl.searchParams.get('sig');
    const tokenParam = parsedUrl.searchParams.get('token');

    if (!cartParam) {
      stopScanner();
      setError({
        title: 'Missing Cart Number',
        message: 'This cart QR code is missing a cart identifier. Please scan the official code on the cart.',
        type: 'security',
        canRetry: true,
      });
      return;
    }

    stopScanner();
    setLoading(true);
    setError(null);

    api.pairCart({
      cart_number: cartParam,
      qr_token: tokenParam || undefined,
      signature: sigParam || undefined,
      customer_phone: phoneInput || undefined,
    })
    .then((session) => {
      setSearchParams({});
      navigate('/user', { replace: true });
      if (typeof window !== 'undefined' && window.history) {
        window.history.replaceState({}, '', '/user');
      }
      onConnected(session);
    })
    .catch((err: any) => {
      setError(categorizeError(err));
    })
    .finally(() => {
      setLoading(false);
    });
  };

  // Demo mode connection handler
  const handleDemoConnect = async (cartNumber: string) => {
    setLoading(true);
    setError(null);
    try {
      const session = await api.pairCart(cartNumber, phoneInput || undefined);
      onConnected(session);
    } catch (err: any) {
      setError(categorizeError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto p-5 min-h-[90vh] flex flex-col justify-between">
      <div>
        {/* Brand Header */}
        <div className="text-center mt-6 mb-6">
          <div className="w-16 h-16 bg-emerald-600 dark:bg-emerald-500 rounded-3xl mx-auto flex items-center justify-center text-white shadow-xl shadow-emerald-500/20 mb-4 transform hover:scale-105 transition-transform">
            <ShoppingCart className="w-8 h-8" />
          </div>
          <h1 className="text-2xl font-bold font-display tracking-tight text-slate-900 dark:text-white">
            {t.appName}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t.tagline}
          </p>
        </div>

        {/* Status / Error Banner */}
        {error && (
          <div className={`mb-6 p-4 rounded-2xl border flex flex-col sm:flex-row items-start gap-3.5 text-sm transition-all animate-fadeIn ${
            error.type === 'waking_up'
              ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/60 text-amber-900 dark:text-amber-200'
              : error.type === 'security'
              ? 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-300'
              : error.type === 'occupied'
              ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/60 text-amber-800 dark:text-amber-300'
              : error.type === 'disabled'
              ? 'bg-purple-50 dark:bg-purple-950/40 border-purple-200 dark:border-purple-900/60 text-purple-800 dark:text-purple-300'
              : error.type === 'camera_denied'
              ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-900/60 text-blue-800 dark:text-blue-300'
              : 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900/60 text-red-800 dark:text-red-300'
          }`}>
            <div className="flex items-start gap-3 w-full">
              <div className="flex-shrink-0 mt-0.5">
                {error.type === 'waking_up' ? (
                  <Loader2 className="w-5 h-5 text-amber-600 dark:text-amber-400 animate-spin" />
                ) : error.type === 'security' ? (
                  <ShieldAlert className="w-5 h-5 text-rose-600 dark:text-rose-400" />
                ) : error.type === 'occupied' ? (
                  <Lock className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                )}
              </div>
              <div className="flex-1">
                {error.title && <div className="font-semibold text-xs uppercase tracking-wider mb-1">{error.title}</div>}
                <div className="leading-relaxed">{error.message}</div>
                {error.type === 'waking_up' && (
                  <div className="mt-2.5 w-full bg-amber-200/60 dark:bg-amber-900/40 rounded-full h-1.5 overflow-hidden">
                    <div className="bg-amber-500 h-1.5 rounded-full animate-pulse w-3/4"></div>
                  </div>
                )}
                {error.canRetry && (
                  <button
                    onClick={startScanner}
                    disabled={loading}
                    className="mt-3 inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors shadow-sm"
                  >
                    <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
                    <span>Scan Again</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Primary Cart Connect Card */}
        <div className="relative border-2 border-emerald-500/40 dark:border-emerald-400/40 rounded-3xl p-6 text-center bg-white dark:bg-[#131B2E] shadow-sm mb-6">
          <div className="w-20 h-20 mx-auto mb-4 bg-emerald-50 dark:bg-emerald-950/60 rounded-3xl flex items-center justify-center text-emerald-600 dark:text-emerald-400 shadow-inner">
            <QrCode className="w-10 h-10" />
          </div>

          <h2 className="font-bold text-slate-900 dark:text-white text-lg">
            {loading ? 'Connecting to Cart...' : 'Connect to Your Cart'}
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5 max-w-xs mx-auto leading-relaxed">
            {loading 
              ? 'Verifying HMAC security signature and reserving cart session...' 
              : 'Scan the official QR code located on your cart handle to unlock and start shopping.'}
          </p>

          {/* Prominent "Scan Cart QR" Button */}
          <button
            onClick={startScanner}
            disabled={loading}
            className="mt-6 w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-4 px-6 rounded-2xl shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2.5 active:scale-95 transition-all disabled:opacity-50 text-sm"
          >
            <Camera className="w-5 h-5" />
            <span>Scan Cart QR</span>
          </button>
        </div>

        {/* Optional Mobile Phone for SMS / Receipt */}
        <div className="mb-4 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl p-4 shadow-sm">
          <label className="block text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
            Mobile Number (Optional for Receipt SMS)
          </label>
          <input
            type="tel"
            value={phoneInput}
            onChange={(e) => setPhoneInput(e.target.value)}
            placeholder="+91 98765 43210"
            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white rounded-xl px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>

        {/* Demo Mode Controls: STRICTLY HIDDEN in production (DEMO_MODE=false) */}
        {isDemoMode && (
          <div className="bg-amber-50/60 dark:bg-amber-950/20 border border-amber-300/80 dark:border-amber-800/60 rounded-2xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-amber-900 dark:text-amber-300 uppercase tracking-wider">
                Manual Cart Picker (Demo Mode Only)
              </span>
              <span className="text-[10px] font-mono bg-amber-200 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200 px-2 py-0.5 rounded-full font-bold">
                DEMO ONLY
              </span>
            </div>
            <div className="flex gap-2">
              <select
                value={cartInput}
                onChange={(e) => setCartInput(e.target.value)}
                className="flex-1 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-amber-500"
              >
                {[1, 2, 3, 4, 5, 6, 7, 8].map((num) => {
                  const c = `CART-${num < 10 ? '00' : '0'}${num}`;
                  return (
                    <option key={c} value={c}>
                      {c} (Floor Level 1)
                    </option>
                  );
                })}
              </select>
              <button
                onClick={() => handleDemoConnect(cartInput)}
                disabled={loading}
                className="bg-amber-600 hover:bg-amber-700 text-white px-4 rounded-xl flex items-center justify-center font-bold text-xs disabled:opacity-50"
              >
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* In-App Camera Scanner Modal */}
      {scannerOpen && (
        <div className="fixed inset-0 z-50 bg-black flex flex-col justify-between animate-fadeIn select-none">
          {/* Header */}
          <div className="p-4 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent z-10 text-white">
            <div className="flex items-center gap-2">
              <Camera className="w-5 h-5 text-emerald-400" />
              <span className="font-bold text-sm">Scan Cart Handle QR</span>
            </div>

            {/* Live Camera Status Badge */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white/10 backdrop-blur-md">
              <span
                className={`w-2 h-2 rounded-full ${
                  cameraStatus === 'ACTIVE'
                    ? 'bg-emerald-400 animate-pulse'
                    : cameraStatus === 'REQUESTING'
                    ? 'bg-amber-400 animate-pulse'
                    : cameraStatus === 'BLOCKED'
                    ? 'bg-red-400'
                    : 'bg-slate-400'
                }`}
              />
              <span>
                {cameraStatus === 'ACTIVE'
                  ? 'Camera Active'
                  : cameraStatus === 'REQUESTING'
                  ? 'Requesting Camera...'
                  : cameraStatus === 'BLOCKED'
                  ? 'Camera Blocked'
                  : cameraStatus === 'IN_USE'
                  ? 'Camera in Use'
                  : cameraStatus === 'NOT_FOUND'
                  ? 'No Camera'
                  : 'Ready'}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {torchSupported && cameraStatus === 'ACTIVE' && (
                <button
                  onClick={toggleTorch}
                  className={`p-2.5 rounded-xl border transition-all ${
                    torchEnabled 
                      ? 'bg-amber-500 text-slate-950 border-amber-400' 
                      : 'bg-white/10 text-white border-white/20 hover:bg-white/20'
                  }`}
                  title="Toggle Flashlight"
                >
                  <Flashlight className="w-4 h-4" />
                </button>
              )}
              <button
                onClick={stopScanner}
                className="p-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 text-white transition-all active:scale-95"
                title="Close Scanner"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Viewport: Explainer vs Real Camera Viewfinder */}
          <div className="relative flex-1 flex items-center justify-center overflow-hidden p-4">
            {cameraStatus === 'REQUESTING' ? (
              <div className="z-20 flex flex-col items-center justify-center text-center text-white p-6 animate-in fade-in">
                <Loader2 className="w-10 h-10 text-emerald-400 animate-spin mb-3" />
                <div className="font-bold text-sm">Connecting to camera...</div>
                <div className="text-xs text-white/70 mt-1 max-w-xs leading-relaxed">
                  Please tap &ldquo;Allow&rdquo; if your browser prompts for camera access.
                </div>
              </div>
            ) : cameraStatus !== 'ACTIVE' ? (
              <div className="z-20 w-full max-w-sm">
                <CameraPermissionExplainer
                  status={cameraStatus}
                  permissionState={permissionState}
                  onRequestPermission={startRealCamera}
                  onRetry={startRealCamera}
                  onClose={stopScanner}
                  title="Camera Needed to Connect"
                  description="SmartCart needs camera access to scan the official QR code located on your cart handle."
                />
              </div>
            ) : (
              <>
                <video
                  ref={videoRef}
                  playsInline
                  autoPlay
                  muted
                  className="absolute inset-0 w-full h-full object-cover"
                />

                {/* Viewfinder Target Reticle */}
                <div className="relative z-10 w-72 h-72 border-2 border-emerald-400 rounded-3xl overflow-hidden shadow-[0_0_0_9999px_rgba(0,0,0,0.6)]">
                  {/* Animated Scan Line */}
                  <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-emerald-400 to-transparent animate-pulse" style={{ animationDuration: '1.8s' }} />

                  {/* Corner Accents */}
                  <div className="absolute top-2 left-2 w-5 h-5 border-t-4 border-l-4 border-emerald-400 rounded-tl-xl" />
                  <div className="absolute top-2 right-2 w-5 h-5 border-t-4 border-r-4 border-emerald-400 rounded-tr-xl" />
                  <div className="absolute bottom-2 left-2 w-5 h-5 border-b-4 border-l-4 border-emerald-400 rounded-bl-xl" />
                  <div className="absolute bottom-2 right-2 w-5 h-5 border-b-4 border-r-4 border-emerald-400 rounded-br-xl" />
                </div>
              </>
            )}
          </div>

          {/* Footer Instruction */}
          {cameraStatus === 'ACTIVE' && (
            <div className="p-6 bg-gradient-to-t from-black/90 to-transparent text-center z-10 space-y-2">
              <p className="text-white text-xs font-semibold">
                Point your camera steadily at the official QR code on your cart
              </p>
              <p className="text-slate-400 text-[11px]">
                Accepts verified store QR codes only
              </p>
            </div>
          )}
        </div>
      )}

      {/* Privacy Notice Banner */}
      <div className="mt-8 mb-4 p-4 bg-slate-100 dark:bg-slate-900/60 rounded-2xl flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-800">
        <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
        <div>
          {t.privacyNote}
        </div>
      </div>
    </div>
  );
};
