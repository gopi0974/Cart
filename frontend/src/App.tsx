import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ShopperApp } from './shopper/ShopperApp';
import { AdminPortal } from './admin/AdminPortal';
import { ScannerTestView } from './shopper/ScannerTestView';
import { CameraTestView } from './shopper/CameraTestView';
import { LanguageProvider } from './services/i18n';

// Lazy-load hardware and diagnostic views so @mediapipe/tasks-vision never enters the shopper bundle
const CartDeviceView = React.lazy(() => import('./device/CartDeviceView').then((m) => ({ default: m.CartDeviceView })));
const DetectorTestView = React.lazy(() => import('./device/DetectorTestView'));

export const App: React.FC = () => {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <Suspense fallback={<div className="min-h-screen bg-[#070A12] flex items-center justify-center text-slate-400 font-mono text-xs">Loading...</div>}>
          <Routes>
            <Route path="/detector-test" element={<DetectorTestView />} />
            <Route path="/camera-test" element={<CameraTestView />} />
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
        </Suspense>
      </BrowserRouter>
    </LanguageProvider>
  );
};

export default App;
