from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ProductUnit = Literal["piece", "kg", "litre", "carton"]


class ShopCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    location: str | None = Field(default=None, max_length=255)


class ShopUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class ShopOut(BaseModel):
    id: int
    code: str
    name: str
    location: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    shop_id: int | None = None
    sku: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    unit: ProductUnit = "piece"
    description: str | None = None


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=2, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    unit: ProductUnit | None = None
    description: str | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: int
    shop_id: int
    sku: str
    name: str
    unit: ProductUnit
    description: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class StockUpsertRequest(BaseModel):
    shop_id: int
    product_id: int
    quantity_on_hand: int = Field(ge=0)
    buying_price: Decimal = Field(gt=0)
    selling_price: Decimal = Field(gt=0)


class StockOut(BaseModel):
    id: int
    shop_id: int
    product_id: int
    quantity_on_hand: int
    buying_price: Decimal
    selling_price: Decimal
    unit_profit: Decimal
    updated_at: datetime

    model_config = {"from_attributes": True}


class StockAdjustRequest(BaseModel):
    quantity_delta: int = Field(default=0, description="Signed delta to apply, may be negative")
    buying_price: Decimal | None = Field(default=None, gt=0)
    selling_price: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=255)


class StockAdjustmentOut(BaseModel):
    id: int
    stock_id: int
    shop_id: int
    product_id: int
    adjusted_by_user_id: int | None
    quantity_before: int
    quantity_after: int
    quantity_delta: int
    reason: str | None
    adjusted_at: datetime

    model_config = {"from_attributes": True}


class SaleCreateRequest(BaseModel):
    shop_id: int
    product_id: int
    quantity: int = Field(gt=0)
    unit_selling_price: Decimal | None = Field(default=None, gt=0)


class SaleOut(BaseModel):
    id: int
    shop_id: int
    product_id: int
    sold_by_user_id: int | None
    quantity: int
    unit_buying_price: Decimal
    unit_selling_price: Decimal
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    sold_at: datetime

    model_config = {"from_attributes": True}


class SaleReturnCreateRequest(BaseModel):
    quantity: int = Field(gt=0)
    restock: bool = True
    note: str | None = Field(default=None, max_length=255)


class SaleReturnOut(BaseModel):
    id: int
    sale_id: int
    shop_id: int
    product_id: int
    processed_by_user_id: int | None
    quantity: int
    unit_buying_price: Decimal
    unit_selling_price: Decimal
    refund_amount: Decimal
    cost_reversed: Decimal
    profit_reversed: Decimal
    restocked: bool
    note: str | None
    returned_at: datetime

    model_config = {"from_attributes": True}


class ProfitReportOut(BaseModel):
    shop_id: int
    period_from: datetime | None
    period_to: datetime | None
    total_revenue: Decimal
    total_cost: Decimal
    total_profit: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    total_sales_records: int


class ProductProfitOut(BaseModel):
    product_id: int
    product_name: str
    total_quantity_sold: int
    total_revenue: Decimal
    total_cost: Decimal
    total_profit: Decimal


class DashboardSummaryOut(BaseModel):
    shop_id: int | None
    period_from: datetime | None
    period_to: datetime | None
    total_revenue: Decimal
    total_cost: Decimal
    total_profit: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    total_sales_records: int
    total_units_sold: int
    low_stock_items: int
    top_products_by_profit: list[ProductProfitOut]


class TrendPointOut(BaseModel):
    bucket_start: datetime
    bucket_label: str
    total_revenue: Decimal
    total_cost: Decimal
    total_profit: Decimal
    total_units_sold: int
    total_sales_records: int


class ChartBarItemOut(BaseModel):
    label: str
    value: Decimal


class PieSliceOut(BaseModel):
    label: str
    value: Decimal
    share_percent: Decimal


class DashboardChartsOut(BaseModel):
    shop_id: int | None
    period_from: datetime | None
    period_to: datetime | None
    granularity: str
    trend: list[TrendPointOut]
    totals_bar: list[ChartBarItemOut]
    profit_by_product_bar: list[ChartBarItemOut]
    revenue_share_pie: list[PieSliceOut]


class ExpenseCreate(BaseModel):
    shop_id: int | None = None
    category: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)
    incurred_at: datetime | None = None


class ExpenseUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=2, max_length=120)
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=255)
    incurred_at: datetime | None = None


class ExpenseOut(BaseModel):
    id: int
    shop_id: int
    created_by_user_id: int | None
    category: str
    amount: Decimal
    note: str | None
    incurred_at: datetime

    model_config = {"from_attributes": True}


class SupplierCreate(BaseModel):
    shop_id: int | None = None
    name: str = Field(min_length=2, max_length=160)
    contact: str | None = Field(default=None, max_length=255)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    contact: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    id: int
    shop_id: int
    name: str
    contact: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseCreate(BaseModel):
    shop_id: int
    product_id: int
    supplier_id: int | None = None
    invoice_number: str | None = Field(default=None, max_length=64)
    quantity: int = Field(gt=0)
    unit_buying_price: Decimal = Field(gt=0)
    unit_selling_price: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=255)
    purchased_at: datetime | None = None


class PurchaseUpdate(BaseModel):
    supplier_id: int | None = None
    invoice_number: str | None = Field(default=None, max_length=64)
    quantity: int | None = Field(default=None, gt=0)
    unit_buying_price: Decimal | None = Field(default=None, gt=0)
    unit_selling_price: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=255)
    purchased_at: datetime | None = None


class PurchaseOut(BaseModel):
    id: int
    shop_id: int
    product_id: int
    supplier_id: int | None
    invoice_number: str | None
    purchased_by_user_id: int | None
    unit: ProductUnit
    quantity: int
    unit_buying_price: Decimal
    unit_selling_price: Decimal
    total_cost: Decimal
    note: str | None
    purchased_at: datetime

    model_config = {"from_attributes": True}


class ReorderSuggestionOut(BaseModel):
    shop_id: int
    product_id: int
    product_name: str
    unit: ProductUnit
    current_stock: int
    avg_daily_sales: Decimal
    recommended_reorder_qty: int
    lookback_days: int
    lead_days: int


class InventoryAuditItemOut(BaseModel):
    event_type: str
    entity_type: str
    entity_id: int
    shop_id: int
    product_id: int | None
    user_id: int | None
    occurred_at: datetime
    summary: str


class LowStockItemOut(BaseModel):
    shop_id: int
    product_id: int
    quantity_on_hand: int
    threshold: int


class TransferStockRequest(BaseModel):
    product_id: int
    from_shop_id: int
    to_shop_id: int
    quantity: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)


class TransferStockUpdate(BaseModel):
    product_id: int | None = None
    from_shop_id: int | None = None
    to_shop_id: int | None = None
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=255)


class StockTransferOut(BaseModel):
    id: int
    product_id: int
    from_shop_id: int
    to_shop_id: int
    transferred_by_user_id: int | None
    quantity: int
    unit_buying_price: Decimal
    unit_selling_price: Decimal
    note: str | None
    transferred_at: datetime

    model_config = {"from_attributes": True}
