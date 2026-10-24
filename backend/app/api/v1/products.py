import csv
import io
import json
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.product import Product, ProductImage, ProductEmbedding
from app.models.session import CartSession, CartItem
from app.models.transaction import AuditLog
from app.models.user import User
from app.api.v1.auth import require_admin_or_manager
from app.ai.vector_store import VectorStoreMatcher
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, BulkUploadResponse

router = APIRouter(prefix="/products", tags=["Product Catalog"])

@router.get("", response_model=List[ProductResponse])
def list_products(
    search: Optional[str] = Query(None, description="Search by name, brand, or barcode"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """Retrieve catalog products with search and category filtering."""
    query = db.query(Product).filter(Product.is_active == True)
    if search:
        s = f"%{search}%"
        query = query.filter((Product.name.ilike(s)) | (Product.brand.ilike(s)) | (Product.barcode.ilike(s)))
    if category and category != "All":
        query = query.filter(Product.category == category)
    
    products = query.order_by(Product.name.asc()).all()
    
    result = []
    for p in products:
        has_emb = db.query(ProductEmbedding).filter(ProductEmbedding.product_id == p.id).count() > 0
        resp = ProductResponse(
            id=p.id,
            barcode=p.barcode,
            name=p.name,
            brand=p.brand,
            category=p.category,
            price=p.price,
            discount_price=p.discount_price,
            weight_grams=p.weight_grams,
            tax_rate=p.tax_rate,
            stock_quantity=p.stock_quantity,
            primary_image_url=p.primary_image_url,
            is_active=p.is_active,
            created_at=p.created_at,
            images=[],
            has_embeddings=has_emb
        )
        result.append(resp)
    return result

@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: str, db: Session = Depends(get_db)):
    """Fetch single product details with 360 image gallery and embedding status."""
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    
    has_emb = db.query(ProductEmbedding).filter(ProductEmbedding.product_id == p.id).count() > 0
    return ProductResponse(
        id=p.id,
        barcode=p.barcode,
        name=p.name,
        brand=p.brand,
        category=p.category,
        price=p.price,
        discount_price=p.discount_price,
        weight_grams=p.weight_grams,
        tax_rate=p.tax_rate,
        stock_quantity=p.stock_quantity,
        primary_image_url=p.primary_image_url,
        is_active=p.is_active,
        created_at=p.created_at,
        images=[img for img in p.images],
        has_embeddings=has_emb
    )

@router.post("", response_model=ProductResponse)
def create_product(prod_in: ProductCreate, db: Session = Depends(get_db)):
    """Add a new product to supermarket inventory."""
    existing = db.query(Product).filter(Product.barcode == prod_in.barcode).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Product with barcode '{prod_in.barcode}' already exists ('{existing.name}'). Please provide a unique barcode."
        )

    product = Product(**prod_in.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductResponse(
        id=product.id,
        barcode=product.barcode,
        name=product.name,
        brand=product.brand,
        category=product.category,
        price=product.price,
        discount_price=product.discount_price,
        weight_grams=product.weight_grams,
        tax_rate=product.tax_rate,
        stock_quantity=product.stock_quantity,
        primary_image_url=product.primary_image_url,
        is_active=product.is_active,
        created_at=product.created_at,
        images=[],
        has_embeddings=False
    )

@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: str, prod_in: ProductUpdate, db: Session = Depends(get_db)):
    """Update existing product details."""
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = prod_in.model_dump(exclude_unset=True)
    if "barcode" in update_data and update_data["barcode"] != p.barcode:
        dup = db.query(Product).filter(Product.barcode == update_data["barcode"], Product.id != product_id).first()
        if dup:
            raise HTTPException(
                status_code=400,
                detail=f"Barcode '{update_data['barcode']}' is already in use by '{dup.name}'. Each product must have a unique barcode."
            )
        # Keep barcodes on existing embeddings in sync
        for emb in p.embeddings:
            emb.barcode = update_data["barcode"]

    for field, val in update_data.items():
        setattr(p, field, val)
    db.commit()
    db.refresh(p)
    has_emb = db.query(ProductEmbedding).filter(ProductEmbedding.product_id == p.id).count() > 0
    return ProductResponse(
        id=p.id,
        barcode=p.barcode,
        name=p.name,
        brand=p.brand,
        category=p.category,
        price=p.price,
        discount_price=p.discount_price,
        weight_grams=p.weight_grams,
        tax_rate=p.tax_rate,
        stock_quantity=p.stock_quantity,
        primary_image_url=p.primary_image_url,
        is_active=p.is_active,
        created_at=p.created_at,
        images=[img for img in p.images],
        has_embeddings=has_emb
    )

