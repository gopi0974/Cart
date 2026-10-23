import React, { useState, useEffect } from 'react';
import { Globe, Sun, Moon } from 'lucide-react';
import { ConnectCartView } from './ConnectCartView';
import { ActiveCartView } from './ActiveCartView';
import { ReceiptView } from './ReceiptView';
import { CartSession, ReceiptData } from '../types';
import { api } from '../services/api';
import { useTranslation, Language } from '../services/i18n';

export const ShopperApp: React.FC = () => {
  const [activeSession, setActiveSession] = useState<CartSession | null>(null);
  const [receipt, setReceipt] = useState<ReceiptData | null>(null);
  const { lang, setLang } = useTranslation();
  const [darkMode, setDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  const toggleDarkMode = () => {
    const next = !darkMode;
    setDarkMode(next);
    if (next) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  // Restore session from localStorage if user refreshed browser
  useEffect(() => {
    const savedSessionId = localStorage.getItem('smartcart_session_id');
    if (savedSessionId) {
      api.getSession(savedSessionId)
        .then((sess) => {
          if (sess.status === 'ACTIVE') {
            setActiveSession(sess);
          } else if (sess.status === 'COMPLETED') {
            api.getReceipt(sess.id).then(setReceipt).catch(() => {});
          }
        })
        .catch(() => {
          localStorage.removeItem('smartcart_session_id');
        });
    }
  }, []);

  const handleConnected = (session: CartSession) => {
    setActiveSession(session);
    setReceipt(null);
    localStorage.setItem('smartcart_session_id', session.id);
  };

  const handleDisconnect = async () => {
    if (activeSession) {
      try {
        await api.exitSession(activeSession.id);
      } catch (err) {
        console.error('Failed to notify backend of session exit:', err);
      }
    }
    setActiveSession(null);
    setReceipt(null);
    localStorage.removeItem('smartcart_session_id');
  };

  const handleCheckoutComplete = async () => {
    if (!activeSession) return;
    try {
      const rec = await api.getReceipt(activeSession.id);
      setReceipt(rec);
      setActiveSession(null);
      localStorage.removeItem('smartcart_session_id');
    } catch (e) {
      console.error('Failed to load receipt:', e);
    }
  };

  const handleNewSession = () => {
    setActiveSession(null);
    setReceipt(null);
    localStorage.removeItem('smartcart_session_id');
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100 flex flex-col justify-start">
      {/* Mobile-Friendly Header with Language & Theme Toggle (Strictly NO Admin Links) */}
      <header className="sticky top-0 z-40 bg-white/95 dark:bg-[#131B2E]/95 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 px-4 py-2.5 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-emerald-600 flex items-center justify-center text-white shadow-md shadow-emerald-600/30 font-bold">
            🛒
          </div>
          <span className="font-display font-bold text-sm tracking-tight text-slate-900 dark:text-white">
            SmartCart Shopper
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Multi-Language Selector */}
          <div className="flex items-center bg-slate-100 dark:bg-slate-800/80 rounded-xl p-1 border border-slate-200 dark:border-slate-700 text-xs font-semibold">
            <Globe className="w-3.5 h-3.5 text-slate-500 ml-1 mr-1" />
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as Language)}
              className="bg-transparent text-slate-700 dark:text-slate-300 pr-1 py-0.5 focus:outline-none cursor-pointer"
            >
              <option value="en" className="dark:bg-slate-900">EN</option>
              <option value="te" className="dark:bg-slate-900">TE</option>
              <option value="hi" className="dark:bg-slate-900">HI</option>
            </select>
          </div>

          {/* Theme Toggle */}
          <button
            onClick={toggleDarkMode}
            className="p-2 rounded-xl text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Toggle Light/Dark Mode"
          >
            {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-600" />}
          </button>
        </div>
      </header>

      {/* Main Content View */}
      <main className="flex-1 w-full max-w-lg mx-auto">
        {receipt ? (
          <ReceiptView receipt={receipt} onNewSession={handleNewSession} />
        ) : activeSession ? (
          <ActiveCartView
            session={activeSession}
            onDisconnect={handleDisconnect}
            onCheckoutComplete={handleCheckoutComplete}
          />
        ) : (
          <ConnectCartView onConnected={handleConnected} />
        )}
      </main>
    </div>
  );
};

export default ShopperApp;
