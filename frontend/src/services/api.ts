import { CartSession, CartItem, Product, ReceiptData, CartFleetItem, CartRegistrationResult, AdminAlert, ReviewCase } from '../types';

export function getApiBaseUrl(): string {
  // Read ONLY from build-time Vite environment variable
  const envApi = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.NEXT_PUBLIC_API_URL;
  if (envApi && typeof envApi === 'string' && envApi.trim()) {
    const raw = envApi.trim().replace(/\/+$/, '');
    return raw.endsWith('/api/v1') ? raw : `${raw}/api/v1`;
  }

  // Local development fallback only
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  if (host === 'localhost' || host === '127.0.0.1') {
    return 'http://localhost:8000/api/v1';
  }

  // In deployed environment, NEVER fall back to same-origin silently.
  throw new Error(
    'CONFIGURATION ERROR: VITE_API_URL environment variable was not provided at build time. ' +
    'Please set VITE_API_URL in your hosting platform (Vercel) to your Render backend URL.'
  );
}

export function getWsBaseUrl(): string {
  const envApi = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.NEXT_PUBLIC_API_URL;
  if (envApi && typeof envApi === 'string' && envApi.trim()) {
    const wsProto = envApi.trim().startsWith('https') ? 'wss' : 'ws';
    const cleanHost = envApi.trim().replace(/^https?:\/\//, '').replace(/\/+$/, '').replace(/\/api\/v1$/, '');
    return `${wsProto}://${cleanHost}`;
  }

  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  if (host === 'localhost' || host === '127.0.0.1') {
    return 'ws://localhost:8000';
  }

  throw new Error(
    'CONFIGURATION ERROR: WebSocket backend URL cannot be determined because VITE_API_URL is missing.'
  );
}

export interface FriendlyApiError extends Error {
  isWakingUp?: boolean;
  isNetworkOffline?: boolean;
  statusCode?: number;
}

async function request<T>(endpoint: string, options: RequestInit = {}, retries = 3): Promise<T> {
  const isFullUrl = endpoint.startsWith('http://') || endpoint.startsWith('https://');
  const baseUrl = getApiBaseUrl();
  const url = isFullUrl
    ? endpoint
    : endpoint.startsWith('/health')
    ? `${baseUrl.replace(/\/api\/v1$/, '')}/health`
    : `${baseUrl}${endpoint}`;

  const adminToken = typeof window !== 'undefined' ? localStorage.getItem('smartcart_admin_token') : null;
  const sessionToken = typeof window !== 'undefined' ? localStorage.getItem('smartcart_session_token') : null;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(adminToken ? { 'Authorization': `Bearer ${adminToken}` } : {}),
    ...(sessionToken ? { 'X-Session-Token': sessionToken } : {}),
    ...(options.headers as Record<string, string> || {}),
  };

  let lastError: any = null;

  for (let attempt = 1; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s timeout

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        let errorDetail = '';
        try {
          const errorBody = await response.json();
          if (typeof errorBody.detail === 'string') {
            errorDetail = errorBody.detail;
          } else if (Array.isArray(errorBody.detail)) {
            errorDetail = errorBody.detail.map((d: any) => d.msg || d.detail || JSON.stringify(d)).join(', ');
          } else if (errorBody.message) {
            errorDetail = errorBody.message;
          }
        } catch {}

        // Developer logging: log status and endpoint path to console only (no backend URL shown to user)
        console.error(`[SmartCart API] HTTP ${response.status} on endpoint: ${endpoint}`, {
          status: response.status,
          endpoint,
          detail: errorDetail || '(none)',
        });

        // 1. HTTP 401: Unauthorized / Session expired -> Send admin to login
        if (response.status === 401) {
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('smartcart:session-expired'));
          }
          const err: FriendlyApiError = new Error('Session expired');
          err.statusCode = 401;
          err.isWakingUp = false;
          throw err;
        }

        // 2. HTTP 500: Internal server error (never say server is waking up)
        if (response.status === 500) {
          const err: FriendlyApiError = new Error('Something went wrong on our side. Please try again.');
          err.statusCode = 500;
          err.isWakingUp = false;
          throw err;
        }

        // 3. Genuine wake-up situations on Render free tier (502, 503, 504)
        if ([502, 503, 504].includes(response.status)) {
          if (attempt < retries) {
            console.warn(`[SmartCart API] Server waking up (${response.status}) on ${endpoint}, retrying ${attempt}/${retries}...`);
            await new Promise((r) => setTimeout(r, attempt * 1500));
            continue;
          }
          const wakeErr: FriendlyApiError = new Error('Starting the cart server, this can take up to a minute... Please tap Retry.');
          wakeErr.statusCode = response.status;
          wakeErr.isWakingUp = true;
          throw wakeErr;
        }

        // 4. User-facing client/auth error: sanitize any backend URLs
        const cleanMsg = (errorDetail || `Request failed (HTTP ${response.status})`).replace(/https?:\/\/[^\s'"]+/g, 'server');
        const err: FriendlyApiError = new Error(cleanMsg);
        err.statusCode = response.status;
        err.isWakingUp = false;
        throw err;
      }

      const responseTimeHeader = response.headers.get('X-Response-Time-Ms');
      const dbQueriesHeader = response.headers.get('X-DB-Queries');

      const data = await response.json();
      if (data && typeof data === 'object') {
        if (responseTimeHeader !== null && (data as any)._response_time_ms === undefined) {
          (data as any)._response_time_ms = parseFloat(responseTimeHeader);
        }
        if (dbQueriesHeader !== null && (data as any)._db_queries === undefined) {
          (data as any)._db_queries = parseInt(dbQueriesHeader, 10);
        }
      }
      return data;
    } catch (err: any) {
      clearTimeout(timeoutId);
      lastError = err;

      // Re-throw if already handled with explicit statusCode
      if (err.statusCode) {
        throw err;
      }

      // Abort / timeout error (genuine wake-up situation)
      if (err.name === 'AbortError') {
        console.error(`[SmartCart API] Request timeout on endpoint: ${endpoint}`);
        const timeoutErr: FriendlyApiError = new Error('Starting the cart server, this can take up to a minute... Please tap Retry.');
        timeoutErr.isWakingUp = true;
        throw timeoutErr;
      }

      // Transient network failure while waking up
      const isFetchFailure = err.name === 'TypeError' || err.message === 'Failed to fetch';
      if (isFetchFailure && attempt < retries) {
        console.warn(`[SmartCart API] Network attempt ${attempt}/${retries} failed on ${endpoint}, retrying in ${attempt * 1.5}s...`);
        await new Promise((r) => setTimeout(r, attempt * 1500));
        continue;
      }

      if (isFetchFailure) {
        const isOffline = typeof navigator !== 'undefined' && !navigator.onLine;
        console.error(`[SmartCart API] Network failure on endpoint: ${endpoint}`, { offline: isOffline });
        const friendlyErr: FriendlyApiError = new Error(
          isOffline
            ? 'No internet connection. Please check your network and try again.'
            : 'Starting the cart server, this can take up to a minute... Please tap Retry.'
        );
        friendlyErr.isWakingUp = !isOffline;
        friendlyErr.isNetworkOffline = isOffline;
        throw friendlyErr;
      }

      console.error(`[SmartCart API] Request error on endpoint: ${endpoint}:`, err.message);
      throw err;
    }
  }

  throw lastError || new Error('Connection failed. Please retry.');
}

