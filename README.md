# 🛒 SmartCart AI - Autonomous Retail Shopping System

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/Frontend-React_18_%2B_Vite-61DAFB.svg?style=flat&logo=react)](https://react.dev)
[![Tailwind CSS](https://img.shields.io/badge/Styling-Tailwind_CSS-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An intelligent, autonomous supermarket shopping cart system that eliminates billing queues. Each cart features an overhead computer vision camera that continuously monitors items placed in or removed from the cart. Shoppers connect their smartphone to the cart via a handle QR code, scan barcodes, and pay directly in the mobile web app with zero wait time.

---

## 🌟 Key Features

### 1. User Mobile Web App (PWA)
- **Instant Cart Connection**: Quick QR code scan pairs the shopper's phone to the physical cart (`CART-01` through `CART-12`).
- **Live Barcode Camera Scanner**: Fast camera scanner with red laser alignment reticle, flashlight/torch toggle, Web Audio API sound chimes (880Hz), and Web Vibration API haptics.
- **Verification State Machine**:
  - `PENDING`: Item scanned; customer prompted to place the item inside the cart basket.
  - `VERIFIED`: Overhead AI camera detects and verifies item visual signature against catalog embeddings.
  - `MISMATCH`: Friendly alert if a different item than scanned is placed.
  - `UNSCANNED ITEM`: Immediate non-accusatory warning if an item enters the basket without being scanned.
- **Strict Checkout Guard**: Payment is permitted only when every item is `VERIFIED` and all warnings are cleared.
- **Digital Tax Invoice & Exit Pass**: Itemized GST tax receipt, printable invoice, and high-contrast **Store Exit Gate Turnstile QR Pass**.

### 2. Built-In Hardware & Vision Simulator
- Emulates overhead wide-angle cart camera feeds and trajectory tracking directly inside the browser using your local webcam.
- Action trigger deck to test correct placements, wrong item mismatches, unscanned additions, and item removals in real time.

### 3. Asynchronous Real-Time Backend
- Built on **Python FastAPI** and **SQLAlchemy 2.0 ORM** with SQLite WAL (PostgreSQL ready).
- Multi-channel **WebSockets** for instant push notifications to shopper phones and admin dashboards (`ITEM_VERIFIED`, `ITEM_MISMATCH`, `UNSCANNED_ITEM_DETECTED`, `ITEM_REMOVAL_DETECTED`).
- Pre-seeded with 3 staff accounts, 12 smart carts, 10 realistic supermarket products with barcodes, prices, weights, GST tax brackets, and multi-angle 360 embeddings.

---

## 🚀 Quickstart & Local Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 1. Clone the Repository
```bash
git clone https://github.com/gopi0974/Cart.git
cd Cart
```

### 2. Start the Backend
```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
* Interactive API Documentation (Swagger): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* Healthcheck: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

### 3. Start the Frontend
```bash
cd ../frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
* Shopper Web App & Simulator: [http://127.0.0.1:5173/](http://127.0.0.1:5173/)

---

## 🧪 Running Automated Backend Tests

The project includes an end-to-end integration test suite covering authentication, catalog querying, cart pairing, item state transitions, checkout validation rules, and fraud detection alerts:

```bash
cd backend
python run_tests.py
```

---

## 🔒 Security & Privacy Notice
The overhead camera monitors strictly the interior basket of the shopping cart. No facial recognition, customer tracking, or biometric recording is performed.
