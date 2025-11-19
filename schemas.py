"""
Database Schemas for Suxhuk Ordering App

Each Pydantic model represents a MongoDB collection. The collection name is the
lowercase of the class name by default.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

# ----------------------------
# Core domain schemas
# ----------------------------

class PaymentMethod(BaseModel):
    label: str = Field(..., description="Friendly name, e.g., Visa ending 1234")
    brand: Optional[str] = Field(None, description="Card brand or type")
    last4: Optional[str] = Field(None, description="Last 4 digits if card")
    details: Optional[dict] = Field(default=None, description="Gateway-specific metadata")

class Customer(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_methods: List[PaymentMethod] = Field(default_factory=list)
    created_at: Optional[datetime] = None

class Inventory(BaseModel):
    product: Literal["suxhuk", "mish_te_teren"]
    price_per_kg: float = Field(..., ge=0)
    min_kg: int = Field(..., ge=1, description="Minimum kg per order")
    step_kg: int = Field(1, ge=1, description="Order increment in kg")
    available_kg: float = Field(0, description="Can go negative for preorder")
    batch_threshold_kg: int = Field(15, ge=1, description="When deficit hits this, start a new batch")

class Order(BaseModel):
    customer_id: str
    product: Literal["suxhuk", "mish_te_teren"]
    quantity_kg: int = Field(..., ge=1)
    total_price_nzd: float
    status: Literal["received", "in_production", "ready_for_collection"] = "received"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    batch_index: Optional[int] = Field(None, description="Optional grouping by 15kg batches")
