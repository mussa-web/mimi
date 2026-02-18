import csv
import io
import math
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_permission, require_system_owner
from app.db.database import get_db
from app.models.inventory import (
    Expense,
    Product,
    Purchase,
    Sale,
    SaleReturn,
    Shop,
    Stock,
    StockAdjustment,
    StockTransfer,
    Supplier,
)
from app.models.user import User, UserRole
from app.schemas.inventory import (
    ChartBarItemOut,
    DashboardSummaryOut,
    DashboardChartsOut,
    ExpenseCreate,
    ExpenseUpdate,
    ExpenseOut,
    LowStockItemOut,
    InventoryAuditItemOut,
    PieSliceOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    ProductProfitOut,
    PurchaseCreate,
    PurchaseOut,
    PurchaseUpdate,
    ReorderSuggestionOut,
    ProfitReportOut,
    SaleCreateRequest,
    SaleReturnCreateRequest,
    SaleReturnOut,
    SaleOut,
    ShopCreate,
    ShopOut,
    ShopUpdate,
    StockOut,
    StockAdjustRequest,
    StockAdjustmentOut,
    StockTransferOut,
    StockUpsertRequest,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
    TrendPointOut,
    TransferStockRequest,
    TransferStockUpdate,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _get_assigned_shop(db: Session, current_user: User) -> Shop:
    shop = db.get(Shop, current_user.shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned shop not found for current user")
    return shop


def _is_system_owner(current_user: User) -> bool:
    return current_user.role == UserRole.SYSTEM_OWNER or current_user.is_global_access


def _enforce_shop_scope(request_shop_id: int, assigned_shop_id: int) -> None:
    if request_shop_id != assigned_shop_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-shop access is not allowed")


def _resolve_effective_shop_id(
    db: Session,
    current_user: User,
    requested_shop_id: int | None,
) -> int | None:
    if _is_system_owner(current_user):
        return requested_shop_id
    assigned_shop = _get_assigned_shop(db, current_user)
    if requested_shop_id is not None:
        _enforce_shop_scope(requested_shop_id, assigned_shop.id)
    return assigned_shop.id


def _bucket_start(value: datetime, granularity: str) -> datetime:
    if granularity == "month":
        return datetime(value.year, value.month, 1)
    if granularity == "week":
        start_date = value.date() - timedelta(days=value.weekday())
        return datetime(start_date.year, start_date.month, start_date.day)
    return datetime(value.year, value.month, value.day)


def _bucket_label(value: datetime, granularity: str) -> str:
    if granularity == "month":
        return value.strftime("%Y-%m")
    if granularity == "week":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return value.strftime("%Y-%m-%d")


def _apply_sale_scope(
    query,
    *,
    effective_shop_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    if effective_shop_id is not None:
        query = query.where(Sale.shop_id == effective_shop_id)
    if date_from is not None:
        query = query.where(Sale.sold_at >= date_from)
    if date_to is not None:
        query = query.where(Sale.sold_at <= date_to)
    return query


def _apply_return_scope(
    query,
    *,
    effective_shop_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    if effective_shop_id is not None:
        query = query.where(SaleReturn.shop_id == effective_shop_id)
    if date_from is not None:
        query = query.where(SaleReturn.returned_at >= date_from)
    if date_to is not None:
        query = query.where(SaleReturn.returned_at <= date_to)
    return query


@router.post("/shops", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
def create_shop(
    payload: ShopCreate,
    _: User = Depends(require_system_owner),
    db: Session = Depends(get_db),
):
    shop = Shop(code=payload.code.strip().upper(), name=payload.name.strip(), location=payload.location)
    db.add(shop)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shop code already exists") from exc
    db.refresh(shop)
    return shop


@router.patch("/shops/{shop_id}", response_model=ShopOut)
def update_shop(
    shop_id: int,
    payload: ShopUpdate,
    _: User = Depends(require_system_owner),
    db: Session = Depends(get_db),
):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")

    if payload.code is not None:
        shop.code = payload.code.strip().upper()
    if payload.name is not None:
        shop.name = payload.name.strip()
    if payload.location is not None:
        shop.location = payload.location.strip() or None
    if payload.is_active is not None:
        shop.is_active = payload.is_active
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shop code already exists") from exc
    db.refresh(shop)
    return shop


@router.delete("/shops/{shop_id}", response_model=ShopOut)
def archive_shop(
    shop_id: int,
    _: User = Depends(require_system_owner),
    db: Session = Depends(get_db),
):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    shop.is_active = False
    db.commit()
    db.refresh(shop)
    return shop


@router.post("/shops/{shop_id}/activate", response_model=ShopOut)
def activate_shop(
    shop_id: int,
    _: User = Depends(require_system_owner),
    db: Session = Depends(get_db),
):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    shop.is_active = True
    db.commit()
    db.refresh(shop)
    return shop


@router.get("/shops", response_model=list[ShopOut])
def list_shops(
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    if _is_system_owner(current_user):
        return list(db.scalars(select(Shop).order_by(Shop.name.asc())).all())
    assigned_shop = _get_assigned_shop(db, current_user)
    return [assigned_shop]


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if _is_system_owner(current_user):
        target_shop_id = payload.shop_id if payload.shop_id is not None else current_user.shop_id
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if payload.shop_id is not None and payload.shop_id != assigned_shop.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-shop access is not allowed")
        target_shop_id = assigned_shop.id

    target_shop = db.get(Shop, target_shop_id)
    if not target_shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not target_shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create product for inactive shop")

    product = Product(
        shop_id=target_shop_id,
        sku=payload.sku.strip().upper(),
        name=payload.name.strip(),
        unit=payload.unit,
        description=payload.description,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product SKU already exists for this shop",
        ) from exc
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(product.shop_id, assigned_shop.id)

    if payload.sku is not None:
        product.sku = payload.sku.strip().upper()
    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.unit is not None:
        product.unit = payload.unit
    if payload.description is not None:
        product.description = payload.description.strip() or None
    if payload.is_active is not None:
        product.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product SKU already exists for this shop") from exc
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", response_model=ProductOut)
def archive_product(
    product_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(product.shop_id, assigned_shop.id)

    product.is_active = False
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/activate", response_model=ProductOut)
def activate_product(
    product_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(product.shop_id, assigned_shop.id)

    shop = db.get(Shop, product.shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate product in inactive shop")

    product.is_active = True
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductOut])
def list_products(
    current_user: User = Depends(require_permission("inventory:view")),
    shop_id: int | None = None,
    db: Session = Depends(get_db),
):
    if _is_system_owner(current_user):
        query = select(Product).order_by(Product.name.asc())
        if shop_id is not None:
            query = query.where(Product.shop_id == shop_id)
        return list(db.scalars(query).all())
    assigned_shop = _get_assigned_shop(db, current_user)
    if shop_id is not None:
        _enforce_shop_scope(shop_id, assigned_shop.id)
    products = db.scalars(
        select(Product)
        .where(Product.shop_id == assigned_shop.id)
        .order_by(Product.name.asc())
    ).all()
    return list(products)


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if _is_system_owner(current_user):
        target_shop_id = payload.shop_id if payload.shop_id is not None else current_user.shop_id
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if payload.shop_id is not None:
            _enforce_shop_scope(payload.shop_id, assigned_shop.id)
        target_shop_id = assigned_shop.id

    shop = db.get(Shop, target_shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create supplier for inactive shop")

    supplier = Supplier(
        shop_id=target_shop_id,
        name=payload.name.strip(),
        contact=payload.contact.strip() if payload.contact else None,
    )
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Supplier name already exists for this shop") from exc
    db.refresh(supplier)
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(supplier.shop_id, assigned_shop.id)

    if payload.name is not None:
        supplier.name = payload.name.strip()
    if payload.contact is not None:
        supplier.contact = payload.contact.strip() or None
    if payload.is_active is not None:
        supplier.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Supplier name already exists for this shop") from exc
    db.refresh(supplier)
    return supplier


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    shop_id: int | None = None,
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Supplier).order_by(Supplier.name.asc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Supplier.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Supplier.shop_id == assigned_shop.id)
    return list(db.scalars(query).all())


@router.delete("/suppliers/{supplier_id}", response_model=SupplierOut)
def archive_supplier(
    supplier_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(supplier.shop_id, assigned_shop.id)
    supplier.is_active = False
    db.commit()
    db.refresh(supplier)
    return supplier


@router.post("/suppliers/{supplier_id}/activate", response_model=SupplierOut)
def activate_supplier(
    supplier_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(supplier.shop_id, assigned_shop.id)
    shop = db.get(Shop, supplier.shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate supplier in inactive shop")
    supplier.is_active = True
    db.commit()
    db.refresh(supplier)
    return supplier


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _remove_purchase_effect(stock: Stock, *, qty: int, buy: Decimal, sell: Decimal) -> None:
    current_qty = int(stock.quantity_on_hand)
    if current_qty < qty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify purchase because purchased stock has already been consumed",
        )
    new_qty = current_qty - qty
    if new_qty == 0:
        stock.quantity_on_hand = 0
        return

    current_buy = Decimal(stock.buying_price)
    current_sell = Decimal(stock.selling_price)
    new_buy = ((current_buy * Decimal(current_qty)) - (buy * Decimal(qty))) / Decimal(new_qty)
    new_sell = ((current_sell * Decimal(current_qty)) - (sell * Decimal(qty))) / Decimal(new_qty)
    stock.quantity_on_hand = new_qty
    stock.buying_price = _quantize_price(new_buy)
    stock.selling_price = _quantize_price(new_sell)


def _apply_purchase_effect(stock: Stock, *, qty: int, buy: Decimal, sell: Decimal) -> None:
    current_qty = int(stock.quantity_on_hand)
    if current_qty == 0:
        stock.quantity_on_hand = qty
        stock.buying_price = _quantize_price(buy)
        stock.selling_price = _quantize_price(sell)
        return

    new_qty = current_qty + qty
    current_buy = Decimal(stock.buying_price)
    current_sell = Decimal(stock.selling_price)
    weighted_buy = ((current_buy * Decimal(current_qty)) + (buy * Decimal(qty))) / Decimal(new_qty)
    weighted_sell = ((current_sell * Decimal(current_qty)) + (sell * Decimal(qty))) / Decimal(new_qty)
    stock.quantity_on_hand = new_qty
    stock.buying_price = _quantize_price(weighted_buy)
    stock.selling_price = _quantize_price(weighted_sell)


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def create_purchase(
    payload: PurchaseCreate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(payload.shop_id, assigned_shop.id)

    shop = db.get(Shop, payload.shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot record purchase for inactive shop")

    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if product.shop_id != payload.shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not belong to target shop")
    if not product.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot purchase inactive product")

    supplier_id = payload.supplier_id
    if supplier_id is not None:
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        if supplier.shop_id != payload.shop_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier does not belong to target shop")
        if not supplier.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier is inactive")
    invoice_number = payload.invoice_number.strip() if payload.invoice_number else None

    stock = db.scalar(
        select(Stock)
        .where(Stock.shop_id == payload.shop_id, Stock.product_id == payload.product_id)
        .with_for_update()
    )

    buy = Decimal(payload.unit_buying_price)
    if payload.unit_selling_price is not None:
        sell = Decimal(payload.unit_selling_price)
    elif stock:
        sell = Decimal(stock.selling_price)
    else:
        sell = buy

    if not stock:
        stock = Stock(
            shop_id=payload.shop_id,
            product_id=payload.product_id,
            quantity_on_hand=0,
            buying_price=_quantize_price(buy),
            selling_price=_quantize_price(sell),
        )
        db.add(stock)
        db.flush()

    _apply_purchase_effect(stock, qty=payload.quantity, buy=buy, sell=sell)

    purchase = Purchase(
        shop_id=payload.shop_id,
        product_id=payload.product_id,
        supplier_id=supplier_id,
        invoice_number=invoice_number,
        purchased_by_user_id=current_user.id,
        unit=product.unit,
        quantity=payload.quantity,
        unit_buying_price=_quantize_price(buy),
        unit_selling_price=_quantize_price(sell),
        total_cost=_quantize_price(buy * Decimal(payload.quantity)),
        note=payload.note.strip() if payload.note else None,
        purchased_at=payload.purchased_at or datetime.utcnow(),
    )
    db.add(purchase)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice number already exists for this shop") from exc
    db.refresh(purchase)
    return purchase


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    shop_id: int | None = None,
    product_id: int | None = None,
    supplier_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Purchase).order_by(Purchase.purchased_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Purchase.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Purchase.shop_id == assigned_shop.id)
    if product_id is not None:
        query = query.where(Purchase.product_id == product_id)
    if supplier_id is not None:
        query = query.where(Purchase.supplier_id == supplier_id)
    if date_from is not None:
        query = query.where(Purchase.purchased_at >= date_from)
    if date_to is not None:
        query = query.where(Purchase.purchased_at <= date_to)
    return list(db.scalars(query).all())


def _build_purchases_query(
    *,
    db: Session,
    current_user: User,
    shop_id: int | None,
    product_id: int | None,
    supplier_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    query = select(Purchase).order_by(Purchase.purchased_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Purchase.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Purchase.shop_id == assigned_shop.id)
    if product_id is not None:
        query = query.where(Purchase.product_id == product_id)
    if supplier_id is not None:
        query = query.where(Purchase.supplier_id == supplier_id)
    if date_from is not None:
        query = query.where(Purchase.purchased_at >= date_from)
    if date_to is not None:
        query = query.where(Purchase.purchased_at <= date_to)
    return query


def _simple_pdf(lines: list[str]) -> bytes:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 780
    content_lines = ["BT", "/F1 10 Tf", "50 800 Td"]
    for line in lines:
        content_lines.append(f"0 {y - 800} Td ({esc(line)}) Tj")
        y -= 14
        if y < 60:
            break
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objects.append(
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    xref_positions = [0]
    for i, obj in enumerate(objects, start=1):
        xref_positions.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_start = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for pos in xref_positions[1:]:
        out.extend(f"{pos:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


@router.get("/purchases/export/csv")
def export_purchases_csv(
    shop_id: int | None = None,
    product_id: int | None = None,
    supplier_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = _build_purchases_query(
        db=db,
        current_user=current_user,
        shop_id=shop_id,
        product_id=product_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    items = list(db.scalars(query).all())
    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(
        [
            "id",
            "shop_id",
            "product_id",
            "supplier_id",
            "unit",
            "quantity",
            "unit_buying_price",
            "unit_selling_price",
            "total_cost",
            "note",
            "purchased_at",
        ]
    )
    for p in items:
        writer.writerow(
            [
                p.id,
                p.shop_id,
                p.product_id,
                p.supplier_id or "",
                p.unit,
                p.quantity,
                str(p.unit_buying_price),
                str(p.unit_selling_price),
                str(p.total_cost),
                p.note or "",
                p.purchased_at.isoformat(),
            ]
        )
    return Response(
        content=sio.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="purchases.csv"'},
    )


@router.get("/purchases/export/pdf")
def export_purchases_pdf(
    shop_id: int | None = None,
    product_id: int | None = None,
    supplier_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = _build_purchases_query(
        db=db,
        current_user=current_user,
        shop_id=shop_id,
        product_id=product_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    items = list(db.scalars(query).all())
    lines = ["Purchase Export"]
    lines.append(f"Rows: {len(items)}")
    lines.append("")
    lines.append("id | shop | product | supplier | unit | qty | buy | sell | total")
    for p in items[:45]:
        lines.append(
            f"{p.id} | {p.shop_id} | {p.product_id} | {p.supplier_id or '-'} | {p.unit} | {p.quantity} | {p.unit_buying_price} | {p.unit_selling_price} | {p.total_cost}"
        )
    pdf_bytes = _simple_pdf(lines)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="purchases.pdf"'},
    )


@router.patch("/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    purchase_id: int,
    payload: PurchaseUpdate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    purchase = db.get(Purchase, purchase_id)
    if not purchase:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(purchase.shop_id, assigned_shop.id)

    stock = db.scalar(
        select(Stock)
        .where(Stock.shop_id == purchase.shop_id, Stock.product_id == purchase.product_id)
        .with_for_update()
    )
    if not stock:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stock record missing for purchase")

    supplier_id = payload.supplier_id if payload.supplier_id is not None else purchase.supplier_id
    invoice_number = payload.invoice_number.strip() if payload.invoice_number else purchase.invoice_number
    if supplier_id is not None:
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        if supplier.shop_id != purchase.shop_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier does not belong to purchase shop")
        if not supplier.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier is inactive")

    new_qty = payload.quantity if payload.quantity is not None else purchase.quantity
    new_buy = Decimal(payload.unit_buying_price) if payload.unit_buying_price is not None else Decimal(purchase.unit_buying_price)
    new_sell = Decimal(payload.unit_selling_price) if payload.unit_selling_price is not None else Decimal(purchase.unit_selling_price)

    _remove_purchase_effect(
        stock,
        qty=purchase.quantity,
        buy=Decimal(purchase.unit_buying_price),
        sell=Decimal(purchase.unit_selling_price),
    )
    _apply_purchase_effect(stock, qty=new_qty, buy=new_buy, sell=new_sell)

    purchase.supplier_id = supplier_id
    purchase.invoice_number = invoice_number
    purchase.quantity = new_qty
    purchase.unit_buying_price = _quantize_price(new_buy)
    purchase.unit_selling_price = _quantize_price(new_sell)
    purchase.total_cost = _quantize_price(new_buy * Decimal(new_qty))
    if payload.note is not None:
        purchase.note = payload.note.strip() or None
    if payload.purchased_at is not None:
        purchase.purchased_at = payload.purchased_at
    purchase.purchased_by_user_id = current_user.id

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice number already exists for this shop") from exc
    db.refresh(purchase)
    return purchase


@router.delete("/purchases/{purchase_id}", response_model=PurchaseOut)
def delete_purchase(
    purchase_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    purchase = db.get(Purchase, purchase_id)
    if not purchase:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(purchase.shop_id, assigned_shop.id)

    stock = db.scalar(
        select(Stock)
        .where(Stock.shop_id == purchase.shop_id, Stock.product_id == purchase.product_id)
        .with_for_update()
    )
    if not stock:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stock record missing for purchase")

    _remove_purchase_effect(
        stock,
        qty=purchase.quantity,
        buy=Decimal(purchase.unit_buying_price),
        sell=Decimal(purchase.unit_selling_price),
    )
    db.delete(purchase)
    db.commit()
    return purchase


@router.put("/stocks", response_model=StockOut)
def upsert_stock(
    payload: StockUpsertRequest,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(payload.shop_id, assigned_shop.id)

    shop = db.get(Shop, payload.shop_id)
    product = db.get(Product, payload.product_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot manage stock for inactive shop")
    if not product.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot manage stock for inactive product")
    if product.shop_id != payload.shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not belong to target shop")

    stock = db.scalar(
        select(Stock).where(
            Stock.shop_id == payload.shop_id,
            Stock.product_id == payload.product_id,
        )
    )
    if not stock:
        stock = Stock(
            shop_id=payload.shop_id,
            product_id=payload.product_id,
            quantity_on_hand=payload.quantity_on_hand,
            buying_price=payload.buying_price,
            selling_price=payload.selling_price,
        )
        db.add(stock)
    else:
        stock.quantity_on_hand = payload.quantity_on_hand
        stock.buying_price = payload.buying_price
        stock.selling_price = payload.selling_price

    db.commit()
    db.refresh(stock)
    return StockOut(
        id=stock.id,
        shop_id=stock.shop_id,
        product_id=stock.product_id,
        quantity_on_hand=stock.quantity_on_hand,
        buying_price=stock.buying_price,
        selling_price=stock.selling_price,
        unit_profit=Decimal(stock.selling_price) - Decimal(stock.buying_price),
        updated_at=stock.updated_at,
    )


@router.get("/stocks", response_model=list[StockOut])
def list_stocks(
    shop_id: int | None = None,
    product_id: int | None = None,
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Stock).order_by(Stock.updated_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Stock.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Stock.shop_id == assigned_shop.id)
    if product_id is not None:
        query = query.where(Stock.product_id == product_id)
    stocks = db.scalars(query).all()
    return [
        StockOut(
            id=s.id,
            shop_id=s.shop_id,
            product_id=s.product_id,
            quantity_on_hand=s.quantity_on_hand,
            buying_price=s.buying_price,
            selling_price=s.selling_price,
            unit_profit=Decimal(s.selling_price) - Decimal(s.buying_price),
            updated_at=s.updated_at,
        )
        for s in stocks
    ]


@router.delete("/stocks/{stock_id}", response_model=StockOut)
def delete_stock(
    stock_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    stock = db.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock record not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(stock.shop_id, assigned_shop.id)

    result = StockOut(
        id=stock.id,
        shop_id=stock.shop_id,
        product_id=stock.product_id,
        quantity_on_hand=stock.quantity_on_hand,
        buying_price=stock.buying_price,
        selling_price=stock.selling_price,
        unit_profit=Decimal(stock.selling_price) - Decimal(stock.buying_price),
        updated_at=stock.updated_at,
    )
    db.delete(stock)
    db.commit()
    return result


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if _is_system_owner(current_user):
        target_shop_id = payload.shop_id if payload.shop_id is not None else current_user.shop_id
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if payload.shop_id is not None:
            _enforce_shop_scope(payload.shop_id, assigned_shop.id)
        target_shop_id = assigned_shop.id

    shop = db.get(Shop, target_shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot record expense for inactive shop")

    expense = Expense(
        shop_id=target_shop_id,
        created_by_user_id=current_user.id,
        category=payload.category.strip(),
        amount=payload.amount,
        note=payload.note.strip() if payload.note else None,
        incurred_at=payload.incurred_at or datetime.utcnow(),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(
    shop_id: int | None = None,
    category: str | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Expense).order_by(Expense.incurred_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Expense.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Expense.shop_id == assigned_shop.id)
    if category is not None and category.strip():
        query = query.where(func.lower(Expense.category) == category.strip().lower())
    if date_from is not None:
        query = query.where(Expense.incurred_at >= date_from)
    if date_to is not None:
        query = query.where(Expense.incurred_at <= date_to)
    return list(db.scalars(query).all())


@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(expense.shop_id, assigned_shop.id)

    if payload.category is not None:
        expense.category = payload.category.strip()
    if payload.amount is not None:
        expense.amount = payload.amount
    if payload.note is not None:
        expense.note = payload.note.strip() or None
    if payload.incurred_at is not None:
        expense.incurred_at = payload.incurred_at

    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}", response_model=ExpenseOut)
def delete_expense(
    expense_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(expense.shop_id, assigned_shop.id)

    db.delete(expense)
    db.commit()
    return expense


@router.post("/stocks/{stock_id}/adjust", response_model=StockOut)
def adjust_stock(
    stock_id: int,
    payload: StockAdjustRequest,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    stock = db.scalar(select(Stock).where(Stock.id == stock_id).with_for_update())
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock record not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(stock.shop_id, assigned_shop.id)

    if payload.quantity_delta == 0 and payload.buying_price is None and payload.selling_price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No adjustment provided",
        )

    quantity_before = int(stock.quantity_on_hand)
    quantity_after = quantity_before + int(payload.quantity_delta)
    if quantity_after < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Adjustment would make stock negative",
        )

    stock.quantity_on_hand = quantity_after
    if payload.buying_price is not None:
        stock.buying_price = payload.buying_price
    if payload.selling_price is not None:
        stock.selling_price = payload.selling_price
    adjustment = StockAdjustment(
        stock_id=stock.id,
        shop_id=stock.shop_id,
        product_id=stock.product_id,
        adjusted_by_user_id=current_user.id,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        quantity_delta=int(payload.quantity_delta),
        reason=payload.reason.strip() if payload.reason else None,
    )
    db.add(adjustment)
    db.commit()
    db.refresh(stock)
    return StockOut(
        id=stock.id,
        shop_id=stock.shop_id,
        product_id=stock.product_id,
        quantity_on_hand=stock.quantity_on_hand,
        buying_price=stock.buying_price,
        selling_price=stock.selling_price,
        unit_profit=Decimal(stock.selling_price) - Decimal(stock.buying_price),
        updated_at=stock.updated_at,
    )


@router.get("/stock-adjustments", response_model=list[StockAdjustmentOut])
def list_stock_adjustments(
    shop_id: int | None = None,
    product_id: int | None = None,
    stock_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(StockAdjustment).order_by(StockAdjustment.adjusted_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(StockAdjustment.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(StockAdjustment.shop_id == assigned_shop.id)
    if product_id is not None:
        query = query.where(StockAdjustment.product_id == product_id)
    if stock_id is not None:
        query = query.where(StockAdjustment.stock_id == stock_id)
    if date_from is not None:
        query = query.where(StockAdjustment.adjusted_at >= date_from)
    if date_to is not None:
        query = query.where(StockAdjustment.adjusted_at <= date_to)
    return list(db.scalars(query).all())


@router.post("/sales", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def create_sale(
    payload: SaleCreateRequest,
    current_user: User = Depends(require_permission("inventory:sell")),
    db: Session = Depends(get_db),
):
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(payload.shop_id, assigned_shop.id)
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if not product.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create sale for inactive product")
    shop = db.get(Shop, payload.shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create sale for inactive shop")
    if product.shop_id != payload.shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not belong to target shop")

    stock = db.scalar(
        select(Stock)
        .where(Stock.shop_id == payload.shop_id, Stock.product_id == payload.product_id)
        .with_for_update()
    )
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock record not found")
    if stock.quantity_on_hand < payload.quantity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient stock quantity")

    unit_buying = Decimal(stock.buying_price)
    unit_selling = Decimal(payload.unit_selling_price) if payload.unit_selling_price else Decimal(stock.selling_price)
    quantity = Decimal(payload.quantity)
    revenue = unit_selling * quantity
    cost = unit_buying * quantity
    profit = revenue - cost

    sale = Sale(
        shop_id=payload.shop_id,
        product_id=payload.product_id,
        sold_by_user_id=current_user.id,
        quantity=payload.quantity,
        unit_buying_price=unit_buying,
        unit_selling_price=unit_selling,
        revenue=revenue,
        cost=cost,
        profit=profit,
    )
    stock.quantity_on_hand -= payload.quantity
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return sale


@router.get("/sales", response_model=list[SaleOut])
def list_sales(
    shop_id: int | None = None,
    product_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Sale).order_by(Sale.sold_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Sale.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Sale.shop_id == assigned_shop.id)
    if product_id is not None:
        query = query.where(Sale.product_id == product_id)
    if date_from is not None:
        query = query.where(Sale.sold_at >= date_from)
    if date_to is not None:
        query = query.where(Sale.sold_at <= date_to)
    return list(db.scalars(query).all())


@router.post("/sales/{sale_id}/returns", response_model=SaleReturnOut, status_code=status.HTTP_201_CREATED)
def create_sale_return(
    sale_id: int,
    payload: SaleReturnCreateRequest,
    current_user: User = Depends(require_permission("inventory:sell")),
    db: Session = Depends(get_db),
):
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")

    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(sale.shop_id, assigned_shop.id)

    shop = db.get(Shop, sale.shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot return sale for inactive shop")

    product = db.get(Product, sale.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    already_returned = int(
        db.scalar(
            select(func.coalesce(func.sum(SaleReturn.quantity), 0)).where(
                SaleReturn.sale_id == sale_id,
            )
        )
        or 0
    )
    remaining_qty = sale.quantity - already_returned
    if remaining_qty <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sale is already fully returned")
    if payload.quantity > remaining_qty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Return quantity exceeds remaining sale quantity ({remaining_qty})",
        )

    unit_buying = Decimal(sale.unit_buying_price)
    unit_selling = Decimal(sale.unit_selling_price)
    quantity = Decimal(payload.quantity)
    refund_amount = unit_selling * quantity
    cost_reversed = unit_buying * quantity
    profit_reversed = refund_amount - cost_reversed

    if payload.restock:
        stock = db.scalar(
            select(Stock)
            .where(Stock.shop_id == sale.shop_id, Stock.product_id == sale.product_id)
            .with_for_update()
        )
        if not stock:
            stock = Stock(
                shop_id=sale.shop_id,
                product_id=sale.product_id,
                quantity_on_hand=payload.quantity,
                buying_price=unit_buying,
                selling_price=unit_selling,
            )
            db.add(stock)
        else:
            stock.quantity_on_hand += payload.quantity

    sale_return = SaleReturn(
        sale_id=sale.id,
        shop_id=sale.shop_id,
        product_id=sale.product_id,
        processed_by_user_id=current_user.id,
        quantity=payload.quantity,
        unit_buying_price=unit_buying,
        unit_selling_price=unit_selling,
        refund_amount=refund_amount,
        cost_reversed=cost_reversed,
        profit_reversed=profit_reversed,
        restocked=payload.restock,
        note=payload.note,
    )
    db.add(sale_return)
    db.commit()
    db.refresh(sale_return)
    return sale_return


@router.get("/returns", response_model=list[SaleReturnOut])
def list_sale_returns(
    shop_id: int | None = None,
    sale_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(SaleReturn).order_by(SaleReturn.returned_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(SaleReturn.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(SaleReturn.shop_id == assigned_shop.id)
    if sale_id is not None:
        query = query.where(SaleReturn.sale_id == sale_id)
    if date_from is not None:
        query = query.where(SaleReturn.returned_at >= date_from)
    if date_to is not None:
        query = query.where(SaleReturn.returned_at <= date_to)
    return list(db.scalars(query).all())


@router.get("/reports/profit/{shop_id}", response_model=ProfitReportOut)
def profit_report(
    shop_id: int,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        _enforce_shop_scope(shop_id, assigned_shop.id)

    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")

    sale_stats = db.execute(
        select(
            func.coalesce(func.sum(Sale.revenue), 0),
            func.coalesce(func.sum(Sale.cost), 0),
            func.coalesce(func.sum(Sale.profit), 0),
            func.count(Sale.id),
        ).where(
            Sale.shop_id == shop_id,
            *( [Sale.sold_at >= date_from] if date_from is not None else [] ),
            *( [Sale.sold_at <= date_to] if date_to is not None else [] ),
        )
    ).one()

    return_stats = db.execute(
        select(
            func.coalesce(func.sum(SaleReturn.refund_amount), 0),
            func.coalesce(func.sum(SaleReturn.cost_reversed), 0),
            func.coalesce(func.sum(SaleReturn.profit_reversed), 0),
        ).where(
            SaleReturn.shop_id == shop_id,
            *( [SaleReturn.returned_at >= date_from] if date_from is not None else [] ),
            *( [SaleReturn.returned_at <= date_to] if date_to is not None else [] ),
        )
    ).one()

    expense_total = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.shop_id == shop_id,
                *( [Expense.incurred_at >= date_from] if date_from is not None else [] ),
                *( [Expense.incurred_at <= date_to] if date_to is not None else [] ),
            )
        )
        or 0
    )

    gross_profit = Decimal(sale_stats[2]) - Decimal(return_stats[2])
    net_profit = gross_profit - expense_total

    return ProfitReportOut(
        shop_id=shop_id,
        period_from=date_from,
        period_to=date_to,
        total_revenue=Decimal(sale_stats[0]) - Decimal(return_stats[0]),
        total_cost=Decimal(sale_stats[1]) - Decimal(return_stats[1]),
        total_profit=gross_profit,
        total_expenses=expense_total,
        net_profit=net_profit,
        total_sales_records=int(sale_stats[3]),
    )


@router.get("/alerts/low-stock", response_model=list[LowStockItemOut])
def low_stock_alerts(
    threshold: int = Query(default=10, ge=0),
    shop_id: int | None = None,
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(Stock).where(Stock.quantity_on_hand <= threshold).order_by(Stock.quantity_on_hand.asc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(Stock.shop_id == shop_id)
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(Stock.shop_id == assigned_shop.id)
    stocks = db.scalars(query).all()
    return [
        LowStockItemOut(
            shop_id=stock.shop_id,
            product_id=stock.product_id,
            quantity_on_hand=stock.quantity_on_hand,
            threshold=threshold,
        )
        for stock in stocks
    ]


@router.get("/alerts/reorder-suggestions", response_model=list[ReorderSuggestionOut])
def reorder_suggestions(
    lookback_days: int = Query(default=30, ge=1, le=365),
    lead_days: int = Query(default=7, ge=1, le=180),
    shop_id: int | None = None,
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    effective_shop_id = _resolve_effective_shop_id(db, current_user, shop_id)
    scope_start = datetime.utcnow() - timedelta(days=lookback_days)

    sales_qty = db.execute(
        _apply_sale_scope(
            select(Sale.shop_id, Sale.product_id, func.coalesce(func.sum(Sale.quantity), 0))
            .group_by(Sale.shop_id, Sale.product_id),
            effective_shop_id=effective_shop_id,
            date_from=scope_start,
            date_to=None,
        )
    ).all()
    returns_qty = db.execute(
        _apply_return_scope(
            select(SaleReturn.shop_id, SaleReturn.product_id, func.coalesce(func.sum(SaleReturn.quantity), 0))
            .group_by(SaleReturn.shop_id, SaleReturn.product_id),
            effective_shop_id=effective_shop_id,
            date_from=scope_start,
            date_to=None,
        )
    ).all()

    net_qty: dict[tuple[int, int], Decimal] = {}
    for shop_val, product_val, qty in sales_qty:
        net_qty[(int(shop_val), int(product_val))] = Decimal(qty)
    for shop_val, product_val, qty in returns_qty:
        key = (int(shop_val), int(product_val))
        net_qty[key] = net_qty.get(key, Decimal(0)) - Decimal(qty)

    stock_query = select(Stock, Product).join(Product, Product.id == Stock.product_id)
    if effective_shop_id is not None:
        stock_query = stock_query.where(Stock.shop_id == effective_shop_id)
    rows = db.execute(stock_query).all()

    result: list[ReorderSuggestionOut] = []
    for stock, product in rows:
        key = (int(stock.shop_id), int(stock.product_id))
        sold_net = net_qty.get(key, Decimal(0))
        if sold_net < 0:
            sold_net = Decimal(0)
        avg_daily = sold_net / Decimal(lookback_days)
        target_qty = avg_daily * Decimal(lead_days)
        reorder_qty = int(max(0, math.ceil(float(target_qty - Decimal(stock.quantity_on_hand)))))
        result.append(
            ReorderSuggestionOut(
                shop_id=stock.shop_id,
                product_id=stock.product_id,
                product_name=product.name,
                unit=product.unit,
                current_stock=stock.quantity_on_hand,
                avg_daily_sales=avg_daily.quantize(Decimal("0.01")),
                recommended_reorder_qty=reorder_qty,
                lookback_days=lookback_days,
                lead_days=lead_days,
            )
        )
    result.sort(key=lambda item: item.recommended_reorder_qty, reverse=True)
    return result


@router.post("/transfers", response_model=StockTransferOut, status_code=status.HTTP_201_CREATED)
def transfer_stock(
    payload: TransferStockRequest,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    if not _is_system_owner(current_user):
        assigned_shop = _get_assigned_shop(db, current_user)
        if payload.from_shop_id != assigned_shop.id and payload.to_shop_id != assigned_shop.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-shop access is not allowed")
        if payload.from_shop_id != assigned_shop.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transfers must originate from your shop")
    if payload.from_shop_id == payload.to_shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source and destination shops must differ")

    source_shop = db.get(Shop, payload.from_shop_id)
    target_shop = db.get(Shop, payload.to_shop_id)
    if not source_shop or not target_shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source or destination shop not found")

    source_product = db.get(Product, payload.product_id)
    if not source_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if not source_product.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer inactive product")
    if source_product.shop_id != payload.from_shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not belong to source shop")
    if not source_shop.is_active or not target_shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer stock involving inactive shop")

    target_product = db.scalar(
        select(Product).where(
            Product.shop_id == payload.to_shop_id,
            Product.sku == source_product.sku,
        )
    )
    if not target_product:
        target_product = Product(
            shop_id=payload.to_shop_id,
            sku=source_product.sku,
            name=source_product.name,
            unit=source_product.unit,
            description=source_product.description,
        )
        db.add(target_product)
        db.flush()

    source_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == payload.from_shop_id,
            Stock.product_id == source_product.id,
        )
        .with_for_update()
    )
    if not source_stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source stock record not found")
    if source_stock.quantity_on_hand < payload.quantity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient source stock quantity")

    target_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == payload.to_shop_id,
            Stock.product_id == target_product.id,
        )
        .with_for_update()
    )

    transfer_qty = payload.quantity
    source_buy = Decimal(source_stock.buying_price)
    source_sell = Decimal(source_stock.selling_price)

    source_stock.quantity_on_hand -= transfer_qty

    if not target_stock:
        target_stock = Stock(
            shop_id=payload.to_shop_id,
            product_id=target_product.id,
            quantity_on_hand=transfer_qty,
            buying_price=source_buy,
            selling_price=source_sell,
        )
        db.add(target_stock)
    else:
        prev_qty = Decimal(target_stock.quantity_on_hand)
        new_qty = Decimal(target_stock.quantity_on_hand + transfer_qty)
        target_buy = Decimal(target_stock.buying_price)
        target_sell = Decimal(target_stock.selling_price)
        weighted_buy = ((target_buy * prev_qty) + (source_buy * Decimal(transfer_qty))) / new_qty
        weighted_sell = ((target_sell * prev_qty) + (source_sell * Decimal(transfer_qty))) / new_qty
        target_stock.quantity_on_hand += transfer_qty
        target_stock.buying_price = weighted_buy.quantize(Decimal("0.01"))
        target_stock.selling_price = weighted_sell.quantize(Decimal("0.01"))

    transfer = StockTransfer(
        product_id=payload.product_id,
        from_shop_id=payload.from_shop_id,
        to_shop_id=payload.to_shop_id,
        transferred_by_user_id=current_user.id,
        quantity=transfer_qty,
        unit_buying_price=source_buy,
        unit_selling_price=source_sell,
        note=payload.note,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


def _validate_transfer_scope(current_user: User, db: Session, from_shop_id: int, to_shop_id: int) -> None:
    if _is_system_owner(current_user):
        return
    assigned_shop = _get_assigned_shop(db, current_user)
    if from_shop_id != assigned_shop.id and to_shop_id != assigned_shop.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-shop access is not allowed")
    if from_shop_id != assigned_shop.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transfers must originate from your shop")


def _reverse_transfer_impact(db: Session, transfer: StockTransfer) -> None:
    source_product = db.get(Product, transfer.product_id)
    if not source_product:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transfer product no longer exists")

    target_product = db.scalar(
        select(Product).where(
            Product.shop_id == transfer.to_shop_id,
            Product.sku == source_product.sku,
        )
    )
    if not target_product:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Destination product for transfer not found")

    source_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == transfer.from_shop_id,
            Stock.product_id == source_product.id,
        )
        .with_for_update()
    )
    if not source_stock:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source stock record missing for transfer")

    target_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == transfer.to_shop_id,
            Stock.product_id == target_product.id,
        )
        .with_for_update()
    )
    if not target_stock:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Destination stock record missing for transfer",
        )
    if target_stock.quantity_on_hand < transfer.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify transfer because destination stock has already been consumed",
        )

    source_stock.quantity_on_hand += transfer.quantity

    target_prev_qty = Decimal(target_stock.quantity_on_hand)
    remove_qty = Decimal(transfer.quantity)
    target_new_qty = target_prev_qty - remove_qty
    target_stock.quantity_on_hand -= transfer.quantity

    if target_new_qty > 0:
        current_buy = Decimal(target_stock.buying_price)
        current_sell = Decimal(target_stock.selling_price)
        transfer_buy = Decimal(transfer.unit_buying_price)
        transfer_sell = Decimal(transfer.unit_selling_price)
        new_buy = ((current_buy * target_prev_qty) - (transfer_buy * remove_qty)) / target_new_qty
        new_sell = ((current_sell * target_prev_qty) - (transfer_sell * remove_qty)) / target_new_qty
        target_stock.buying_price = new_buy.quantize(Decimal("0.01"))
        target_stock.selling_price = new_sell.quantize(Decimal("0.01"))


def _apply_transfer_impact(
    db: Session,
    payload: TransferStockRequest,
) -> tuple[int, Decimal, Decimal]:
    if payload.from_shop_id == payload.to_shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source and destination shops must differ")

    source_shop = db.get(Shop, payload.from_shop_id)
    target_shop = db.get(Shop, payload.to_shop_id)
    if not source_shop or not target_shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source or destination shop not found")
    if not source_shop.is_active or not target_shop.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer stock involving inactive shop")

    source_product = db.get(Product, payload.product_id)
    if not source_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if not source_product.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer inactive product")
    if source_product.shop_id != payload.from_shop_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not belong to source shop")

    target_product = db.scalar(
        select(Product).where(
            Product.shop_id == payload.to_shop_id,
            Product.sku == source_product.sku,
        )
    )
    if not target_product:
        target_product = Product(
            shop_id=payload.to_shop_id,
            sku=source_product.sku,
            name=source_product.name,
            unit=source_product.unit,
            description=source_product.description,
        )
        db.add(target_product)
        db.flush()

    source_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == payload.from_shop_id,
            Stock.product_id == source_product.id,
        )
        .with_for_update()
    )
    if not source_stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source stock record not found")
    if source_stock.quantity_on_hand < payload.quantity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient source stock quantity")

    target_stock = db.scalar(
        select(Stock)
        .where(
            Stock.shop_id == payload.to_shop_id,
            Stock.product_id == target_product.id,
        )
        .with_for_update()
    )

    transfer_qty = payload.quantity
    source_buy = Decimal(source_stock.buying_price)
    source_sell = Decimal(source_stock.selling_price)

    source_stock.quantity_on_hand -= transfer_qty

    if not target_stock:
        target_stock = Stock(
            shop_id=payload.to_shop_id,
            product_id=target_product.id,
            quantity_on_hand=transfer_qty,
            buying_price=source_buy,
            selling_price=source_sell,
        )
        db.add(target_stock)
    else:
        prev_qty = Decimal(target_stock.quantity_on_hand)
        new_qty = Decimal(target_stock.quantity_on_hand + transfer_qty)
        target_buy = Decimal(target_stock.buying_price)
        target_sell = Decimal(target_stock.selling_price)
        weighted_buy = ((target_buy * prev_qty) + (source_buy * Decimal(transfer_qty))) / new_qty
        weighted_sell = ((target_sell * prev_qty) + (source_sell * Decimal(transfer_qty))) / new_qty
        target_stock.quantity_on_hand += transfer_qty
        target_stock.buying_price = weighted_buy.quantize(Decimal("0.01"))
        target_stock.selling_price = weighted_sell.quantize(Decimal("0.01"))

    return source_product.id, source_buy, source_sell


@router.patch("/transfers/{transfer_id}", response_model=StockTransferOut)
def update_transfer(
    transfer_id: int,
    payload: TransferStockUpdate,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    transfer = db.get(StockTransfer, transfer_id)
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")

    new_product_id = payload.product_id if payload.product_id is not None else transfer.product_id
    new_from_shop_id = payload.from_shop_id if payload.from_shop_id is not None else transfer.from_shop_id
    new_to_shop_id = payload.to_shop_id if payload.to_shop_id is not None else transfer.to_shop_id
    new_quantity = payload.quantity if payload.quantity is not None else transfer.quantity
    new_note = payload.note if payload.note is not None else transfer.note

    _validate_transfer_scope(current_user, db, new_from_shop_id, new_to_shop_id)

    if (
        new_product_id == transfer.product_id
        and new_from_shop_id == transfer.from_shop_id
        and new_to_shop_id == transfer.to_shop_id
        and new_quantity == transfer.quantity
        and new_note == transfer.note
    ):
        return transfer

    try:
        _reverse_transfer_impact(db, transfer)
        applied_product_id, applied_buy, applied_sell = _apply_transfer_impact(
            db,
            TransferStockRequest(
                product_id=new_product_id,
                from_shop_id=new_from_shop_id,
                to_shop_id=new_to_shop_id,
                quantity=new_quantity,
                note=new_note,
            ),
        )
        transfer.product_id = applied_product_id
        transfer.from_shop_id = new_from_shop_id
        transfer.to_shop_id = new_to_shop_id
        transfer.quantity = new_quantity
        transfer.unit_buying_price = applied_buy
        transfer.unit_selling_price = applied_sell
        transfer.note = new_note
        transfer.transferred_by_user_id = current_user.id
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    db.refresh(transfer)
    return transfer


@router.delete("/transfers/{transfer_id}", response_model=StockTransferOut)
def delete_transfer(
    transfer_id: int,
    current_user: User = Depends(require_permission("inventory:manage")),
    db: Session = Depends(get_db),
):
    transfer = db.get(StockTransfer, transfer_id)
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")

    _validate_transfer_scope(current_user, db, transfer.from_shop_id, transfer.to_shop_id)

    try:
        _reverse_transfer_impact(db, transfer)
        db.delete(transfer)
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    return transfer


@router.get("/transfers", response_model=list[StockTransferOut])
def list_transfers(
    shop_id: int | None = None,
    product_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    query = select(StockTransfer).order_by(StockTransfer.transferred_at.desc())
    if _is_system_owner(current_user):
        if shop_id is not None:
            query = query.where(
                (StockTransfer.from_shop_id == shop_id) | (StockTransfer.to_shop_id == shop_id)
            )
    else:
        assigned_shop = _get_assigned_shop(db, current_user)
        if shop_id is not None:
            _enforce_shop_scope(shop_id, assigned_shop.id)
        query = query.where(
            (StockTransfer.from_shop_id == assigned_shop.id) | (StockTransfer.to_shop_id == assigned_shop.id)
        )
    if product_id is not None:
        query = query.where(StockTransfer.product_id == product_id)
    if date_from is not None:
        query = query.where(StockTransfer.transferred_at >= date_from)
    if date_to is not None:
        query = query.where(StockTransfer.transferred_at <= date_to)
    return list(db.scalars(query).all())


@router.get("/audit/timeline", response_model=list[InventoryAuditItemOut])
def inventory_audit_timeline(
    shop_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    effective_shop_id = _resolve_effective_shop_id(db, current_user, shop_id)

    items: list[InventoryAuditItemOut] = []

    sales_query = select(Sale)
    returns_query = select(SaleReturn)
    adjustments_query = select(StockAdjustment)
    expenses_query = select(Expense)
    transfers_query = select(StockTransfer)
    purchases_query = select(Purchase)
    if effective_shop_id is not None:
        sales_query = sales_query.where(Sale.shop_id == effective_shop_id)
        returns_query = returns_query.where(SaleReturn.shop_id == effective_shop_id)
        adjustments_query = adjustments_query.where(StockAdjustment.shop_id == effective_shop_id)
        expenses_query = expenses_query.where(Expense.shop_id == effective_shop_id)
        transfers_query = transfers_query.where(
            (StockTransfer.from_shop_id == effective_shop_id)
            | (StockTransfer.to_shop_id == effective_shop_id)
        )
        purchases_query = purchases_query.where(Purchase.shop_id == effective_shop_id)
    if date_from is not None:
        sales_query = sales_query.where(Sale.sold_at >= date_from)
        returns_query = returns_query.where(SaleReturn.returned_at >= date_from)
        adjustments_query = adjustments_query.where(StockAdjustment.adjusted_at >= date_from)
        expenses_query = expenses_query.where(Expense.incurred_at >= date_from)
        transfers_query = transfers_query.where(StockTransfer.transferred_at >= date_from)
        purchases_query = purchases_query.where(Purchase.purchased_at >= date_from)
    if date_to is not None:
        sales_query = sales_query.where(Sale.sold_at <= date_to)
        returns_query = returns_query.where(SaleReturn.returned_at <= date_to)
        adjustments_query = adjustments_query.where(StockAdjustment.adjusted_at <= date_to)
        expenses_query = expenses_query.where(Expense.incurred_at <= date_to)
        transfers_query = transfers_query.where(StockTransfer.transferred_at <= date_to)
        purchases_query = purchases_query.where(Purchase.purchased_at <= date_to)

    for row in db.scalars(sales_query.order_by(Sale.sold_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="sale.recorded",
                entity_type="sale",
                entity_id=row.id,
                shop_id=row.shop_id,
                product_id=row.product_id,
                user_id=row.sold_by_user_id,
                occurred_at=row.sold_at,
                summary=f"Sold qty={row.quantity} revenue={row.revenue}",
            )
        )
    for row in db.scalars(returns_query.order_by(SaleReturn.returned_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="sale.returned",
                entity_type="sale_return",
                entity_id=row.id,
                shop_id=row.shop_id,
                product_id=row.product_id,
                user_id=row.processed_by_user_id,
                occurred_at=row.returned_at,
                summary=f"Returned qty={row.quantity} refund={row.refund_amount}",
            )
        )
    for row in db.scalars(adjustments_query.order_by(StockAdjustment.adjusted_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="stock.adjusted",
                entity_type="stock_adjustment",
                entity_id=row.id,
                shop_id=row.shop_id,
                product_id=row.product_id,
                user_id=row.adjusted_by_user_id,
                occurred_at=row.adjusted_at,
                summary=f"Delta={row.quantity_delta} {row.quantity_before}->{row.quantity_after}",
            )
        )
    for row in db.scalars(expenses_query.order_by(Expense.incurred_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="expense.recorded",
                entity_type="expense",
                entity_id=row.id,
                shop_id=row.shop_id,
                product_id=None,
                user_id=row.created_by_user_id,
                occurred_at=row.incurred_at,
                summary=f"{row.category} amount={row.amount}",
            )
        )
    for row in db.scalars(transfers_query.order_by(StockTransfer.transferred_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="stock.transferred",
                entity_type="stock_transfer",
                entity_id=row.id,
                shop_id=row.from_shop_id,
                product_id=row.product_id,
                user_id=row.transferred_by_user_id,
                occurred_at=row.transferred_at,
                summary=f"{row.from_shop_id}->{row.to_shop_id} qty={row.quantity}",
            )
        )
    for row in db.scalars(purchases_query.order_by(Purchase.purchased_at.desc()).limit(limit)).all():
        items.append(
            InventoryAuditItemOut(
                event_type="purchase.recorded",
                entity_type="purchase",
                entity_id=row.id,
                shop_id=row.shop_id,
                product_id=row.product_id,
                user_id=row.purchased_by_user_id,
                occurred_at=row.purchased_at,
                summary=f"Purchased qty={row.quantity} cost={row.total_cost}",
            )
        )

    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return items[:limit]


@router.get("/reports/profit-by-product", response_model=list[ProductProfitOut])
def product_profit_report(
    shop_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    effective_shop_id = _resolve_effective_shop_id(db, current_user, shop_id)

    sales_rows = db.execute(
        _apply_sale_scope(
            select(
                Sale.product_id,
                Product.name,
                func.coalesce(func.sum(Sale.quantity), 0).label("quantity"),
                func.coalesce(func.sum(Sale.revenue), 0).label("revenue"),
                func.coalesce(func.sum(Sale.cost), 0).label("cost"),
                func.coalesce(func.sum(Sale.profit), 0).label("profit"),
            )
            .join(Product, Product.id == Sale.product_id)
            .group_by(Sale.product_id, Product.name),
            effective_shop_id=effective_shop_id,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()

    returns_rows = db.execute(
        _apply_return_scope(
            select(
                SaleReturn.product_id,
                Product.name,
                func.coalesce(func.sum(SaleReturn.quantity), 0).label("quantity"),
                func.coalesce(func.sum(SaleReturn.refund_amount), 0).label("revenue"),
                func.coalesce(func.sum(SaleReturn.cost_reversed), 0).label("cost"),
                func.coalesce(func.sum(SaleReturn.profit_reversed), 0).label("profit"),
            )
            .join(Product, Product.id == SaleReturn.product_id)
            .group_by(SaleReturn.product_id, Product.name),
            effective_shop_id=effective_shop_id,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()

    merged: dict[int, dict[str, Decimal | int | str]] = {}

    for row in sales_rows:
        product_id = int(row[0])
        merged[product_id] = {
            "name": str(row[1]),
            "quantity": int(row[2] or 0),
            "revenue": Decimal(row[3]),
            "cost": Decimal(row[4]),
            "profit": Decimal(row[5]),
        }

    for row in returns_rows:
        product_id = int(row[0])
        entry = merged.get(product_id)
        if entry is None:
            entry = {
                "name": str(row[1]),
                "quantity": 0,
                "revenue": Decimal("0"),
                "cost": Decimal("0"),
                "profit": Decimal("0"),
            }
            merged[product_id] = entry
        entry["quantity"] = int(entry["quantity"]) - int(row[2] or 0)
        entry["revenue"] = Decimal(entry["revenue"]) - Decimal(row[3])
        entry["cost"] = Decimal(entry["cost"]) - Decimal(row[4])
        entry["profit"] = Decimal(entry["profit"]) - Decimal(row[5])

    result = [
        ProductProfitOut(
            product_id=product_id,
            product_name=str(values["name"]),
            total_quantity_sold=int(values["quantity"]),
            total_revenue=Decimal(values["revenue"]),
            total_cost=Decimal(values["cost"]),
            total_profit=Decimal(values["profit"]),
        )
        for product_id, values in merged.items()
    ]
    result.sort(key=lambda item: item.total_profit, reverse=True)
    return result


@router.get("/reports/dashboard", response_model=DashboardSummaryOut)
def dashboard_summary(
    shop_id: int | None = None,
    threshold: int = Query(default=10, ge=0),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    effective_shop_id = _resolve_effective_shop_id(db, current_user, shop_id)

    sales_query = _apply_sale_scope(
        select(Sale),
        effective_shop_id=effective_shop_id,
        date_from=date_from,
        date_to=date_to,
    )
    sales_sub = sales_query.subquery()

    sale_totals = db.execute(
        select(
            func.coalesce(func.sum(sales_sub.c.revenue), 0),
            func.coalesce(func.sum(sales_sub.c.cost), 0),
            func.coalesce(func.sum(sales_sub.c.profit), 0),
            func.count(sales_sub.c.id),
            func.coalesce(func.sum(sales_sub.c.quantity), 0),
        )
    ).one()

    returns_sub = _apply_return_scope(
        select(SaleReturn),
        effective_shop_id=effective_shop_id,
        date_from=date_from,
        date_to=date_to,
    ).subquery()

    return_totals = db.execute(
        select(
            func.coalesce(func.sum(returns_sub.c.refund_amount), 0),
            func.coalesce(func.sum(returns_sub.c.cost_reversed), 0),
            func.coalesce(func.sum(returns_sub.c.profit_reversed), 0),
            func.coalesce(func.sum(returns_sub.c.quantity), 0),
        )
    ).one()

    expenses_total = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                *( [Expense.shop_id == effective_shop_id] if effective_shop_id is not None else [] ),
                *( [Expense.incurred_at >= date_from] if date_from is not None else [] ),
                *( [Expense.incurred_at <= date_to] if date_to is not None else [] ),
            )
        )
        or 0
    )

    low_stock_query = select(func.count(Stock.id)).where(Stock.quantity_on_hand <= threshold)
    if effective_shop_id is not None:
        low_stock_query = low_stock_query.where(Stock.shop_id == effective_shop_id)
    low_stock_count = int(db.scalar(low_stock_query) or 0)

    top_products = product_profit_report(
        shop_id=effective_shop_id,
        date_from=date_from,
        date_to=date_to,
        current_user=current_user,  # dependency bypass for internal reuse
        db=db,
    )[:5]

    gross_profit = Decimal(sale_totals[2]) - Decimal(return_totals[2])
    net_profit = gross_profit - expenses_total

    return DashboardSummaryOut(
        shop_id=effective_shop_id,
        period_from=date_from,
        period_to=date_to,
        total_revenue=Decimal(sale_totals[0]) - Decimal(return_totals[0]),
        total_cost=Decimal(sale_totals[1]) - Decimal(return_totals[1]),
        total_profit=gross_profit,
        total_expenses=expenses_total,
        net_profit=net_profit,
        total_sales_records=int(sale_totals[3]),
        total_units_sold=int(sale_totals[4]) - int(return_totals[3]),
        low_stock_items=low_stock_count,
        top_products_by_profit=top_products,
    )


@router.get("/reports/dashboard-charts", response_model=DashboardChartsOut)
def dashboard_charts(
    shop_id: int | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    granularity: str = Query(default="day", pattern="^(day|week|month)$"),
    top_n: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(require_permission("inventory:view")),
    db: Session = Depends(get_db),
):
    effective_shop_id = _resolve_effective_shop_id(db, current_user, shop_id)

    sales_query = select(
        Sale.sold_at,
        Sale.product_id,
        Sale.revenue,
        Sale.cost,
        Sale.profit,
        Sale.quantity,
    ).order_by(Sale.sold_at.asc())
    sales_rows = db.execute(
        _apply_sale_scope(
            sales_query,
            effective_shop_id=effective_shop_id,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()

    returns_query = select(
        SaleReturn.returned_at,
        SaleReturn.product_id,
        SaleReturn.refund_amount,
        SaleReturn.cost_reversed,
        SaleReturn.profit_reversed,
        SaleReturn.quantity,
    ).order_by(SaleReturn.returned_at.asc())
    return_rows = db.execute(
        _apply_return_scope(
            returns_query,
            effective_shop_id=effective_shop_id,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()

    trend_buckets: dict[datetime, dict[str, Decimal | int]] = {}
    product_profit: dict[int, Decimal] = {}
    product_revenue: dict[int, Decimal] = {}
    total_revenue = Decimal("0")
    total_cost = Decimal("0")
    total_profit = Decimal("0")
    total_units = 0
    total_sales_records = 0

    for sold_at, product_id, revenue, cost, profit, quantity in sales_rows:
        bucket = _bucket_start(sold_at, granularity)
        bucket_data = trend_buckets.get(bucket)
        if bucket_data is None:
            bucket_data = {
                "revenue": Decimal("0"),
                "cost": Decimal("0"),
                "profit": Decimal("0"),
                "units": 0,
                "count": 0,
            }
            trend_buckets[bucket] = bucket_data

        bucket_data["revenue"] = Decimal(bucket_data["revenue"]) + Decimal(revenue)
        bucket_data["cost"] = Decimal(bucket_data["cost"]) + Decimal(cost)
        bucket_data["profit"] = Decimal(bucket_data["profit"]) + Decimal(profit)
        bucket_data["units"] = int(bucket_data["units"]) + int(quantity)
        bucket_data["count"] = int(bucket_data["count"]) + 1

        total_revenue += Decimal(revenue)
        total_cost += Decimal(cost)
        total_profit += Decimal(profit)
        total_units += int(quantity)
        total_sales_records += 1

        product_profit[product_id] = product_profit.get(product_id, Decimal("0")) + Decimal(profit)
        product_revenue[product_id] = product_revenue.get(product_id, Decimal("0")) + Decimal(revenue)

    for returned_at, product_id, refund_amount, cost_reversed, profit_reversed, quantity in return_rows:
        bucket = _bucket_start(returned_at, granularity)
        bucket_data = trend_buckets.get(bucket)
        if bucket_data is None:
            bucket_data = {
                "revenue": Decimal("0"),
                "cost": Decimal("0"),
                "profit": Decimal("0"),
                "units": 0,
                "count": 0,
            }
            trend_buckets[bucket] = bucket_data

        bucket_data["revenue"] = Decimal(bucket_data["revenue"]) - Decimal(refund_amount)
        bucket_data["cost"] = Decimal(bucket_data["cost"]) - Decimal(cost_reversed)
        bucket_data["profit"] = Decimal(bucket_data["profit"]) - Decimal(profit_reversed)
        bucket_data["units"] = int(bucket_data["units"]) - int(quantity)

        total_revenue -= Decimal(refund_amount)
        total_cost -= Decimal(cost_reversed)
        total_profit -= Decimal(profit_reversed)
        total_units -= int(quantity)

        product_profit[product_id] = product_profit.get(product_id, Decimal("0")) - Decimal(profit_reversed)
        product_revenue[product_id] = product_revenue.get(product_id, Decimal("0")) - Decimal(refund_amount)

    expenses_total = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                *( [Expense.shop_id == effective_shop_id] if effective_shop_id is not None else [] ),
                *( [Expense.incurred_at >= date_from] if date_from is not None else [] ),
                *( [Expense.incurred_at <= date_to] if date_to is not None else [] ),
            )
        )
        or 0
    )
    net_profit = total_profit - expenses_total

    trend = [
        TrendPointOut(
            bucket_start=bucket,
            bucket_label=_bucket_label(bucket, granularity),
            total_revenue=Decimal(values["revenue"]),
            total_cost=Decimal(values["cost"]),
            total_profit=Decimal(values["profit"]),
            total_units_sold=int(values["units"]),
            total_sales_records=int(values["count"]),
        )
        for bucket, values in sorted(trend_buckets.items(), key=lambda item: item[0])
    ]

    totals_bar = [
        ChartBarItemOut(label="Revenue", value=total_revenue),
        ChartBarItemOut(label="Cost", value=total_cost),
        ChartBarItemOut(label="Profit", value=total_profit),
        ChartBarItemOut(label="Expenses", value=expenses_total),
        ChartBarItemOut(label="Net", value=net_profit),
        ChartBarItemOut(label="Units", value=Decimal(total_units)),
        ChartBarItemOut(label="Sales", value=Decimal(total_sales_records)),
    ]

    product_ids = list(product_profit.keys())
    product_names: dict[int, str] = {}
    if product_ids:
        name_rows = db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        ).all()
        product_names = {int(row[0]): str(row[1]) for row in name_rows}

    ranked_profit = sorted(product_profit.items(), key=lambda item: item[1], reverse=True)
    top_profit = ranked_profit[:top_n]
    profit_by_product_bar = [
        ChartBarItemOut(
            label=product_names.get(product_id, f"Product {product_id}"),
            value=value,
        )
        for product_id, value in top_profit
    ]

    ranked_revenue = sorted(
        ((product_id, value) for product_id, value in product_revenue.items() if value > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    top_revenue = ranked_revenue[:top_n]
    other_revenue = Decimal("0")
    if len(ranked_revenue) > top_n:
        other_revenue = sum((value for _, value in ranked_revenue[top_n:]), Decimal("0"))
    pie_total = sum((value for _, value in top_revenue), Decimal("0")) + other_revenue

    revenue_share_pie = [
        PieSliceOut(
            label=product_names.get(product_id, f"Product {product_id}"),
            value=value,
            share_percent=(value / pie_total * Decimal("100")) if pie_total > 0 else Decimal("0"),
        )
        for product_id, value in top_revenue
    ]
    if other_revenue > 0:
        revenue_share_pie.append(
            PieSliceOut(
                label="Others",
                value=other_revenue,
                share_percent=(other_revenue / pie_total * Decimal("100")) if pie_total > 0 else Decimal("0"),
            )
        )

    return DashboardChartsOut(
        shop_id=effective_shop_id,
        period_from=date_from,
        period_to=date_to,
        granularity=granularity,
        trend=trend,
        totals_bar=totals_bar,
        profit_by_product_bar=profit_by_product_bar,
        revenue_share_pie=revenue_share_pie,
    )
