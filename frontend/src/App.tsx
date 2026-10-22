import React, { useState, useEffect } from 'react';
import { ShoppingCart, Cpu, LayoutDashboard, Sun, Moon } from 'lucide-react';
import { ShopperApp } from './shopper/ShopperApp';
import { AdminPortal } from './admin/AdminPortal';
import { CartSimulatorView } from './simulator/CartSimulatorView';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'SHOPPER' | 'ADMIN' | 'SIMULATOR'>('SHOPPER');
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100 transition-colors">
      {/* Universal Top Switcher Bar */}
      <header className="sticky top-0 z-40 bg-white/90 dark:bg-[#131B2E]/90 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 px-4 py-2.5 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-emerald-600 flex items-center justify-center text-white shadow-md shadow-emerald-600/30 font-bold">
            🛒
          </div>
          <span className="font-display font-bold text-sm tracking-tight text-slate-900 dark:text-white">
            SmartCart AI
          </span>
        </div>

        {/* View Mode Switcher Pills */}
        <div className="flex bg-slate-100 dark:bg-slate-900/80 p-1 rounded-xl border border-slate-200 dark:border-slate-800 text-xs font-semibold">
          <button
            onClick={() => setActiveTab('SHOPPER')}
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all ${
              activeTab === 'SHOPPER'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <ShoppingCart className="w-3.5 h-3.5" />
            Shopper App
          </button>

          <button
            onClick={() => setActiveTab('ADMIN')}
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all ${
              activeTab === 'ADMIN'
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            Admin Portal
          </button>

          <button
            onClick={() => setActiveTab('SIMULATOR')}
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all ${
              activeTab === 'SIMULATOR'
                ? 'bg-purple-600 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            Hardware Simulator
          </button>
        </div>

        {/* Theme Toggle */}
        <button
          onClick={() => setDarkMode(!darkMode)}
          className="p-2 rounded-xl text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title="Toggle Light/Dark Mode"
        >
          {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-600" />}
        </button>
      </header>

      {/* Main Container */}
      <main className="w-full">
        {activeTab === 'SHOPPER' && <ShopperApp />}
        {activeTab === 'ADMIN' && <AdminPortal />}
        {activeTab === 'SIMULATOR' && <CartSimulatorView />}
      </main>
    </div>
  );
};

export default App;
