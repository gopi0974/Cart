from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.alert import Alert, ReviewCase
from app.models.transaction import Transaction, ModelVersion, AuditLog
from app.models.product import Product
from app.schemas.cart import CartResponse, CartCreate
from app.schemas.alert import AlertResponse, AlertResolutionRequest, ReviewCaseResponse, ReviewDecisionRequest
from app.services.alert_service import AlertService
from app.services.session_service import SessionService
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/admin", tags=["Admin Portal"])

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """Executive KPI metrics and live operational status."""
    total_carts = db.query(Cart).count()
    active_carts = db.query(Cart).filter(Cart.status.in_(["ACTIVE", "ALERT"])).count()
    open_incidents = db.query(Alert).filter(Alert.status == "OPEN").count()
    
    # Revenue today
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_txs = db.query(Transaction).filter(
        Transaction.created_at >= today_start,
        Transaction.status == "SUCCESS"
    ).all()
    revenue_today = sum(tx.amount for tx in today_txs)
    
    # Active model accuracy
    active_model = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    ai_accuracy = round(active_model.accuracy * 100, 1) if active_model else 98.4

    # Latest 5 incidents
    recent_alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(5).all()

    return {
        "active_carts": active_carts,
        "total_carts": total_carts,
        "revenue_today": round(revenue_today, 2),
        "open_incidents": open_incidents,
        "ai_accuracy": ai_accuracy,
        "recent_alerts": [
            {
                "id": a.id,
                "cart_number": a.cart.cart_number if a.cart else "N/A",
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "status": a.status,
                "created_at": a.created_at
            }
            for a in recent_alerts
        ]
    }

@router.get("/carts", response_model=List[CartResponse])
def list_carts(db: Session = Depends(get_db)):
    """Retrieve all physical carts with health, battery, camera, and active session details."""
    carts = db.query(Cart).order_by(Cart.cart_number.asc()).all()
    results = []
    for c in carts:
        active_sess = db.query(CartSession).filter(
            CartSession.cart_id == c.id,
            CartSession.status == "ACTIVE"
        ).first()
        
        results.append(CartResponse(
            id=c.id,
            cart_number=c.cart_number,
            qr_code_token=c.qr_code_token,
            status=c.status,
            battery_level=c.battery_level,
            camera_status=c.camera_status,
            last_heartbeat=c.last_heartbeat,
            active_session_id=active_sess.id if active_sess else None,
            item_count=active_sess.item_count if active_sess else 0,
            total_amount=active_sess.total_amount if active_sess else 0.0
        ))
    return results

@router.post("/carts", response_model=CartResponse)
def register_cart(cart_in: CartCreate, db: Session = Depends(get_db)):
    """Register new smart cart in the supermarket fleet."""
    cart_num = cart_in.cart_number.upper().strip()
    existing = db.query(Cart).filter(Cart.cart_number == cart_num).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Cart '{cart_num}' is already registered.")

    new_cart = Cart(
        cart_number=cart_num,
        qr_code_token=f"QR-{cart_num}",
        status="IDLE",
        battery_level=100,
        camera_status="ONLINE"
    )
    db.add(new_cart)
    db.commit()
    db.refresh(new_cart)
    return CartResponse(
        id=new_cart.id,
        cart_number=new_cart.cart_number,
        qr_code_token=new_cart.qr_code_token,
        status=new_cart.status,
        battery_level=new_cart.battery_level,
        camera_status=new_cart.camera_status,
        last_heartbeat=new_cart.last_heartbeat
    )

@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by OPEN, RESOLVED, DISMISSED"),
    db: Session = Depends(get_db)
):
    """Retrieve security incidents and mismatch alerts."""
    query = db.query(Alert)
    if status and status != "ALL":
        query = query.filter(Alert.status == status)
    alerts = query.order_by(Alert.created_at.desc()).all()
    
    return [
        AlertResponse(
            id=a.id,
            cart_id=a.cart_id,
            cart_number=a.cart.cart_number if a.cart else "N/A",
            session_id=a.session_id,
            alert_type=a.alert_type,
            severity=a.severity,
            message=a.message,
            evidence_snapshot_url=a.evidence_snapshot_url,
            status=a.status,
            resolved_by=a.resolved_by,
            resolution_notes=a.resolution_notes,
            created_at=a.created_at,
            resolved_at=a.resolved_at
        )
        for a in alerts
    ]

