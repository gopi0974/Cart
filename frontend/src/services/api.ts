import { CartSession, CartItem, Product, ReceiptData, CartFleetItem, CartRegistrationResult, AdminAlert, ReviewCase } from '../types';

export function getApiBaseUrl(): string {
  // Read ONLY from build-time Vite environment variable
  const envApi = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.NEXT_PUBLIC_API_URL;
  if (envApi && typeof envApi === 'string' && envApi.trim()) {
    const raw = envApi.trim().replace(/\/+$/, '');
    return raw.endsWith('/api/v1') ? raw : `${raw}/api/v1`;
  }

  // Same-origin or local development fallback
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const proto = isHttps ? 'https' : 'http';
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';

  if (host === 'localhost' || host === '127.0.0.1') {
    return `${proto}://${host}:8000/api/v1`;
  }
  return `${proto}://${host}/api/v1`;
}

export function getWsBaseUrl(): string {
  const envApi = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.NEXT_PUBLIC_API_URL;
  if (envApi && typeof envApi === 'string' && envApi.trim()) {
    const wsProto = envApi.trim().startsWith('https') ? 'wss' : 'ws';
    const cleanHost = envApi.trim().replace(/^https?:\/\//, '').replace(/\/+$/, '').replace(/\/api\/v1$/, '');
    return `${wsProto}://${cleanHost}`;
  }

  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const proto = isHttps ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  if (host === 'localhost' || host === '127.0.0.1') {
    return `${proto}://${host}:8000`;
  }
  return `${proto}://${host}`;
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

  const token = typeof window !== 'undefined' ? localStorage.getItem('smartcart_admin_token') : null;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
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

        // Backend waking up (Render free tier spin-up returns 502, 503, or 504)
        if ([502, 503, 504].includes(response.status) && attempt < retries) {
          console.warn(`[SmartCart API] Server waking up (${response.status}), retrying ${attempt}/${retries}...`);
          await new Promise((r) => setTimeout(r, attempt * 1500));
          continue;
        }

        const err: FriendlyApiError = new Error(
          errorDetail || (response.status === 503 ? 'Starting the cart server, this can take up to a minute...' : `Request failed (HTTP ${response.status})`)
        );
        err.statusCode = response.status;
        if (response.status === 503) {
          err.isWakingUp = true;
        }
        throw err;
      }

      return response.json();
    } catch (err: any) {
      clearTimeout(timeoutId);
      lastError = err;

      // Abort / timeout error
      if (err.name === 'AbortError') {
        const timeoutErr: FriendlyApiError = new Error('The cart server is taking longer than usual to respond. Please tap Retry.');
        timeoutErr.isWakingUp = true;
        throw timeoutErr;
      }

      // Transient network failure while waking up
      const isFetchFailure = err.name === 'TypeError' && err.message === 'Failed to fetch';
      if (isFetchFailure && attempt < retries) {
        console.warn(`[SmartCart API] Network attempt ${attempt}/${retries} failed, retrying in ${attempt * 1.5}s...`);
        await new Promise((r) => setTimeout(r, attempt * 1500));
        continue;
      }

      if (isFetchFailure) {
        const isOffline = typeof navigator !== 'undefined' && !navigator.onLine;
        const friendlyErr: FriendlyApiError = new Error(
          isOffline
            ? 'No internet connection. Please check your network and try again.'
            : 'Starting the cart server, this can take up to a minute... Please tap Retry.'
        );
        friendlyErr.isWakingUp = !isOffline;
        friendlyErr.isNetworkOffline = isOffline;
        console.error('[SmartCart API] Connection failed:', { url, originalError: err.message });
        throw friendlyErr;
      }

      throw err;
    }
  }

  throw lastError || new Error('Connection failed. Please retry.');
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
  async pairCart(qrToken: string, phone?: string, signature?: string, cartNumber?: string): Promise<CartSession> {
    return request<CartSession>('/shopper/pair', {
      method: 'POST',
      body: JSON.stringify({ 
        qr_token: qrToken, 
        customer_phone: phone,
        signature: signature,
        cart_number: cartNumber
      }),
    });
  },

  async connectViaQR(cartNumber: string, qrToken: string, sig?: string, phone?: string): Promise<CartSession> {
    const params = new URLSearchParams({ cart: cartNumber, token: qrToken });
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
    storage_ok: boolean;
    vectors_count?: number;
    products_enrolled?: number;
    embed_ms_last?: number | null;
    embed_ms_avg?: number | null;
    memory_rss_mb?: number;
  }> {
    return request('/health');
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

  async complete360Scan(productId: string, captures: { angle_tag: string; image_data_url: string }[]) {
    return request(`/vision/products/${productId}/360-scan/complete`, {
      method: 'POST',
      body: JSON.stringify({ captures }),
    });
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
