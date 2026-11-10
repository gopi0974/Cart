/**
 * SmartCart AI - Modular Cart Camera & Hardware Streaming Client
 * ----------------------------------------------------------------
 * Connects to /ws/device with first-message authentication (no tokens in URL).
 * Streams motion-gated 640x480 JPEG frames (quality 0.7) at 2-5 FPS, plus 10s keep-alives.
 * Runs in-browser face and hand detection: withholds images if a face is detected (privacy enforcement).
 * Transmits 5-second heartbeats and handles automatic reconnection with exponential backoff.
 */

import { CameraHelper } from '../services/cameraHelper';

export interface CartCameraConfig {
  token: string;
  videoElement: HTMLVideoElement;
  onStatusChange: (status: 'CONNECTING' | 'ONLINE' | 'OFFLINE' | 'RECONNECTING', message?: string) => void;
  onMotionChange: (isMotion: boolean, motionLevel?: number) => void;
  onVisionFlagsChange?: (flags: { handPresent: boolean; facePresent: boolean; privacyRedacted: boolean }) => void;
  onLog: (message: string, level?: 'info' | 'warn' | 'error' | 'success') => void;
  onFrameSent: (info: { fps: number; sizeKb: number; timestamp: number; isReference?: boolean; faceWithheld?: boolean }) => void;
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

  // Optional native FaceDetector
  private nativeFaceDetector: any = null;

  constructor(config: CartCameraConfig) {
    this.config = config;
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.targetWidth;
    this.canvas.height = this.targetHeight;
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });

    if (typeof window !== 'undefined' && 'FaceDetector' in window) {
      try {
        this.nativeFaceDetector = new (window as any).FaceDetector({ fastMode: true, maxDetectedFaces: 2 });
      } catch {
        this.nativeFaceDetector = null;
      }
    }
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

      // Connect to WebSocket device channel with first-message auth
      this.connectWebSocket();

      // Start motion & vision detection loop (15 checks per sec)
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
   */
  public captureReferenceFrame(): boolean {
    if (!this.isRunning || !this.ctx || !this.config.videoElement || this.ws?.readyState !== WebSocket.OPEN) {
      this.config.onLog('Cannot capture reference: camera or WebSocket is not online.', 'warn');
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
        hand_present: this.handPresent,
        face_present: false, // reference should have no face
        motion_level: this.motionLevel,
        timestamp: Date.now()
      }));

      this.lastFrameSentTime = Date.now();
      this.config.onLog('Empty cart reference frame captured and transmitted.', 'success');
      this.config.onFrameSent({
        fps: this.currentFps,
        sizeKb,
        timestamp: Date.now(),
        isReference: true
      });
      return true;
    } catch (e: any) {
      this.config.onLog(`Failed to capture reference frame: ${e.message}`, 'error');
      return false;
    }
  }

  private connectWebSocket(): void {
    if (!this.isRunning) return;

    // Connect to /ws/device without token in query string
    const wsUrl = getDeviceWsUrl();
    const isReconnect = this.reconnectAttempts > 0;

    this.config.onStatusChange(isReconnect ? 'RECONNECTING' : 'CONNECTING');
    this.config.onLog(`Connecting to WebSocket server (${wsUrl})...`, 'info');

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.config.onLog('WebSocket connected. Sending first-message auth token...', 'info');

        // Step 1: FIRST MESSAGE AUTH
        this.ws?.send(JSON.stringify({
          type: 'auth',
          token: this.config.token.trim()
        }));
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'auth_ok') {
            this.config.onStatusChange('ONLINE');
            this.config.onLog(`Device authenticated! Cart: ${data.cart_number} (Online)`, 'success');

            // Start 5-second heartbeat loop
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

          } else if (data.type === 'reference_frame_ack') {
            this.config.onLog('Server acknowledged empty cart reference frame.', 'success');

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

  private async detectVisionFeatures(ctx: CanvasRenderingContext2D, width: number, height: number): Promise<{ handPresent: boolean; facePresent: boolean }> {
    let facePresent = false;
    let handPresent = false;

    // 1. Native FaceDetector API (Chromium / Edge / Android)
    if (this.nativeFaceDetector && this.config.videoElement) {
      try {
        const faces = await this.nativeFaceDetector.detect(this.config.videoElement);
        if (faces && faces.length > 0) {
          facePresent = true;
        }
      } catch {}
    }

    // 2. Skin tone & Upper-Region Cluster Detector (Cross-Browser Fallback)
    try {
      const imgData = ctx.getImageData(0, 0, width, height);
      const data = imgData.data;
      const totalPixels = width * height;
      let upperSkinPixels = 0;
      let lowerSkinPixels = 0;

      for (let i = 0; i < data.length; i += 4 * 4) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const pixelIdx = i / 4;
        const yCoord = Math.floor(pixelIdx / width);

        // Standard biometric skin-tone filter: R > G > B, (R - G) > 15, R > 90
        const isSkin = (r > 95 && g > 40 && b > 20 && r > g && r > b && (r - g) > 15 && Math.abs(r - g) > 15);
        if (isSkin) {
          if (yCoord < height * 0.45) {
            upperSkinPixels++;
          } else {
            lowerSkinPixels++;
          }
        }
      }

      // Upper skin cluster indicates face / person looking down into basket
      const upperSampled = totalPixels * 0.45 / 4;
      if (upperSkinPixels / upperSampled > 0.08) {
        facePresent = true;
      }

      // Lower/side skin cluster indicates hands reaching into basket
      const lowerSampled = totalPixels * 0.55 / 4;
      if (lowerSkinPixels / lowerSampled > 0.05) {
        handPresent = true;
      }
    } catch {}

    return { handPresent, facePresent };
  }

  private startMotionDetector(): void {
    this.motionCheckInterval = setInterval(async () => {
      if (!this.isRunning || !this.ctx || !this.config.videoElement) return;
      if (this.config.videoElement.readyState < 2) return;

      try {
        // Draw miniature frame (64x48) for lightning-fast motion & vision computation
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

          // Evaluate hand and face features
          const { handPresent, facePresent } = await this.detectVisionFeatures(this.ctx, 64, 48);
          this.handPresent = handPresent;
          this.facePresent = facePresent;

          if (this.config.onVisionFlagsChange) {
            this.config.onVisionFlagsChange({
              handPresent,
              facePresent,
              privacyRedacted: facePresent
            });
          }

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
      let dataUrl: string | null = null;
      let sizeKb = 0;

      // PRIVACY ENFORCEMENT: If face is detected, do NOT send image data!
      if (this.facePresent) {
        dataUrl = null;
        sizeKb = 0;
      } else {
        this.ctx.drawImage(this.config.videoElement, 0, 0, this.targetWidth, this.targetHeight);
        dataUrl = this.canvas.toDataURL('image/jpeg', this.jpegQuality);
        sizeKb = Math.round((dataUrl.length * 0.75) / 1024);
      }

      this.ws.send(JSON.stringify({
        type: 'frame',
        format: 'jpeg',
        data: dataUrl,
        hand_present: this.handPresent,
        face_present: this.facePresent,
        motion_level: this.motionLevel,
        privacy_redacted: this.facePresent,
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
        faceWithheld: this.facePresent
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
