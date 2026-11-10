import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Camera,
  CameraOff,
  Cpu,
  Wifi,
  WifiOff,
  RefreshCw,
  Eye,
  EyeOff,
  Layers,
  ShieldCheck,
  ShieldAlert,
  Trash2,
  AlertTriangle,
  Activity,
  UserCheck,
  Hand
} from 'lucide-react';
import { CartCameraManager } from './cartCamera';
import { getApiBaseUrl } from '../services/api';
import { privacyDetector, DetectorState } from '../services/privacyDetector';
import { Link } from 'react-router-dom';

interface LogEntry {
  id: string;
  time: string;
  text: string;
  level: 'info' | 'warn' | 'error' | 'success';
}

export const CartDeviceView: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialCart = searchParams.get('cart') || 'CART-003';
  
  const [selectedCart, setSelectedCart] = useState(initialCart);
  
  // STRICT SECURITY RULE: Device token is typed/pasted once and kept in React MEMORY ONLY.
  // Never stored in localStorage, sessionStorage, URL or logs.
  const [deviceToken, setDeviceToken] = useState<string>('');
  const [showToken, setShowToken] = useState<boolean>(false);
  const [availableCarts, setAvailableCarts] = useState<Array<{ id: string; cart_number: string }>>([]);

  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTING' | 'ONLINE' | 'OFFLINE' | 'RECONNECTING'>('OFFLINE');
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [isMotion, setIsMotion] = useState<boolean>(false);
  const [motionLevel, setMotionLevel] = useState<number>(0);
  
  // Vision flags
  const [handPresent, setHandPresent] = useState<boolean>(false);
  const [facePresent, setFacePresent] = useState<boolean>(false);
  const [handCount, setHandCount] = useState<number>(0);
  const [faceWithheldCount, setFaceWithheldCount] = useState<number>(0);
  const [detectorState, setDetectorState] = useState<DetectorState>(privacyDetector.getState());
  const [detectorMs, setDetectorMs] = useState<number>(0);

  // Subscribe to privacy detector lifecycle state
  useEffect(() => {
    return privacyDetector.subscribeState((s) => {
      setDetectorState(s);
    });
  }, []);

  const [telemetry, setTelemetry] = useState<{ fps: number; sizeKb: number; count: number; lastHeartbeat: string }>({
    fps: 0,
    sizeKb: 0,
    count: 0,
    lastHeartbeat: 'Never'
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

  // Auto-scroll event log
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Load available carts list
  useEffect(() => {
    fetch(`${getApiBaseUrl()}/shopper/available-carts`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableCarts(data);
        }
      })
      .catch(() => {
        setAvailableCarts([
          { id: '1', cart_number: 'CART-001' },
          { id: '2', cart_number: 'CART-002' },
          { id: '3', cart_number: 'CART-003' }
        ]);
      });
  }, []);

  const handleStart = async () => {
    if (!deviceToken.trim()) {
      addLog('Error: Please enter or paste the Cart Device Token.', 'error');
      return;
    }
    if (!videoRef.current) return;

    addLog(`Initializing camera device for ${selectedCart}...`, 'info');
    setIsRunning(true);
    setConnectionStatus('CONNECTING');

    const manager = new CartCameraManager({
      token: deviceToken.trim(),
      videoElement: videoRef.current,
      onStatusChange: (status, msg) => {
        setConnectionStatus(status);
        if (msg) setStatusMessage(msg);
        if (status === 'OFFLINE' && (msg?.toLowerCase().includes('token') || msg?.toLowerCase().includes('disabled'))) {
          setIsRunning(false);
        }
      },
      onMotionChange: (motion, level) => {
        setIsMotion(motion);
        setMotionLevel(level || 0);
      },
      onVisionFlagsChange: (flags) => {
        setHandPresent(flags.handPresent);
        setFacePresent(flags.facePresent);
        setHandCount(flags.handCount);
        setDetectorMs(flags.processingMs);
      },
      onDetectorStateChange: (state) => {
        setDetectorState(state);
      },
      onLog: (text, level) => {
        addLog(text, level);
      },
      onFrameSent: ({ fps, sizeKb, faceWithheld }) => {
        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];
        setTelemetry((prev) => ({
          fps,
          sizeKb,
          count: prev.count + 1,
          lastHeartbeat: timeStr
        }));
        if (faceWithheld) {
          setFaceWithheldCount((c) => c + 1);
        }
      },
      onVerificationResult: (res) => {
        addLog(`AI Verification Event: ${res.product_name || 'Item'} (${res.action || 'MATCH'})`, 'success');
      }
    });

    cameraManagerRef.current = manager;

    try {
      await manager.start();
    } catch {
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
    setMotionLevel(0);
    setHandPresent(false);
    setFacePresent(false);
    setTelemetry((prev) => ({ ...prev, fps: 0, sizeKb: 0 }));
    addLog('Camera streaming stopped by operator.', 'info');
  };

  const handleCaptureReference = () => {
    if (!cameraManagerRef.current) {
      addLog('Cannot capture reference: Camera is not running.', 'warn');
      return;
    }
    const ok = cameraManagerRef.current.captureReferenceFrame();
    if (ok) {
      addLog('Empty cart reference captured and sent to server.', 'success');
    }
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
                Cart Camera Device Console
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/80 border border-cyan-800/60 text-cyan-300">
                Overhead Vision Streamer
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              Webcam overhead camera & motion detector for {selectedCart}
            </p>
          </div>
        </div>

        {/* Live Status Indicator */}
        <div className="flex items-center gap-3">
          {/* Privacy Detector Status Badge */}
          {detectorState.status === 'loading' ? (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 font-mono text-xs font-semibold animate-pulse">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-amber-400" />
              <span>Loading detector...</span>
            </div>
          ) : detectorState.status === 'ready' ? (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 font-mono text-xs font-semibold">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Detector: {detectorState.delegate} ({detectorMs}ms)</span>
            </div>
          ) : detectorState.status === 'error' ? (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-red-500/30 bg-red-500/10 text-red-300 font-mono text-xs font-semibold">
              <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
              <span>Detector Error</span>
            </div>
          ) : null}

          <Link
            to="/detector-test"
            className="hidden sm:flex items-center gap-1 px-3 py-1.5 rounded-xl border border-slate-700 hover:border-slate-600 bg-slate-900/60 hover:bg-slate-800 text-xs font-mono text-slate-300 transition-all"
            title="Open Detector Visual Diagnostic"
          >
            <span>/detector-test</span>
          </Link>

          <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border font-mono text-xs font-semibold bg-slate-900/60">
            {connectionStatus === 'ONLINE' ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400 font-bold">ONLINE</span>
              </>
            ) : connectionStatus === 'CONNECTING' ? (
              <>
                <RefreshCw className="w-4 h-4 text-amber-400 animate-spin" />
                <span className="text-amber-400">CONNECTING...</span>
              </>
            ) : connectionStatus === 'RECONNECTING' ? (
              <>
                <RefreshCw className="w-4 h-4 text-amber-400 animate-spin" />
                <span className="text-amber-400">RECONNECTING...</span>
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
            {/* Live Video Element - ALWAYS MOUNTED */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`w-full h-full object-cover transition-opacity duration-200 ${isRunning ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
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
                  Enter device token and tap &ldquo;Start Camera Stream&rdquo; to connect this laptop webcam as {selectedCart}&rsquo;s overhead camera.
                </p>
              </div>
            )}

            {/* Live Overlays when active */}
            {isRunning && (
              <>
                {/* Vision Feature Badges */}
                <div className="absolute top-4 left-4 flex flex-col gap-2 z-10">
                  <div className={`px-2.5 py-1 rounded-xl text-[11px] font-mono font-bold flex items-center gap-1.5 backdrop-blur-md border ${
                    isMotion 
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-lg shadow-emerald-500/20' 
                      : 'bg-black/60 text-slate-400 border-white/10'
                  }`}>
                    <Activity className={`w-3.5 h-3.5 ${isMotion ? 'animate-pulse text-emerald-400' : ''}`} />
                    <span>MOTION: {isMotion ? `ACTIVE (${(motionLevel * 100).toFixed(0)}%)` : 'IDLE (10s Keep-Alive)'}</span>
                  </div>

                  <div className={`px-2.5 py-1 rounded-xl text-[11px] font-mono font-bold flex items-center gap-1.5 backdrop-blur-md border ${
                    handPresent 
                      ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' 
                      : 'bg-black/60 text-slate-500 border-white/10'
                  }`}>
                    <Hand className="w-3.5 h-3.5" />
                    <span>HAND: {handPresent ? `PRESENT (${handCount})` : 'CLEAR'}</span>
                  </div>

                  {/* Safe Failure Banner if detector not ready */}
                  {isRunning && detectorState.status !== 'ready' && (
                    <div className="px-2.5 py-1 rounded-xl text-[11px] font-mono font-bold flex items-center gap-1.5 backdrop-blur-md bg-red-500/25 text-red-300 border border-red-500/40 animate-pulse">
                      <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                      <span>Privacy detector not ready, frames are not being sent</span>
                    </div>
                  )}

                  {facePresent && (
                    <div className="px-2.5 py-1 rounded-xl text-[11px] font-mono font-bold flex items-center gap-1.5 backdrop-blur-md bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse">
                      <UserCheck className="w-3.5 h-3.5 text-amber-400" />
                      <span>FACE DETECTED: IMAGE WITHHELD</span>
                    </div>
                  )}
                </div>

                {/* Bottom Telemetry HUD */}
                <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between text-[11px] font-mono text-white/90 bg-black/70 backdrop-blur-md px-3.5 py-2 rounded-2xl border border-white/10 z-10">
                  <div>
                    <span className="text-slate-400">FPS:</span> <span className="font-bold text-cyan-400">{telemetry.fps}</span>
                    <span className="mx-2 text-slate-600">|</span>
                    <span className="text-slate-400">Size:</span> <span className="font-bold">{telemetry.sizeKb} KB</span>
                    <span className="mx-2 text-slate-600">|</span>
                    <span className="text-slate-400">Frames:</span> <span className="font-bold text-emerald-400">{telemetry.count}</span>
                    <span className="mx-2 text-slate-600">|</span>
                    <span className="text-slate-400">Infer:</span> <span className="font-bold text-amber-400">{detectorMs}ms</span>
                  </div>
                  <div>
                    <span className="text-slate-400">Heartbeat:</span> <span className="text-slate-200">{telemetry.lastHeartbeat}</span>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Privacy Note Banner */}
          <div className="p-4 bg-emerald-950/20 border border-emerald-500/30 rounded-2xl text-xs text-emerald-200 flex items-start gap-3">
            <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="font-bold text-emerald-300">Privacy Protection Active</div>
              <p className="text-[11px] text-emerald-400/90 leading-relaxed font-medium">
                Face detection reduces but does not guarantee that faces are not captured. Point the camera at the cart interior only.
              </p>
              <p className="text-[10px] text-slate-400 leading-relaxed">
                Powered by in-browser self-hosted MediaPipe Face & Hand Landmarker models ({detectorState.delegate || 'CPU'} delegate).
                {faceWithheldCount > 0 && <span className="font-bold ml-1 text-amber-300">({faceWithheldCount} frames withheld so far)</span>}
              </p>
            </div>
          </div>
        </div>

        {/* Right Column: Controls, Credentials & Log */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          
          {/* Hardware Configuration Card */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-cyan-400" />
              Cart Device Settings
            </h2>

            {/* Cart Selector */}
            <div>
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                Cart Assignment
              </label>
              <select
                value={selectedCart}
                onChange={(e) => setSelectedCart(e.target.value)}
                disabled={isRunning}
                className="w-full bg-[#131B2E] border border-slate-700 text-white rounded-xl px-3.5 py-2.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50"
              >
                {availableCarts.map((c) => (
                  <option key={c.cart_number} value={c.cart_number}>
                    {c.cart_number}
                  </option>
                ))}
              </select>
            </div>

            {/* Device Token Input (Memory only, never stored in localStorage) */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Device Authentication Token
                </label>
                <span className="text-[10px] text-amber-400 font-mono">Kept in memory only</span>
              </div>

              <div className="relative">
                <input
                  type={showToken ? 'text' : 'password'}
                  value={deviceToken}
                  onChange={(e) => setDeviceToken(e.target.value)}
                  placeholder="Paste cart device token from Admin > Carts..."
                  disabled={isRunning}
                  className="w-full bg-[#131B2E] border border-slate-700 text-white rounded-xl px-3.5 py-2.5 pr-10 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => setShowToken(!showToken)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                  title={showToken ? 'Hide token' : 'Show token'}
                >
                  {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[10px] text-slate-500 mt-1">
                Obtain this token from <strong>Admin &gt; Carts &gt; Device Token</strong>. It is sent in the first WebSocket message and never stored.
              </p>
            </div>

            {/* Main Action Buttons */}
            <div className="flex gap-2 pt-2">
              {!isRunning ? (
                <button
                  onClick={handleStart}
                  className="flex-1 py-3 px-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-cyan-600/30 active:scale-95 transition-all"
                >
                  <Camera className="w-4 h-4" />
                  Start Camera Stream
                </button>
              ) : (
                <button
                  onClick={handleStop}
                  className="flex-1 py-3 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-rose-600/30 active:scale-95 transition-all"
                >
                  <CameraOff className="w-4 h-4" />
                  Stop Camera Stream
                </button>
              )}

              {isRunning && (
                <button
                  onClick={handleCaptureReference}
                  className="py-3 px-4 rounded-xl bg-emerald-700 hover:bg-emerald-600 text-white font-bold text-xs flex items-center justify-center gap-1.5 transition-all active:scale-95"
                  title="Capture empty cart reference frame"
                >
                  <Layers className="w-4 h-4" />
                  <span>Capture Ref</span>
                </button>
              )}
            </div>
          </div>

          {/* Event Log Console Card */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl flex-1 flex flex-col">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Hardware Event Log
              </span>
              <button
                onClick={() => setLogs([])}
                className="text-slate-500 hover:text-slate-300 text-xs flex items-center gap-1"
                title="Clear log"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Clear</span>
              </button>
            </div>

            <div
              ref={logContainerRef}
              className="flex-1 min-h-[220px] max-h-[320px] overflow-y-auto space-y-1.5 pt-3 font-mono text-[11px]"
            >
              {logs.length === 0 ? (
                <div className="text-slate-600 italic text-center py-6">
                  No events yet. Start the stream to begin session logging.
                </div>
              ) : (
                logs.map((log) => (
                  <div key={log.id} className="flex items-start gap-2">
                    <span className="text-slate-500 shrink-0">{log.time}</span>
                    <span
                      className={`break-all ${
                        log.level === 'error'
                          ? 'text-rose-400 font-bold'
                          : log.level === 'warn'
                          ? 'text-amber-400'
                          : log.level === 'success'
                          ? 'text-emerald-400'
                          : 'text-slate-300'
                      }`}
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