class BulkDeleteRequest(BaseModel):
    product_ids: List[str]

@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Soft delete product from active catalog:
    1. Blocks deletion if product is currently present in an active shopping cart.
    2. Removes embeddings from vector store so it is no longer recognized.
    3. Soft deletes (marks is_active=False, is_deleted=True) so past receipts still show the product.
    4. Records deletion in immutable audit log (who, what, when). Only Admin/Manager permitted.
    """
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p or not p.is_active:
        raise HTTPException(status_code=404, detail="Product not found or already deleted")

    # 1. Block deletion if product is in an active cart
    active_items = (
        db.query(CartItem)
        .join(CartSession, CartItem.session_id == CartSession.id)
        .filter(
            CartItem.product_id == p.id,
            CartItem.status != "REMOVED",
            CartSession.status == "ACTIVE"
        )
        .all()
    )
    if active_items:
        cart_numbers = set()
        for item in active_items:
            if item.session and item.session.cart:
                cart_numbers.add(item.session.cart.cart_number)
        carts_str = ", ".join(cart_numbers) if cart_numbers else "one or more active carts"
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete '{p.name}'. This product is currently in active shopping cart(s): {carts_str}. Deletion is blocked until the shopper completes checkout or removes the item."
        )

    # 2. Remove embeddings from vector store so it is no longer recognized
    removed_embeddings_count = VectorStoreMatcher.delete_embeddings_for_product(db, p.id)

    # 3. Soft delete (mark as inactive & deleted)
    p.is_active = False
    p.is_deleted = True

    # 4. Record in audit log (who, what, when)
    audit = AuditLog(
        user_id=current_user.id,
        action="DELETE_PRODUCT",
        entity_type="PRODUCT",
        entity_id=p.id,
        details_json=json.dumps({
            "barcode": p.barcode,
            "product_name": p.name,
            "brand": p.brand,
            "deleted_by_email": current_user.email,
            "deleted_by_name": current_user.full_name,
            "deleted_by_role": current_user.role,
            "embeddings_removed": removed_embeddings_count,
            "deleted_at": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "message": f"Product '{p.name}' deleted successfully.",
        "product_id": p.id,
        "product_name": p.name,
        "embeddings_removed": removed_embeddings_count
    }

@router.post("/{product_id}/restore")
def restore_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Restore a previously deleted product back to active catalog."""
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    p.is_active = True
    p.is_deleted = False

    audit = AuditLog(
        user_id=current_user.id,
        action="RESTORE_PRODUCT",
        entity_type="PRODUCT",
        entity_id=p.id,
        details_json=json.dumps({
            "barcode": p.barcode,
            "product_name": p.name,
            "restored_by_email": current_user.email,
            "restored_by_role": current_user.role,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    db.refresh(p)
    return {"status": "SUCCESS", "message": f"Product '{p.name}' restored successfully."}

@router.post("/bulk-delete")
def bulk_delete_products(
    req: BulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Bulk soft delete products, removing their AI embeddings and logging audit trail."""
    if not req.product_ids:
        raise HTTPException(status_code=400, detail="No product IDs provided for deletion.")

    # 1. Check for active cart conflicts across all requested items
    active_conflicts = (
        db.query(CartItem)
        .join(CartSession, CartItem.session_id == CartSession.id)
        .filter(
            CartItem.product_id.in_(req.product_ids),
            CartItem.status != "REMOVED",
            CartSession.status == "ACTIVE"
        )
        .all()
    )
    if active_conflicts:
        conflict_prods = set()
        conflict_carts = set()
        for ci in active_conflicts:
            if ci.product:
                conflict_prods.add(ci.product.name)
            if ci.session and ci.session.cart:
                conflict_carts.add(ci.session.cart.cart_number)
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete selected products. The following item(s) are currently in active cart(s) ({', '.join(conflict_carts)}): {', '.join(conflict_prods)}. Deletion is blocked until carts complete checkout or items are removed."
        )

    deleted_count = 0
    deleted_names = []

    for pid in req.product_ids:
        p = db.query(Product).filter(Product.id == pid, Product.is_active == True).first()
        if not p:
            continue

        VectorStoreMatcher.delete_embeddings_for_product(db, p.id)
        p.is_active = False
        p.is_deleted = True

        audit = AuditLog(
            user_id=current_user.id,
            action="BULK_DELETE_PRODUCT",
            entity_type="PRODUCT",
            entity_id=p.id,
            details_json=json.dumps({
                "barcode": p.barcode,
                "product_name": p.name,
                "deleted_by_email": current_user.email,
                "deleted_by_role": current_user.role,
                "timestamp": datetime.utcnow().isoformat()
            }),
            created_at=datetime.utcnow()
        )
        db.add(audit)
        deleted_count += 1
        deleted_names.append(p.name)

    db.commit()
    return {
        "status": "SUCCESS",
        "message": f"Successfully deleted {deleted_count} product(s).",
        "deleted_count": deleted_count,
        "deleted_names": deleted_names
    }

@router.post("/bulk-upload", response_model=BulkUploadResponse)
async def bulk_upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import inventory catalog via CSV file."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    content = await file.read()
    decoded = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))

    success_count = 0
    error_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=2):
        barcode = row.get("barcode", "").strip()
        name = row.get("name", "").strip()
        price_str = row.get("price", "").strip()

        if not barcode or not name or not price_str:
            errors.append(f"Row {row_idx}: Missing required fields (barcode, name, price)")
            error_count += 1
            continue

        try:
            price = float(price_str)
            discount_price = float(row.get("discount_price")) if row.get("discount_price") else None
            weight_grams = int(row.get("weight_grams", 100))
            tax_rate = float(row.get("tax_rate", 5.0))
            stock = int(row.get("stock_quantity", 50))
            brand = row.get("brand", "Generic").strip()
            category = row.get("category", "General").strip()
            image_url = row.get("primary_image_url", "").strip() or None

            existing = db.query(Product).filter(Product.barcode == barcode).first()
            if existing:
                existing.name = name
                existing.price = price
                existing.discount_price = discount_price
                existing.brand = brand
                existing.category = category
                existing.weight_grams = weight_grams
                existing.tax_rate = tax_rate
                existing.stock_quantity = stock
                if image_url:
                    existing.primary_image_url = image_url
            else:
                new_p = Product(
                    barcode=barcode,
                    name=name,
                    brand=brand,
                    category=category,
                    price=price,
                    discount_price=discount_price,
                    weight_grams=weight_grams,
                    tax_rate=tax_rate,
                    stock_quantity=stock,
                    primary_image_url=image_url
                )
                db.add(new_p)
            success_count += 1
        except Exception as e:
            errors.append(f"Row {row_idx} ({barcode}): {str(e)}")
            error_count += 1

    db.commit()
    return BulkUploadResponse(
        success_count=success_count,
        error_count=error_count,
        errors=errors[:10]  # Return first 10 errors
    )
