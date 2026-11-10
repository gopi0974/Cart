import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Globe, Sun, Moon, CheckCircle2, ArrowRight } from 'lucide-react';
import { ConnectCartView } from './ConnectCartView';
import { ActiveCartView } from './ActiveCartView';
import { ReceiptView } from './ReceiptView';
import { CartSession, ReceiptData } from '../types';
import { api } from '../services/api';
import { wsRegistry } from '../services/wsRegistry';
import { useTranslation, Language } from '../services/i18n';

export const ShopperApp: React.FC = () => {
  const navigate = useNavigate();
  const [activeSession, setActiveSession] = useState<CartSession | null>(null);
  const [leftCartNotification, setLeftCartNotification] = useState<string | null>(null);
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

  // Restore session from localStorage ONLY if still ACTIVE on the server
  useEffect(() => {
    const savedSessionId = localStorage.getItem('smartcart_session_id');
    const savedSessionToken = localStorage.getItem('smartcart_session_token');
    if (savedSessionId && savedSessionToken) {
      api.getSession(savedSessionId)
        .then((sess) => {
          if (sess.status === 'ACTIVE') {
            setActiveSession(sess);
          } else {
            // Never auto-resume ended or abandoned sessions
            localStorage.removeItem('smartcart_session_id');
            localStorage.removeItem('smartcart_session_token');
            sessionStorage.removeItem('smartcart_session_id');
            sessionStorage.removeItem('smartcart_session_token');
            if (sess.status === 'COMPLETED') {
              api.getReceipt(sess.id).then(setReceipt).catch(() => {});
            }
          }
        })
        .catch(() => {
          localStorage.removeItem('smartcart_session_id');
          localStorage.removeItem('smartcart_session_token');
          sessionStorage.removeItem('smartcart_session_id');
          sessionStorage.removeItem('smartcart_session_token');
        });
    } else {
      localStorage.removeItem('smartcart_session_id');
      localStorage.removeItem('smartcart_session_token');
    }
  }, []);

  // Auto-dismiss "You left Cart N" notification after 4 seconds
  useEffect(() => {
    if (!leftCartNotification) return;
    const timer = setTimeout(() => {
      setLeftCartNotification(null);
    }, 4000);
    return () => clearTimeout(timer);
  }, [leftCartNotification]);

  const handleConnected = (session: CartSession) => {
    setLeftCartNotification(null);
    setActiveSession(session);
    setReceipt(null);
    localStorage.setItem('smartcart_session_id', session.id);
    if (session.session_token) {
      localStorage.setItem('smartcart_session_token', session.session_token);
    }
  };

  const handleDisconnect = async () => {
    if (!activeSession) return;
    const cartNum = activeSession.cart_number;

    // 1. Await end-session call on backend
    try {
      await api.exitSession(activeSession.id);
    } catch (err: any) {
      console.error('Failed to notify backend of session exit:', err);
      // Re-throw so ActiveCartView does NOT clear state and does not pretend it worked
      throw err;
    }

    // 2. Force close all active WebSockets without auto-reconnect
    wsRegistry.closeAll();

    // 3. Purge every stored session key
    localStorage.removeItem('smartcart_session_id');
    localStorage.removeItem('smartcart_session_token');
    sessionStorage.removeItem('smartcart_session_id');
    sessionStorage.removeItem('smartcart_session_token');

    // 4. Strip cart and sig from the URL & navigate React Router to /user
    navigate('/user', { replace: true });
    if (typeof window !== 'undefined' && window.history) {
      window.history.replaceState({}, '', '/user');
    }

    // 5. Clear active session state and show "You left Cart N"
    setActiveSession(null);
    setReceipt(null);
    setLeftCartNotification(cartNum);
  };

  const handleCheckoutComplete = async () => {
    if (!activeSession) return;
    try {
      const rec = await api.getReceipt(activeSession.id);
      setReceipt(rec);
      setActiveSession(null);
      localStorage.removeItem('smartcart_session_id');
      localStorage.removeItem('smartcart_session_token');
    } catch (e) {
      console.error('Failed to load receipt:', e);
    }
  };

  const handleNewSession = () => {
    setActiveSession(null);
    setReceipt(null);
    setLeftCartNotification(null);
    localStorage.removeItem('smartcart_session_id');
    localStorage.removeItem('smartcart_session_token');
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
        ) : leftCartNotification ? (
          <div className="p-6 max-w-md mx-auto min-h-[70vh] flex flex-col items-center justify-center text-center animate-in fade-in zoom-in-95 duration-200">
            <div className="w-16 h-16 rounded-3xl bg-emerald-100 dark:bg-emerald-950/60 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-4 shadow-lg shadow-emerald-600/20">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold font-display text-slate-900 dark:text-white mb-2">
              You left Cart {leftCartNotification}
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-400 max-w-xs mb-6 leading-relaxed">
              Your shopping session has ended and this cart has been released. It is now free for new shoppers.
            </p>
            <button
              onClick={() => setLeftCartNotification(null)}
              className="py-3 px-6 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs flex items-center gap-2 shadow-lg shadow-emerald-600/25 active:scale-95 transition-all"
            >
              <span>Scan another cart</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
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
