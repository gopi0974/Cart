/**
 * Shared Camera & MediaStream Helper (Task 2)
 * -------------------------------------------
 * Provides robust cross-platform webcam / back camera access for Android Chrome and iPhone Safari.
 * Enforces HTTPS security checks, graceful constraint fallbacks, torch/zoom capabilities, and track cleanup.
 */

export interface CameraErrorResult {
  code: 'INSECURE_CONTEXT' | 'PERMISSION_DENIED' | 'NOT_FOUND' | 'IN_USE' | 'NOT_SUPPORTED' | 'UNKNOWN';
  message: string;
  originalError?: any;
}

export class CameraHelper {
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
        message: 'Camera access requires a secure HTTPS connection. Please load this page over HTTPS.',
      };
      throw err;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const err: CameraErrorResult = {
        code: 'NOT_SUPPORTED',
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
      return await navigator.mediaDevices.getUserMedia(primaryConstraints);
    } catch (primaryErr: any) {
      console.warn('Primary 720p camera constraints failed, attempting fallback:', primaryErr?.name || primaryErr);

      // 2. Fallback to minimal constraints if specific resolution was rejected
      try {
        const fallbackConstraints: MediaStreamConstraints = {
          video: { facingMode: facing },
          audio: false,
        };
        return await navigator.mediaDevices.getUserMedia(fallbackConstraints);
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
        message: 'Camera permission denied. Please allow camera access in your browser or device settings.',
        originalError: err,
      };
    }
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      return {
        code: 'NOT_FOUND',
        message: 'No camera found on this device.',
        originalError: err,
      };
    }
    if (name === 'NotReadableError' || name === 'TrackStartError') {
      return {
        code: 'IN_USE',
        message: 'Camera is in use by another app or browser tab. Please close other camera apps and refresh.',
        originalError: err,
      };
    }
    if (name === 'SecurityError') {
      return {
        code: 'INSECURE_CONTEXT',
        message: 'Camera access blocked due to insecure context (HTTPS required).',
        originalError: err,
      };
    }
    return {
      code: 'UNKNOWN',
      message: err?.message || 'Unable to access camera. Please check device permissions.',
      originalError: err,
    };
  }

  /**
   * Stop all active video and audio tracks in a stream.
   */
  static stopStream(stream: MediaStream | null | undefined): void {
    if (!stream) return;
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
