import React, { useState } from 'react';
import {
  LayoutDashboard, ShoppingCart, AlertTriangle, Layers, Camera, CheckSquare,
  QrCode, Cpu, ShieldCheck, ChevronRight, Menu, X, Eye
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
import { Product } from '../types';

export const AdminPortal: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<string>('DASHBOARD');
  const [targetProduct, setTargetProduct] = useState<Product | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleStart360Scan = (prod: Product) => {
    setTargetProduct(prod);
    setCurrentTab('SCAN_360');
  };

  const NAV_ITEMS = [
    { id: 'DASHBOARD', label: 'Overview', icon: LayoutDashboard },
    { id: 'FLEET', label: 'Live Cart Monitor', icon: ShoppingCart },
    { id: 'ALERTS', label: 'Incidents & Alerts', icon: AlertTriangle },
    { id: 'REVIEWS', label: 'AI Review Queue', icon: CheckSquare },
    { id: 'PRODUCTS', label: 'Product Inventory', icon: Layers },
    { id: 'CARTS_REGISTRY', label: 'Fleet & QR Sheet', icon: QrCode },
    { id: 'MODELS', label: 'AI Models & Stats', icon: Cpu },
  ];

  return (
    <div className="flex min-h-[92vh] bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100">
      {/* Sidebar for Desktop */}
      <aside className="hidden lg:flex w-64 flex-col justify-between border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-[#131B2E] p-4 shadow-sm">
        <div className="space-y-6">
          <div className="px-2 pt-2">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
              Store Staff Portal
            </span>
            <div className="text-xs font-medium text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              SuperMart Hypermarket
            </div>
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

        {/* Staff Profile Footer */}
        <div className="p-3 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-2xl flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-xl bg-slate-900 text-white font-bold text-xs flex items-center justify-center">
              SJ
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">Sarah J.</div>
              <div className="text-[10px] text-slate-400">Store Admin</div>
            </div>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-600 font-bold">
            PROD
          </span>
        </div>
      </aside>

      {/* Main Admin Content Body */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full">
        {/* Mobile Navigation Dropdown Button */}
        <div className="lg:hidden mb-4 flex justify-between items-center bg-white dark:bg-[#131B2E] p-3 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold font-display text-slate-900 dark:text-white">
            {NAV_ITEMS.find((n) => n.id === currentTab)?.label || 'Portal Navigation'}
          </span>
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800"
          >
            {mobileMenuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>
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
          </div>
        )}

        {/* Dynamic Route Switching */}
        {currentTab === 'DASHBOARD' && <AdminDashboard onNavigate={setCurrentTab} />}
        {currentTab === 'FLEET' && <LiveCartMonitor />}
        {currentTab === 'ALERTS' && <AlertFeedView />}
        {currentTab === 'REVIEWS' && <ReviewQueueView />}
        {currentTab === 'PRODUCTS' && <ProductCatalogView onStart360Scan={handleStart360Scan} />}
        {currentTab === 'SCAN_360' && targetProduct && (
          <Guided360ScanView
            product={targetProduct}
            onComplete={() => setCurrentTab('PRODUCTS')}
            onPreviewTest={() => setCurrentTab('PREVIEW_TEST')}
          />
        )}
        {currentTab === 'PREVIEW_TEST' && (
          <PreviewTestView onBackToCatalog={() => setCurrentTab('PRODUCTS')} />
        )}
        {currentTab === 'CARTS_REGISTRY' && <CartFleetView />}
        {currentTab === 'MODELS' && <ModelManagerView />}
      </main>
    </div>
  );
};