@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def resolve_alert(alert_id: str, req: AlertResolutionRequest, db: Session = Depends(get_db)):
    """Resolve or dismiss an active incident."""
    alert = await AlertService.resolve_alert(
        db=db,
        alert_id=alert_id,
        user_id="STAFF_MANUAL",
        notes=req.resolution_notes,
        action=req.action
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return AlertResponse(
        id=alert.id,
        cart_id=alert.cart_id,
        cart_number=alert.cart.cart_number if alert.cart else "N/A",
        session_id=alert.session_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
        evidence_snapshot_url=alert.evidence_snapshot_url,
        status=alert.status,
        resolved_by=alert.resolved_by,
        resolution_notes=alert.resolution_notes,
        created_at=alert.created_at,
        resolved_at=alert.resolved_at
    )

@router.get("/review-queue", response_model=List[ReviewCaseResponse])
def get_review_queue(db: Session = Depends(get_db)):
    """Retrieve low-confidence cases requiring staff human-in-the-loop validation."""
    cases = db.query(ReviewCase).filter(ReviewCase.status == "PENDING").all()
    result = []
    for c in cases:
        scanned_prod = None
        if c.scanned_barcode:
            scanned_prod = db.query(Product).filter(Product.barcode == c.scanned_barcode).first()
        
        cart = db.query(Cart).filter(Cart.id == c.cart_id).first()
        result.append(ReviewCaseResponse(
            id=c.id,
            alert_id=c.alert_id,
            cart_id=c.cart_id,
            cart_number=cart.cart_number if cart else "N/A",
            scanned_barcode=c.scanned_barcode,
            scanned_product_name=scanned_prod.name if scanned_prod else None,
            scanned_product_image=scanned_prod.primary_image_url if scanned_prod else None,
            predicted_product_id=c.predicted_product_id,
            predicted_product_name=c.predicted_product.name if c.predicted_product else None,
            confidence=c.confidence,
            evidence_image_url=c.evidence_image_url,
            status=c.status,
            created_at=c.created_at
        ))
    return result

@router.post("/review-queue/{case_id}/decision")
async def submit_review_decision(case_id: str, req: ReviewDecisionRequest, db: Session = Depends(get_db)):
    """Approve or reject a low-confidence detection."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Review case not found")

    case.status = "APPROVED" if req.decision == "APPROVE" else "REJECTED"
    case.feedback_saved_for_training = req.save_for_training
    
    # If approved, resolve the associated alert
    if req.decision == "APPROVE":
        await AlertService.resolve_alert(
            db=db,
            alert_id=case.alert_id,
            user_id="STAFF_REVIEWER",
            notes=f"Staff approved match. {req.notes or ''}",
            action="RESOLVED"
        )
        # If there's an active session with this barcode in PENDING, verify it!
        if case.scanned_barcode:
            active_session = db.query(CartSession).filter(
                CartSession.cart_id == case.cart_id,
                CartSession.status == "ACTIVE"
            ).first()
            if active_session:
                await SessionService.verify_item_placement(
                    db=db,
                    session_id=active_session.id,
                    barcode=case.scanned_barcode,
                    confidence=1.0,
                    evidence_url=case.evidence_image_url
                )
    else:
        # Rejected
        alert = db.query(Alert).filter(Alert.id == case.alert_id).first()
        if alert:
            alert.status = "IN_REVIEW"
            alert.resolution_notes = f"Staff confirmed mismatch. Security intervention required. {req.notes or ''}"

    db.commit()
    return {"status": "SUCCESS", "message": f"Review case {case.status.lower()}."}

@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    """List AI model checkpoints, accuracy stats, and active version."""
    models = db.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()
    return models

@router.post("/models/{model_id}/activate")
def activate_model(model_id: str, db: Session = Depends(get_db)):
    """One-click rollback or activation of an AI model version."""
    target_model = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not target_model:
        raise HTTPException(status_code=404, detail="Model version not found")

    # Deactivate all others
    db.query(ModelVersion).update({ModelVersion.is_active: False})
    target_model.is_active = True
    db.commit()
    return {"status": "SUCCESS", "message": f"Activated model {target_model.version_tag}."}

@router.get("/reports")
def get_reports(db: Session = Depends(get_db)):
    """Sales, mismatch, and theft prevention statistical report."""
    total_txs = db.query(Transaction).filter(Transaction.status == "SUCCESS").all()
    gross_sales = sum(tx.amount for tx in total_txs)
    
    total_alerts = db.query(Alert).count()
    unscanned_alerts = db.query(Alert).filter(Alert.alert_type == "UNSCANNED_ITEM").count()
    mismatch_alerts = db.query(Alert).filter(Alert.alert_type == "MISMATCH_ITEM").count()

    return {
        "total_transactions": len(total_txs),
        "gross_sales": round(gross_sales, 2),
        "theft_prevention_stats": {
            "total_alerts_intercepted": total_alerts,
            "unscanned_items_prevented": unscanned_alerts,
            "mismatch_items_caught": mismatch_alerts,
            "estimated_loss_prevented": round(unscanned_alerts * 125.0 + mismatch_alerts * 85.0, 2)
        }
    }
