import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { 
  Camera, ArrowLeft, RefreshCw, Smartphone, Laptop, CheckCircle2, 
  AlertCircle, ShieldCheck, Video, Sliders, Flashlight, Eye
} from 'lucide-react';
import { CameraHelper } from '../services/cameraHelper';

interface VideoDeviceInfo {
  deviceId: string;
  label: string;
  groupId: string;
}

const READY_STATE_MAP: Record<number, string> = {
  0: 'HAVE_NOTHING (0)',
  1: 'HAVE_METADATA (1)',
  2: 'HAVE_CURRENT_DATA (2)',
  3: 'HAVE_FUTURE_DATA (3)',
  4: 'HAVE_ENOUGH_DATA (4)',
};

export const CameraTestView: React.FC = () => {
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');
  const [deviceList, setDeviceList] = useState<VideoDeviceInfo[]>([]);
  
  // Track settings
  const [trackSettings, setTrackSettings] = useState<MediaTrackSettings | null>(null);
  const [trackCapabilities, setTrackCapabilities] = useState<any>(null);
  
  // Video element telemetry
  const [readyState, setReadyState] = useState<number>(0);
  const [videoWidth, setVideoWidth] = useState<number>(0);
  const [videoHeight, setVideoHeight] = useState<number>(0);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  
  // Error telemetry
  const [lastError, setLastError] = useState<{ name: string; message: string } | null>(null);

  // Snapshot test
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotStats, setSnapshotStats] = useState<{ avgBrightness: number; isBlack: boolean } | null>(null);

  // Torch
  const [torchEnabled, setTorchEnabled] = useState<boolean>(false);
  const [torchSupported, setTorchSupported] = useState<boolean>(false);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const tickerRef = useRef<any>(null);

  // Refresh available camera devices
  const refreshDevices = useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.enumerateDevices) {
      return;
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoInputs = devices
        .filter((d) => d.kind === 'videoinput')
        .map((d, idx) => ({
          deviceId: d.deviceId,
          label: d.label || `Camera ${idx + 1} (${d.deviceId.slice(0, 8)}...)`,
          groupId: d.groupId,
        }));
      setDeviceList(videoInputs);
    } catch (err: any) {
      console.warn('Failed to enumerate devices:', err);
    }
  }, []);

  // Stop camera tracks and release element
  const stopCamera = useCallback(() => {
    if (tickerRef.current) {
      clearInterval(tickerRef.current);
      tickerRef.current = null;
    }
    if (streamRef.current) {
      CameraHelper.stopStream(streamRef.current);
      streamRef.current = null;
    }
    CameraHelper.stopAllStreams();
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsRunning(false);
    setTrackSettings(null);
    setTrackCapabilities(null);
    setTorchEnabled(false);
    setTorchSupported(false);
    setReadyState(0);
    setVideoWidth(0);
    setVideoHeight(0);
  }, []);

  // Start camera stream
  const startCamera = useCallback(async (overrideDeviceId?: string, overrideFacing?: 'environment' | 'user') => {
    stopCamera();
    setLastError(null);

    const targetFacing = overrideFacing || facingMode;
    const targetDevice = overrideDeviceId !== undefined ? overrideDeviceId : selectedDeviceId;

    try {
      let stream: MediaStream;
      if (targetDevice) {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            deviceId: { exact: targetDevice },
            width: { ideal: 1280, min: 640 },
            height: { ideal: 720, min: 480 },
          },
          audio: false,
        });
      } else {
        stream = await CameraHelper.openCamera({
          idealWidth: 1280,
          idealHeight: 720,
          facingMode: targetFacing,
        });
      }

      streamRef.current = stream;

      const track = stream.getVideoTracks()[0];
      if (track) {
        const settings = track.getSettings ? track.getSettings() : {};
        setTrackSettings(settings);
        const caps = track.getCapabilities ? (track.getCapabilities() as any) : null;
        setTrackCapabilities(caps);
        if (caps && caps.torch) {
          setTorchSupported(true);
        }
      }

      if (videoRef.current) {
        await CameraHelper.attachStreamToVideo(videoRef.current, stream, {
          checkTimeoutMs: 3000,
          onNoPicture: (state) => {
            console.warn('[CameraTestView] onNoPicture triggered. readyState:', state);
          },
        });
      }

      setIsRunning(true);
      await refreshDevices();

      // Start 250ms telemetry poll
      tickerRef.current = setInterval(() => {
        if (videoRef.current) {
          setReadyState(videoRef.current.readyState);
          setVideoWidth(videoRef.current.videoWidth);
          setVideoHeight(videoRef.current.videoHeight);
          setIsPaused(videoRef.current.paused);
        }
      }, 250);

    } catch (err: any) {
      console.error('CameraTestView start error:', err);
      setLastError({
        name: err?.name || 'Error',
        message: err?.message || String(err),
      });
      setIsRunning(false);
    }
  }, [facingMode, selectedDeviceId, stopCamera, refreshDevices]);

  // Initial mount device query
  useEffect(() => {
    refreshDevices();
    return () => {
      stopCamera();
    };
  }, [refreshDevices, stopCamera]);

  // Toggle facing mode
  const handleToggleFacing = () => {
    const nextFacing = facingMode === 'environment' ? 'user' : 'environment';
    setFacingMode(nextFacing);
    setSelectedDeviceId('');
    startCamera('', nextFacing);
  };

  // Switch to specific camera
  const handleSelectDevice = (devId: string) => {
    setSelectedDeviceId(devId);
    startCamera(devId);
  };

  // Toggle hardware torch
  const handleToggleTorch = async () => {
    if (!streamRef.current) return;
    const next = !torchEnabled;
    const ok = await CameraHelper.setTorch(streamRef.current, next);
    if (ok) setTorchEnabled(next);
  };

  // Capture test snapshot to verify non-black frames
  const handleTakeSnapshot = () => {
    if (!videoRef.current || videoRef.current.videoWidth === 0) return;
    const video = videoRef.current;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
    setSnapshotUrl(dataUrl);

    // Compute pixel brightness
    try {
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imgData.data;
      let totalLuma = 0;
      const step = 4 * 10; // sample every 10th pixel for speed
      let samples = 0;
      for (let i = 0; i < data.length; i += step) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        totalLuma += 0.299 * r + 0.587 * g + 0.114 * b;
        samples++;
      }
      const avgBrightness = samples > 0 ? Math.round(totalLuma / samples) : 0;
      setSnapshotStats({
        avgBrightness,
        isBlack: avgBrightness < 5,
      });
    } catch (e) {
      console.warn('Snapshot brightness computation failed:', e);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-6 font-sans">
      <div className="max-w-3xl mx-auto space-y-6">
        
        {/* Top Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Link
              to="/user"
              className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition-all active:scale-95"
              title="Return to Shopper App"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div>
              <h1 className="text-xl font-bold flex items-center gap-2">
                <Camera className="w-6 h-6 text-emerald-400" />
                Hardware Camera Diagnostic
              </h1>
              <p className="text-xs text-slate-400">
                Cross-platform camera stream, telemetry & frame inspection
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => refreshDevices()}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-all"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Scan Devices
            </button>
          </div>
        </div>

        {/* Live Video Viewport Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl p-4 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Video className="w-4 h-4 text-emerald-400" />
              Live Viewfinder Element
            </span>

            <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold ${
              isRunning 
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' 
                : 'bg-slate-800 text-slate-400'
            }`}>
              {isRunning ? 'STREAM ACTIVE' : 'STOPPED'}
            </span>
          </div>

          {/* Video Container */}
          <div className="relative w-full aspect-video bg-black rounded-2xl overflow-hidden border border-slate-800 flex items-center justify-center">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover"
            />

            {!isRunning && (
              <div className="z-10 text-center p-6 text-slate-500 space-y-2">
                <Camera className="w-12 h-12 mx-auto opacity-30" />
                <div className="text-sm font-semibold">Camera is idle</div>
                <div className="text-xs">Tap &ldquo;Start Camera&rdquo; below to begin stream diagnostic</div>
              </div>
            )}

            {/* In-view overlay telemetry pill */}
            {isRunning && (
              <div className="absolute bottom-3 left-3 z-10 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded-xl border border-white/10 text-xs font-mono space-y-0.5">
                <div className="text-emerald-400 font-bold">
                  {videoWidth} × {videoHeight} px
                </div>
                <div className="text-slate-300 text-[10px]">
                  State: {READY_STATE_MAP[readyState] || readyState}
                </div>
              </div>
            )}
          </div>

          {/* Viewfinder Controls */}
          <div className="flex flex-wrap items-center gap-2 pt-2">
            {!isRunning ? (
              <button
                onClick={() => startCamera()}
                className="flex-1 py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-sm flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/20 active:scale-95 transition-all"
              >
                <Camera className="w-4 h-4" />
                Start Camera
              </button>
            ) : (
              <button
                onClick={stopCamera}
                className="flex-1 py-3 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-sm flex items-center justify-center gap-2 shadow-lg shadow-rose-600/20 active:scale-95 transition-all"
              >
                Stop Camera
              </button>
            )}

            <button
              onClick={handleToggleFacing}
              className="py-3 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-xs flex items-center gap-2 transition-all active:scale-95"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Flip: {facingMode === 'environment' ? 'Rear' : 'Front'}
            </button>

            {torchSupported && isRunning && (
              <button
                onClick={handleToggleTorch}
                className={`py-3 px-4 rounded-xl text-xs font-bold flex items-center gap-2 transition-all active:scale-95 ${
                  torchEnabled 
                    ? 'bg-amber-400 text-slate-950 shadow-lg shadow-amber-400/30' 
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
                }`}
              >
                <Flashlight className="w-3.5 h-3.5" />
                Torch {torchEnabled ? 'ON' : 'OFF'}
              </button>
            )}

            {isRunning && (
              <button
                onClick={handleTakeSnapshot}
                className="py-3 px-4 rounded-xl bg-emerald-700/80 hover:bg-emerald-600 text-white font-semibold text-xs flex items-center gap-2 transition-all active:scale-95"
              >
                <Eye className="w-3.5 h-3.5" />
                Inspect Frame
              </button>
            )}
          </div>
        </div>

        {/* Error Banner (if any) */}
        {lastError && (
          <div className="p-4 bg-red-950/60 border border-red-800 rounded-2xl flex items-start gap-3 text-red-200 animate-in fade-in">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="font-bold text-sm">Camera Error: {lastError.name}</div>
              <div className="text-xs text-red-300 font-mono">{lastError.message}</div>
            </div>
          </div>
        )}

        {/* Snapshot Frame Inspection Result */}
        {snapshotUrl && (
          <div className="bg-slate-900 border border-slate-800 rounded-3xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Frame Pixel Inspection
              </span>
              {snapshotStats && (
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                  snapshotStats.isBlack 
                    ? 'bg-red-500/20 text-red-400 border border-red-500/30' 
                    : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                }`}>
                  {snapshotStats.isBlack ? 'BLANK / BLACK FRAME (0-4 luma)' : `VALID PICTURE (${snapshotStats.avgBrightness} avg luma)`}
                </span>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-4 items-center">
              <img
                src={snapshotUrl}
                alt="Camera snapshot"
                className="w-48 h-auto rounded-xl border border-slate-700 shadow-md"
              />
              <div className="text-xs space-y-1.5 text-slate-300">
                <div><strong>Resolution:</strong> {videoWidth} × {videoHeight}</div>
                <div><strong>Average Luma:</strong> {snapshotStats?.avgBrightness ?? 'N/A'} / 255</div>
                <div><strong>Frame Status:</strong> {snapshotStats?.isBlack ? 'FAIL: Sensor or track returned black' : 'PASS: Actual light detected'}</div>
              </div>
            </div>
          </div>
        )}

        {/* Live Telemetry Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          
          {/* Video Element State */}
          <div className="bg-slate-900 border border-slate-800 rounded-3xl p-5 space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Video className="w-4 h-4 text-emerald-400" />
              HTMLVideoElement Telemetry
            </h3>

            <div className="space-y-2 font-mono text-xs">
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">readyState</span>
                <span className={readyState >= 2 ? 'text-emerald-400 font-bold' : 'text-amber-400'}>
                  {READY_STATE_MAP[readyState] || readyState}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">videoWidth</span>
                <span className={videoWidth > 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                  {videoWidth} px
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">videoHeight</span>
                <span className={videoHeight > 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                  {videoHeight} px
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">paused / ended</span>
                <span className="text-slate-200">
                  {isPaused ? 'PAUSED' : 'PLAYING'} / {videoRef.current?.ended ? 'ENDED' : 'NO'}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">muted / playsInline</span>
                <span className="text-emerald-400">
                  {String(videoRef.current?.muted)} / {String(videoRef.current?.playsInline)}
                </span>
              </div>
            </div>
          </div>

          {/* Active MediaStreamTrack Settings */}
          <div className="bg-slate-900 border border-slate-800 rounded-3xl p-5 space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-emerald-400" />
              Active Track Settings
            </h3>

            {trackSettings ? (
              <div className="space-y-2 font-mono text-xs">
                <div className="flex justify-between py-1 border-b border-slate-800">
                  <span className="text-slate-400">facingMode</span>
                  <span className="text-emerald-400 font-bold">{trackSettings.facingMode || 'unknown'}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-800">
                  <span className="text-slate-400">track resolution</span>
                  <span className="text-emerald-400">{trackSettings.width} × {trackSettings.height}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-800">
                  <span className="text-slate-400">frameRate</span>
                  <span className="text-slate-200">{trackSettings.frameRate ? `${Math.round(trackSettings.frameRate)} fps` : 'N/A'}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-800">
                  <span className="text-slate-400">aspectRatio</span>
                  <span className="text-slate-200">{trackSettings.aspectRatio ? trackSettings.aspectRatio.toFixed(2) : 'N/A'}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-800">
                  <span className="text-slate-400">deviceId</span>
                  <span className="text-slate-400 truncate max-w-[140px]">{trackSettings.deviceId || 'default'}</span>
                </div>
              </div>
            ) : (
              <div className="text-xs text-slate-500 italic py-4 text-center">
                Track inactive. Start camera to inspect hardware track settings.
              </div>
            )}
          </div>
        </div>

        {/* Connected Camera Devices List */}
        <div className="bg-slate-900 border border-slate-800 rounded-3xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Camera className="w-4 h-4 text-emerald-400" />
              Connected Camera Devices ({deviceList.length})
            </h3>
            <span className="text-[11px] text-slate-400">
              navigator.mediaDevices.enumerateDevices
            </span>
          </div>

          {deviceList.length === 0 ? (
            <div className="text-xs text-slate-500 py-3 text-center">
              No video devices listed yet. Grant camera permission or click &ldquo;Scan Devices&rdquo;.
            </div>
          ) : (
            <div className="space-y-2">
              {deviceList.map((dev, idx) => {
                const isSelected = selectedDeviceId === dev.deviceId || (!selectedDeviceId && idx === 0 && isRunning);
                return (
                  <div
                    key={dev.deviceId || idx}
                    className={`p-3 rounded-2xl border flex items-center justify-between gap-3 transition-all ${
                      isSelected 
                        ? 'bg-emerald-950/30 border-emerald-500/40 text-white' 
                        : 'bg-slate-800/40 border-slate-800 text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    <div className="space-y-0.5 truncate">
                      <div className="text-xs font-semibold truncate flex items-center gap-2">
                        {dev.label}
                        {isSelected && <span className="text-[10px] text-emerald-400 font-bold bg-emerald-950 px-2 py-0.5 rounded-full">ACTIVE</span>}
                      </div>
                      <div className="text-[10px] font-mono text-slate-400 truncate">
                        ID: {dev.deviceId ? `${dev.deviceId.slice(0, 24)}...` : 'default'}
                      </div>
                    </div>

                    <button
                      onClick={() => handleSelectDevice(dev.deviceId)}
                      className="px-3 py-1.5 rounded-xl bg-slate-700 hover:bg-emerald-600 text-xs font-bold text-white transition-all active:scale-95 shrink-0"
                    >
                      Use
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Mobile Platform Specs Reference */}
        <div className="p-4 bg-slate-900/60 border border-slate-800/80 rounded-2xl text-xs text-slate-400 space-y-2">
          <div className="font-bold text-slate-300 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Mobile Platform Diagnostics Checklist
          </div>
          <ul className="list-disc list-inside space-y-1 text-[11px] text-slate-400">
            <li><strong>iPhone Safari (iOS WebKit):</strong> Requires <code className="text-slate-300">playsInline</code> + <code className="text-slate-300">webkit-playsinline</code> and <code className="text-slate-300">muted=true</code> to avoid full-screen video takeover or freezing.</li>
            <li><strong>Android Chrome (Blink):</strong> Requires secure context (<code className="text-slate-300">HTTPS</code> or localhost); supports continuous autofocus constraints.</li>
            <li><strong>Camera Concurrency:</strong> Single owner active stream model strictly cleans previous tracks before requesting new hardware access.</li>
          </ul>
        </div>

      </div>
    </div>
  );
};
export default CameraTestView;
