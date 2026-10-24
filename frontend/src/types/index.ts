export type ItemStatus = 'PENDING' | 'VERIFIED' | 'WARNING_MISMATCH' | 'WARNING_UNSCANNED' | 'REMOVED' | 'REMOVING' | 'REMOVED_PENDING_RESCAN';

export interface CartItem {
  id: string;
  product_id: string;
  product_name: string;
  product_barcode: string;
  product_image_url?: string;
  brand: string;
  category: string;
  quantity: number;
  unit_price: number;
  status: ItemStatus;
  scanned_at: string;
  verified_at?: string;
  confidence_score?: number;
  verification_evidence_url?: string;
}

export interface ActiveWarning {
  type: 'UNSCANNED_ITEM' | 'MISMATCH_ITEM' | 'REMOVAL_WITHOUT_RESCAN' | 'ITEM_REMOVING' | 'REMOVED_PENDING_RESCAN';
  message: string;
  target_barcode?: string;
  action_required: string;
  item_id?: string;
  product_name?: string;
}

export interface CartSession {
  id: string;
  cart_id: string;
  cart_number: string;
  camera_status?: 'ONLINE' | 'OFFLINE';
  status: 'ACTIVE' | 'COMPLETED' | 'ABANDONED';
  started_at: string;
  subtotal_amount: number;
  total_tax: number;
  total_discount: number;
  total_amount: number;
  item_count: number;
  items: CartItem[];
  active_warnings: ActiveWarning[];
  can_checkout: boolean;
}

export interface Product {
  id: string;
  barcode: string;
  name: string;
  brand: string;
  category: string;
  price: number;
  discount_price?: number;
  weight_grams: number;
  tax_rate: number;
  stock_quantity: number;
  primary_image_url?: string;
  is_active: boolean;
  has_embeddings: boolean;
}

export interface ReceiptItem {
  name: string;
  quantity: number;
  unit_price: number;
  total_price: number;
}

export interface ReceiptData {
  id: string;
  receipt_number: string;
  session_id: string;
  cart_number: string;
  customer_phone?: string;
  payment_method: string;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total_paid: number;
  items: ReceiptItem[];
  timestamp: string;
  store_name: string;
  store_tax_id: string;
}

export interface CartFleetItem {
  id: string;
  cart_number: string;
  qr_code_token: string;
  is_enabled: boolean;
  signed_connect_url?: string;
  status: 'IDLE' | 'ACTIVE' | 'ALERT' | 'MAINTENANCE';
  battery_level: number;
  camera_status: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  last_heartbeat: string;
  active_session_id?: string;
  item_count: number;
  total_amount: number;
}

export interface CartRegistrationResult extends CartFleetItem {
  device_token: string;
  security_notice: string;
}


export interface AdminAlert {
  id: string;
  cart_id: string;
  cart_number: string;
  session_id?: string;
  alert_type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  message: string;
  evidence_snapshot_url?: string;
  status: 'OPEN' | 'RESOLVED' | 'DISMISSED';
  created_at: string;
}

export interface ReviewCase {
  id: string;
  alert_id: string;
  cart_id: string;
  cart_number: string;
  scanned_barcode?: string;
  scanned_product_name?: string;
  scanned_product_image?: string;
  predicted_product_id?: string;
  predicted_product_name?: string;
  confidence: number;
  evidence_image_url: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  created_at: string;
}
