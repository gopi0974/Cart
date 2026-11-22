import React, { useState, useEffect, useMemo } from 'react';
import {
  LayoutDashboard, ShoppingCart, AlertTriangle, Layers, Camera, CheckSquare,
  QrCode, Cpu, ChevronRight, Menu, X, Eye, BarChart3, Users,
  LogOut, Sun, Moon, Activity, FlaskConical, Search, RefreshCw
} from 'lucide-react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { AdminDashboard } from './AdminDashboard';
import { LiveCartMonitor } from './LiveCartMonitor';
import { AlertFeedView } from './AlertFeedView';
import { ReviewQueueView } from './ReviewQueueView';
import { ProductCatalogView } from './ProductCatalogView';
import { Guided360ScanView } from './Guided360ScanView';
import { PreviewTestView } from './PreviewTestView';
import { RecognitionLabView } from './RecognitionLabView';
import { CartFleetView } from './CartFleetView';
import { ModelManagerView } from './ModelManagerView';
import { SystemDiagnosticsView } from './SystemDiagnosticsView';
import { ReportsView } from './ReportsView';
import { StaffRolesView } from './StaffRolesView';
import { AdminLogin } from './AdminLogin';
import { Product } from '../types';
import { api } from '../services/api';
import { wsRegistry } from '../services/wsRegistry';
import { CameraHelper } from '../services/cameraHelper';

export interface AuthUser {
  email: string;
  full_name: string;
  role: string;
}

export interface AdminNavItem {
  id: string;
  label: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
  pageTitle: string;
}

export const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { id: 'DASHBOARD', label: 'Overview', path: '/admin/overview', icon: LayoutDashboard, pageTitle: 'Operations Executive Overview' },
  { id: 'FLEET', label: 'Live Cart Monitor', path: '/admin/fleet', icon: ShoppingCart, pageTitle: 'Active Supermarket Cart Fleet' },
  { id: 'ALERTS', label: 'Incidents & Alerts', path: '/admin/alerts', icon: AlertTriangle, pageTitle: 'Real-Time Security & AI Incident Center' },
  { id: 'REVIEWS', label: 'AI Review Queue', path: '/admin/reviews', icon: CheckSquare, pageTitle: 'AI Confidence Exception Review Queue' },
  { id: 'PRODUCTS', label: 'Product Inventory', path: '/admin/products', icon: Layers, pageTitle: 'Product Catalog & Vision Registry' },
  { id: 'SCAN_360', label: '360° Vision Scan', path: '/admin/products/scan', icon: Camera, pageTitle: 'Guided 360° Vision Enrollment' },
  { id: 'PREVIEW_TEST', label: 'Recognition Preview', path: '/admin/preview-test', icon: Eye, pageTitle: 'AI Recognition Preview Test' },
  { id: 'RECOGNITION_LAB', label: 'Recognition Lab', path: '/admin/recognition-lab', icon: FlaskConical, pageTitle: 'AI Recognition Lab & Model Benchmark' },
  { id: 'MODELS', label: 'AI Models & Stats', path: '/admin/models', icon: Cpu, pageTitle: 'AI Model & Embedding Health Registry' },
  { id: 'SYSTEM', label: 'Settings & System', path: '/admin/system', icon: Activity, pageTitle: 'Backend System Diagnostics & Telemetry' },
  { id: 'REPORTS', label: 'Financial & Loss Reports', path: '/admin/reports', icon: BarChart3, pageTitle: 'Loss Prevention & Financial Telemetry Reports' },
  { id: 'CARTS_REGISTRY', label: 'Fleet & QR Sheet', path: '/admin/carts', icon: QrCode, pageTitle: 'Cart Fleet Registry & Pair QR Sheet' },
  { id: 'STAFF', label: 'Staff & Roles', path: '/admin/staff', icon: Users, pageTitle: 'Staff Directory & Role Assignments' },
];

export type AdminRouteKey =
  | 'DASHBOARD'
  | 'FLEET'
  | 'ALERTS'
  | 'REVIEWS'
  | 'PRODUCTS'
  | 'SCAN_360'
  | 'PREVIEW_TEST'
  | 'RECOGNITION_LAB'
  | 'MODELS'
  | 'SYSTEM'
  | 'REPORTS'
  | 'CARTS_REGISTRY'
  | 'STAFF'
  | 'NOT_FOUND';

