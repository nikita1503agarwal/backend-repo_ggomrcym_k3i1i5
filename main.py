import os
from typing import List, Optional, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime, timezone

from database import db, create_document, get_documents
from bson import ObjectId

# ---------- Helpers ----------

def to_str_id(doc: dict) -> dict:
    if not doc:
        return doc
    d = doc.copy()
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # convert datetime to iso
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d

# ---------- App ----------

app = FastAPI(title="Suxhuk Ordering API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------

class PaymentMethod(BaseModel):
    label: str
    brand: Optional[str] = None
    last4: Optional[str] = None
    details: Optional[dict] = None

class CustomerIn(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_methods: List[PaymentMethod] = Field(default_factory=list)

class CustomerOut(CustomerIn):
    id: str

class InventoryItemIn(BaseModel):
    product: Literal["suxhuk", "mish_te_teren"]
    price_per_kg: float = Field(..., ge=0)
    min_kg: int = Field(..., ge=1)
    step_kg: int = Field(1, ge=1)
    available_kg: float = 0
    batch_threshold_kg: int = Field(15, ge=1)

class InventoryItemOut(InventoryItemIn):
    id: str

class OrderIn(BaseModel):
    customer_id: str
    product: Literal["suxhuk", "mish_te_teren"]
    quantity_kg: int = Field(..., ge=1)
    notes: Optional[str] = None

class OrderStatusUpdate(BaseModel):
    status: Literal["received", "in_production", "ready_for_collection"]

class OrderOut(BaseModel):
    id: str
    customer_id: str
    product: str
    quantity_kg: int
    total_price_nzd: float
    status: str
    created_at: str
    notes: Optional[str] = None
    batch_index: Optional[int] = None

# ---------- Root & Health ----------

@app.get("/")
def read_root():
    return {"message": "Suxhuk Ordering API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response

# ---------- Customers ----------

@app.get("/customers", response_model=List[CustomerOut])
def list_customers():
    docs = get_documents("customer")
    return [CustomerOut(**to_str_id(d)) for d in docs]

@app.post("/customers", response_model=CustomerOut)
def upsert_customer(data: CustomerIn):
    # Upsert by email
    existing = db["customer"].find_one({"email": data.email})
    now = datetime.now(timezone.utc)
    payload = data.model_dump()
    payload.update({"updated_at": now, "created_at": existing.get("created_at") if existing else now})
    if existing:
        db["customer"].update_one({"_id": existing["_id"]}, {"$set": payload})
        doc = db["customer"].find_one({"_id": existing["_id"]})
    else:
        new_id = create_document("customer", payload)
        doc = db["customer"].find_one({"_id": ObjectId(new_id)})
    return CustomerOut(**to_str_id(doc))

@app.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str):
    try:
        doc = db["customer"].find_one({"_id": ObjectId(customer_id)})
    except Exception:
        raise HTTPException(400, "Invalid customer id")
    if not doc:
        raise HTTPException(404, "Customer not found")
    return CustomerOut(**to_str_id(doc))

@app.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: str, data: CustomerIn):
    try:
        oid = ObjectId(customer_id)
    except Exception:
        raise HTTPException(400, "Invalid customer id")
    payload = data.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc)
    res = db["customer"].update_one({"_id": oid}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    doc = db["customer"].find_one({"_id": oid})
    return CustomerOut(**to_str_id(doc))

# ---------- Inventory ----------

@app.get("/inventory", response_model=List[InventoryItemOut])
def list_inventory():
    docs = get_documents("inventory")
    # Ensure we always have entries for both products with defaults
    existing_products = {d.get("product") for d in docs}
    defaults = []
    if "suxhuk" not in existing_products:
        defaults.append({
            "product": "suxhuk",
            "price_per_kg": 50.0,
            "min_kg": 1,
            "step_kg": 1,
            "available_kg": 0,
            "batch_threshold_kg": 15,
        })
    if "mish_te_teren" not in existing_products:
        defaults.append({
            "product": "mish_te_teren",
            "price_per_kg": 65.0,
            "min_kg": 3,
            "step_kg": 1,
            "available_kg": 0,
            "batch_threshold_kg": 15,
        })
    for item in defaults:
        create_document("inventory", item)
    docs = get_documents("inventory")
    return [InventoryItemOut(**to_str_id(d)) for d in docs]

@app.post("/inventory", response_model=InventoryItemOut)
def create_or_update_inventory(item: InventoryItemIn):
    existing = db["inventory"].find_one({"product": item.product})
    payload = item.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc)
    if existing:
        db["inventory"].update_one({"_id": existing["_id"]}, {"$set": payload})
        doc = db["inventory"].find_one({"_id": existing["_id"]})
    else:
        new_id = create_document("inventory", payload)
        doc = db["inventory"].find_one({"_id": ObjectId(new_id)})
    return InventoryItemOut(**to_str_id(doc))

