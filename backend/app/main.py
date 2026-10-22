import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db, SessionLocal
from app.utils.seed_data import seed_database
from app.websocket.manager import ws_manager

# API Routers
from app.api.v1.auth import router as auth_router
from app.api.v1.shopper import router as shopper_router
from app.api.v1.products import router as products_router
from app.api.v1.admin import router as admin_router
from app.api.v1.vision import router as vision_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smartcart")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize SQLite database and populate realistic seed data
    logger.info("Initializing database and seeding catalog...")
    init_db()
    db = SessionLocal()
    try:
        seed_database(db)
        logger.info("Database initialized and catalog seeded successfully.")
    finally:
        db.close()
    yield
    logger.info("Shutting down SmartCart AI backend...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API and Real-Time Event Hub for the AI Smart Shopping Cart System",
    lifespan=lifespan
)

# Enable CORS for local dev frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static uploads directory for images & snapshots
app.mount("/uploads", StaticFiles(directory=str(settings.UPLOADS_DIR)), name="uploads")

# Include API Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(shopper_router, prefix=settings.API_V1_STR)
app.include_router(products_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(vision_router, prefix=settings.API_V1_STR)

# Real-Time WebSocket Endpoints
@app.websocket("/ws/cart/{cart_id}")
async def websocket_cart_endpoint(websocket: WebSocket, cart_id: str):
    """Cart-specific channel for Shopper Mobile App and Smart Cart Camera Agent."""
    await ws_manager.connect_cart(websocket, cart_id)
    try:
        while True:
            # Keep connection alive & handle incoming pings
            data = await websocket.receive_text()
            # Echo or handle client pings
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect_cart(websocket, cart_id)
    except Exception as e:
        logger.error(f"WebSocket error on cart {cart_id}: {e}")
        ws_manager.disconnect_cart(websocket, cart_id)

@app.websocket("/ws/admin")
async def websocket_admin_endpoint(websocket: WebSocket):
    """Store staff admin portal channel for real-time fleet events and alerts."""
    await ws_manager.connect_admin(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect_admin(websocket)
    except Exception as e:
        logger.error(f"WebSocket error on admin channel: {e}")
        ws_manager.disconnect_admin(websocket)

@app.get("/")
def root():
    return {
        "system": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "ONLINE",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
