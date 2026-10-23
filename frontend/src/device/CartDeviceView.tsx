import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Camera,
  CameraOff,
  Radio,
  Wifi,
  WifiOff,
  Cpu,
  Activity,
  Terminal,
  ShieldCheck,
  ShieldAlert,
  Layers,
  Sparkles,
  RefreshCw,
  Eye,
  EyeOff,
  Trash2
} from 'lucide-react';
import { CartCameraManager } from './cartCamera';
import { getApiBaseUrl } from '../services/api';

interface LogEntry {
  id: string;
  time: string;
  text: string;
  level: 'info' | 'warn' | 'error' | 'success';
}

export const CartDeviceView: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialCart = searchParams.get('cart') || 'CART-001';
  
  const [selectedCart, setSelectedCart] = useState(initialCart);
  const [deviceToken, setDeviceToken] = useState(() => {
    return sessionStorage.getItem(`device_token_${initialCart}`) || 'CART001_SECRET_TOKEN_2026';
  });
  const [showToken, setShowToken] = useState(false);
  const [availableCarts, setAvailableCarts] = useState<Array<{ id: string; cart_number: string }>>([]);

  const [isRunning, setIsRunning] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTING' | 'ONLINE' | 'OFFLINE'>('OFFLINE');
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [isMotion, setIsMotion] = useState(false);
  const [telemetry, setTelemetry] = useState<{ fps: number; sizeKb: number; count: number }>({
    fps: 0,
    sizeKb: 0,
    count: 0
  });

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraManagerRef = useRef<CartCameraManager | null>(null);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

  const addLog = (text: string, level: 'info' | 'warn' | 'error' | 'success' = 'info') => {
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');
    setLogs((prev) => [
      ...prev.slice(-150),
      { id: Math.random().toString(36).substring(2, 9), time: timeStr, text, level }
    ]);
  };

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Load available carts from API
  useEffect(() => {
    fetch(`${getApiBaseUrl()}/shopper/available-carts`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableCarts(data);
        }
      })
      .catch(() => {
        // Fallback default list
        setAvailableCarts([
          { id: '1', cart_number: 'CART-001' },
          { id: '2', cart_number: 'CART-002' },
          { id: '3', cart_number: 'CART-003' }
        ]);
      });
  }, []);

  // Update token when cart changes
  const handleCartChange = (cartNum: string) => {
    setSelectedCart(cartNum);
    const saved = sessionStorage.getItem(`device_token_${cartNum}`);
    if (saved) {
      setDeviceToken(saved);
    } else if (cartNum === 'CART-001') {
      setDeviceToken('CART001_SECRET_TOKEN_2026');
    } else if (cartNum === 'CART-002') {
      setDeviceToken('CART002_SECRET_TOKEN_2026');
    } else if (cartNum === 'CART-003') {
      setDeviceToken('CART003_SECRET_TOKEN_2026');
    } else {
      setDeviceToken('');
    }
  };

  const handleStart = async () => {
    if (!deviceToken.trim()) {
      addLog('Error: Please enter or paste the Cart Device Token.', 'error');
      return;
    }
    if (!videoRef.current) return;

    // Save token in session memory
    sessionStorage.setItem(`device_token_${selectedCart}`, deviceToken.trim());

    addLog(`Initializing camera device for ${selectedCart}...`, 'info');
    setIsRunning(true);

    const manager = new CartCameraManager({
      token: deviceToken.trim(),
      videoElement: videoRef.current,
      onStatusChange: (status, msg) => {
        setConnectionStatus(status);
        if (msg) setStatusMessage(msg);
        if (status === 'OFFLINE' && msg?.toLowerCase().includes('token')) {
          setIsRunning(false);
        }
      },
      onMotionChange: (motion) => {
        setIsMotion(motion);
      },
      onLog: (text, level) => {
        addLog(text, level);
      },
      onFrameSent: ({ fps, sizeKb }) => {
        setTelemetry((prev) => ({
          fps,
          sizeKb,
          count: prev.count + 1
        }));
      },
      onVerificationResult: (res) => {
        addLog(`AI Camera Match: ${res.product_name} (${res.barcode}) CONFIRMED`, 'success');
      }
    });

    cameraManagerRef.current = manager;

    try {
      await manager.start();
    } catch (err) {
      setIsRunning(false);
      cameraManagerRef.current = null;
    }
  };

  const handleStop = () => {
    if (cameraManagerRef.current) {
      cameraManagerRef.current.stop();
      cameraManagerRef.current = null;
    }
    setIsRunning(false);
    setConnectionStatus('OFFLINE');
    setIsMotion(false);
    setTelemetry({ fps: 0, sizeKb: 0, count: 0 });
    addLog('Camera streaming stopped by operator.', 'info');
  };

  useEffect(() => {
    return () => {
      if (cameraManagerRef.current) {
        cameraManagerRef.current.stop();
      }
    };
  }, []);

  return (
    <div className="min-h-screen bg-[#070A12] text-slate-100 flex flex-col font-sans select-none">
      {/* Top Telemetry Header */}
      <header className="border-b border-slate-800/80 bg-[#0B0F19]/90 backdrop-blur-md px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400 shadow-lg shadow-cyan-500/10">
            <Cpu className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-display font-bold text-sm tracking-wide text-white uppercase">
                SmartCart Device Simulator
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/80 border border-cyan-800/60 text-cyan-300">
                ESP32-CAM Mode
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              Webcam overhead camera & motion detector
            </p>
          </div>
        </div>

        {/* Live Status Indicator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border font-mono text-xs font-semibold bg-slate-900/60">
            {connectionStatus === 'ONLINE' ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400">ONLINE</span>
              </>
            ) : connectionStatus === 'CONNECTING' ? (
              <>
                <RefreshCw className="w-4 h-4 text-amber-400 animate-spin" />
                <span className="text-amber-400">CONNECTING...</span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-slate-500" />
                <span className="text-slate-400">OFFLINE</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Hardware Console Grid */}
      <main className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-7xl mx-auto w-full">
        {/* Left Column: Camera Preview & Viewfinder */}
        <div className="lg:col-span-7 flex flex-col gap-4">
          <div className="relative bg-[#0D1322] border border-slate-800 rounded-3xl overflow-hidden shadow-2xl flex flex-col items-center justify-center min-h-[420px] aspect-[4/3]">
            {/* Live Video Element */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`w-full h-full object-cover ${isRunning ? 'block' : 'hidden'}`}
            />

            {/* Offline / Idle Placeholder */}
            {!isRunning && (
              <div className="p-8 text-center flex flex-col items-center">
                <div className="w-20 h-20 rounded-3xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-center text-slate-500 mb-4 shadow-inner">
                  <CameraOff className="w-10 h-10" />
                </div>
                <h3 className="text-base font-semibold text-slate-300 font-display">
                  Camera Feed Inactive
                </h3>
                <p className="text-xs text-slate-500 max-w-sm mt-1">
                  Click 'Start Camera' below to initialize laptop webcam overhead stream and calibrate motion detection.
                </p>
              </div>
            )}

            {/* Viewfinder Overlays (HUD) */}
            {isRunning && (
              <>
                {/* Viewfinder Corner Reticles */}
                <div className="absolute top-4 left-4 w-6 h-6 border-t-2 border-l-2 border-cyan-400/80 pointer-events-none"></div>
                <div className="absolute top-4 right-4 w-6 h-6 border-t-2 border-r-2 border-cyan-400/80 pointer-events-none"></div>
                <div className="absolute bottom-4 left-4 w-6 h-6 border-b-2 border-l-2 border-cyan-400/80 pointer-events-none"></div>
                <div className="absolute bottom-4 right-4 w-6 h-6 border-b-2 border-r-2 border-cyan-400/80 pointer-events-none"></div>

                {/* Overhead Crosshair Center */}
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-30">
                  <div className="w-12 h-12 border border-dashed border-white/60 rounded-full"></div>
                </div>

                {/* Top Overlay Badges */}
                <div className="absolute top-4 inset-x-4 flex items-center justify-between pointer-events-none">
                  <div className="px-2.5 py-1 rounded-lg bg-black/60 backdrop-blur-md border border-white/10 text-[11px] font-mono text-cyan-300 flex items-center gap-1.5 shadow-lg">
                    <Radio className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
                    <span>640×480 • 75% Q</span>
                  </div>

                  {/* Motion Sensor Dynamic Pill */}
                  <div className={`px-3 py-1 rounded-lg backdrop-blur-md border text-[11px] font-mono font-bold flex items-center gap-2 transition-all ${
                    isMotion
                      ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300 shadow-lg shadow-emerald-500/20 animate-pulse'
                      : 'bg-black/60 border-white/10 text-slate-400'
                  }`}>
                    <Activity className={`w-3.5 h-3.5 ${isMotion ? 'text-emerald-400' : 'text-slate-500'}`} />
                    <span>{isMotion ? 'MOTION DETECTED (STREAMING)' : 'IDLE (STANDBY)'}</span>
                  </div>
                </div>

                {/* Bottom Telemetry HUD */}
                <div className="absolute bottom-4 inset-x-4 flex items-center justify-between pointer-events-none">
                  <div className="px-2.5 py-1 rounded-lg bg-black/60 backdrop-blur-md border border-white/10 text-[11px] font-mono text-slate-300">
                    Target: <span className="text-white font-bold">{selectedCart}</span>
                  </div>

                  <div className="px-2.5 py-1 rounded-lg bg-black/60 backdrop-blur-md border border-white/10 text-[11px] font-mono text-slate-300 flex items-center gap-3">
                    <span>Rate: <strong className="text-cyan-300">{telemetry.fps} FPS</strong></span>
                    <span>Frame: <strong className="text-cyan-300">{telemetry.sizeKb} KB</strong></span>
                    <span>Sent: <strong className="text-cyan-300">{telemetry.count}</strong></span>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Action Control Bar */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-2xl p-4 flex items-center justify-between gap-4">
            <div className="text-xs text-slate-400">
              {isRunning ? (
                <span className="flex items-center gap-2 text-emerald-400 font-mono">
                  <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                  Stream active • Frames sent only on motion
                </span>
              ) : (
                <span>Webcam idle. Start camera to connect.</span>
              )}
            </div>

            <button
              onClick={isRunning ? handleStop : handleStart}
              className={`px-6 py-2.5 rounded-xl font-medium text-sm transition-all flex items-center gap-2 font-display ${
                isRunning
                  ? 'bg-rose-600 hover:bg-rose-700 text-white shadow-lg shadow-rose-600/30 active:scale-95'
                  : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg shadow-emerald-600/30 active:scale-95'
              }`}
            >
              {isRunning ? (
                <>
                  <CameraOff className="w-4 h-4" />
                  Stop Camera
                </>
              ) : (
                <>
                  <Camera className="w-4 h-4" />
                  Start Camera
                </>
              )}
            </button>
          </div>
        </div>

        {/* Right Column: Configuration & Real-Time Event Log */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          {/* Cart & Device Token Credentials Card */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl">
            <div className="flex items-center gap-2.5 mb-4">
              <ShieldCheck className="w-5 h-5 text-cyan-400" />
              <h3 className="font-semibold text-sm text-slate-200 uppercase tracking-wider font-display">
                Device Authentication
              </h3>
            </div>

            <div className="space-y-4">
              {/* Cart Selection */}
              <div>
                <label className="block text-xs font-mono text-slate-400 uppercase tracking-wider mb-1.5">
                  Assigned Cart Number
                </label>
                <select
                  value={selectedCart}
                  onChange={(e) => handleCartChange(e.target.value)}
                  disabled={isRunning}
                  className="w-full bg-[#080C16] border border-slate-700 text-slate-200 rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50 cursor-pointer"
                >
                  {availableCarts.map((c) => (
                    <option key={c.id} value={c.cart_number}>
                      {c.cart_number}
                    </option>
                  ))}
                </select>
              </div>

              {/* Device Token */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-mono text-slate-400 uppercase tracking-wider">
                    Secret Device Token
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                  >
                    {showToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    <span>{showToken ? 'Hide' : 'Reveal'}</span>
                  </button>
                </div>
                <input
                  type={showToken ? 'text' : 'password'}
                  value={deviceToken}
                  onChange={(e) => setDeviceToken(e.target.value)}
                  disabled={isRunning}
                  placeholder="Paste cart device token..."
                  className="w-full bg-[#080C16] border border-slate-700 text-slate-200 rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50"
                />
                <p className="text-[11px] text-slate-500 mt-1 font-mono">
                  Stored strictly in memory. Server authenticates via SHA-256 hash.
                </p>
              </div>
            </div>
          </div>

          {/* Real-Time Terminal Event Log */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl flex-1 flex flex-col min-h-[300px]">
            <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-cyan-400" />
                <span className="font-semibold text-xs text-slate-300 font-mono uppercase tracking-wider">
                  Hardware Event Log
                </span>
              </div>
              <button
                onClick={() => setLogs([])}
                className="text-slate-500 hover:text-slate-300 transition-colors p-1"
                title="Clear Log"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Scrollable Log Container */}
            <div
              ref={logContainerRef}
              className="flex-1 bg-[#050811] rounded-2xl p-3 font-mono text-xs overflow-y-auto space-y-1.5 border border-slate-900 max-h-[340px]"
            >
              {logs.length === 0 ? (
                <div className="text-slate-600 text-center py-8">
                  Ready. Start camera to stream telemetry.
                </div>
              ) : (
                logs.map((log) => (
                  <div key={log.id} className="flex items-start gap-2 leading-relaxed">
                    <span className="text-slate-500 flex-shrink-0 text-[10px]">
                      [{log.time}]
                    </span>
                    <span
                      className={
                        log.level === 'success'
                          ? 'text-emerald-400'
                          : log.level === 'warn'
                          ? 'text-amber-400'
                          : log.level === 'error'
                          ? 'text-rose-400 font-semibold'
                          : 'text-slate-300'
                      }
                    >
                      {log.text}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default CartDeviceView;
