import { CartSession, Product, ReceiptData, CartFleetItem, CartRegistrationResult, AdminAlert, ReviewCase } from '../types';

export function getApiBaseUrl(): string {
  if ((import.meta as any).env?.VITE_API_URL) {
    const raw = (import.meta as any).env.VITE_API_URL.replace(/\/+$/, '');
    return raw.endsWith('/api/v1') ? raw : `${raw}/api/v1`;
  }
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const proto = isHttps ? 'https' : 'http';
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  return `${proto}://${host}:8000/api/v1`;
}

export function getWsBaseUrl(): string {
  const envApi = (import.meta as any).env?.VITE_API_URL;
  if (envApi) {
    const wsProto = envApi.startsWith('https') ? 'wss' : 'ws';
    const cleanHost = envApi.replace(/^https?:\/\//, '').replace(/\/+$/, '');
    return `${wsProto}://${cleanHost}`;
  }
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const proto = isHttps ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  return `${proto}://${host}:8000`;
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${getApiBaseUrl()}${endpoint}`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('smartcart_admin_token') : null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string> || {}),
  };

  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(errorBody.detail || 'Network request failed');
  }
  return response.json();
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

  async rescanRemove(sessionId: string, barcode: string) {
    return request(`/shopper/${sessionId}/rescan-remove`, {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    });
  },

  async applyCoupon(sessionId: string, couponCode: string) {
    return request<{ status: string; coupon_code: string; discount_amount: number; new_total: number; description: string }>(
      `/shopper/${sessionId}/apply-coupon`,
      {
        method: 'POST',
        body: JSON.stringify({ coupon_code: couponCode }),
      }
    );
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
    return request<{ status: string; message: string }>(`/shopper/${sessionId}/exit`, {
      method: 'POST',
    });
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

  async deleteProduct(productId: string) {
    return request(`/products/${productId}`, { method: 'DELETE' });
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
    return request<{ matched: boolean; confidence: number; product_name?: string; message: string }>(
      '/vision/products/preview-test',
      {
        method: 'POST',
        body: JSON.stringify({ image_data_url: imageDataUrl, target_barcode: targetBarcode }),
      }
    );
  },
};
