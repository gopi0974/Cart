import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard, ShoppingCart, AlertTriangle, Layers, Camera, CheckSquare,
  QrCode, Cpu, ShieldCheck, ChevronRight, Menu, X, Eye, BarChart3, Users,
  LogOut, Sun, Moon
} from 'lucide-react';
import { AdminDashboard } from './AdminDashboard';
import { LiveCartMonitor } from './LiveCartMonitor';
import { AlertFeedView } from './AlertFeedView';
import { ReviewQueueView } from './ReviewQueueView';
import { ProductCatalogView } from './ProductCatalogView';
import { Guided360ScanView } from './Guided360ScanView';
import { PreviewTestView } from './PreviewTestView';
import { CartFleetView } from './CartFleetView';
import { ModelManagerView } from './ModelManagerView';
import { ReportsView } from './ReportsView';
import { StaffRolesView } from './StaffRolesView';
import { AdminLogin } from './AdminLogin';
import { Product } from '../types';
import { api } from '../services/api';

interface AuthUser {
  email: string;
  full_name: string;
  role: string;
}

export const AdminPortal: React.FC = () => {
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

  const [currentTab, setCurrentTab] = useState<string>('DASHBOARD');
  const [targetProduct, setTargetProduct] = useState<Product | null>(null);
  const [productList, setProductList] = useState<Product[]>([]);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(() => {
    return document.documentElement.classList.contains('dark');
  });

  const toggleDarkMode = () => {
    const next = !darkMode;
    setDarkMode(next);
    if (next) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  useEffect(() => {
    if (authUser && currentTab === 'SCAN_360' && !targetProduct) {
      api.getProducts().then((prods) => {
        setProductList(prods);
        if (prods.length > 0 && !targetProduct) {
          setTargetProduct(prods[0]);
        }
      }).catch(() => {});
    }
  }, [authUser, currentTab, targetProduct]);

  const handleStart360Scan = (prod: Product) => {
    setTargetProduct(prod);
    setCurrentTab('SCAN_360');
  };

  const handleLogout = () => {
    localStorage.removeItem('smartcart_admin_token');
    localStorage.removeItem('smartcart_admin_user');
    setAuthUser(null);
  };

  if (!authUser) {
    return <AdminLogin onLoginSuccess={(u) => setAuthUser(u)} />;
  }

  const NAV_ITEMS = [
    { id: 'DASHBOARD', label: 'Overview', icon: LayoutDashboard },
    { id: 'FLEET', label: 'Live Cart Monitor', icon: ShoppingCart },
    { id: 'ALERTS', label: 'Incidents & Alerts', icon: AlertTriangle },
    { id: 'REVIEWS', label: 'AI Review Queue', icon: CheckSquare },
    { id: 'PRODUCTS', label: 'Product Inventory', icon: Layers },
    { id: 'SCAN_360', label: '360° Vision Scan', icon: Camera },
    { id: 'MODELS', label: 'AI Models & Stats', icon: Cpu },
    { id: 'REPORTS', label: 'Financial & Loss Reports', icon: BarChart3 },
    { id: 'CARTS_REGISTRY', label: 'Fleet & QR Sheet', icon: QrCode },
    { id: 'STAFF', label: 'Staff & Roles', icon: Users },
  ];

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
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setCurrentTab(item.id)}
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
            onClick={handleLogout}
            className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
            title="Sign Out"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </aside>

      {/* Main Admin Content Body */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full overflow-y-auto">
        {/* Mobile Navigation Header */}
        <div className="lg:hidden mb-4 flex justify-between items-center bg-white dark:bg-[#131B2E] p-3 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-display text-slate-900 dark:text-white">
              {NAV_ITEMS.find((n) => n.id === currentTab)?.label || 'Portal Navigation'}
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
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  setCurrentTab(item.id);
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
                onClick={handleLogout}
                className="text-xs text-red-500 font-semibold flex items-center gap-1"
              >
                <LogOut className="w-3 h-3" /> Logout
              </button>
            </div>
          </div>
        )}

        {/* Dynamic Route Switching */}
        {currentTab === 'DASHBOARD' && <AdminDashboard onNavigate={setCurrentTab} />}
        {currentTab === 'FLEET' && <LiveCartMonitor />}
        {currentTab === 'ALERTS' && <AlertFeedView />}
        {currentTab === 'REVIEWS' && <ReviewQueueView />}
        {currentTab === 'PRODUCTS' && <ProductCatalogView onStart360Scan={handleStart360Scan} />}
        {currentTab === 'SCAN_360' && (
          targetProduct ? (
            <Guided360ScanView
              product={targetProduct}
              onComplete={() => setCurrentTab('PRODUCTS')}
              onPreviewTest={() => setCurrentTab('PREVIEW_TEST')}
            />
          ) : (
            <div className="p-8 text-center space-y-4 bg-white dark:bg-[#131B2E] rounded-3xl border border-slate-200 dark:border-slate-800">
              <Camera className="w-10 h-10 text-purple-500 mx-auto" />
              <h2 className="text-lg font-bold font-display text-slate-900 dark:text-white">
                Select a Product for 360° Vision Enrollment
              </h2>
              <p className="text-xs text-slate-500 max-w-sm mx-auto">
                Select any item from the catalog to begin capturing 360-degree packaging angles and generate visual embeddings.
              </p>
              {productList.length > 0 && (
                <div className="flex flex-wrap gap-2 justify-center max-w-lg mx-auto pt-2">
                  {productList.slice(0, 6).map((p) => (
                    <button
                      key={p.id}
                      onClick={() => setTargetProduct(p)}
                      className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-semibold hover:border-purple-500 hover:text-purple-600 transition-colors"
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        )}
        {currentTab === 'PREVIEW_TEST' && (
          <PreviewTestView initialProduct={targetProduct} onBackToCatalog={() => setCurrentTab('PRODUCTS')} />
        )}
        {currentTab === 'MODELS' && <ModelManagerView />}
        {currentTab === 'REPORTS' && <ReportsView />}
        {currentTab === 'CARTS_REGISTRY' && <CartFleetView />}
        {currentTab === 'STAFF' && <StaffRolesView />}
      </main>
    </div>
  );
};

export default AdminPortal;
