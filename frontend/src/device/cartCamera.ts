/**
 * SmartCart AI - Modular Cart Camera & Hardware Streaming Client
 * ----------------------------------------------------------------
 * Connects to /ws/device with first-message authentication (no tokens in URL).
 * Streams motion-gated 640x480 JPEG frames (quality 0.7) at 2-5 FPS, plus 10s keep-alives.
 * Real in-browser face and hand detection powered by self-hosted MediaPipe tasks-vision.
 * Privacy rule: If face_present or detector not ready, frame image data is withheld.
 * Transmits 5-second heartbeats and handles automatic reconnection with exponential backoff.
 */

import { CameraHelper } from '../services/cameraHelper';
import {
  privacyDetector,
  NormalizedBox,
  DetectorState
} from '../services/privacyDetector';

export interface VisionFlagsPayload {
  handPresent: boolean;
  facePresent: boolean;
  handCount: number;
  faceBoxes: NormalizedBox[];
  handBoxes: NormalizedBox[];
  detectorReady: boolean;
  privacyRedacted: boolean;
  processingMs: number;
  delegate: 'GPU' | 'CPU' | null;
  error?: string;
}

export interface CartCameraConfig {
  token: string;
  videoElement: HTMLVideoElement;
  onStatusChange: (status: 'CONNECTING' | 'ONLINE' | 'OFFLINE' | 'RECONNECTING', message?: string) => void;
  onMotionChange: (isMotion: boolean, motionLevel?: number) => void;
  onVisionFlagsChange?: (flags: VisionFlagsPayload) => void;
  onDetectorStateChange?: (state: DetectorState) => void;
  onLog: (message: string, level?: 'info' | 'warn' | 'error' | 'success') => void;
  onFrameSent: (info: { fps: number; sizeKb: number; timestamp: number; isReference?: boolean; faceWithheld?: boolean; detectorReady?: boolean }) => void;
  onVerificationResult?: (result: any) => void;
}

