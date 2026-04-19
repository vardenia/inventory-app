from flask import Flask, jsonify, request, abort
from pymongo import MongoClient, TEXT
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime
import os
import re

app = Flask(__name__)

# ── Database connection ──────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
client = MongoClient(MONGO_URI)
db = client["inventory"]
products_col = db["products"]

# Ensure a full-text search index exists on name + category + description
products_col.create_index([("product_name", TEXT), ("product_category", TEXT), ("description", TEXT)],
                          name="full_text_search")


# ── Helpers ──────────────────────────────────────────────────────────────────
def serialize(doc):
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    return doc


def validate_object_id(pid):
    try:
        return ObjectId(pid)
    except (InvalidId, TypeError):
        abort(400, description=f"'{pid}' is not a valid product id.")


def validate_payload(data, required_fields):
    missing = [f for f in required_fields if f not in data]
    if missing:
        abort(400, description=f"Missing required fields: {missing}")


# ── Routes ───────────────────────────────────────────────────────────────────

# GET /products  – list all products (supports ?search=, ?category=, ?min_price=, ?max_price=)
@app.route("/products", methods=["GET"])
def list_products():
    query = {}
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    if search:
        query["$text"] = {"$search": search}

    if category:
        query["product_category"] = {"$regex": re.escape(category), "$options": "i"}

    price_filter = {}
    if min_price is not None:
        try:
            price_filter["$gte"] = float(min_price)
        except ValueError:
            abort(400, description="min_price must be a number.")
    if max_price is not None:
        try:
            price_filter["$lte"] = float(max_price)
        except ValueError:
            abort(400, description="max_price must be a number.")
    if price_filter:
        query["price"] = price_filter

    docs = list(products_col.find(query))
    return jsonify([serialize(d) for d in docs]), 200


# GET /products/analytics  – aggregated metrics  (must be before /<id>)
@app.route("/products/analytics", methods=["GET"])
def analytics():
    pipeline_summary = [
        {
            "$group": {
                "_id": None,
                "total_products": {"$sum": 1},
                "average_price": {"$avg": "$price"},
                "total_inventory_value": {"$sum": {"$multiply": ["$price", "$available_quantity"]}},
                "total_units": {"$sum": "$available_quantity"},
            }
        }
    ]

    pipeline_categories = [
        {"$group": {"_id": "$product_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]

    pipeline_price_by_cat = [
        {
            "$group": {
                "_id": "$product_category",
                "avg_price": {"$avg": "$price"},
                "min_price": {"$min": "$price"},
                "max_price": {"$max": "$price"},
            }
        },
        {"$sort": {"avg_price": -1}},
    ]

    pipeline_low_stock = [
        {"$match": {"available_quantity": {"$lte": 10}}},
        {"$project": {"product_name": 1, "product_category": 1, "available_quantity": 1, "price": 1}},
        {"$sort": {"available_quantity": 1}},
    ]

    summary_result = list(products_col.aggregate(pipeline_summary))
    summary = summary_result[0] if summary_result else {}
    summary.pop("_id", None)

    categories = list(products_col.aggregate(pipeline_categories))
    most_popular_category = categories[0]["_id"] if categories else None

    price_by_category = [
        {
            "category": c["_id"],
            "avg_price": round(c["avg_price"], 2),
            "min_price": c["min_price"],
            "max_price": c["max_price"],
        }
        for c in products_col.aggregate(pipeline_price_by_cat)
    ]

    low_stock = [serialize(d) for d in products_col.aggregate(pipeline_low_stock)]

    return jsonify({
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_products": summary.get("total_products", 0),
            "average_price": round(summary.get("average_price", 0), 2),
            "total_inventory_value": round(summary.get("total_inventory_value", 0), 2),
            "total_units_in_stock": summary.get("total_units", 0),
            "most_popular_category": most_popular_category,
        },
        "category_breakdown": [{"category": c["_id"], "product_count": c["count"]} for c in categories],
        "price_by_category": price_by_category,
        "low_stock_alert": low_stock,
    }), 200


# GET /products/<id>  – fetch one product
@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    oid = validate_object_id(pid)
    doc = products_col.find_one({"_id": oid})
    if not doc:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(doc)), 200


# POST /products  – create a product
@app.route("/products", methods=["POST"])
def create_product():
    data = request.get_json(force=True, silent=True) or {}
    required = ["product_name", "product_category", "price", "available_quantity"]
    validate_payload(data, required)

    try:
        price = float(data["price"])
        qty = int(data["available_quantity"])
    except (ValueError, TypeError):
        abort(400, description="price must be a number and available_quantity must be an integer.")

    if price < 0 or qty < 0:
        abort(400, description="price and available_quantity must be non-negative.")

    product = {
        "product_name": str(data["product_name"]).strip(),
        "product_category": str(data["product_category"]).strip(),
        "price": price,
        "available_quantity": qty,
        "description": str(data.get("description", "")).strip(),
        "sku": str(data.get("sku", "")).strip(),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

    result = products_col.insert_one(product)
    product["id"] = str(result.inserted_id)
    product.pop("_id", None)
    return jsonify(product), 201


# PUT /products/<id>  – update a product
@app.route("/products/<pid>", methods=["PUT"])
def update_product(pid):
    oid = validate_object_id(pid)
    data = request.get_json(force=True, silent=True) or {}
    if not data:
        abort(400, description="Request body must be a non-empty JSON object.")

    allowed = {"product_name", "product_category", "price", "available_quantity", "description", "sku"}
    updates = {k: v for k, v in data.items() if k in allowed}

    if "price" in updates:
        try:
            updates["price"] = float(updates["price"])
            if updates["price"] < 0:
                raise ValueError
        except (ValueError, TypeError):
            abort(400, description="price must be a non-negative number.")

    if "available_quantity" in updates:
        try:
            updates["available_quantity"] = int(updates["available_quantity"])
            if updates["available_quantity"] < 0:
                raise ValueError
        except (ValueError, TypeError):
            abort(400, description="available_quantity must be a non-negative integer.")

    updates["updated_at"] = datetime.utcnow().isoformat() + "Z"

    result = products_col.find_one_and_update(
        {"_id": oid}, {"$set": updates}, return_document=True
    )
    if not result:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(result)), 200


# DELETE /products/<id>  – delete a product
@app.route("/products/<pid>", methods=["DELETE"])
def delete_product(pid):
    oid = validate_object_id(pid)
    result = products_col.delete_one({"_id": oid})
    if result.deleted_count == 0:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify({"message": f"Product '{pid}' deleted successfully."}), 200


# ── Error handlers ───────────────────────────────────────────────────────────
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
