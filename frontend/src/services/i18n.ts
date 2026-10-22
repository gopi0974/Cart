import React, { createContext, useContext, useState, useEffect } from 'react';

export type Language = 'en' | 'te' | 'hi';

export const translations = {
  en: {
    appName: 'SmartCart AI',
    tagline: 'SuperMart Autonomous Retail • No Billing Queues',
    connectTitle: 'Point camera at Cart Handle QR',
    connectDesc: 'Scan the QR code printed on your shopping cart to pair your phone instantly.',
    connectBtn: 'Connect to Cart',
    privacyNote: 'Privacy Guaranteed: Overhead camera strictly monitors cart items. No facial recording.',
    cartItems: 'Cart Items',
    scanBarcode: 'Scan Barcode',
    pay: 'Pay',
    pendingStatus: 'PENDING • Place item in cart',
    verifiedStatus: 'VERIFIED BY AI',
    mismatchStatus: 'MISMATCH DETECTED',
    unscannedStatus: 'UNSCANNED ITEM',
    emptyCartTitle: 'Your cart is empty',
    emptyCartDesc: 'Tap "Scan Barcode" below to scan your first grocery item.',
    subtotal: 'Subtotal',
    tax: 'Tax',
    total: 'Total',
    coupons: 'Have a Promo Code?',
    apply: 'Apply',
    paidInFull: 'PAID IN FULL',
    finishSession: 'Finish & Return Cart',
  },
  te: {
    appName: 'స్మార్ట్ కార్ట్ AI',
    tagline: 'సూపర్‌మార్ట్ స్మార్ట్ షాపింగ్ • బిల్లింగ్ క్యూలు లేవు',
    connectTitle: 'కార్ట్ హ్యాండిల్ QR కోడ్‌ను స్కాన్ చేయండి',
    connectDesc: 'మీ ఫోన్‌ను తక్షణమే కనెక్ట్ చేయడానికి కార్ట్‌పై ఉన్న QR కోడ్‌ను స్కాన్ చేయండి.',
    connectBtn: 'కార్ట్‌కు కనెక్ట్ అవ్వండి',
    privacyNote: 'గోప్యత హామీ: కెమెరా కార్ట్ లోపల వస్తువులను మాత్రమే చూస్తుంది. ముఖ రికార్డింగ్ లేదు.',
    cartItems: 'కార్ట్‌లోని వస్తువులు',
    scanBarcode: 'బార్‌కోడ్ స్కాన్ చేయండి',
    pay: 'చెల్లించండి',
    pendingStatus: 'పెండింగ్ • వస్తువును కార్ట్‌లో ఉంచండి',
    verifiedStatus: 'AI ద్వారా ధృవీకరించబడింది',
    mismatchStatus: 'తప్పు వస్తువు గుర్తించబడింది',
    unscannedStatus: 'స్కాన్ చేయని వస్తువు',
    emptyCartTitle: 'మీ కార్ట్ ఖాళీగా ఉంది',
    emptyCartDesc: 'వస్తువును స్కాన్ చేయడానికి క్రింది "బార్‌కోడ్ స్కాన్ చేయండి" బటన్‌ను నొక్కండి.',
    subtotal: 'ఉపమొత్తం',
    tax: 'పన్ను (GST)',
    total: 'మొత్తం',
    coupons: 'ప్రోమో కోడ్ ఉందా?',
    apply: 'వర్తింపజేయి',
    paidInFull: 'చెల్లింపు పూర్తయింది',
    finishSession: 'పూర్తి చేసి కార్ట్ అప్పగించండి',
  },
  hi: {
    appName: 'स्मार्ट कार्ट AI',
    tagline: 'सुपरमार्ट ऑटोनॉमस रिटेल • बिना किसी लाइन के बिलिंग',
    connectTitle: 'कार्ट हैंडल पर लगे QR को स्कैन करें',
    connectDesc: 'फोन को कार्ट से कनेक्ट करने के लिए हैंडल पर प्रिंटेड QR कोड स्कैन करें।',
    connectBtn: 'कार्ट से कनेक्ट करें',
    privacyNote: 'गोपनीयता सुरक्षित: कैमरा केवल कार्ट के सामान पर नजर रखता है। चेहरा रिकॉर्ड नहीं होता।',
    cartItems: 'कार्ट का सामान',
    scanBarcode: 'बारकोड स्कैन करें',
    pay: 'भुगतान करें',
    pendingStatus: 'लंबित • सामान को कार्ट में रखें',
    verifiedStatus: 'AI द्वारा सत्यापित',
    mismatchStatus: 'गलत सामान का पता चला',
    unscannedStatus: 'बिना स्कैन किया हुआ सामान',
    emptyCartTitle: 'आपकी कार्ट खाली है',
    emptyCartDesc: 'पहला सामान जोड़ने के लिए नीचे दिए गए "बारकोड स्कैन करें" पर टैप करें।',
    subtotal: 'उप-योग',
    tax: 'कर (GST)',
    total: 'कुल योग',
    coupons: 'प्रोमो कोड दर्ज करें',
    apply: 'लागू करें',
    paidInFull: 'भुगतान सफल',
    finishSession: 'समाप्त करें और कार्ट वापस करें',
  }
};

interface LanguageContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: typeof translations['en'];
}

const LanguageContext = createContext<LanguageContextType>({
  lang: 'en',
  setLang: () => {},
  t: translations.en,
});

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLang] = useState<Language>(() => {
    return (localStorage.getItem('smartcart_lang') as Language) || 'en';
  });

  useEffect(() => {
    localStorage.setItem('smartcart_lang', lang);
  }, [lang]);

  const value = {
    lang,
    setLang,
    t: translations[lang] || translations.en,
  };

  return React.createElement(LanguageContext.Provider, { value }, children);
};

export const useTranslation = () => useContext(LanguageContext);
