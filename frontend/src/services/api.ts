import { CartSession, Product, ReceiptData, CartFleetItem, AdminAlert, ReviewCase } from '../types';

const API_BASE = 'http://localhost:8000/api/v1';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
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
  // Shopper Mobile Endpoints
  async pairCart(qrToken: string, phone?: string): Promise<CartSession> {
    return request<CartSession>('/shopper/pair', {
      method: 'POST',
      body: JSON.stringify({ qr_token: qrToken, customer_phone: phone }),
    });
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
    return request<{ status: string; receipt_number: string; exit_gate_token: string; amount_paid: number }>(
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

  async verifyExitGate(exitToken: string) {
    return request<{
      valid: boolean;
      gate_unlocked: boolean;
      receipt_number?: string;
      cart_number?: string;
      amount_paid?: number;
      item_count?: number;
      message: string;
    }>('/shopper/verify-exit-gate', {
      method: 'POST',
      body: JSON.stringify({ exit_token: exitToken }),
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

  async registerCart(cartNumber: string): Promise<CartFleetItem> {
    return request<CartFleetItem>('/admin/carts', {
      method: 'POST',
      body: JSON.stringify({ cart_number: cartNumber }),
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
