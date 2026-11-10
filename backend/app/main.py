import os
import uuid
import time
import json
import asyncio
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, status, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings, is_valid_base_url, get_base_url_host
from app.database import init_db, SessionLocal, check_db_health, get_db
from app.utils.seed_data import seed_database
from app.utils.perf import reset_query_count, get_query_count, db_query_counter
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
            from app.migrations import refresh_schema_cache
            refresh_schema_cache()

            from app.services.scan_worker import cleanup_orphaned_jobs_on_startup
            cleanup_orphaned_jobs_on_startup()

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
        expose_headers=["X-Response-Time-Ms", "X-DB-Queries"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Response-Time-Ms", "X-DB-Queries"],
    )

# Performance Monitoring Middleware (Request Timing & Database Query Count)
@app.middleware("http")
async def performance_metrics_middleware(request: Request, call_next):
    token = reset_query_count()
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        queries = get_query_count()
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
        response.headers["X-DB-Queries"] = str(queries)
        if duration_ms > 150 or request.url.path.startswith("/api/v1/"):
            logger.info(f"[PERF] {request.method} {request.url.path} -> {response.status_code} ({duration_ms:.2f}ms, {queries} db queries)")
        return response
    finally:
        db_query_counter.reset(token)

# Mount static uploads directory for images & snapshots
app.mount("/uploads", StaticFiles(directory=str(settings.UPLOADS_DIR)), name="uploads")

# Include API Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(shopper_router, prefix=settings.API_V1_STR)
app.include_router(products_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(vision_router, prefix=settings.API_V1_STR)

from app.utils.sanitization import sanitize_secrets, SanitizingLogFilter
from app.api.v1.auth import get_current_user

# Attach secret sanitization filter to root and uvicorn logging handlers
_sanitizing_filter = SanitizingLogFilter()
for handler in logging.root.handlers:
    handler.addFilter(_sanitizing_filter)
for log_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
    _logger = logging.getLogger(log_name)
    _logger.addFilter(_sanitizing_filter)
    for h in _logger.handlers:
        h.addFilter(_sanitizing_filter)


def _get_public_health_data():
    """
    Minimal public health check:
    Returns strictly {status, database_ok, schema_ok, model_loaded}.
    Uses cheap SELECT 1 (cached for up to 10s) and cached schema health.
    Never opens Alembic contexts on requests and never includes secrets.
    """
    db_ok = check_db_health(max_age_seconds=10.0)
    model_ok = is_model_ready()

    schema_ok = False
    if db_ok:
        try:
            from app.migrations import check_schema_health
            schema_ok = check_schema_health()
        except Exception:
            schema_ok = False

    overall_status = "HEALTHY"
    if not db_ok:
        overall_status = "UNHEALTHY"
    elif not schema_ok:
        overall_status = "DEGRADED"
    elif not model_ok:
        overall_status = "STARTING"

    return {
        "status": overall_status,
        "database_ok": db_ok,
        "schema_ok": schema_ok,
        "model_loaded": model_ok,
    }


# In-memory TTL cache for expensive database health aggregations (15s TTL, satisfies 10-30s requirement)
_detailed_health_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "total_products": 0,
    "vectors_count": 0,
    "products_enrolled": 0,
    "storage_ok": True,
    "last_job_data": None,
}
HEALTH_CACHE_TTL_SECONDS = 15.0