export function getDeviceWsUrl(): string {
  const envApi = (import.meta as any).env?.VITE_API_URL;
  if (envApi) {
    const wsProto = envApi.startsWith('https') ? 'wss' : 'ws';
    const cleanHost = envApi.replace(/^https?:\/\//, '');
    return `${wsProto}://${cleanHost}/ws/device`;
  }
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const defaultPort = 8000;
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  return `${isHttps ? 'wss' : 'ws'}://${host}:${defaultPort}/ws/device`;
}

export class CartCameraManager {
  private config: CartCameraConfig;
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D | null;
  private prevFrameData: Uint8ClampedArray | null = null;
  
  private isRunning = false;
  private isMotion = false;
  private lastMotionTime = 0;
  private lastFrameSentTime = 0;
  private motionLevel = 0.0;
  private handPresent = false;
  private facePresent = false;
  private detectorReady = false;

  private motionCheckInterval: any = null;
  private frameSendInterval: any = null;
  private heartbeatInterval: any = null;
  private reconnectTimer: any = null;
  private reconnectAttempts = 0;
  
  private framesSentCount = 0;
  private lastFpsCalcTime = Date.now();
  private currentFps = 0;

  // Frame specs: 640x480 at ~3.3 FPS (300ms) during motion, quality 0.70
  private readonly targetWidth = 640;
  private readonly targetHeight = 480;
  private readonly jpegQuality = 0.70;
  private readonly frameIntervalMs = 300; // ~3.3 FPS during motion
  private readonly keepAliveIntervalMs = 10000; // 10s keep-alive frame
  private readonly motionThreshold = 22; // Pixel difference sensitivity
  private readonly motionPixelRatio = 0.025; // 2.5% of pixels changed to trigger motion
  private readonly motionCooldownMs = 1200; // Cooldown after movement ceases

  constructor(config: CartCameraConfig) {
    this.config = config;
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.targetWidth;
    this.canvas.height = this.targetHeight;
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
  }

  public async start(): Promise<void> {
    if (this.isRunning) return;
    this.isRunning = true;
    this.reconnectAttempts = 0;

    try {
      this.config.onLog('Requesting camera stream (640x480 overhead view)...', 'info');
      
      // Use shared openCamera helper & attachStreamToVideo
      this.stream = await CameraHelper.openCamera({
        idealWidth: this.targetWidth,
        idealHeight: this.targetHeight,
        facingMode: 'environment',
      });

      await CameraHelper.attachStreamToVideo(this.config.videoElement, this.stream, {
        checkTimeoutMs: 3000,
        onNoPicture: (state) => {
          this.config.onLog(`Warning: Camera stream attached but videoWidth is 0 (readyState: ${state})`, 'warn');
        },
      });

      this.config.onLog('Camera live preview active.', 'success');

      // Initialize self-hosted MediaPipe privacy detector
      try {
        this.config.onLog('Loading self-hosted MediaPipe Face & Hand Landmarker...', 'info');
        await privacyDetector.load();
        const detState = privacyDetector.getState();
        this.detectorReady = detState.status === 'ready';
        if (this.config.onDetectorStateChange) {
          this.config.onDetectorStateChange(detState);
        }
        this.config.onLog(`Privacy detector ready (${detState.delegate} delegate).`, 'success');
      } catch (detErr: any) {
        this.detectorReady = false;
        this.config.onLog(`Privacy detector failed to load: ${detErr.message}. Images will be withheld.`, 'error');
        if (this.config.onDetectorStateChange) {
          this.config.onDetectorStateChange(privacyDetector.getState());
        }
      }

      // Connect to WebSocket device channel with first-message auth
      this.connectWebSocket();

      // Start motion detection loop (15 checks per sec)
      this.startMotionDetector();

      // Start streaming loop (sends frames during motion or every 10s keepalive)
      this.startFrameStreamer();
    } catch (err: any) {
      this.isRunning = false;
      const parsed = CameraHelper.parseCameraError(err);
      this.config.onStatusChange('OFFLINE', parsed.message);
      this.config.onLog(`Camera Error: ${parsed.message}`, 'error');
      throw err;
    }
  }

  public stop(): void {
    this.isRunning = false;
    this.isMotion = false;
    this.config.onMotionChange(false, 0);

    // Stop media stream tracks
    if (this.stream) {
      CameraHelper.stopStream(this.stream);
      this.stream = null;
    }
    if (this.config.videoElement) {
      this.config.videoElement.srcObject = null;
    }

    // Stop timers
    if (this.motionCheckInterval) clearInterval(this.motionCheckInterval);
    if (this.frameSendInterval) clearInterval(this.frameSendInterval);
    if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

    // Close WebSocket
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      try {
        this.ws.close();
      } catch {}
      this.ws = null;
    }

    this.prevFrameData = null;
    this.config.onStatusChange('OFFLINE');
    this.config.onLog('Cart device camera stopped.', 'info');
  }

  /**
   * Explicitly captures an empty-cart reference frame.
   * Safe failure: refused if detector is not ready or if face is present.
   */
  public captureReferenceFrame(): boolean {
    if (!this.isRunning || !this.ctx || !this.config.videoElement || this.ws?.readyState !== WebSocket.OPEN) {
      this.config.onLog('Cannot capture reference: camera or WebSocket is not online.', 'warn');
      return false;
    }

    const det = privacyDetector.detect(this.config.videoElement);
    if (!det.detector_ready) {
      this.config.onLog('Cannot capture reference: Privacy detector is not ready.', 'error');
      return false;
    }
    if (det.face_present) {
      this.config.onLog('Cannot capture reference: Face detected in frame. Remove face from view.', 'error');
      return false;
    }

    try {
      this.ctx.drawImage(this.config.videoElement, 0, 0, this.targetWidth, this.targetHeight);
      const dataUrl = this.canvas.toDataURL('image/jpeg', this.jpegQuality);
      const sizeKb = Math.round((dataUrl.length * 0.75) / 1024);

      this.ws.send(JSON.stringify({
        type: 'reference_frame',
        format: 'jpeg',
        data: dataUrl,
        is_reference: true,
        detector_ready: true,
        hand_present: det.hand_present,
        hand_count: det.hand_count,
        face_present: false,
        face_boxes: [],
        hand_boxes: det.hand_boxes,
        motion_level: this.motionLevel,
        timestamp: Date.now()
      }));

      this.lastFrameSentTime = Date.now();
      this.config.onLog('Empty cart reference frame captured and transmitted.', 'success');
      this.config.onFrameSent({
        fps: this.currentFps,
        sizeKb,
        timestamp: Date.now(),
        isReference: true,
        detectorReady: true
      });
      return true;
    } catch (e: any) {
      this.config.onLog(`Failed to capture reference frame: ${e.message}`, 'error');
      return false;
    }
  }

  private connectWebSocket(): void {
    if (!this.isRunning) return;

    const wsUrl = getDeviceWsUrl();
    const isReconnect = this.reconnectAttempts > 0;

    this.config.onStatusChange(isReconnect ? 'RECONNECTING' : 'CONNECTING');
    this.config.onLog(`Connecting to WebSocket server (${wsUrl})...`, 'info');

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.config.onLog('WebSocket transport connected. Authenticating via first message...', 'info');

        // Transmit FIRST-MESSAGE authentication (Token never placed in URL)
        this.ws?.send(JSON.stringify({
          type: 'auth',
          token: this.config.token.trim(),
          client: 'CartCameraWebcamClient',
          version: '2.0.0'
        }));
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'auth_ok') {
            this.config.onStatusChange('ONLINE');
            this.config.onLog(`Cart camera authenticated! Cart: ${data.cart_number} (ID: ${data.cart_id})`, 'success');

            // Start 5-second heartbeats
            if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = setInterval(() => {
              this.sendHeartbeat();
            }, 5000);

            // Send initial frame immediately on connect
            this.sendFramePayload(false);

          } else if (data.type === 'heartbeat_ack') {
            // Heartbeat acknowledged

          } else if (data.type === 'frame_ack') {
            // Frame received by server

          } else if (data.type === 'reference_ack') {
            this.config.onLog('Server acknowledged empty cart reference baseline.', 'success');

          } else if (data.type === 'frame_error') {
            this.config.onLog(`Server frame error: ${data.message}`, 'warn');

          } else if (data.type === 'vision_status') {
            this.config.onLog(`[Vision] ${data.message}`, 'info');

          } else if (data.type === 'verification_result' && this.config.onVerificationResult) {
            this.config.onVerificationResult(data);
          }
        } catch {
          // Non-JSON pong or raw text
        }
      };

      this.ws.onerror = () => {
        this.config.onLog('WebSocket connection error.', 'error');
      };

      this.ws.onclose = (event) => {
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);

        // Terminal auth errors: 4001 (timeout), 4003 (URL token), 4004 (unknown token), 4005 (disabled/regen)
        if (event.code === 4001 || event.code === 4003 || event.code === 4004 || event.code === 4005 || event.code === 1008) {
          const reason = event.reason || (
            event.code === 4004 ? 'Unknown device token' :
            event.code === 4005 ? 'Cart disabled or token regenerated' :
            event.code === 4003 ? 'Token in URL rejected' : 'Authentication failed'
          );
          this.config.onStatusChange('OFFLINE', reason);
          this.config.onLog(`Device authentication rejected (${event.code}): ${reason}`, 'error');
          this.isRunning = false;
          return;
        }

        // 4009: Replaced by new device connection
        if (event.code === 4009) {
          this.config.onStatusChange('OFFLINE', 'Replaced by newer device session');
          this.config.onLog('Device connection superseded by another connection for this cart.', 'warn');
          this.isRunning = false;
          return;
        }

        this.config.onStatusChange('OFFLINE', 'Connection lost');
        this.config.onLog(`WebSocket closed (${event.code}). Attempting reconnect...`, 'warn');

        if (this.isRunning) {
          const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 8000);
          this.reconnectAttempts++;
          this.reconnectTimer = setTimeout(() => {
            this.connectWebSocket();
          }, delay);
        }
      };
    } catch (err: any) {
      this.config.onLog(`Failed to initialize WebSocket: ${err.message}`, 'error');
    }
  }

  private sendHeartbeat(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'heartbeat',
        battery: 100,
        timestamp: Date.now()
      }));
    }
  }

  private startMotionDetector(): void {
    this.motionCheckInterval = setInterval(() => {
      if (!this.isRunning || !this.ctx || !this.config.videoElement) return;
      if (this.config.videoElement.readyState < 2) return;

      try {
        // Draw miniature frame (64x48) for lightning-fast motion computation
        this.ctx.drawImage(this.config.videoElement, 0, 0, 64, 48);
        const imgData = this.ctx.getImageData(0, 0, 64, 48);
        const data = imgData.data;

        if (this.prevFrameData) {
          let diffCount = 0;
          const totalPixels = 64 * 48;

          for (let i = 0; i < data.length; i += 4) {
            const currY = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            const prevY = 0.299 * this.prevFrameData[i] + 0.587 * this.prevFrameData[i + 1] + 0.114 * this.prevFrameData[i + 2];
            if (Math.abs(currY - prevY) > this.motionThreshold) {
              diffCount++;
            }
          }

          const ratio = diffCount / totalPixels;
          this.motionLevel = Math.round(ratio * 100) / 100;
          const now = Date.now();

          if (ratio > this.motionPixelRatio) {
            this.lastMotionTime = now;
            if (!this.isMotion) {
              this.isMotion = true;
              this.config.onMotionChange(true, this.motionLevel);
              this.config.onLog(`Motion detected (level ${(this.motionLevel * 100).toFixed(0)}%). Streaming active.`, 'info');
              if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'motion', state: 'start' }));
              }
            }
          } else if (this.isMotion && (now - this.lastMotionTime > this.motionCooldownMs)) {
            this.isMotion = false;
            this.config.onMotionChange(false, 0);
            this.config.onLog('Motion ceased. Pausing active stream (10s keep-alive continues).', 'info');
            if (this.ws?.readyState === WebSocket.OPEN) {
              this.ws.send(JSON.stringify({ type: 'motion', state: 'stop' }));
            }
          }
        }

        this.prevFrameData = new Uint8ClampedArray(data);
      } catch {}
    }, 70);
  }

  private sendFramePayload(isKeepAlive: boolean = false): void {
    if (!this.ctx || !this.config.videoElement || this.ws?.readyState !== WebSocket.OPEN) return;

    try {
      const now = Date.now();

      // 1. Run real MediaPipe detector on downscaled copy (~320 px)
      const det = privacyDetector.detect(this.config.videoElement);
      this.handPresent = det.hand_present;
      this.facePresent = det.face_present;
      this.detectorReady = det.detector_ready;

      if (this.config.onVisionFlagsChange) {
        this.config.onVisionFlagsChange({
          handPresent: det.hand_present,
          facePresent: det.face_present,
          handCount: det.hand_count,
          faceBoxes: det.face_boxes,
          handBoxes: det.hand_boxes,
          detectorReady: det.detector_ready,
          privacyRedacted: det.face_present || !det.detector_ready,
          processingMs: det.processing_ms,
          delegate: det.delegate,
          error: det.error
        });
      }

      // SAFE FAILURE: If detector is not ready or failed, do NOT send images
      if (!det.detector_ready) {
        this.config.onLog('Privacy detector not ready, frames are not being sent', 'warn');
        this.ws.send(JSON.stringify({
          type: 'frame',
          data: null,
          detector_ready: false,
          face_present: false,
          hand_present: false,
          hand_count: 0,
          face_boxes: [],
          hand_boxes: [],
          motion_level: this.motionLevel,
          is_keepalive: isKeepAlive,
          timestamp: now
        }));
        this.config.onFrameSent({
          fps: this.currentFps || (this.isMotion ? 3 : 0),
          sizeKb: 0,
          timestamp: now,
          faceWithheld: true,
          detectorReady: false
        });
        return;
      }

      // PRIVACY ENFORCEMENT: If face detected, image is WITHHELD (data: null)
      let dataUrl: string | null = null;
      let sizeKb = 0;
      let faceWithheld = false;

      if (det.face_present) {
        dataUrl = null;
        sizeKb = 0;
        faceWithheld = true;
      } else {
        this.ctx.drawImage(this.config.videoElement, 0, 0, this.targetWidth, this.targetHeight);
        dataUrl = this.canvas.toDataURL('image/jpeg', this.jpegQuality);
        sizeKb = Math.round((dataUrl.length * 0.75) / 1024);
      }

      this.ws.send(JSON.stringify({
        type: 'frame',
        format: 'jpeg',
        data: dataUrl,
        detector_ready: true,
        face_present: det.face_present,
        hand_present: det.hand_present,
        hand_count: det.hand_count,
        face_boxes: det.face_boxes,
        hand_boxes: det.hand_boxes,
        processing_ms: det.processing_ms,
        motion_level: this.motionLevel,
        privacy_redacted: det.face_present,
        is_keepalive: isKeepAlive,
        timestamp: now
      }));

      this.lastFrameSentTime = now;
      this.framesSentCount++;

      if (now - this.lastFpsCalcTime >= 1000) {
        this.currentFps = this.framesSentCount;
        this.framesSentCount = 0;
        this.lastFpsCalcTime = now;
      }

      this.config.onFrameSent({
        fps: this.currentFps || (this.isMotion ? 3 : 0),
        sizeKb,
        timestamp: now,
        faceWithheld,
        detectorReady: true
      });
    } catch (err: any) {
      this.config.onLog(`Frame capture error: ${err.message}`, 'warn');
    }
  }

  private startFrameStreamer(): void {
    this.frameSendInterval = setInterval(() => {
      if (!this.isRunning || this.ws?.readyState !== WebSocket.OPEN) return;
      const now = Date.now();

      // Send frame if motion is active (at ~3.3 FPS)
      if (this.isMotion) {
        this.sendFramePayload(false);
      }
      // OR send keep-alive frame every 10 seconds if idle
      else if (now - this.lastFrameSentTime >= this.keepAliveIntervalMs) {
        this.sendFramePayload(true);
      }
    }, this.frameIntervalMs);
  }
}
