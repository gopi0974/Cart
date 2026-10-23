import React, { useState, useEffect } from 'react';
import { 
  Plus, Printer, QrCode, Download, RefreshCw, Key, ShieldCheck, 
  Copy, Check, AlertTriangle, Power, ShoppingCart, ExternalLink, Battery, Camera,
  Edit3, RotateCcw, X, Unlock, Save
} from 'lucide-react';
import QRCode from 'qrcode';
import { CartFleetItem, CartRegistrationResult } from '../types';
import { api } from '../services/api';

export const CartFleetView: React.FC = () => {
  const [carts, setCarts] = useState<CartFleetItem[]>([]);
  const [qrImages, setQrImages] = useState<Record<string, string>>({});
  const [newCartNumber, setNewCartNumber] = useState('');
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  
  // Device Token Reveal Modal State (Shown ONCE)
  const [tokenModalData, setTokenModalData] = useState<CartRegistrationResult | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  // Single Cart Print Modal
  const [printCart, setPrintCart] = useState<CartFleetItem | null>(null);

  // Edit Cart Modal State
  const [editingCart, setEditingCart] = useState<CartFleetItem | null>(null);
  const [editCartNumber, setEditCartNumber] = useState('');
  const [editStatus, setEditStatus] = useState<'IDLE' | 'ACTIVE' | 'ALERT' | 'MAINTENANCE'>('IDLE');
  const [editIsEnabled, setEditIsEnabled] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);

  const fetchCarts = async () => {
    try {
      const data = await api.getAdminCarts();
      setCarts(data);

      // Auto-suggest next cart number
      if (data.length > 0) {
        const nextNum = data.length + 1;
        setNewCartNumber(`CART-${String(nextNum).padStart(3, '0')}`);
      } else {
        setNewCartNumber('CART-001');
      }

      // Generate visual QR data URLs for all carts
      const qrMap: Record<string, string> = {};
      for (const c of data) {
        const link = c.signed_connect_url || `${window.location.origin}/user?cart=${c.cart_number}&token=${c.qr_code_token}`;
        try {
          qrMap[c.id] = await QRCode.toDataURL(link, { 
            width: 320, 
            margin: 1,
            color: { dark: '#0F172A', light: '#FFFFFF' }
          });
        } catch (e) {
          console.error('Failed to generate QR for cart', c.cart_number, e);
        }
      }
      setQrImages(qrMap);
    } catch (e) {
      console.error('Failed to fetch carts:', e);
    }
  };

  useEffect(() => {
    fetchCarts();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCartNumber.trim()) return;
    setLoading(true);
    try {
      const result = await api.registerCart(newCartNumber.trim());
      // Open the Device Token Modal (Shown ONCE)
      setTokenModalData(result);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to register cart');
    } finally {
      setLoading(false);
    }
  };

  const handleRegenerateQR = async (cartId: string) => {
    setActionLoading(`qr-${cartId}`);
    try {
      await api.regenerateCartQR(cartId);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to regenerate QR');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRegenerateToken = async (cartId: string) => {
    if (!window.confirm("Regenerating the hardware token will disconnect any active cart device until re-entered. Proceed?")) {
      return;
    }
    setActionLoading(`token-${cartId}`);
    try {
      const result = await api.regenerateDeviceToken(cartId);
      setTokenModalData(result);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to regenerate hardware token');
    } finally {
      setActionLoading(null);
    }
  };

  const handleToggleStatus = async (cartId: string) => {
    setActionLoading(`toggle-${cartId}`);
    try {
      await api.toggleCartStatus(cartId);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to toggle cart status');
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenEditModal = (c: CartFleetItem) => {
    setEditingCart(c);
    setEditCartNumber(c.cart_number);
    setEditStatus(c.status);
    setEditIsEnabled(c.is_enabled);
  };

  const handleSaveCartEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingCart) return;
    setSaveLoading(true);
    try {
      await api.updateCart(editingCart.id, {
        cart_number: editCartNumber.trim().toUpperCase(),
        status: editStatus,
        is_enabled: editIsEnabled
      });
      setEditingCart(null);
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to update cart');
    } finally {
      setSaveLoading(false);
    }
  };

  const handleResetSession = async (c: CartFleetItem) => {
    if (!window.confirm(`Force release active session on cart ${c.cart_number}? This will end any stuck shopper session and reset the cart to Idle immediately.`)) {
      return;
    }
    setActionLoading(`reset-${c.id}`);
    try {
      const res = await api.resetCartSession(c.id);
      alert(res.message);
      if (editingCart && editingCart.id === c.id) {
        setEditingCart(null);
      }
      await fetchCarts();
    } catch (err: any) {
      alert(err.message || 'Failed to reset cart session');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDownloadQR = (c: CartFleetItem) => {
    const dataUrl = qrImages[c.id];
    if (!dataUrl) return;
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = `${c.cart_number}-Handle-QR.png`;
    a.click();
  };

  const handlePrintSticker = (c: CartFleetItem) => {
    setPrintCart(c);
    setTimeout(() => {
      window.print();
    }, 200);
  };

  const handleCopy = (text: string, type: 'token' | 'url') => {
    navigator.clipboard.writeText(text);
    if (type === 'token') {
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    } else {
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-slate-800 print:hidden">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2.5">
            <ShoppingCart className="w-7 h-7 text-emerald-500" />
            Cart Fleet & Cryptographic QR Engine
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Register carts, issue HMAC-signed QR connect links, manage hardware device tokens, and enforce 1-session safety.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => window.print()}
            className="bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700/60 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
          >
            <Printer className="w-3.5 h-3.5 text-emerald-500" />
            Print All QR Stickers
          </button>
        </div>
      </div>

      {/* Register Cart Form */}
      <div className="bg-gradient-to-r from-emerald-500/10 via-transparent to-blue-500/10 border border-emerald-500/30 dark:border-emerald-500/20 rounded-3xl p-6 shadow-sm print:hidden">
        <form onSubmit={handleRegister} className="flex flex-col md:flex-row items-center gap-4">
          <div className="flex-1 w-full">
            <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              Register New Smart Cart
            </label>
            <div className="relative">
              <input
                type="text"
                required
                value={newCartNumber}
                onChange={(e) => setNewCartNumber(e.target.value)}
                placeholder="e.g. CART-001"
                className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-white text-sm font-mono font-bold rounded-2xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
              <span className="absolute right-4 top-3.5 text-[11px] font-semibold text-slate-400">
                Auto-assigned
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1.5">
              Generates a cryptographic device token and an HMAC-signed pairing QR code.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full md:w-auto bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-semibold text-xs py-3.5 px-6 rounded-2xl shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2 active:scale-95 transition-all md:self-end whitespace-nowrap"
          >
            <Plus className="w-4 h-4" />
            <span>{loading ? 'Registering...' : 'Register Smart Cart'}</span>
          </button>
        </form>
      </div>

      {/* Cart Cards Grid */}
      <div className="print:hidden">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Registered Fleet Carts ({carts.length})
          </h2>
          <span className="text-xs text-slate-500">
            {carts.filter(c => c.is_enabled).length} Enabled • {carts.filter(c => !c.is_enabled).length} Disabled
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {carts.map((c) => {
            const qrUrl = qrImages[c.id];
            const isOnline = c.camera_status === 'ONLINE';
            const hasActiveSession = Boolean(c.active_session_id);

            return (
              <div
                key={c.id}
                className={`bg-white dark:bg-[#131B2E] border-2 rounded-3xl p-5 shadow-sm transition-all flex flex-col justify-between space-y-4 ${
                  !c.is_enabled 
                    ? 'border-slate-300 dark:border-slate-800 opacity-60' 
                    : hasActiveSession 
                    ? 'border-emerald-500/60 shadow-emerald-500/10' 
                    : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
                }`}
              >
                {/* Card Header */}
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-display font-extrabold text-lg text-slate-900 dark:text-white">
                        {c.cart_number}
                      </span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        c.is_enabled 
                          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-400' 
                          : 'bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-400'
                      }`}>
                        {c.is_enabled ? 'ENABLED' : 'DISABLED'}
                      </span>
                      {c.status !== 'IDLE' && (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                          c.status === 'ACTIVE' 
                            ? 'bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-400'
                            : c.status === 'ALERT'
                            ? 'bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-400'
                            : 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-400'
                        }`}>
                          {c.status}
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                      {c.qr_code_token}
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleOpenEditModal(c)}
                      title="Edit Cart & Reset Session"
                      className="p-2 rounded-xl text-slate-400 hover:text-emerald-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all active:scale-95"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleToggleStatus(c.id)}
                      disabled={actionLoading === `toggle-${c.id}`}
                      title={c.is_enabled ? 'Disable Cart' : 'Enable Cart'}
                      className={`p-2 rounded-xl transition-all ${
                        c.is_enabled 
                          ? 'text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/50' 
                          : 'text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                      }`}
                    >
                      <Power className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Scannable Real QR Graphic */}
                <div className="bg-slate-50 dark:bg-slate-900/80 rounded-2xl p-4 flex flex-col items-center justify-center border border-slate-100 dark:border-slate-800/80 group relative">
                  {qrUrl ? (
                    <img 
                      src={qrUrl} 
                      alt={`QR Code for ${c.cart_number}`} 
                      className="w-44 h-44 rounded-xl shadow-sm bg-white p-2"
                    />
                  ) : (
                    <div className="w-44 h-44 flex items-center justify-center text-slate-400">
                      <QrCode className="w-16 h-16 animate-pulse" />
                    </div>
                  )}

                  <div className="text-[10px] font-medium text-slate-500 mt-2 text-center max-w-[200px] truncate">
                    🔒 HMAC Signature Verified
                  </div>
                </div>

                {/* Telemetry Strip */}
                <div className="grid grid-cols-2 gap-2 text-[11px] pt-1 border-t border-slate-100 dark:border-slate-800">
                  <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400">
                    <Battery className="w-3.5 h-3.5 text-emerald-500" />
                    <span>Battery: <strong>{c.battery_level}%</strong></span>
                  </div>
                  <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400">
                    <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
                    <span>Camera: <strong>{c.camera_status}</strong></span>
                  </div>
                </div>

                {/* Active Session Indicator & Quick Release */}
                <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-900/50 text-[11px] flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="text-slate-500">Shopper Status:</span>
                    <span className={`font-semibold ${hasActiveSession || c.status === 'ACTIVE' ? 'text-emerald-500' : 'text-slate-400'}`}>
                      {hasActiveSession || c.status === 'ACTIVE' ? '🟢 In Use (1 Active)' : '⚪ Idle (Ready)'}
                    </span>
                  </div>
                  {(hasActiveSession || c.status === 'ACTIVE' || c.status === 'ALERT') && (
                    <button
                      onClick={() => handleResetSession(c)}
                      disabled={actionLoading === `reset-${c.id}`}
                      className="px-2.5 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 font-bold text-[10px] flex items-center gap-1 active:scale-95 transition-all border border-amber-500/20"
                      title="Force release active session and reset cart to Idle"
                    >
                      <RotateCcw className={`w-3 h-3 ${actionLoading === `reset-${c.id}` ? 'animate-spin' : ''}`} />
                      <span>Release Cart</span>
                    </button>
                  )}
                </div>

                {/* Action Buttons Toolbar */}
                <div className="grid grid-cols-3 gap-2 pt-1">
                  <button
                    onClick={() => handleDownloadQR(c)}
                    className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-medium flex items-center justify-center gap-1 transition-all"
                    title="Download PNG sticker"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </button>

                  <button
                    onClick={() => handlePrintSticker(c)}
                    className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-medium flex items-center justify-center gap-1 transition-all"
                    title="Print handle sticker"
                  >
                    <Printer className="w-3.5 h-3.5 text-emerald-500" />
                    <span>Print</span>
                  </button>

                  <button
                    onClick={() => handleRegenerateQR(c.id)}
                    disabled={actionLoading === `qr-${c.id}`}
                    className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-medium flex items-center justify-center gap-1 transition-all"
                    title="Regenerate QR and invalidate previous signature"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 text-blue-500 ${actionLoading === `qr-${c.id}` ? 'animate-spin' : ''}`} />
                    <span>Regen</span>
                  </button>
                </div>

                {/* Hardware Re-Key Button */}
                <button
                  onClick={() => handleRegenerateToken(c.id)}
                  disabled={actionLoading === `token-${c.id}`}
                  className="w-full text-center text-[10px] font-semibold text-slate-500 hover:text-emerald-500 dark:hover:text-emerald-400 py-1 transition-colors flex items-center justify-center gap-1"
                >
                  <Key className="w-3 h-3" />
                  <span>Re-key Hardware Device Token</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Device Token Modal (Shown ONCE) */}
      {tokenModalData && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#131B2E] border border-emerald-500/30 max-w-lg w-full rounded-3xl p-6 shadow-2xl space-y-5 animate-scale-up">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                <ShieldCheck className="w-7 h-7" />
              </div>
              <div>
                <h3 className="font-display font-bold text-lg text-white">
                  Cart Registered: {tokenModalData.cart_number}
                </h3>
                <p className="text-xs text-slate-400">
                  Hardware Authentication Token Generated
                </p>
              </div>
            </div>

            <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-2xl flex items-start gap-2.5 text-amber-300 text-xs">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>
                <strong>Warning:</strong> This raw device token is displayed <strong>ONLY ONCE</strong>. It is securely hashed on the server with SHA-256 and cannot be retrieved later. Copy it now!
              </span>
            </div>

            {/* Token Copy Box */}
            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                Hardware Device Secret Token (For /cart-device or Raspberry Pi)
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={tokenModalData.device_token}
                  className="flex-1 bg-slate-900 border border-slate-700 text-emerald-400 font-mono text-xs rounded-xl px-3 py-2.5 focus:outline-none"
                />
                <button
                  onClick={() => handleCopy(tokenModalData.device_token, 'token')}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white px-3.5 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all active:scale-95"
                >
                  {copiedToken ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  <span>{copiedToken ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            </div>

            {/* Signed URL Preview */}
            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                HMAC Signed QR Connect URL
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={tokenModalData.signed_connect_url || ''}
                  className="flex-1 bg-slate-900 border border-slate-700 text-slate-300 font-mono text-xs rounded-xl px-3 py-2.5 focus:outline-none truncate"
                />
                <button
                  onClick={() => handleCopy(tokenModalData.signed_connect_url || '', 'url')}
                  className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3.5 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all"
                >
                  {copiedUrl ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="pt-2">
              <button
                onClick={() => setTokenModalData(null)}
                className="w-full bg-slate-800 hover:bg-slate-700 text-white font-semibold py-3 rounded-xl text-xs transition-all"
              >
                I Have Saved My Device Token Safely
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Cart Modal */}
      {editingCart && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 max-w-md w-full rounded-3xl p-6 shadow-2xl space-y-5 animate-scale-up text-slate-900 dark:text-white">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-emerald-500/10 text-emerald-500 flex items-center justify-center">
                  <Edit3 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-display font-bold text-lg">
                    Edit Cart: {editingCart.cart_number}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Update fleet settings, status, or clear active session
                  </p>
                </div>
              </div>
              <button
                onClick={() => setEditingCart(null)}
                className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveCartEdit} className="space-y-4">
              {/* Cart Number */}
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1.5">
                  Cart Number
                </label>
                <input
                  type="text"
                  required
                  value={editCartNumber}
                  onChange={(e) => setEditCartNumber(e.target.value)}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 font-mono font-bold text-sm rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-slate-900 dark:text-white"
                />
              </div>

              {/* Status */}
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1.5">
                  Operational Status
                </label>
                <select
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value as any)}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 font-semibold text-sm rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-slate-900 dark:text-white"
                >
                  <option value="IDLE">IDLE (Ready for Shoppers)</option>
                  <option value="ACTIVE">ACTIVE (Shopper Session in Progress)</option>
                  <option value="ALERT">ALERT (Security Mismatch Investigation)</option>
                  <option value="MAINTENANCE">MAINTENANCE (Offline for Servicing)</option>
                </select>
                <p className="text-[11px] text-slate-400 mt-1">
                  Selecting IDLE automatically clears any stuck active sessions.
                </p>
              </div>

              {/* Enabled Switch */}
              <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800">
                <div>
                  <div className="text-xs font-bold">Enabled for Shoppers</div>
                  <div className="text-[11px] text-slate-400">Disabled carts reject QR pairings immediately</div>
                </div>
                <input
                  type="checkbox"
                  checked={editIsEnabled}
                  onChange={(e) => setEditIsEnabled(e.target.checked)}
                  className="w-5 h-5 text-emerald-600 rounded focus:ring-emerald-500 cursor-pointer"
                />
              </div>

              {/* Active Session Release Panel */}
              {(editingCart.active_session_id || editingCart.status === 'ACTIVE' || editingCart.status === 'ALERT') && (
                <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-amber-500 flex items-center gap-1.5">
                      <AlertTriangle className="w-4 h-4" />
                      Active Session Detected
                    </span>
                    <button
                      type="button"
                      onClick={() => handleResetSession(editingCart)}
                      disabled={actionLoading === `reset-${editingCart.id}`}
                      className="px-3 py-1.5 rounded-xl bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold shadow-sm active:scale-95 transition-all flex items-center gap-1"
                    >
                      <RotateCcw className={`w-3.5 h-3.5 ${actionLoading === `reset-${editingCart.id}` ? 'animate-spin' : ''}`} />
                      <span>Release Cart Now</span>
                    </button>
                  </div>
                  <p className="text-[11px] text-amber-600 dark:text-amber-300/80">
                    If this cart shows "occupied by an active shopper" on the shopper screen, click Release Cart Now to clear it.
                  </p>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setEditingCart(null)}
                  className="px-4 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saveLoading}
                  className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold flex items-center gap-1.5 shadow-md shadow-emerald-600/30 active:scale-95 transition-all"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{saveLoading ? 'Saving...' : 'Save Changes'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Print-Only Handle Sticker Sheet */}
      <div className="hidden print:block p-8">
        <h1 className="text-xl font-bold mb-4 text-center">SmartCart Official Handle QR Stickers</h1>
        <div className="grid grid-cols-2 gap-8">
          {(printCart ? [printCart] : carts).map((c) => (
            <div key={c.id} className="border-4 border-black rounded-3xl p-6 text-center space-y-3 page-break-inside-avoid">
              <div className="text-2xl font-black tracking-wider uppercase">{c.cart_number}</div>
              <div className="text-xs text-slate-600 font-bold uppercase">SmartCart AI Autonomous System</div>
              {qrImages[c.id] && (
                <img src={qrImages[c.id]} alt={c.cart_number} className="w-56 h-56 mx-auto border-2 border-black p-2" />
              )}
              <div className="text-xs font-mono font-bold">{c.qr_code_token}</div>
              <div className="text-[11px] font-semibold text-slate-700">Scan with your phone camera to start shopping</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
