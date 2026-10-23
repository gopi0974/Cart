# 🛒 SmartCart AI - Autonomous Retail Shopping & Vision Platform

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/Frontend-React_18_%2B_Vite-61DAFB.svg?style=flat&logo=react)](https://react.dev)
[![Tailwind CSS](https://img.shields.io/badge/Styling-Tailwind_CSS-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)
[![PyTorch](https://img.shields.io/badge/AI_Vision-PyTorch_%2B_DINOv2-EE4C2C.svg?style=flat&logo=pytorch)](https://pytorch.org)
[![Docker](https://img.shields.io/badge/Deployment-Docker_%2B_Compose-2496ED.svg?style=flat&logo=docker)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An end-to-end, production-grade autonomous supermarket shopping cart system that eliminates billing lines. Each cart possesses an overhead camera continuously monitoring cart interior additions and removals. Shoppers pair their phone via QR, scan barcodes, and pay on their phone, while AI validates that what was scanned matches what physically entered the basket. Supermarket staff utilize a real-time web portal for fleet monitoring, fraud alert triage, low-confidence review, and phone-like **Guided 360° Item Enrollment**.

---

## 🏗️ System Architecture

```text
[ Shopper Mobile App (PWA) ]   <--->   [ FastAPI Asynchronous Hub ]   <--->   [ Overhead Cart Camera / Simulator ]
        |                                          |                                           |
    QR Pairing /                               WebSockets                                YOLOv8 Trajectory &
    Barcode Scanner                           (Live Sync)                               DINOv2 Embeddings
        |                                          |                                           |
[ Digital Exit QR Pass ]       <--->   [ Admin Operations Portal ]     <--->   [ Vector DB (FAISS / 360 Index) ]
```

---

## 🌟 Key Functional Features

### 1. User Mobile Web App (Shopper PWA)
- **Instant Handle Pairing**: Scan the cart's unique QR code to pair phone and cart (`CART-01` to `CART-12`).
- **Live Barcode Camera Scanner**: Fast camera scanner with red laser alignment reticle, flashlight/torch toggle, Web Audio API sound chimes (880Hz), and Web Vibration API haptics (40ms). Includes quick-test barcode presets.
- **Verification State Machine**:
  - `PENDING`: Scanned item awaiting physical placement in cart basket (warm amber pulse).
  - `VERIFIED`: Confirmed by overhead camera visual matcher (green check animation + confidence).
  - `MISMATCH`: Friendly alert when a different product than scanned is placed.
  - `UNSCANNED ITEM`: Immediate non-accusatory warning if an item enters the basket without being scanned.
  - `REMOVAL`: Confirms item taken out and prompts customer to rescan barcode to drop it from the bill.
- **Digital Tax Invoice**: Split GST breakdown, sandbox UPI & Card checkout, and printable/PDF tax invoice.

### 2. Mart Staff Admin Portal
- **Fleet Live Monitoring Grid**: Visual status cards for all carts (`Active`, `Alert`, `Idle`) with battery levels, camera health, current item counts, and live camera feed inspection modal.
- **Incident & Alert Triage**: Real-time fraud detection stream with severity tags (`CRITICAL`, `HIGH`, `MEDIUM`), cart ID, timestamp, camera evidence snapshot, and staff resolution modal.
- **Human-In-The-Loop Review Queue**: Side-by-side evidence inspection against 360 catalog references with 1-click hotkey approvals (`A` to approve, `R` to reject) that save feedback to fine-tune the model.
- **Product Inventory & Bulk CSV**: Complete product CRUD, stock tracking, and instant CSV bulk catalog ingestion.
- **AI Model Registry**: Active model version tracking (`v1.0.0-dinov2`), accuracy stats (98.4%), false-alarm rates (0.8%), confidence threshold sliders, and 1-click model rollback.
- **Cart Management & QR Sheet**: Register new smart carts and print high-contrast handle QR stickers.

### 3. Guided 360° Item Scan (Key Admin Feature)
- **Face-Enrollment Style UI**: Circular segmented progress ring that fills as each perspective is captured.
- **Voice & Visual Guidance**: Web Speech API audio commands aloud ("Show the front", "Rotate slowly to the right", "Show the back", "Tilt up", "Tilt down", "Bring it closer to show the label", "Hold still").
- **Automatic Quality Heuristics**: Evaluates focus sharpness and lighting before confirming angle.
- **Thumbnail Review & Vector Extraction**: Review all 7 captured angles, retake any angle, extract 512-dim visual embeddings, and index them into the vector database.
- **Recognition Preview Test Bench**: Live test mode where staff hold the enrolled item in front of the camera to verify >90% AI recognition before placing it on store shelves.

### 4. Built-in Hardware & Camera Simulator
- Interactive simulator allowing full end-to-end testing without physical cart hardware.
- Real-time action triggers:
  1. `[✔ 1. Item Placed]`: Confirms scanned item physically placed -> triggers `ITEM_VERIFIED`.
  2. `[⚠️ 2. Wrong Item Placed]`: Simulates mismatch -> triggers `ITEM_MISMATCH` & security alert.
  3. `[🚨 3. Unscanned Item]`: Simulates un-scanned addition -> triggers theft alert and blocks checkout.
  4. `[📤 4. Item Removed]`: Simulates removal -> prompts rescan to drop item from bill.

---

## 🚀 Quickstart & Local Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 1. Start the Backend API & WebSocket Hub
```bash
cd backend
python run_tests.py     # Verify all 9 integration test suites pass
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
* Interactive Swagger API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. Start the Frontend Application
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
* **Shopper Mobile Web App**: [http://127.0.0.1:5173/user](http://127.0.0.1:5173/user)
* **Mart Staff Admin Portal**: [http://127.0.0.1:5173/admin](http://127.0.0.1:5173/admin)
* Root `http://127.0.0.1:5173/` automatically redirects to `/user`.

---

## 🐳 Docker Deployment

Run the complete platform via Docker Compose:
```bash
docker-compose up --build
```
* Backend API: [http://localhost:8000](http://localhost:8000)
* Web Frontend: [http://localhost:5173](http://localhost:5173)

---

## 🔑 Pre-Seeded Demonstration Accounts

| Role | Email | Password | Access Level |
| :--- | :--- | :--- | :--- |
| **Store Admin** | `admin@supermart.com` | `admin123` | Full Fleet, Catalog, 360 Scan, Model Controls |
| **Floor Manager** | `manager@supermart.com` | `manager123` | Cart Monitoring, Alert Resolution, Review Queue |
| **Store Associate** | `staff@supermart.com` | `staff123` | Inventory viewing and customer assistance |

---

## 🔒 Privacy & Compliance
Overhead wide-angle cameras strictly capture the interior basin of the cart basket. No shopper facial recognition, biometric analysis, or customer tracking is conducted.



