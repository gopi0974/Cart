import React, { useState, useEffect } from 'react';
import { ConnectCartView } from './ConnectCartView';
import { ActiveCartView } from './ActiveCartView';
import { ReceiptView } from './ReceiptView';
import { CartSession, ReceiptData } from '../types';
import { api } from '../services/api';

export const ShopperApp: React.FC = () => {
  const [activeSession, setActiveSession] = useState<CartSession | null>(null);
  const [receipt, setReceipt] = useState<ReceiptData | null>(null);

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

  const handleDisconnect = () => {
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
    </div>
  );
};