export const matchAdminRoute = (pathname: string): AdminRouteKey => {
  const normalized = pathname.replace(/\/+$/, '') || '/admin';
  if (normalized === '/admin' || normalized === '/admin/overview' || normalized === '/admin/dashboard') return 'DASHBOARD';
  if (normalized === '/admin/fleet') return 'FLEET';
  if (normalized === '/admin/alerts') return 'ALERTS';
  if (normalized === '/admin/reviews') return 'REVIEWS';
  if (normalized === '/admin/products') return 'PRODUCTS';
  if (normalized === '/admin/products/scan') return 'SCAN_360';
  if (normalized === '/admin/preview-test') return 'PREVIEW_TEST';
  if (normalized === '/admin/recognition-lab') return 'RECOGNITION_LAB';
  if (normalized === '/admin/models') return 'MODELS';
  if (normalized === '/admin/system') return 'SYSTEM';
  if (normalized === '/admin/reports') return 'REPORTS';
  if (normalized === '/admin/carts') return 'CARTS_REGISTRY';
  if (normalized === '/admin/staff') return 'STAFF';
  return 'NOT_FOUND';
};

export const AdminNotFound: React.FC<{ currentPath: string; onGoOverview: () => void }> = ({
  currentPath,
  onGoOverview,
}) => {
  return (
    <div className="p-8 sm:p-12 text-center space-y-5 bg-white dark:bg-[#131B2E] rounded-3xl border border-slate-200 dark:border-slate-800 max-w-lg mx-auto mt-8 sm:mt-16 shadow-sm animate-fade-in">
      <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 text-amber-600 dark:text-amber-400 flex items-center justify-center mx-auto">
        <AlertTriangle className="w-7 h-7" />
      </div>
      <div>
        <h2 className="text-xl font-bold font-display text-slate-900 dark:text-white">
          Admin Page Not Found
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
          The requested admin route <code className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono text-slate-700 dark:text-slate-300 font-semibold">{currentPath}</code> does not exist or has moved.
        </p>
      </div>
      <div className="pt-2">
        <button
          onClick={onGoOverview}
          className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-600/20 transition-all inline-flex items-center gap-2"
        >
          <LayoutDashboard className="w-4 h-4" />
          <span>Return to Operations Overview</span>
        </button>
      </div>
    </div>
  );
};

interface ScanProductSelectorProps {
  products: Product[];
  loading: boolean;
  onSelectProduct: (product: Product) => void;
  onRefresh: () => void;
}

