"""
seed.py – Populate the inventory database with sample product data.
Run once after the containers are up:  docker compose exec api python seed.py
"""

from pymongo import MongoClient
from datetime import datetime
import os
import sys

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
client = MongoClient(MONGO_URI)
db = client["inventory"]
col = db["products"]

SAMPLE_PRODUCTS = [
    # Electronics
    {"product_name": "4K Smart TV 55-inch", "product_category": "Electronics",
     "price": 699.99, "available_quantity": 45, "sku": "EL-TV-001",
     "description": "55-inch 4K UHD Smart TV with HDR and built-in streaming apps."},
    {"product_name": "Wireless Noise-Cancelling Headphones", "product_category": "Electronics",
     "price": 249.99, "available_quantity": 120, "sku": "EL-HP-002",
     "description": "Over-ear headphones with 30-hour battery life and ANC."},
    {"product_name": "Gaming Laptop 15-inch", "product_category": "Electronics",
     "price": 1399.00, "available_quantity": 30, "sku": "EL-LP-003",
     "description": "RTX 4060 GPU, 16 GB RAM, 512 GB NVMe SSD."},
    {"product_name": "USB-C Hub 7-in-1", "product_category": "Electronics",
     "price": 39.99, "available_quantity": 200, "sku": "EL-HB-004",
     "description": "HDMI, 3× USB-A, SD card reader, PD charging."},
    {"product_name": "Mechanical Keyboard RGB", "product_category": "Electronics",
     "price": 89.99, "available_quantity": 8, "sku": "EL-KB-005",
     "description": "TKL layout, Cherry MX Brown switches, per-key RGB."},

    # Clothing
    {"product_name": "Men's Running Shoes", "product_category": "Clothing",
     "price": 119.99, "available_quantity": 75, "sku": "CL-SH-001",
     "description": "Lightweight mesh upper, responsive foam midsole."},
    {"product_name": "Women's Yoga Pants", "product_category": "Clothing",
     "price": 54.99, "available_quantity": 150, "sku": "CL-YP-002",
     "description": "4-way stretch fabric, moisture-wicking, high-waist."},
    {"product_name": "Winter Down Jacket", "product_category": "Clothing",
     "price": 189.00, "available_quantity": 60, "sku": "CL-JK-003",
     "description": "650-fill power, water-resistant shell, packable."},
    {"product_name": "Classic Cotton T-Shirt", "product_category": "Clothing",
     "price": 19.99, "available_quantity": 300, "sku": "CL-TS-004",
     "description": "100% organic cotton, available in 12 colours."},
    {"product_name": "Slim Fit Chinos", "product_category": "Clothing",
     "price": 64.99, "available_quantity": 5, "sku": "CL-CH-005",
     "description": "Stretch twill, wrinkle-resistant, machine washable."},

    # Home & Kitchen
    {"product_name": "Air Fryer 5.8 Qt", "product_category": "Home & Kitchen",
     "price": 79.99, "available_quantity": 90, "sku": "HK-AF-001",
     "description": "Rapid hot-air circulation, 7 preset cooking programs."},
    {"product_name": "Robot Vacuum Cleaner", "product_category": "Home & Kitchen",
     "price": 329.99, "available_quantity": 35, "sku": "HK-RV-002",
     "description": "LiDAR navigation, auto-empty base, app-controlled."},
    {"product_name": "Cast Iron Skillet 12-inch", "product_category": "Home & Kitchen",
     "price": 44.95, "available_quantity": 55, "sku": "HK-SK-003",
     "description": "Pre-seasoned, compatible with all stovetops and oven."},
    {"product_name": "Bamboo Cutting Board Set", "product_category": "Home & Kitchen",
     "price": 29.99, "available_quantity": 110, "sku": "HK-CB-004",
     "description": "Set of 3 sizes, juice groove, non-slip feet."},
    {"product_name": "Smart Coffee Maker", "product_category": "Home & Kitchen",
     "price": 149.99, "available_quantity": 7, "sku": "HK-CM-005",
     "description": "Wi-Fi enabled, schedule brews, 12-cup capacity."},

    # Sports & Outdoors
    {"product_name": "Adjustable Dumbbell Set 5–52 lb", "product_category": "Sports & Outdoors",
     "price": 349.00, "available_quantity": 22, "sku": "SO-DB-001",
     "description": "Replaces 15 sets, dial-select weight system."},
    {"product_name": "Yoga Mat Premium 6mm", "product_category": "Sports & Outdoors",
     "price": 34.99, "available_quantity": 180, "sku": "SO-YM-002",
     "description": "Non-slip texture, eco-friendly TPE, includes carry strap."},
    {"product_name": "Camping Tent 4-Person", "product_category": "Sports & Outdoors",
     "price": 199.95, "available_quantity": 18, "sku": "SO-TN-003",
     "description": "3-season, 2-door, rainfly included, 5-min setup."},
    {"product_name": "Hydration Running Vest", "product_category": "Sports & Outdoors",
     "price": 89.99, "available_quantity": 3, "sku": "SO-HV-004",
     "description": "2L reservoir, 8 pockets, reflective strips."},
    {"product_name": "Foam Roller 36-inch", "product_category": "Sports & Outdoors",
     "price": 24.99, "available_quantity": 95, "sku": "SO-FR-005",
     "description": "High-density EVA foam, textured surface for myofascial release."},

    # Books
    {"product_name": "Python Data Science Handbook", "product_category": "Books",
     "price": 49.99, "available_quantity": 65, "sku": "BK-DS-001",
     "description": "Covers NumPy, Pandas, Matplotlib, and Scikit-Learn."},
    {"product_name": "Clean Code", "product_category": "Books",
     "price": 39.99, "available_quantity": 80, "sku": "BK-SE-002",
     "description": "A handbook of agile software craftsmanship by Robert C. Martin."},
    {"product_name": "Atomic Habits", "product_category": "Books",
     "price": 16.99, "available_quantity": 200, "sku": "BK-PD-003",
     "description": "An easy & proven way to build good habits and break bad ones."},
]

now = datetime.utcnow().isoformat() + "Z"
for p in SAMPLE_PRODUCTS:
    p["created_at"] = now
    p["updated_at"] = now

# Wrap the database calls in a try/except so that a connection failure produces
# a readable error message rather than a raw PyMongo traceback.
# The finally block ensures the connection is always closed, whether the
# insert succeeded or failed — without it, a failure would leave the
# connection open.
try:
    col.delete_many({})  # wipe existing data before re-seeding
    result = col.insert_many(SAMPLE_PRODUCTS)
    print(f"✅  Inserted {len(result.inserted_ids)} products into inventory.products.")
except Exception as e:
    print(f"❌  Seeding failed: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    client.close()
