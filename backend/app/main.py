import os
import uuid
import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.database import init_db, SessionLocal, check_db_health, get_db
from app.utils.seed_data import seed_database
from app.websocket.manager import ws_manager
from app.websocket.device_handler import handle_device_websocket
from app.websocket.auth import authenticate_admin_ws, authenticate_cart_ws
from app.ai.feature_extractor import (
    start_background_model_loader,
    is_model_ready,
    get_embedding_metrics,
    MODEL_NAME,
    VECTOR_DIM
)

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
    logger.info("Initializing SmartCart AI backend...")

    # 1. Start ONNX INT8 CLIP model loading in background thread (port opens immediately)
    start_background_model_loader()

    # 2. Initialize database schemas and verify connection
    db_healthy = check_db_health()
    if db_healthy:
        try:
            init_db()
            if SessionLocal:
                db = SessionLocal()
                try:
                    seed_database(db)
                    try:
                        from app.ai.vector_store import VectorStoreMatcher
                        VectorStoreMatcher.sync_to_disk(db)
                    except Exception as ve:
                        logger.warning(f"Vector disk cache sync skipped: {ve}")
                finally:
                    db.close()
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    else:
        logger.warning("Database unreachable at boot. Health check will report database_ok=false.")

    # 3. Start background camera watchdog task (10s offline timeout)
    import asyncio
    from app.services.device_watchdog import run_camera_watchdog
    watchdog_task = asyncio.create_task(run_camera_watchdog())

    yield

    if watchdog_task:
        watchdog_task.cancel()
    logger.info("Shutting down SmartCart AI backend...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API and Real-Time Event Hub for the AI Smart Shopping Cart System",
    lifespan=lifespan
)

# Robust CORS Configuration: Allow frontend origins and local development
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if not cors_origins or "*" in cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$|^https://.*\.onrender\.com$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
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

def _get_health_data():
    """Compute real system health metrics across database, AI model, and filesystem."""
    db_ok = check_db_health()
    model_ok = is_model_ready()

    # Check database migration status (schema_ok: true only when DB is at latest Alembic head)
    schema_ok = False
    if db_ok:
        try:
            from app.migrations import check_schema_health
            schema_ok = check_schema_health()
        except Exception:
            schema_ok = False

    # Verify storage writeability
    storage_ok = False
    try:
        test_file = settings.EVIDENCE_DIR / f".probe_{uuid.uuid4().hex[:6]}"
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        storage_ok = True
    except Exception:
        storage_ok = False

    # Count real stored vectors and enrolled products from database if db is reachable
    vectors_count = 0
    products_enrolled = 0
    if db_ok and SessionLocal:
        try:
            db = SessionLocal()
            try:
                from app.models.product import ProductEmbedding
                vectors_count = db.query(ProductEmbedding).count()
                # Count distinct products that have registered embeddings
                from sqlalchemy import func
                products_enrolled = db.query(func.count(func.distinct(ProductEmbedding.product_id))).scalar() or 0
            finally:
                db.close()
        except Exception:
            pass

    # Read real resident memory (RSS in MB)
    memory_rss_mb = 0.0
    try:
        import psutil
        memory_rss_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass

    overall_status = "HEALTHY"
    if not db_ok:
        overall_status = "UNHEALTHY"
    elif not schema_ok:
        overall_status = "DEGRADED"
    elif not model_ok:
        overall_status = "STARTING"
    elif not storage_ok:
        overall_status = "DEGRADED"

    metrics = get_embedding_metrics()

    return {
        "status": overall_status,
        "schema_ok": schema_ok,
        "database_ok": db_ok,
        "model_loaded": model_ok,
        "model_name": MODEL_NAME,
        "vector_dimension": VECTOR_DIM,
        "storage_ok": storage_ok,
        "vectors_count": vectors_count,
        "products_enrolled": products_enrolled,
        "embed_ms_last": metrics["embed_ms_last"],
        "embed_ms_avg": metrics["embed_ms_avg"],
        "memory_rss_mb": memory_rss_mb,
        "demo_mode": settings.DEMO_MODE,
    }

@app.get("/health")
def health_check(response: Response):
    """
    Comprehensive system health check:
    Reports live status, model state, database connectivity, and vector inventory.
    Returns HTTP 200 when healthy/starting, HTTP 503 when critical DB service is down.
    """
    data = _get_health_data()
    if not data["database_ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return data

@app.get(f"{settings.API_V1_STR}/health")
def api_health_check(response: Response):
    """API v1 health route alias."""
    return health_check(response)

# Real-Time WebSocket Endpoints
@app.websocket("/ws/cart/{cart_id}")
async def websocket_cart_endpoint(
    websocket: WebSocket,
    cart_id: str,
    token: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Cart-specific channel for Shopper Mobile App and Smart Cart Camera Agent.
    Requires a valid shopper session token or staff JWT.
    Rejects unauthenticated connections with close code 1008 (Policy Violation) before accepting.
    """
    auth_token = token or websocket.query_params.get("token") or websocket.headers.get("x-session-token")
    if not authenticate_cart_ws(cart_id, auth_token, db):
        logger.warning(f"Rejecting unauthorized /ws/cart/{cart_id} connection.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect_cart(websocket, cart_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect_cart(websocket, cart_id)
    except Exception as e:
        logger.error(f"WebSocket error on cart {cart_id}: {e}")
        ws_manager.disconnect_cart(websocket, cart_id)

@app.websocket("/ws/admin")
async def websocket_admin_endpoint(
    websocket: WebSocket,
    token: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Store staff admin portal channel for real-time fleet events and alerts.
    Requires a valid staff JWT access token.
    Rejects unauthenticated connections with close code 1008 (Policy Violation) before accepting.
    """
    auth_token = token or websocket.query_params.get("token")
    user = authenticate_admin_ws(auth_token, db)
    if not user:
        logger.warning("Rejecting unauthorized /ws/admin connection.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

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

@app.websocket("/ws/device")
async def websocket_device_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    Dedicated authenticated hardware / webcam streaming channel.
    Authenticates via device token, derives cart context server-side.
    """
    await handle_device_websocket(websocket, token=token)

@app.get("/")
def root():
    return {
        "system": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "ONLINE",
        "docs_url": "/docs",
        "health_url": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
