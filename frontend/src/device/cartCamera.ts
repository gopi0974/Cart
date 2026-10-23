/**
 * SmartCart AI - Modular Cart Camera & Hardware Streaming Client
 * 
 * Implements the exact communication protocol that the production ESP32-CAM
 * hardware will send, allowing seamless drop-in replacement with zero backend changes.
 */

export interface CartCameraConfig {
  token: string;
  videoElement: HTMLVideoElement;
  onStatusChange: (status: 'CONNECTING' | 'ONLINE' | 'OFFLINE', message?: string) => void;
  onMotionChange: (isMotion: boolean) => void;
  onLog: (message: string, level?: 'info' | 'warn' | 'error' | 'success') => void;
  onFrameSent: (info: { fps: number; sizeKb: number; timestamp: number }) => void;
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
  private motionCheckInterval: any = null;
  private frameSendInterval: any = null;
  private heartbeatInterval: any = null;
  private reconnectTimer: any = null;
  private reconnectAttempts = 0;
  
  private framesSentCount = 0;
  private lastFpsCalcTime = Date.now();
  private currentFps = 0;

  // Frame specs: 640x480 at ~3 FPS during active motion
  private readonly targetWidth = 640;
  private readonly targetHeight = 480;
  private readonly jpegQuality = 0.75;
  private readonly frameIntervalMs = 333; // ~3 FPS
  private readonly motionThreshold = 22; // Pixel difference sensitivity
  private readonly motionPixelRatio = 0.025; // 2.5% of pixels changed to trigger motion
  private readonly motionCooldownMs = 1400; // Hold motion state for 1.4s after movement ceases

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
      this.config.onLog('Requesting webcam access (640x480 overhead view)...', 'info');
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: this.targetWidth },
          height: { ideal: this.targetHeight },
          facingMode: 'environment'
        },
        audio: false
      });

      this.config.videoElement.srcObject = this.stream;
      await this.config.videoElement.play();
      this.config.onLog('Laptop webcam live preview active.', 'success');

      // Connect to WebSocket device channel
      this.connectWebSocket();

      // Start motion detection loop (15 checks per sec)
      this.startMotionDetector();

      // Start streaming loop (sends frames only while motion is active)
      this.startFrameStreamer();
    } catch (err: any) {
      this.isRunning = false;
      this.config.onStatusChange('OFFLINE', err.message || 'Camera permission denied');
      this.config.onLog(`Camera Error: ${err.message || 'Unable to access webcam'}`, 'error');
      throw err;
    }
  }

  public stop(): void {
    this.isRunning = false;
    this.isMotion = false;
    this.config.onMotionChange(false);

    // Stop media stream tracks
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
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
      this.ws.close();
      this.ws = null;
    }

    this.prevFrameData = null;
    this.config.onStatusChange('OFFLINE');
    this.config.onLog('Cart device camera stopped.', 'info');
  }

  private connectWebSocket(): void {
    if (!this.isRunning) return;

    const baseWs = getDeviceWsUrl();
    const wsUrl = `${baseWs}?token=${encodeURIComponent(this.config.token.trim())}`;

    this.config.onStatusChange('CONNECTING');
    this.config.onLog(`Connecting to WebSocket server (${wsUrl.split('?')[0]})...`, 'info');

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.config.onStatusChange('ONLINE');
        this.config.onLog('WebSocket authenticated & device online with backend server!', 'success');

        // Start heartbeat every 5 seconds
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
        this.heartbeatInterval = setInterval(() => {
          this.sendHeartbeat();
        }, 5000);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'connected') {
            this.config.onLog(`Server assigned Cart Number: ${data.cart_number}`, 'success');
          } else if (data.type === 'heartbeat_ack') {
            // Heartbeat acknowledged
          } else if (data.type === 'verification_result') {
            this.config.onLog(`AI Verified Item: ${data.product_name} (${data.barcode})`, 'success');
            if (this.config.onVerificationResult) {
              this.config.onVerificationResult(data);
            }
          } else if (data.type === 'frame_ack') {
            // Frame acknowledged
          } else if (data.type === 'frame_error') {
            this.config.onLog(`Server Frame Warning: ${data.message}`, 'warn');
          }
        } catch {
          // Non-JSON pong or raw text
        }
      };

      this.ws.onerror = (e) => {
        this.config.onLog('WebSocket connection error.', 'error');
      };

      this.ws.onclose = (event) => {
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);

        if (event.code === 1008 || event.reason?.toLowerCase().includes('token') || event.reason?.toLowerCase().includes('disabled')) {
          this.config.onStatusChange('OFFLINE', event.reason || 'Device Token Rejected / Unknown');
          this.config.onLog(`Authentication Rejected: ${event.reason || 'Invalid or disabled device token.'}`, 'error');
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
    // Check for pixel difference 15 times a second (lightweight subsampled grid)
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
            // Luminance formula
            const currY = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            const prevY = 0.299 * this.prevFrameData[i] + 0.587 * this.prevFrameData[i + 1] + 0.114 * this.prevFrameData[i + 2];
            if (Math.abs(currY - prevY) > this.motionThreshold) {
              diffCount++;
            }
          }

          const ratio = diffCount / totalPixels;
          const now = Date.now();

          if (ratio > this.motionPixelRatio) {
            this.lastMotionTime = now;
            if (!this.isMotion) {
              this.isMotion = true;
              this.config.onMotionChange(true);
              this.config.onLog('Motion detected in cart! Camera streaming active.', 'info');
              if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'motion', state: 'start' }));
              }
            }
          } else if (this.isMotion && (now - this.lastMotionTime > this.motionCooldownMs)) {
            this.isMotion = false;
            this.config.onMotionChange(false);
            this.config.onLog('Motion ceased. Camera stream paused to conserve bandwidth.', 'info');
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
              this.ws.send(JSON.stringify({ type: 'motion', state: 'stop' }));
            }
          }
        }

        // Store current frame
        this.prevFrameData = new Uint8ClampedArray(data);
      } catch {
        // Ignore frame read hiccup
      }
    }, 70);
  }

  private startFrameStreamer(): void {
    // Sends frame at ~3 FPS (333ms) ONLY while motion is active
    this.frameSendInterval = setInterval(() => {
      if (!this.isRunning || !this.isMotion || !this.ctx || !this.config.videoElement) return;
      if (this.ws?.readyState !== WebSocket.OPEN) return;

      try {
        // Capture full 640x480 frame for AI
        this.ctx.drawImage(this.config.videoElement, 0, 0, this.targetWidth, this.targetHeight);
        const dataUrl = this.canvas.toDataURL('image/jpeg', this.jpegQuality);
        const sizeKb = Math.round((dataUrl.length * 0.75) / 1024);

        // Send frame in ESP32-CAM compatible JSON format
        this.ws.send(JSON.stringify({
          type: 'frame',
          format: 'jpeg',
          data: dataUrl,
          timestamp: Date.now()
        }));

        this.framesSentCount++;
        const now = Date.now();
        if (now - this.lastFpsCalcTime >= 1000) {
          this.currentFps = this.framesSentCount;
          this.framesSentCount = 0;
          this.lastFpsCalcTime = now;
        }

        this.config.onFrameSent({
          fps: this.currentFps || 3,
          sizeKb,
          timestamp: now
        });
      } catch (err: any) {
        this.config.onLog(`Frame capture error: ${err.message}`, 'warn');
      }
    }, this.frameIntervalMs);
  }
}