def _get_detailed_health_data(fresh: bool = False):
    """
    Full diagnostic metrics for authenticated staff portal (/admin/system-health).
    Always masks database credentials, passwords, and tokens.
    Caches expensive DB count aggregations and storage probes for 15s to guarantee sub-millisecond responses.
    """
    db_ok = check_db_health()
    model_ok = is_model_ready()

    schema_ok = False
    current_revision = None
    head_revision = None
    migration_error = None
    if db_ok:
        try:
            from app.migrations import get_schema_info
            schema_info = get_schema_info()
            schema_ok = schema_info.get("is_up_to_date", False)
            current_revision = schema_info.get("current_revision")
            head_revision = schema_info.get("head_revision")
            migration_error = sanitize_secrets(schema_info.get("migration_error"))
        except Exception as e:
            schema_ok = False
            migration_error = sanitize_secrets(str(e)[:200])

    now = time.time()
    cache_valid = (not fresh) and (now - _detailed_health_cache["timestamp"] < HEALTH_CACHE_TTL_SECONDS)

    if cache_valid:
        storage_ok = _detailed_health_cache["storage_ok"]
        total_products = _detailed_health_cache["total_products"]
        vectors_count = _detailed_health_cache["vectors_count"]
        products_enrolled = _detailed_health_cache["products_enrolled"]
        last_job_data = _detailed_health_cache["last_job_data"]
    else:
        storage_ok = False
        try:
            test_file = settings.EVIDENCE_DIR / f".probe_{uuid.uuid4().hex[:6]}"
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            storage_ok = True
        except Exception:
            storage_ok = False

        total_products = 0
        vectors_count = 0
        products_enrolled = 0
        last_job_data = None
        if db_ok and SessionLocal:
            try:
                db = SessionLocal()
                try:
                    from app.models.product import Product, ProductEmbedding
                    from app.models.scan_job import ScanJob
                    from sqlalchemy import func
                    total_products = db.query(Product).count()
                    vectors_count = db.query(ProductEmbedding).count()
                    products_enrolled = db.query(func.count(func.distinct(ProductEmbedding.product_id))).scalar() or 0

                    last_job = db.query(ScanJob).order_by(ScanJob.created_at.desc()).first()
                    if last_job:
                        dur_ms = 0.0
                        if last_job.created_at and last_job.updated_at:
                            dur_ms = round((last_job.updated_at - last_job.created_at).total_seconds() * 1000.0, 1)
                        last_job_data = {
                            "id": last_job.id,
                            "status": last_job.status,
                            "duration_ms": dur_ms,
                        }
                finally:
                    db.close()
            except Exception:
                pass

        _detailed_health_cache["timestamp"] = now
        _detailed_health_cache["storage_ok"] = storage_ok
        _detailed_health_cache["total_products"] = total_products
        _detailed_health_cache["vectors_count"] = vectors_count
        _detailed_health_cache["products_enrolled"] = products_enrolled
        _detailed_health_cache["last_job_data"] = last_job_data

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

    worker_metrics = {}
    try:
        from app.services.scan_worker import get_worker_timing_metrics
        worker_metrics = get_worker_timing_metrics()
    except Exception:
        pass

    # Fall back to DB last_job_data if worker hasn't processed a scan job during this process runtime
    if not worker_metrics.get("last_job_id") and last_job_data:
        worker_metrics["last_job_id"] = last_job_data["id"]
        worker_metrics["last_job_status"] = last_job_data["status"]
        if worker_metrics.get("total_duration_ms", 0.0) == 0.0 and last_job_data.get("duration_ms"):
            worker_metrics["total_duration_ms"] = last_job_data["duration_ms"]

    storage_type = "Local Disk"
    try:
        from app.services.storage_service import StorageService
        storage_svc = StorageService()
        if storage_svc.is_supabase_configured:
            storage_type = "Supabase Storage (Cloud)"
    except Exception:
        pass

    base_url_host = get_base_url_host(settings.BASE_URL)
    base_url_valid = is_valid_base_url(settings.BASE_URL, demo_mode=settings.DEMO_MODE)
    base_url_warning = None if base_url_valid else "Set BASE_URL to your public https address"

    return {
        "status": overall_status,
        "database_ok": db_ok,
        "schema_ok": schema_ok,
        "model_loaded": model_ok,
        "current_revision": current_revision,
        "head_revision": head_revision,
        "migration_error": migration_error,
        "model_name": MODEL_NAME,
        "vector_dimension": VECTOR_DIM,
        "storage_ok": storage_ok,
        "storage_type": storage_type,
        "total_products": total_products,
        "vectors_count": vectors_count,
        "products_enrolled": products_enrolled,
        "embed_ms_last": metrics["embed_ms_last"],
        "embed_ms_avg": metrics["embed_ms_avg"],
        "scan_worker_metrics": worker_metrics,
        "memory_rss_mb": memory_rss_mb,
        "ram_budget_mb": 512.0,
        "demo_mode": settings.DEMO_MODE,
        "use_mock": settings.USE_MOCK,
        "base_url_host": base_url_host,
        "base_url_valid": base_url_valid,
        "base_url_warning": base_url_warning,
    }


# Backwards compatibility alias
_get_health_data = _get_public_health_data


@app.get("/health")
def health_check(response: Response):
    """
    Public health check: minimal status indicators.
    Returns HTTP 200 when healthy/starting, HTTP 503 when critical DB service is down.
    Never exposes internal configurations, revisions, or credentials.
    """
    data = _get_public_health_data()
    if not data["database_ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return data


@app.get(f"{settings.API_V1_STR}/health")
def api_health_check(response: Response):
    """API v1 health route alias (minimal public output)."""
    return health_check(response)


@app.get("/admin/system-health")
@app.get(f"{settings.API_V1_STR}/admin/system-health")
def admin_system_health(fresh: bool = False, current_user=Depends(get_current_user)):
    """
    Detailed system health diagnostics for authenticated staff.
    Includes schema revisions, sanitized migration error (if any), model metrics,
    memory usage, vector counts, storage type, and worker timings.
    Never exposes raw database credentials or connection strings.
    """
    return _get_detailed_health_data(fresh=fresh)

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
    Supports token via query parameter, 'x-session-token' header, OR first-message auth:
    {"type": "auth", "token": "<token>"}.
    """
    auth_token = token or websocket.query_params.get("token") or websocket.headers.get("x-session-token")
    if not auth_token:
        # Await first message authentication
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            data = json.loads(raw)
            if isinstance(data, dict):
                auth_token = data.get("token")
        except Exception:
            auth_token = None

        if not authenticate_cart_ws(cart_id, auth_token, db):
            logger.warning(f"Rejecting unauthorized /ws/cart/{cart_id} first-message connection.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.send_json({"type": "auth_ok"})
        await ws_manager.connect_cart(websocket, cart_id)
    else:
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
    Supports token via query parameter OR first-message auth:
    {"type": "auth", "token": "<jwt>"}.
    """
    auth_token = token or websocket.query_params.get("token")
    if not auth_token:
        # Await first message authentication
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            data = json.loads(raw)
            if isinstance(data, dict):
                auth_token = data.get("token")
        except Exception:
            auth_token = None

        user = authenticate_admin_ws(auth_token, db)
        if not user:
            logger.warning("Rejecting unauthorized /ws/admin first-message connection.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.send_json({"type": "auth_ok"})
        await ws_manager.connect_admin(websocket)
    else:
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
