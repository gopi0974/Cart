import React, { useState, useEffect, useRef } from 'react';
import {
  Camera,
  CameraOff,
  Cpu,
  ShieldCheck,
  ShieldAlert,
  Activity,
  Hand,
  UserCheck,
  RefreshCw,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Sliders,
  Layers,
  Info
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { CameraHelper } from '../services/cameraHelper';
import {
  privacyDetector,
  DetectorState,
  PrivacyDetectionResult,
  DetectedFaceBox
} from '../services/privacyDetector';
import { DETECTOR_PROFILES, DetectorProfile, getDetectorProfile } from '../config/detectorProfiles';

export const DetectorTestView: React.FC = () => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [detectorState, setDetectorState] = useState<DetectorState>(privacyDetector.getState());
  const [detectionResult, setDetectionResult] = useState<PrivacyDetectionResult | null>(null);
  const [activeProfile, setActiveProfile] = useState<'privacy' | 'enrollment'>('enrollment');
  const [facingMode, setFacingMode] = useState<'user' | 'environment'>('user');
  const [fps, setFps] = useState(0);
  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const frameCountRef = useRef(0);
  const lastFpsCalcRef = useRef(Date.now());
  const activeProfileRef = useRef<'privacy' | 'enrollment'>('enrollment');
  activeProfileRef.current = activeProfile;

  // Subscribe to detector state
  useEffect(() => {
    return privacyDetector.subscribeState((s) => {
      setDetectorState(s);
    });
  }, []);

  // Initialize MediaPipe models on page mount
  useEffect(() => {
    privacyDetector.load().catch((err) => {
      console.warn('Initial detector load warning:', err);
    });
  }, []);

  const startCamera = async () => {
    setCameraError(null);
    try {
      if (streamRef.current) {
        CameraHelper.stopStream(streamRef.current);
      }

      const stream = await CameraHelper.openCamera({
        idealWidth: 640,
        idealHeight: 480,
        facingMode
      });
      streamRef.current = stream;

      if (videoRef.current) {
        await CameraHelper.attachStreamToVideo(videoRef.current, stream, {
          checkTimeoutMs: 3000
        });
      }

      setIsRunning(true);
      frameCountRef.current = 0;
      lastFpsCalcRef.current = Date.now();
    } catch (err: any) {
      const parsed = CameraHelper.parseCameraError(err);
      setCameraError(parsed.message);
      setIsRunning(false);
    }
  };

  const stopCamera = () => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (streamRef.current) {
      CameraHelper.stopStream(streamRef.current);
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    }
    setIsRunning(false);
    setDetectionResult(null);
  };

  // Inference & visual bounding box rendering loop
  useEffect(() => {
    if (!isRunning) return;

    let active = true;

    const renderLoop = () => {
      if (!active) return;

      const video = videoRef.current;
      const canvas = canvasRef.current;

      if (video && canvas && video.readyState >= 2) {
        const vw = video.videoWidth || 640;
        const vh = video.videoHeight || 480;

        if (canvas.width !== vw || canvas.height !== vh) {
          canvas.width = vw;
          canvas.height = vh;
        }

        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, vw, vh);

          // Run real MediaPipe detection with active profile
          const currentProf = activeProfileRef.current;
          const result = privacyDetector.detect(video, currentProf);
          setDetectionResult(result);

          if (result.detector_ready) {
            setLatencyHistory((prev) => [...prev.slice(-29), result.processing_ms]);

            const profileCfg = getDetectorProfile(currentProf);

            // 1. Draw Face Bounding Boxes with telemetry
            result.face_boxes.forEach((box, idx) => {
              const bx = box.x * vw;
              const by = box.y * vh;
              const bw = box.width * vw;
              const bh = box.height * vh;

              const isQualifying = result.active_face_boxes.some(
                (ab) => Math.abs(ab.x - box.x) < 0.02 && Math.abs(ab.y - box.y) < 0.02
              );

              // Color coding: Red = Active Qualifying Intrusion, Amber = Below Threshold/Pending, Slate = Static Ignored
              let strokeColor = '#F59E0B'; // Amber default
              let fillColor = 'rgba(245, 158, 11, 0.15)';
              let statusLabel = `PENDING (${box.consecutiveFrames}/${profileCfg.minConsecutiveFrames})`;

              if (box.isStaticBackground) {
                strokeColor = '#64748B'; // Slate
                fillColor = 'rgba(100, 116, 139, 0.15)';
                statusLabel = 'STATIC POSTER (IGNORED)';
              } else if (isQualifying) {
                strokeColor = '#EF4444'; // Red
                fillColor = 'rgba(239, 68, 68, 0.25)';
                statusLabel = `FLAG ACTIVE (${box.consecutiveFrames}f)`;
              } else if (box.score < profileCfg.minFaceConfidence) {
                strokeColor = '#EAB308';
                statusLabel = `LOW CONF (${Math.round(box.score * 100)}% < ${Math.round(profileCfg.minFaceConfidence * 100)}%)`;
              } else if (box.width < profileCfg.minFaceBoxWidthFraction) {
                strokeColor = '#EAB308';
                statusLabel = `TOO SMALL (${(box.widthFraction * 100).toFixed(1)}% < ${(profileCfg.minFaceBoxWidthFraction * 100).toFixed(0)}%)`;
              }

              ctx.strokeStyle = strokeColor;
              ctx.lineWidth = isQualifying ? 3.5 : 2;
              ctx.strokeRect(bx, by, bw, bh);
              ctx.fillStyle = fillColor;
              ctx.fillRect(bx, by, bw, bh);

              // Telemetry tag above box
              const tagText = `FACE #${idx + 1}: ${Math.round(box.score * 100)}% | ${(box.widthFraction * 100).toFixed(1)}%w x ${(box.heightFraction * 100).toFixed(1)}%h (${(box.areaFraction * 100).toFixed(1)}% area) | ${statusLabel}`;
              ctx.font = 'bold 11px monospace';
              const textMetrics = ctx.measureText(tagText);
              const tagWidth = textMetrics.width + 12;
              const tagHeight = 22;
              const tagY = Math.max(0, by - tagHeight);

              ctx.fillStyle = strokeColor;
              ctx.fillRect(bx, tagY, tagWidth, tagHeight);
              ctx.fillStyle = '#FFFFFF';
              ctx.fillText(tagText, bx + 6, tagY + 15);

              // Sub-tag with exact coordinates below box
              ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
              const posText = `pos: (${(box.x * 100).toFixed(1)}%, ${(box.y * 100).toFixed(1)}%) | pers: ${box.consecutiveFrames} frames`;
              const posMetrics = ctx.measureText(posText);
              ctx.fillRect(bx, by + bh, posMetrics.width + 10, 18);
              ctx.fillStyle = '#CBD5E1';
              ctx.fillText(posText, bx + 5, by + bh + 13);
            });

            // 2. Draw Hand Bounding Boxes
            result.hand_boxes.forEach((box, idx) => {
              const bx = box.x * vw;
              const by = box.y * vh;
              const bw = box.width * vw;
              const bh = box.height * vh;

              ctx.strokeStyle = '#06B6D4';
              ctx.lineWidth = 2.5;
              ctx.strokeRect(bx, by, bw, bh);

              ctx.fillStyle = 'rgba(6, 182, 212, 0.15)';
              ctx.fillRect(bx, by, bw, bh);

              ctx.fillStyle = '#06B6D4';
              ctx.fillRect(bx, Math.max(0, by - 20), 80, 20);
              ctx.fillStyle = '#070A12';
              ctx.font = 'bold 11px monospace';
              ctx.fillText(`HAND #${idx + 1}`, bx + 6, Math.max(14, by - 6));
            });
          }

          // Compute FPS
          frameCountRef.current++;
          const now = Date.now();
          if (now - lastFpsCalcRef.current >= 1000) {
            setFps(frameCountRef.current);
            frameCountRef.current = 0;
            lastFpsCalcRef.current = now;
          }
        }
      }

      animFrameRef.current = requestAnimationFrame(renderLoop);
    };

    animFrameRef.current = requestAnimationFrame(renderLoop);

    return () => {
      active = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isRunning]);

  const avgLatency = latencyHistory.length > 0
    ? Math.round(latencyHistory.reduce((a, b) => a + b, 0) / latencyHistory.length)
    : 0;

  const currentProfileConfig = getDetectorProfile(activeProfile);

  return (
    <div className="min-h-screen bg-[#070A12] text-slate-100 flex flex-col font-sans select-none">
      
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/cart-device"
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-all flex items-center gap-1.5 text-xs font-mono"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>/cart-device</span>
          </Link>

          <div>
            <div className="flex items-center gap-2">
              <span className="font-display font-bold text-sm tracking-wide text-white uppercase">
                MediaPipe Vision Diagnostic & Telemetry
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/80 border border-cyan-800/60 text-cyan-300">
                Self-Hosted Model Benchmark
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              Live face confidence score, box size fraction, consecutive frame persistence, and location tracking
            </p>
          </div>
        </div>

        {/* Profile Switcher & Detector Status Badge */}
        <div className="flex items-center gap-3">
          {/* Profile Switcher Toggle */}
          <div className="flex items-center bg-slate-900 border border-slate-700 rounded-xl p-1 gap-1">
            <button
              onClick={() => setActiveProfile('privacy')}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                activeProfile === 'privacy'
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Privacy (Cart)
            </button>
            <button
              onClick={() => setActiveProfile('enrollment')}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                activeProfile === 'enrollment'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Enrollment (360)
            </button>
          </div>

          {detectorState.status === 'loading' ? (
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 font-mono text-xs font-semibold animate-pulse">
              <RefreshCw className="w-4 h-4 animate-spin text-amber-400" />
              <span>Loading detector...</span>
            </div>
          ) : detectorState.status === 'ready' ? (
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 font-mono text-xs font-semibold">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>Ready ({detectorState.delegate || 'CPU'})</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-red-500/30 bg-red-500/10 text-red-300 font-mono text-xs font-semibold">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              <span>Failed</span>
            </div>
          )}
        </div>
      </header>

      {/* Main Content Grid */}
      <main className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-7xl mx-auto w-full">
        
        {/* Left: Live Viewfinder with Overlay Canvas */}
        <div className="lg:col-span-8 flex flex-col gap-4">
          <div className="relative bg-[#0D1322] border border-slate-800 rounded-3xl overflow-hidden shadow-2xl flex items-center justify-center min-h-[460px] aspect-[4/3]">
            
            {/* Live Video Element */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`w-full h-full object-cover transition-opacity duration-200 ${isRunning ? 'opacity-100' : 'opacity-0'}`}
            />

            {/* Visual Bounding Box Overlay Canvas */}
            <canvas
              ref={canvasRef}
              className={`absolute inset-0 w-full h-full object-cover pointer-events-none z-10 ${isRunning ? 'opacity-100' : 'opacity-0'}`}
            />

            {/* Inactive State */}
            {!isRunning && (
              <div className="p-8 text-center flex flex-col items-center">
                <div className="w-20 h-20 rounded-3xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-center text-slate-500 mb-4 shadow-inner">
                  <CameraOff className="w-10 h-10" />
                </div>
                <h3 className="text-base font-semibold text-slate-300 font-display">
                  Diagnostic Feed Inactive
                </h3>
                <p className="text-xs text-slate-500 max-w-sm mt-1">
                  Start the camera to benchmark self-hosted MediaPipe Face & Hand Landmarker performance and inspect live detection telemetry.
                </p>
                {cameraError && (
                  <div className="mt-3 p-3 bg-red-950/40 border border-red-500/40 rounded-xl text-xs text-red-300">
                    {cameraError}
                  </div>
                )}
              </div>
            )}

            {/* Overlaid Live Badges */}
            {isRunning && (
              <div className="absolute top-4 left-4 flex flex-col gap-2 z-20">
                <div className={`px-3 py-1 rounded-xl text-xs font-mono font-bold flex items-center gap-1.5 backdrop-blur-md border ${
                  detectionResult?.face_present
                    ? 'bg-red-500/30 text-red-300 border-red-500/60 shadow-lg shadow-red-500/20 animate-pulse'
                    : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                }`}>
                  <UserCheck className="w-3.5 h-3.5" />
                  <span>FACE FLAG: {detectionResult?.face_present ? 'RAISED (WITHHELD)' : 'CLEAR'}</span>
                </div>

                <div className={`px-3 py-1 rounded-xl text-xs font-mono font-bold flex items-center gap-1.5 backdrop-blur-md border ${
                  detectionResult?.hand_present
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                    : 'bg-black/60 text-slate-500 border-white/10'
                }`}>
                  <Hand className="w-3.5 h-3.5" />
                  <span>HANDS: {detectionResult?.hand_present ? `ACTIVE (${detectionResult.hand_count})` : 'CLEAR'}</span>
                </div>

                <div className="px-2.5 py-0.5 rounded-lg text-[10px] font-mono bg-slate-900/80 border border-slate-700 text-slate-300 w-fit">
                  Profile: <strong className="text-cyan-300 uppercase">{activeProfile}</strong> (conf ≥ {currentProfileConfig.minFaceConfidence}, min-size {Math.round(currentProfileConfig.minFaceBoxWidthFraction * 100)}%w, {currentProfileConfig.minConsecutiveFrames} frames)
                </div>
              </div>
            )}

            {/* Bottom HUD Bar */}
            {isRunning && (
              <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between text-xs font-mono text-white/90 bg-black/75 backdrop-blur-md px-4 py-2.5 rounded-2xl border border-white/10 z-20">
                <div className="flex items-center gap-3">
                  <span>Inference: <strong className="text-amber-400">{detectionResult?.processing_ms || 0}ms</strong> (Avg {avgLatency}ms)</span>
                  <span className="text-slate-600">|</span>
                  <span>Loop: <strong className="text-cyan-400">{fps} FPS</strong></span>
                  <span className="text-slate-600">|</span>
                  <span>Delegate: <strong className="text-emerald-400">{detectorState.delegate}</strong></span>
                </div>
              </div>
            )}
          </div>

          {/* Telemetry Breakdown Card for Live Detections */}
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-2xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-bold text-slate-300 uppercase flex items-center gap-1.5">
                <Info className="w-4 h-4 text-cyan-400" />
                Live Detected Faces Telemetry ({detectionResult?.face_boxes.length || 0})
              </span>
              <span className="text-[11px] font-mono text-slate-400">
                Qualifying Intrusion Count: <strong className="text-red-400">{detectionResult?.active_face_boxes.length || 0}</strong>
              </span>
            </div>

            {(!detectionResult || detectionResult.face_boxes.length === 0) ? (
              <div className="p-3 bg-emerald-950/20 border border-emerald-500/30 rounded-xl text-xs font-mono text-emerald-400 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
                <span>Zero faces detected. Frame is completely clear.</span>
              </div>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {detectionResult.face_boxes.map((fb, idx) => {
                  const isQualifying = detectionResult.active_face_boxes.some(
                    (ab) => Math.abs(ab.x - fb.x) < 0.02 && Math.abs(ab.y - fb.y) < 0.02
                  );

                  return (
                    <div
                      key={idx}
                      className={`p-2.5 rounded-xl border font-mono text-xs flex items-center justify-between gap-3 ${
                        fb.isStaticBackground
                          ? 'bg-slate-800/40 border-slate-700 text-slate-400'
                          : isQualifying
                          ? 'bg-red-950/30 border-red-500/50 text-red-200'
                          : 'bg-amber-950/20 border-amber-500/40 text-amber-200'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-bold">Face #{idx + 1}</span>
                        <span className="px-1.5 py-0.5 rounded bg-black/40 text-[10px]">
                          Conf: <strong>{Math.round(fb.score * 100)}%</strong>
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-black/40 text-[10px]">
                          Size: <strong>{(fb.widthFraction * 100).toFixed(1)}%w x {(fb.heightFraction * 100).toFixed(1)}%h</strong> ({(fb.areaFraction * 100).toFixed(1)}% area)
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-black/40 text-[10px]">
                          Loc: <strong>({(fb.x * 100).toFixed(1)}%, {(fb.y * 100).toFixed(1)}%)</strong>
                        </span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-black/50">
                          {fb.consecutiveFrames} frame{fb.consecutiveFrames > 1 ? 's' : ''}
                        </span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          fb.isStaticBackground
                            ? 'bg-slate-700 text-slate-300'
                            : isQualifying
                            ? 'bg-red-500 text-white'
                            : 'bg-amber-600 text-amber-100'
                        }`}>
                          {fb.isStaticBackground
                            ? 'STATIC IGNORED'
                            : isQualifying
                            ? 'FLAG RAISED'
                            : fb.score < currentProfileConfig.minFaceConfidence
                            ? 'LOW CONF'
                            : fb.width < currentProfileConfig.minFaceBoxWidthFraction
                            ? 'BELOW MIN SIZE'
                            : 'PENDING CONSECUTIVE'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: Metrics & Benchmarking Cards */}
        <div className="lg:col-span-4 flex flex-col gap-4">
          
          {/* Controls Card */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-cyan-400" />
              Camera & Model Controls
            </h3>

            <div className="space-y-2">
              {!isRunning ? (
                <button
                  onClick={startCamera}
                  className="w-full py-3 px-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-cyan-600/30 active:scale-95 transition-all"
                >
                  <Camera className="w-4 h-4" />
                  Start Diagnostic Camera
                </button>
              ) : (
                <button
                  onClick={stopCamera}
                  className="w-full py-3 px-4 rounded-xl bg-red-600/80 hover:bg-red-500 text-white font-bold text-xs flex items-center justify-center gap-2 active:scale-95 transition-all"
                >
                  <CameraOff className="w-4 h-4" />
                  Stop Camera
                </button>
              )}

              <button
                onClick={() => {
                  const next = facingMode === 'user' ? 'environment' : 'user';
                  setFacingMode(next);
                  if (isRunning) {
                    stopCamera();
                    setTimeout(startCamera, 150);
                  }
                }}
                className="w-full py-2.5 px-3 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 text-xs font-mono flex items-center justify-center gap-2 transition-all"
              >
                <span>Facing Mode: <strong>{facingMode}</strong></span>
              </button>
            </div>
          </div>

          {/* Active Profile Configuration Breakdown */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl space-y-3 font-mono text-xs">
            <h3 className="font-bold uppercase tracking-wider text-slate-400 text-[11px] flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-400" />
              Active Profile: {activeProfile.toUpperCase()}
            </h3>

            <div className="space-y-2 text-slate-300 text-[11px]">
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Min Confidence:</span>
                <span className="text-cyan-400 font-bold">{currentProfileConfig.minFaceConfidence} ({Math.round(currentProfileConfig.minFaceConfidence * 100)}%)</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Min Box Width:</span>
                <span className="text-cyan-400 font-bold">{Math.round(currentProfileConfig.minFaceBoxWidthFraction * 100)}% of frame width</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Min Consecutive Frames:</span>
                <span className="text-purple-400 font-bold">{currentProfileConfig.minConsecutiveFrames} frames</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Retention Cooldown:</span>
                <span className="text-emerald-400 font-bold">{currentProfileConfig.cooldownMs} ms ({currentProfileConfig.cooldownFrames}f)</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Large Face Gating:</span>
                <span className="text-amber-400 font-bold">&gt; {Math.round(currentProfileConfig.largeFaceAreaThreshold * 100)}% frame area</span>
              </div>
            </div>
          </div>

          {/* Model Specification Card */}
          <div className="bg-[#0D1322] border border-slate-800 rounded-3xl p-5 shadow-xl space-y-3 font-mono text-xs">
            <h3 className="font-bold uppercase tracking-wider text-slate-400 text-[11px] flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-400" />
              Self-Hosted Model Specs
            </h3>

            <div className="space-y-2 text-slate-300 text-[11px]">
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Face Detector:</span>
                <span className="text-cyan-400 font-bold">blaze_face_short_range (229 KB)</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Hand Landmarker:</span>
                <span className="text-cyan-400 font-bold">hand_landmarker.task (7.8 MB)</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">WASM Runtime:</span>
                <span className="text-purple-400 font-bold">vision_wasm_internal (14.6 MB)</span>
              </div>
              <div className="p-2.5 rounded-xl bg-[#131B2E] border border-slate-700 flex justify-between">
                <span className="text-slate-400">Downscale Processing:</span>
                <span className="text-emerald-400 font-bold">320 px width copy</span>
              </div>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
};
export default DetectorTestView;