@app.put("/inventory/{product}", response_model=InventoryItemOut)
def update_inventory(product: str, item: InventoryItemIn):
    if item.product != product:
        raise HTTPException(400, "Product path and body mismatch")
    existing = db["inventory"].find_one({"product": product})
    if not existing:
        raise HTTPException(404, "Inventory item not found")
    payload = item.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc)
    db["inventory"].update_one({"_id": existing["_id"]}, {"$set": payload})
    doc = db["inventory"].find_one({"_id": existing["_id"]})
    return InventoryItemOut(**to_str_id(doc))

# ---------- Orders ----------

@app.get("/orders", response_model=List[OrderOut])
def list_orders():
    docs = get_documents("order")
    out = []
    for d in docs:
        d = to_str_id(d)
        d["created_at"] = d.get("created_at", datetime.now(timezone.utc)).isoformat() if isinstance(d.get("created_at"), datetime) else d.get("created_at")
        out.append(OrderOut(**d))
    return out

@app.post("/orders", response_model=OrderOut)
def create_order(order: OrderIn):
    # Validate customer exists
    try:
        cust = db["customer"].find_one({"_id": ObjectId(order.customer_id)})
    except Exception:
        raise HTTPException(400, "Invalid customer id")
    if not cust:
        raise HTTPException(404, "Customer not found")

    # Load inventory item
    inv = db["inventory"].find_one({"product": order.product})
    if not inv:
        raise HTTPException(400, "Inventory for product not configured yet")

    # Enforce min and step
    if order.quantity_kg < int(inv.get("min_kg", 1)):
        raise HTTPException(400, f"Minimum order is {inv.get('min_kg')} kg")
    step = int(inv.get("step_kg", 1))
    if order.quantity_kg % step != 0:
        raise HTTPException(400, f"Quantity must be in increments of {step} kg")

    # Calculate total and batch index based on deficit
    price_per_kg = float(inv.get("price_per_kg", 0))
    total = round(price_per_kg * order.quantity_kg, 2)

    new_available = float(inv.get("available_kg", 0)) - order.quantity_kg
    deficit = abs(new_available) if new_available < 0 else 0
    threshold = int(inv.get("batch_threshold_kg", 15))
    batch_index = (deficit - 1) // threshold if deficit > 0 else 0

    order_doc = {
        "customer_id": order.customer_id,
        "product": order.product,
        "quantity_kg": int(order.quantity_kg),
        "total_price_nzd": total,
        "status": "received",
        "notes": order.notes,
        "batch_index": int(batch_index),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    new_id = create_document("order", order_doc)

    # Update inventory available kg
    db["inventory"].update_one({"_id": inv["_id"]}, {"$set": {"available_kg": new_available, "updated_at": datetime.now(timezone.utc)}})

    saved = db["order"].find_one({"_id": ObjectId(new_id)})
    saved = to_str_id(saved)
    saved["created_at"] = saved.get("created_at").isoformat()
    return OrderOut(**saved)

@app.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_order_status(order_id: str, body: OrderStatusUpdate):
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(400, "Invalid order id")
    res = db["order"].update_one({"_id": oid}, {"$set": {"status": body.status, "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(404, "Order not found")
    doc = db["order"].find_one({"_id": oid})
    out = to_str_id(doc)
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return OrderOut(**out)

# Simple helper to clear and seed inventory (optional for quick start)
@app.post("/seed")
def seed_defaults():
    # Ensure suxhuk and mish_te_teren with default prices and mins
    defaults = [
        {
            "product": "suxhuk",
            "price_per_kg": 50.0,
            "min_kg": 1,
            "step_kg": 1,
            "available_kg": 0,
            "batch_threshold_kg": 15,
        },
        {
            "product": "mish_te_teren",
            "price_per_kg": 65.0,
            "min_kg": 3,
            "step_kg": 1,
            "available_kg": 0,
            "batch_threshold_kg": 15,
        },
    ]
    for item in defaults:
        existing = db["inventory"].find_one({"product": item["product"]})
        if existing:
            db["inventory"].update_one({"_id": existing["_id"]}, {"$set": item})
        else:
            create_document("inventory", item)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
