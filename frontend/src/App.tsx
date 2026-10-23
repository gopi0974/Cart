import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ShopperApp } from './shopper/ShopperApp';
import { AdminPortal } from './admin/AdminPortal';
import { CartDeviceView } from './device/CartDeviceView';
import { ScannerTestView } from './shopper/ScannerTestView';
import { LanguageProvider } from './services/i18n';

export const App: React.FC = () => {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/scanner-test" element={<ScannerTestView />} />
          <Route path="/cart-device" element={<CartDeviceView />} />
          <Route path="/user" element={<ShopperApp />} />
          <Route path="/user/connect" element={<ShopperApp />} />
          <Route path="/shopper" element={<ShopperApp />} />
          <Route path="/shopper/connect" element={<ShopperApp />} />
          <Route path="/connect" element={<ShopperApp />} />
          <Route path="/admin" element={<AdminPortal />} />
          <Route path="/admin/*" element={<AdminPortal />} />
          <Route path="/" element={<Navigate to="/user" replace />} />
          <Route path="*" element={<Navigate to="/user" replace />} />
        </Routes>
      </BrowserRouter>
    </LanguageProvider>
  );
};

export default App;