export interface ScanJobResponse {
  job_id: string;
  product_id: string;
  status: 'PENDING' | 'PROCESSING' | 'ENROLLED' | 'FAILED' | 'CANCELLED';
  stage: string;
  stage_message?: string;
  done: number;
  total: number;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export const api = {
  // Staff Auth & Access Control
  async login(email: string, password: string): Promise<{ access_token: string; role: string; full_name: string; email: string }> {
    return request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  async getStaff(): Promise<any[]> {
    return request('/auth/staff');
  },

  async createStaff(data: any): Promise<any> {
    return request('/auth/staff', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getReports(): Promise<any> {
    return request('/admin/reports');
  },

  // Shopper Mobile Endpoints
  async getShopperConfig(): Promise<{ demo_mode: boolean; base_url?: string | null }> {
    return request('/shopper/config');
  },

  async pairCart(
    cartNumberOrToken: string | { cart_number?: string; qr_token?: string; signature?: string; customer_phone?: string },
    phone?: string,
    signature?: string,
    cartNumber?: string
  ): Promise<CartSession> {
    let body: any = {};
    if (typeof cartNumberOrToken === 'object') {
      body = cartNumberOrToken;
    } else {
      body = {
        cart_number: cartNumber || cartNumberOrToken,
        qr_token: cartNumberOrToken.startsWith('QR-') ? cartNumberOrToken : undefined,
        customer_phone: phone,
        signature: signature,
      };
    }
    return request<CartSession>('/shopper/pair', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  async connectViaQR(cartNumber: string, sig?: string, phone?: string): Promise<CartSession> {
    const params = new URLSearchParams({ cart: cartNumber });
    if (sig) params.append('sig', sig);
    if (phone) params.append('phone', phone);
    return request<CartSession>(`/shopper/connect?${params.toString()}`);
  },

  async getSession(sessionId: string): Promise<CartSession> {
    return request<CartSession>(`/shopper/${sessionId}`);
  },

  async scanItem(sessionId: string, barcode: string) {
    return request(`/shopper/${sessionId}/scan-item`, {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    });
  },

  async initiateItemRemove(sessionId: string, itemId: string): Promise<CartItem> {
    return request<CartItem>(`/shopper/${sessionId}/items/${itemId}/initiate-remove`, {
      method: 'POST',
    });
  },

  async verifyItemRemoval(sessionId: string, itemId: string, imageDataUrl?: string): Promise<{
    removed: boolean;
    status: string;
    message: string;
    uncertain?: boolean;
    evidence_url?: string;
  }> {
    return request(`/shopper/${sessionId}/items/${itemId}/verify-removal`, {
      method: 'POST',
      body: JSON.stringify({ image_data_url: imageDataUrl }),
    });
  },

  async cancelItemRemove(sessionId: string, itemId: string): Promise<CartItem> {
    return request<CartItem>(`/shopper/${sessionId}/items/${itemId}/cancel-remove`, {
      method: 'POST',
    });
  },

  async rescanRemove(sessionId: string, barcode: string): Promise<{ status: string; message: string; product_name?: string }> {
    return request(`/shopper/${sessionId}/rescan-remove`, {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    });
  },

  async checkout(sessionId: string, paymentMethod: string = 'UPI', upiId?: string) {
    return request<{ status: string; receipt_number: string; amount_paid: number }>(
      `/shopper/${sessionId}/checkout`,
      {
        method: 'POST',
        body: JSON.stringify({ payment_method: paymentMethod, upi_id: upiId }),
      }
    );
  },

  async getReceipt(sessionId: string): Promise<ReceiptData> {
    return request<ReceiptData>(`/shopper/${sessionId}/receipt`);
  },

  async exitSession(sessionId: string): Promise<{ status: string; message: string }> {
    return request<{ status: string; message: string }>(`/shopper/${sessionId}/end-session`, {
      method: 'POST',
    });
  },

  async checkHealth(): Promise<{
    status: string;
    model_loaded: boolean;
    database_ok: boolean;
    schema_ok: boolean;
  }> {
    return request('/health');
  },

  clearAllCaches(): void {
    if (typeof sessionStorage !== 'undefined') {
      try {
        sessionStorage.clear();
      } catch {}
    }
  },

  async getSystemHealth(fresh: boolean = false): Promise<{
    status: string;
    model_loaded: boolean;
    database_ok: boolean;
    schema_ok: boolean;
    current_revision?: string | null;
    head_revision?: string | null;
    migration_error?: string | null;
    model_name?: string;
    vector_dimension?: number;
    storage_ok?: boolean;
    storage_type?: string;
    total_products?: number;
    vectors_count?: number;
    products_enrolled?: number;
    embed_ms_last?: number | null;
    embed_ms_avg?: number | null;
    memory_rss_mb?: number;
    ram_budget_mb?: number;
    scan_worker_metrics?: {
      download_storage_ms_total?: number;
      download_storage_ms_avg?: number;
      background_removal_ms_total?: number;
      background_removal_ms_avg?: number;
      crop_resize_ms_total?: number;
      crop_resize_ms_avg?: number;
      embedding_ms_total?: number;
      embedding_ms_avg?: number;
      database_save_ms_total?: number;
      total_duration_ms?: number;
      frames_processed?: number;
      last_job_id?: string | null;
      last_job_status?: string | null;
      updated_at?: string | null;
    };
    demo_mode?: boolean;
    use_mock?: boolean;
    _response_time_ms?: number;
    _db_queries?: number;
  }> {
    return request(`/admin/system-health${fresh ? '?fresh=true' : ''}`);
  },

  // Products Master
  async getProducts(search?: string, category?: string): Promise<Product[]> {
    const params = new URLSearchParams();
    if (search) params.append('search', search);
    if (category) params.append('category', category);
    return request<Product[]>(`/products?${params.toString()}`);
  },

  async createProduct(data: Partial<Product>): Promise<Product> {
    return request<Product>('/products', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateProduct(productId: string, data: Partial<Product>): Promise<Product> {
    return request<Product>(`/products/${productId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async deleteProduct(productId: string) {
    return request<{ status: string; message: string; product_id: string; product_name: string }>(
      `/products/${productId}`,
      { method: 'DELETE' }
    );
  },

  async restoreProduct(productId: string) {
    return request<{ status: string; message: string }>(`/products/${productId}/restore`, {
      method: 'POST',
    });
  },

  async bulkDeleteProducts(productIds: string[]) {
    return request<{ status: string; message: string; deleted_count: number; deleted_names: string[] }>(
      '/products/bulk-delete',
      {
        method: 'POST',
        body: JSON.stringify({ product_ids: productIds }),
      }
    );
  },

  async bulkUploadCSV(file: File): Promise<{ success_count: number; error_count: number; errors: string[] }> {
    const formData = new FormData();
    formData.append('file', file);
    return request('/products/bulk-upload', {
      method: 'POST',
      body: formData,
    });
  },

  // Admin Fleet & Incident Management
  async getAdminOverview() {
    return request<{
      active_carts: number;
      total_carts: number;
      revenue_today: number;
      open_incidents: number;
      ai_accuracy: number;
      recent_alerts: any[];
    }>('/admin/overview');
  },

  async getAdminCarts(): Promise<CartFleetItem[]> {
    return request<CartFleetItem[]>('/admin/carts');
  },

  async registerCart(cartNumber: string): Promise<CartRegistrationResult> {
    return request<CartRegistrationResult>('/admin/carts', {
      method: 'POST',
      body: JSON.stringify({ cart_number: cartNumber }),
    });
  },

  async regenerateCartQR(cartId: string): Promise<CartFleetItem> {
    return request<CartFleetItem>(`/admin/carts/${cartId}/regenerate-qr`, {
      method: 'POST',
    });
  },

  async regenerateDeviceToken(cartId: string): Promise<CartRegistrationResult> {
    return request<CartRegistrationResult>(`/admin/carts/${cartId}/regenerate-token`, {
      method: 'POST',
    });
  },

  async toggleCartStatus(cartId: string): Promise<CartFleetItem> {
    return request<CartFleetItem>(`/admin/carts/${cartId}/toggle-status`, {
      method: 'POST',
    });
  },

  async resetCartSession(cartId: string): Promise<{ status: string; message: string }> {
    return request<{ status: string; message: string }>(`/admin/carts/${cartId}/reset-session`, {
      method: 'POST',
    });
  },

  async updateCart(cartId: string, updates: Partial<{ cart_number: string; status: string; is_enabled: boolean; battery_level: number; camera_status: string }>): Promise<CartFleetItem> {
    return request<CartFleetItem>(`/admin/carts/${cartId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  },

  async getAdminAlerts(status?: string): Promise<AdminAlert[]> {
    const q = status ? `?status=${status}` : '';
    return request<AdminAlert[]>(`/admin/alerts${q}`);
  },

  async resolveAlert(alertId: string, notes: string, action: string = 'RESOLVED'): Promise<AdminAlert> {
    return request<AdminAlert>(`/admin/alerts/${alertId}`, {
      method: 'PATCH',
      body: JSON.stringify({ resolution_notes: notes, action }),
    });
  },

  async forceRemoveFromAlert(alertId: string, reason: string, cartItemId?: string, barcode?: string) {
    return request<{
      status: string;
      message: string;
      product_name: string;
      new_subtotal: number;
      new_total: number;
    }>(`/admin/alerts/${alertId}/force-remove`, {
      method: 'POST',
      body: JSON.stringify({ reason, cart_item_id: cartItemId, barcode }),
    });
  },

  async forceRemoveSessionItem(sessionId: string, itemId: string, reason: string) {
    return request<{
      status: string;
      message: string;
      product_name: string;
      new_subtotal: number;
      new_total: number;
    }>(`/admin/sessions/${sessionId}/items/${itemId}/force-remove`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },

  async getAdminSessionItems(sessionId: string) {
    return request<{
      session_id: string;
      cart_id: string;
      status: string;
      item_count: number;
      subtotal_amount: number;
      total_amount: number;
      items: CartItem[];
    }>(`/admin/sessions/${sessionId}/items`);
  },


  async getReviewQueue(): Promise<ReviewCase[]> {
    return request<ReviewCase[]>('/admin/review-queue');
  },

  async submitReviewDecision(caseId: string, decision: 'APPROVE' | 'REJECT', notes?: string) {
    return request(`/admin/review-queue/${caseId}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes, save_for_training: true }),
    });
  },

  async getModels() {
    return request<any[]>('/admin/models');
  },

  async getModelHealth(): Promise<{
    status: string;
    model_name: string;
    model_version: string;
    vector_dimension: number;
    enrolled_products_count: number;
    total_vectors_count: number;
    last_enrollment_time: string | null;
    offline_cached: boolean;
    confidence_high: number;
    confidence_low: number;
  }> {
    return request('/admin/model-health');
  },

  async updateModelThresholds(confidenceHigh: number, confidenceLow: number) {
    return request('/admin/model-thresholds', {
      method: 'POST',
      body: JSON.stringify({
        confidence_high: confidenceHigh,
        confidence_low: confidenceLow,
      }),
    });
  },

  async activateModel(modelId: string) {
    return request(`/admin/models/${modelId}/activate`, { method: 'POST' });
  },

  // Vision Simulator & 360 Scan
  async simulateAction(payload: {
    cart_id: string;
    action_type: 'PLACE_CORRECT' | 'PLACE_WRONG' | 'PLACE_UNSCANNED' | 'REMOVE_ITEM';
    barcode?: string;
    detected_barcode?: string;
    confidence?: number;
    evidence_url?: string;
  }) {
    return request<{ status: string; event: string; item_name?: string; detected_as?: string }>(
      '/vision/simulate-action',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  },

  async init360ScanUpload(productId: string, files: { angle_tag: string; filename: string; poor_crop?: boolean }[]) {
    return request<{
      job_id: string;
      product_id: string;
      direct_upload: boolean;
      upload_items: {
        angle_tag: string;
        filename: string;
        upload_url: string;
        frame_ref: string;
        poor_crop: boolean;
      }[];
    }>(`/vision/products/${productId}/360-scan/init-upload`, {
      method: 'POST',
      body: JSON.stringify({ files }),
    });
  },

  async complete360Scan(
    productId: string,
    payload:
      | { angle_tag: string; image_data_url: string; original_image_data_url?: string; poor_crop?: boolean }[]
      | {
          job_id?: string;
          frames?: { angle_tag: string; frame_ref: string; poor_crop?: boolean }[];
          captures?: { angle_tag: string; image_data_url: string; original_image_data_url?: string; poor_crop?: boolean }[];
        }
  ) {
    const body = Array.isArray(payload) ? { captures: payload } : payload;
    return request<ScanJobResponse>(
      `/vision/products/${productId}/360-scan/complete`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      }
    );
  },

  async getScanJob(jobId: string) {
    return request<ScanJobResponse>(`/vision/jobs/${jobId}`, {
      method: 'GET',
    });
  },

  async retryScanJob(jobId: string, payload?: { confirm_partial?: boolean }) {
    return request<{
      status: string;
      job_id?: string;
      message: string;
      requires_confirmation?: boolean;
      surviving_count?: number;
      total_count?: number;
      missing_angles?: string[];
    }>(
      `/vision/jobs/${jobId}/retry`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
      }
    );
  },

  async cancelScanJob(jobId: string) {
    return request<{ status: string; job_id: string; message: string }>(
      `/vision/jobs/${jobId}/cancel`,
      {
        method: 'POST',
      }
    );
  },

  async deleteScanJob(jobId: string) {
    return request<{ status: string; job_id: string; message: string }>(
      `/vision/jobs/${jobId}`,
      {
        method: 'DELETE',
      }
    );
  },

  async getProductActiveJob(productId: string) {
    return request<{ has_active_job: boolean; job: ScanJobResponse | null }>(
      `/vision/products/${productId}/active-job`,
      {
        method: 'GET',
      }
    );
  },

  async previewTest(imageDataUrl: string, targetBarcode?: string) {
    return request<{
      matched: boolean;
      confidence: number;
      product_name?: string;
      barcode?: string;
      target_barcode?: string;
      target_confidence?: number;
      threshold_high?: number;
      top_matches?: Array<{
        product_id: string;
        product_name: string;
        barcode: string;
        similarity: number;
        matched_angle: string;
        image_path?: string;
      }>;
      message: string;
    }>('/vision/products/preview-test', {
      method: 'POST',
      body: JSON.stringify({ image_data_url: imageDataUrl, target_barcode: targetBarcode }),
    });
  },
};
