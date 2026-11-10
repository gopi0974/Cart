/**
 * Shared Camera & MediaStream Helper (Task 2)
 * -------------------------------------------
 * Provides robust cross-platform webcam / back camera access for Android Chrome and iPhone Safari.
 * Enforces HTTPS security checks, graceful constraint fallbacks, torch/zoom capabilities, and track cleanup.
 */

export type CameraStatus = 'IDLE' | 'REQUESTING' | 'ACTIVE' | 'BLOCKED' | 'NOT_FOUND' | 'IN_USE' | 'INSECURE' | 'NO_PICTURE' | 'ERROR';
export type CameraPermissionState = 'granted' | 'denied' | 'prompt' | 'unsupported';

export interface CameraErrorResult {
  code: 'INSECURE_CONTEXT' | 'PERMISSION_DENIED' | 'NOT_FOUND' | 'IN_USE' | 'NOT_SUPPORTED' | 'UNKNOWN';
  status: CameraStatus;
  message: string;
  originalError?: any;
}

export interface AttachStreamOptions {
  checkTimeoutMs?: number;
  onNoPicture?: (readyState: number) => void;
}

export class CameraHelper {
  private static activeStreams = new Set<MediaStream>();
  public static hasEverBeenGranted: boolean = false;

  /**
   * Check browser camera permission using navigator.permissions.query where supported.
   * In Safari or unsupported browsers, returns 'unsupported' (unless previously granted in session).
   */
  static async checkPermission(): Promise<CameraPermissionState> {
    if (typeof navigator === 'undefined' || !navigator.permissions || !navigator.permissions.query) {
      return this.hasEverBeenGranted ? 'granted' : 'unsupported';
    }
    try {
      const status = await navigator.permissions.query({ name: 'camera' as any });
      if (status.state === 'granted') {
        this.hasEverBeenGranted = true;
      }
      return status.state as CameraPermissionState;
    } catch {
      return this.hasEverBeenGranted ? 'granted' : 'unsupported';
    }
  }

  /**
   * Open the camera stream with concurrency protection:
   * Stops previous camera streams first, optionally preserving a specified stream.
   */
  static async openCamera(options?: {
    idealWidth?: number;
    idealHeight?: number;
    facingMode?: 'environment' | 'user';
    preserveStream?: MediaStream | null;
  }): Promise<MediaStream> {
    // 1. Strict concurrency enforcement: stop all previous streams except any specified
    this.stopAllStreams(options?.preserveStream);

    // 2. Request fresh back-camera stream
    const stream = await this.getBackCameraStream(options);
    this.hasEverBeenGranted = true;
    return stream;
  }

  /**
   * Register an active MediaStream for global lifecycle tracking.
   */
  static registerStream(stream: MediaStream): () => void {
    this.activeStreams.add(stream);
    return () => {
      this.activeStreams.delete(stream);
    };
  }

  /**
   * Immediately stops active camera tracks across the application
   * and clears srcObject on DOM video elements, optionally preserving one specific stream.
   */
  static stopAllStreams(exceptStream?: MediaStream | null): void {
    this.activeStreams.forEach((stream) => {
      if (stream !== exceptStream) {
        this.stopStream(stream);
      }
    });
    if (exceptStream) {
      this.activeStreams = new Set([exceptStream]);
    } else {
      this.activeStreams.clear();
    }

    if (typeof document !== 'undefined') {
      try {
        document.querySelectorAll('video').forEach((video) => {
          if (video.srcObject instanceof MediaStream && video.srcObject !== exceptStream) {
            this.stopStream(video.srcObject);
            video.srcObject = null;
          }
        });
      } catch (err) {
        console.warn('Error clearing video element streams:', err);
      }
    }
  }