const ScanProductSelector: React.FC<ScanProductSelectorProps> = ({
  products,
  loading,
  onSelectProduct,
  onRefresh,
}) => {
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return products;
    return products.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.barcode && p.barcode.toLowerCase().includes(q))
    );
  }, [products, search]);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <Camera className="w-6 h-6 text-purple-600 dark:text-purple-400" />
            <span>Guided 360° Vision Enrollment Hub</span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Select a product from the catalog below to capture multi-angle packaging frames and enroll real visual embeddings.
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 transition-colors shadow-sm"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh Catalog
        </button>
      </div>

      {/* Search Input */}
      <div className="relative max-w-md">
        <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
        <input
          type="text"
          placeholder="Filter by product name or barcode..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-2 bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-xl text-xs text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:border-purple-500 shadow-sm"
        />
      </div>

      {/* Product Grid */}
      {filtered.length === 0 ? (
        <div className="p-12 text-center bg-white dark:bg-[#131B2E] rounded-3xl border border-slate-200 dark:border-slate-800 text-slate-400 text-xs">
          {products.length === 0 ? 'Loading store product catalog...' : 'No products found matching your search.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((prod) => (
            <div
              key={prod.id}
              className="p-4 bg-white dark:bg-[#131B2E] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm hover:border-purple-400 dark:hover:border-purple-700 transition-all flex flex-col justify-between gap-3"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white truncate" title={prod.name}>
                    {prod.name}
                  </h3>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold shrink-0 ${
                      prod.has_embeddings
                        ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/50'
                        : 'bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50'
                    }`}
                  >
                    {prod.has_embeddings ? 'Enrolled' : 'Pending 360'}
                  </span>
                </div>
                <div className="text-[11px] font-mono text-slate-400 mt-1">
                  Barcode: {prod.barcode || 'N/A'}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Price: ₹{prod.price?.toFixed(2) || '0.00'}
                </div>
              </div>

              <button
                onClick={() => onSelectProduct(prod)}
                className="w-full py-2 bg-purple-50 hover:bg-purple-100 dark:bg-purple-950/60 dark:hover:bg-purple-900/60 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
              >
                <Camera className="w-3.5 h-3.5" />
                <span>Enroll 360° Vision →</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export const AdminPortal: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [authUser, setAuthUser] = useState<AuthUser | null>(() => {
    try {
      const saved = localStorage.getItem('smartcart_admin_user');
      const token = localStorage.getItem('smartcart_admin_token');
      if (saved && token) {
        return JSON.parse(saved);
      }
    } catch {}
    return null;
  });

  const [targetProduct, setTargetProduct] = useState<Product | null>(null);
  const [productList, setProductList] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState<boolean>(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(() => {
    return document.documentElement.classList.contains('dark');
  });
  const [healthData, setHealthData] = useState<any>(null);
  const [backendStatus, setBackendStatus] = useState<'CONNECTED' | 'WAKING_UP' | 'OFFLINE'>('WAKING_UP');
  const [sessionExpiredMsg, setSessionExpiredMsg] = useState<string | null>(null);

  const currentRouteKey = useMemo(() => matchAdminRoute(location.pathname), [location.pathname]);

  // Root /admin normalization: redirect to /admin/overview
  useEffect(() => {
    if (location.pathname === '/admin' || location.pathname === '/admin/') {
      navigate('/admin/overview', { replace: true });
    }
  }, [location.pathname, navigate]);

  // Strict Camera Lifecycle Enforcement:
  // Whenever the active route is neither 360 scan nor preview test, stop all webcam streams immediately.
  useEffect(() => {
    if (
      !location.pathname.startsWith('/admin/products/scan') &&
      !location.pathname.startsWith('/admin/preview-test')
    ) {
      CameraHelper.stopAllStreams();
    }
  }, [location.pathname]);

  const handleLogout = (expiredMsg?: string) => {
    // 1. Clear tokens and auth storage
    localStorage.removeItem('smartcart_admin_token');
    localStorage.removeItem('smartcart_admin_user');

    // 2. Clear cached data and stored page/filters
    try {
      sessionStorage.clear();
    } catch {}
    api.clearAllCaches();

    // 3. Force close all active WebSockets
    wsRegistry.closeAll();

    // 4. Force stop all active camera tracks
    CameraHelper.stopAllStreams();

    // 5. Reset internal state
    setAuthUser(null);
    setTargetProduct(null);
    setProductList([]);
    setHealthData(null);

    // 6. Navigate to login / overview
    navigate('/admin/overview');

    // 7. Set expired message if applicable
    if (expiredMsg) {
      setSessionExpiredMsg(expiredMsg);
    } else {
      setSessionExpiredMsg(null);
    }
  };

  useEffect(() => {
    const handleExpiredEvent = () => {
      handleLogout('Session expired');
    };
    window.addEventListener('smartcart:session-expired', handleExpiredEvent);
    return () => window.removeEventListener('smartcart:session-expired', handleExpiredEvent);
  }, []);

  const fetchHealth = async () => {
    try {
      const data = await api.getSystemHealth().catch((e) => {
        if (e?.statusCode === 401) throw e;
        return api.checkHealth();
      });
      setHealthData(data);
      setBackendStatus('CONNECTED');
    } catch (err: any) {
      if (err?.statusCode === 401) {
        handleLogout('Session expired');
        return;
      }
      if (err?.isWakingUp) {
        setBackendStatus('WAKING_UP');
      } else {
        setBackendStatus('OFFLINE');
      }
    }
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const toggleDarkMode = () => {
    const next = !darkMode;
    setDarkMode(next);
    if (next) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  const loadProductList = async () => {
    setLoadingProducts(true);
    try {
      const prods = await api.getProducts();
      setProductList(prods);
      return prods;
    } catch (e) {
      return [];
    } finally {
      setLoadingProducts(false);
    }
  };

  // Sync targetProduct with URL query parameter ?productId=... on /admin/products/scan
  useEffect(() => {
    if (authUser && location.pathname.startsWith('/admin/products/scan')) {
      const productId = searchParams.get('productId');
      if (productId) {
        if (!targetProduct || targetProduct.id !== productId) {
          loadProductList().then((prods) => {
            const found = prods.find((p) => p.id === productId);
            if (found) {
              setTargetProduct(found);
            }
          });
        }
      } else {
        if (productList.length === 0) {
          loadProductList();
        }
      }
    }
  }, [authUser, location.pathname, searchParams]);

  const handleStart360Scan = (prod: Product) => {
    CameraHelper.stopAllStreams();
    setTargetProduct(prod);
    navigate(`/admin/products/scan?productId=${prod.id}`);
  };

  const navigateTo = (destination: string) => {
    CameraHelper.stopAllStreams();
    if (destination.startsWith('/admin')) {
      navigate(destination);
      return;
    }
    const matched = ADMIN_NAV_ITEMS.find((n) => n.id === destination);
    if (matched) {
      navigate(matched.path);
    } else {
      navigate('/admin/overview');
    }
  };

  if (!authUser) {
    return (
      <AdminLogin
        sessionExpiredMessage={sessionExpiredMsg}
        onLoginSuccess={(u) => {
          setAuthUser(u);
          setSessionExpiredMsg(null);
          navigate('/admin/overview');
        }}
      />
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100">
      {/* Sidebar for Desktop */}
      <aside className="hidden lg:flex w-64 flex-col justify-between border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-[#131B2E] p-4 shadow-sm shrink-0">
        <div className="space-y-6">
          <div className="px-2 pt-2 flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-0.5">
                Staff Control Center
              </span>
              <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                SuperMart Admin
              </div>
            </div>

            {/* Dark Mode Toggle */}
            <button
              onClick={toggleDarkMode}
              className="p-1.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
              title="Toggle Dark/Light Mode"
            >
              {darkMode ? <Sun className="w-3.5 h-3.5 text-amber-400" /> : <Moon className="w-3.5 h-3.5 text-slate-600" />}
            </button>
          </div>

          <nav className="space-y-1">
            {ADMIN_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive =
                location.pathname === item.path ||
                (item.path === '/admin/overview' && (location.pathname === '/admin' || location.pathname === '/admin/')) ||
                (item.path !== '/admin/overview' && location.pathname.startsWith(item.path));

              return (
                <button
                  key={item.id}
                  onClick={() => {
                    CameraHelper.stopAllStreams();
                    if (item.id === 'SCAN_360' && !searchParams.get('productId')) {
                      setTargetProduct(null);
                    }
                    navigate(item.path);
                  }}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 shadow-sm border border-emerald-200 dark:border-emerald-800/40'
                      : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className={`w-4 h-4 ${isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}`} />
                    <span>{item.label}</span>
                  </div>
                  {isActive && <ChevronRight className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Staff Profile & Logout */}
        <div className="p-3 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-2xl flex items-center justify-between">
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="w-7 h-7 rounded-xl bg-slate-900 text-white font-bold text-xs flex items-center justify-center shrink-0">
              {authUser.full_name ? authUser.full_name.slice(0, 2).toUpperCase() : 'AD'}
            </div>
            <div className="overflow-hidden">
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
                {authUser.full_name || 'Admin User'}
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                {authUser.role || 'ADMIN'}
              </div>
            </div>
          </div>
          <button
            onClick={() => handleLogout()}
            className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
            title="Sign Out"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Backend System Status Indicator Button */}
        <button
          onClick={() => {
            CameraHelper.stopAllStreams();
            navigate('/admin/system');
          }}
          className="px-3 py-2 bg-slate-50/80 dark:bg-slate-900/40 border border-slate-200/80 dark:border-slate-800/80 rounded-xl flex items-center justify-between text-[11px] hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors w-full text-left"
          title="Click to view Backend System Diagnostics & /health"
        >
          <div className="flex items-center gap-2 overflow-hidden">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                backendStatus === 'CONNECTED'
                  ? 'bg-emerald-500 animate-pulse'
                  : backendStatus === 'WAKING_UP'
                  ? 'bg-amber-500 animate-pulse'
                  : 'bg-red-500'
              }`}
            />
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              {backendStatus === 'CONNECTED'
                ? 'Connected'
                : backendStatus === 'WAKING_UP'
                ? 'Waking up...'
                : 'Offline'}
            </span>
          </div>
          <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold hover:underline shrink-0 ml-1">
            Diagnostics
          </span>
        </button>
      </aside>

      {/* Main Admin Content Body */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full overflow-y-auto">
        {/* Mock Mode Alert Banner */}
        {healthData?.use_mock && (
          <div className="mb-4 p-3.5 bg-amber-500/10 border-2 border-amber-500/40 rounded-2xl flex items-center justify-between gap-3 text-amber-900 dark:text-amber-200 shadow-sm animate-pulse">
            <div className="flex items-center gap-2.5">
              <span className="px-2 py-0.5 rounded-full bg-amber-500 text-white font-bold text-[10px] tracking-wider uppercase">
                MOCK MODE ACTIVE
              </span>
              <span className="text-xs font-medium">
                Hardware camera simulation is enabled on this store backend. Mock vision action endpoints are active.
              </span>
            </div>
            <span className="text-[10px] font-mono text-amber-700 dark:text-amber-300 font-semibold shrink-0">
              USE_MOCK=true
            </span>
          </div>
        )}

        {/* Mobile Navigation Header */}
        <div className="lg:hidden mb-4 flex justify-between items-center bg-white dark:bg-[#131B2E] p-3 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-display text-slate-900 dark:text-white">
              {ADMIN_NAV_ITEMS.find((n) => n.id === currentRouteKey)?.label || 'Staff Control Center'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleDarkMode}
              className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300"
            >
              {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
            </button>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300"
            >
              {mobileMenuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {/* Mobile Menu Flyout */}
        {mobileMenuOpen && (
          <div className="lg:hidden mb-4 bg-white dark:bg-[#131B2E] p-3 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-xl space-y-1">
            {ADMIN_NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  CameraHelper.stopAllStreams();
                  if (item.id === 'SCAN_360' && !searchParams.get('productId')) {
                    setTargetProduct(null);
                  }
                  navigate(item.path);
                  setMobileMenuOpen(false);
                }}
                className="w-full text-left px-3 py-2 rounded-xl text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
              >
                {item.label}
              </button>
            ))}
            <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center px-3">
              <span className="text-xs text-slate-400 font-mono">{authUser.email}</span>
              <button
                onClick={() => handleLogout()}
                className="text-xs text-red-500 font-semibold flex items-center gap-1"
              >
                <LogOut className="w-3 h-3" /> Logout
              </button>
            </div>
          </div>
        )}

        {/* Stable URL Route Rendering */}
        {currentRouteKey === 'DASHBOARD' && <AdminDashboard onNavigate={navigateTo} />}
        {currentRouteKey === 'FLEET' && <LiveCartMonitor />}
        {currentRouteKey === 'ALERTS' && <AlertFeedView />}
        {currentRouteKey === 'REVIEWS' && <ReviewQueueView />}
        {currentRouteKey === 'PRODUCTS' && <ProductCatalogView onStart360Scan={handleStart360Scan} />}
        {currentRouteKey === 'SCAN_360' && (
          targetProduct ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between bg-white dark:bg-[#131B2E] p-3 rounded-2xl border border-slate-200 dark:border-slate-800">
                <div className="text-xs text-slate-600 dark:text-slate-300">
                  Currently enrolling: <strong className="text-slate-900 dark:text-white">{targetProduct.name}</strong> ({targetProduct.barcode})
                </div>
                <button
                  onClick={() => {
                    CameraHelper.stopAllStreams();
                    setTargetProduct(null);
                    navigate('/admin/products/scan');
                  }}
                  className="px-3 py-1 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-colors"
                >
                  Switch Product
                </button>
              </div>
              <Guided360ScanView
                product={targetProduct}
                onComplete={() => {
                  CameraHelper.stopAllStreams();
                  setTargetProduct(null);
                  navigate('/admin/products');
                }}
                onPreviewTest={() => {
                  CameraHelper.stopAllStreams();
                  navigate('/admin/preview-test');
                }}
              />
            </div>
          ) : (
            <ScanProductSelector
              products={productList}
              loading={loadingProducts}
              onSelectProduct={handleStart360Scan}
              onRefresh={loadProductList}
            />
          )
        )}
        {currentRouteKey === 'PREVIEW_TEST' && (
          <PreviewTestView
            initialProduct={targetProduct}
            onBackToCatalog={() => {
              CameraHelper.stopAllStreams();
              navigate('/admin/products');
            }}
          />
        )}
        {currentRouteKey === 'RECOGNITION_LAB' && <RecognitionLabView />}
        {currentRouteKey === 'MODELS' && <ModelManagerView />}
        {currentRouteKey === 'SYSTEM' && (
          <SystemDiagnosticsView
            health={healthData}
            status={backendStatus}
            onRefresh={fetchHealth}
            onSessionExpired={() => handleLogout('Session expired')}
          />
        )}
        {currentRouteKey === 'REPORTS' && <ReportsView />}
        {currentRouteKey === 'CARTS_REGISTRY' && <CartFleetView />}
        {currentRouteKey === 'STAFF' && <StaffRolesView />}
        {currentRouteKey === 'NOT_FOUND' && (
          <AdminNotFound
            currentPath={location.pathname}
            onGoOverview={() => {
              CameraHelper.stopAllStreams();
              navigate('/admin/overview');
            }}
          />
        )}
      </main>
    </div>
  );
};

export default AdminPortal;