  /**
   * Safely attaches a MediaStream to an HTMLVideoElement:
   * 1. Enforces autoPlay, muted, playsInline, webkit-playsinline attributes.
   * 2. Sets video.srcObject = stream.
   * 3. Waits for 'loadedmetadata' event before resolving.
   * 4. Calls video.play() and safely handles promise rejection.
   * 5. Checks if videoWidth is 0 after checkTimeoutMs (default 3s).
   *    If so, logs readyState and calls onNoPicture(readyState).
   */
  static async attachStreamToVideo(
    video: HTMLVideoElement,
    stream: MediaStream,
    options?: AttachStreamOptions
  ): Promise<{ width: number; height: number; readyState: number }> {
    if (!video) {
      throw new Error('Video element is required to attach camera stream.');
    }

    // 1. Set mobile playback attributes
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('playsinline', 'true');
    video.setAttribute('webkit-playsinline', 'true');

    // 2. Assign stream to srcObject
    if (video.srcObject !== stream) {
      video.srcObject = stream;
    }

    // 3. Await loadedmetadata event (with 2500ms fallback)
    await new Promise<void>((resolve) => {
      if (video.readyState >= 1) {
        resolve();
        return;
      }
      let resolved = false;
      const handleMetadata = () => {
        if (!resolved) {
          resolved = true;
          video.removeEventListener('loadedmetadata', handleMetadata);
          resolve();
        }
      };
      video.addEventListener('loadedmetadata', handleMetadata, { once: true });
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          video.removeEventListener('loadedmetadata', handleMetadata);
          resolve();
        }
      }, 2500);
    });

    // 4. Await video.play() and catch rejection safely
    try {
      const playPromise = video.play();
      if (playPromise !== undefined) {
        await playPromise;
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        console.warn('[CameraHelper] video.play() rejected:', err);
      }
    }

    // 5. Check videoWidth after 3000ms
    const checkTimeout = options?.checkTimeoutMs ?? 3000;
    setTimeout(() => {
      if (video.srcObject === stream) {
        if (video.videoWidth === 0 || video.videoHeight === 0) {
          console.error(
            `[CameraHelper] Camera is on but videoWidth is 0 after ${checkTimeout}ms. readyState: ${video.readyState}, networkState: ${video.networkState}`
          );
          if (options?.onNoPicture) {
            options.onNoPicture(video.readyState);
          }
        }
      }
    }, checkTimeout);

    return {
      width: video.videoWidth || 0,
      height: video.videoHeight || 0,
      readyState: video.readyState,
    };
  }

  /**
   * Check if running in a secure context (HTTPS or localhost).
   */
  static isSecureContext(): boolean {
    if (typeof window === 'undefined') return false;
    return Boolean(window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');
  }

  /**
   * Request camera stream with optimal 1280x720 back-camera constraints and continuous autofocus.
   */
  static async getBackCameraStream(options?: {
    idealWidth?: number;
    idealHeight?: number;
    facingMode?: 'environment' | 'user';
  }): Promise<MediaStream> {
    if (!this.isSecureContext()) {
      const err: CameraErrorResult = {
        code: 'INSECURE_CONTEXT',
        status: 'INSECURE',
        message: 'Camera access requires a secure HTTPS connection. Please load this page over HTTPS.',
      };
      throw err;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const err: CameraErrorResult = {
        code: 'NOT_SUPPORTED',
        status: 'ERROR',
        message: 'Camera access is not supported by this browser.',
      };
      throw err;
    }

    const facing = options?.facingMode || 'environment';
    const width = options?.idealWidth || 1280;
    const height = options?.idealHeight || 720;

    // 1. Try optimal HD constraints with continuous focus
    const primaryConstraints: MediaStreamConstraints = {
      video: {
        facingMode: { ideal: facing },
        width: { ideal: width, min: 640 },
        height: { ideal: height, min: 480 },
        // Continuous autofocus where supported by Android Chrome
        ...(navigator.userAgent.includes('Android')
          ? { advanced: [{ focusMode: 'continuous' } as any] }
          : {}),
      },
      audio: false,
    };

    try {
      const stream = await navigator.mediaDevices.getUserMedia(primaryConstraints);
      this.registerStream(stream);
      return stream;
    } catch (primaryErr: any) {
      console.warn('Primary 720p camera constraints failed, attempting fallback:', primaryErr?.name || primaryErr);

      // 2. Fallback to minimal constraints if specific resolution was rejected
      try {
        const fallbackConstraints: MediaStreamConstraints = {
          video: { facingMode: facing },
          audio: false,
        };
        const stream = await navigator.mediaDevices.getUserMedia(fallbackConstraints);
        this.registerStream(stream);
        return stream;
      } catch (fallbackErr: any) {
        throw this.parseCameraError(fallbackErr);
      }
    }
  }

  /**
   * Parse browser DOMExceptions into friendly actionable messages.
   */
  static parseCameraError(err: any): CameraErrorResult {
    const name = err?.name || '';
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      return {
        code: 'PERMISSION_DENIED',
        status: 'BLOCKED',
        message: 'Camera permission denied. Please allow camera access in your browser or device settings.',
        originalError: err,
      };
    }
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      return {
        code: 'NOT_FOUND',
        status: 'NOT_FOUND',
        message: 'No camera found on this device.',
        originalError: err,
      };
    }
    if (name === 'NotReadableError' || name === 'TrackStartError') {
      return {
        code: 'IN_USE',
        status: 'IN_USE',
        message: 'Camera is in use by another app or browser tab. Please close other camera apps and refresh.',
        originalError: err,
      };
    }
    if (name === 'SecurityError') {
      return {
        code: 'INSECURE_CONTEXT',
        status: 'INSECURE',
        message: 'Camera access blocked due to insecure context (HTTPS required).',
        originalError: err,
      };
    }
    return {
      code: 'UNKNOWN',
      status: 'ERROR',
      message: err?.message || 'Unable to access camera. Please check device permissions.',
      originalError: err,
    };
  }

  /**
   * Stop all active video and audio tracks in a stream.
   */
  static stopStream(stream: MediaStream | null | undefined): void {
    if (!stream) return;
    this.activeStreams.delete(stream);
    try {
      stream.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {}
      });
    } catch (e) {
      console.warn('Error stopping stream tracks:', e);
    }
  }

  /**
   * Check if torch / flashlight is supported on the active video track.
   */
  static isTorchSupported(stream: MediaStream | null): boolean {
    if (!stream) return false;
    const track = stream.getVideoTracks()[0];
    if (!track || !track.getCapabilities) return false;
    const caps = track.getCapabilities() as any;
    return Boolean(caps && caps.torch);
  }

  /**
   * Toggle hardware torch / flashlight.
   */
  static async setTorch(stream: MediaStream | null, enabled: boolean): Promise<boolean> {
    if (!stream) return false;
    const track = stream.getVideoTracks()[0];
    if (!track) return false;
    try {
      const caps = (track.getCapabilities ? track.getCapabilities() : {}) as any;
      if (caps.torch) {
        await (track as any).applyConstraints({
          advanced: [{ torch: enabled }],
        });
        return true;
      }
    } catch (e) {
      console.warn('Failed to set torch constraint:', e);
    }
    return false;
  }

  /**
   * Get zoom capability range if supported.
   */
  static getZoomCapabilities(stream: MediaStream | null): { min: number; max: number; step: number; current: number } | null {
    if (!stream) return null;
    const track = stream.getVideoTracks()[0];
    if (!track || !track.getCapabilities) return null;
    const caps = track.getCapabilities() as any;
    const settings = track.getSettings ? (track.getSettings() as any) : {};
    if (caps && caps.zoom) {
      return {
        min: caps.zoom.min || 1,
        max: caps.zoom.max || 5,
        step: caps.zoom.step || 0.1,
        current: settings.zoom || 1,
      };
    }
    return null;
  }

  /**
   * Set digital or optical zoom level.
   */
  static async setZoom(stream: MediaStream | null, zoom: number): Promise<boolean> {
    if (!stream) return false;
    const track = stream.getVideoTracks()[0];
    if (!track) return false;
    try {
      await (track as any).applyConstraints({
        advanced: [{ zoom }],
      });
      return true;
    } catch (e) {
      console.warn('Failed to apply zoom constraint:', e);
      return false;
    }
  }

  /**
   * Trigger tap-to-focus on camera track.
   */
  static async triggerFocus(stream: MediaStream | null): Promise<void> {
    if (!stream) return;
    const track = stream.getVideoTracks()[0];
    if (!track) return;
    try {
      const caps = (track.getCapabilities ? track.getCapabilities() : {}) as any;
      if (caps && caps.focusMode && caps.focusMode.includes('continuous')) {
        await (track as any).applyConstraints({
          advanced: [{ focusMode: 'continuous' }],
        });
      }
    } catch {}
  }
}
