from flask import Flask, jsonify, request, abort
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime
import re

from db import repo, serialize
from models import Product, ProductValidator

app = Flask(__name__)

APP_VERSION = "1.3.0"


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_object_id(pid):
    """Convert a string to a MongoDB ObjectId, or abort with 400."""
    try:
        return ObjectId(pid)
    except (InvalidId, TypeError):
        abort(400, description=f"'{pid}' is not a valid product id.")


# ── Routes ────────────────────────────────────────────────────────────────────

# GET /health
@app.route("/health", methods=["GET"])
def health():
    db_status, db_error = repo.ping()
    status = "ok" if db_status == "ok" else "degraded"
    payload = {
        "status": status,
        "version": APP_VERSION,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "services": {
            "database": {"status": db_status},
        },
    }
    if db_error:
        payload["services"]["database"]["error"] = db_error
    return jsonify(payload), 200 if status == "ok" else 503


# GET /products
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

    try:
        docs = repo.find_all(query)
    except RuntimeError as e:
        abort(503, description=str(e))

    return jsonify([serialize(d) for d in docs]), 200


# GET /products/analytics  (registered before /<pid> to avoid route collision)
@app.route("/products/analytics", methods=["GET"])
def analytics():
    try:
        summary, categories, price_by_category, low_stock = repo.get_analytics()
    except RuntimeError as e:
        abort(503, description=str(e))

    most_popular_category = categories[0]["_id"] if categories else None

    return jsonify({
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_products": summary.get("total_products", 0),
            "average_price": round(summary.get("average_price", 0), 2),
            "total_inventory_value": round(summary.get("total_inventory_value", 0), 2),
            "total_units_in_stock": summary.get("total_units", 0),
            "most_popular_category": most_popular_category,
        },
        "category_breakdown": [
            {"category": c["_id"], "product_count": c["count"]} for c in categories
        ],
        "price_by_category": [
            {
                "category": c["_id"],
                "avg_price": round(c["avg_price"], 2),
                "min_price": c["min_price"],
                "max_price": c["max_price"],
            }
            for c in price_by_category
        ],
        "low_stock_alert": [serialize(d) for d in low_stock],
    }), 200


# GET /products/<id>
@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    oid = parse_object_id(pid)
    try:
        doc = repo.find_by_id(oid)
    except RuntimeError as e:
        abort(503, description=str(e))
    if not doc:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(doc)), 200


# POST /products
@app.route("/products", methods=["POST"])
def create_product():
    data = request.get_json(force=True, silent=True) or {}

    try:
        ProductValidator.validate_create(data)
        product = Product.from_dict(data)
    except ValueError as e:
        abort(400, description=str(e))

    try:
        created = repo.create(product.to_dict())
    except RuntimeError as e:
        abort(503, description=str(e))

    return jsonify(created), 201


# PUT /products/<id>
@app.route("/products/<pid>", methods=["PUT"])
def update_product(pid):
    oid = parse_object_id(pid)
    data = request.get_json(force=True, silent=True) or {}

    try:
        updates = ProductValidator.validate_update(data)
    except ValueError as e:
        abort(400, description=str(e))

    # Coerce types after validation
    if "price" in updates:
        updates["price"] = float(updates["price"])
    if "available_quantity" in updates:
        updates["available_quantity"] = int(updates["available_quantity"])
    updates["updated_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        result = repo.update(oid, updates)
    except RuntimeError as e:
        abort(503, description=str(e))

    if not result:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(result)), 200


# DELETE /products/<id>
@app.route("/products/<pid>", methods=["DELETE"])
def delete_product(pid):
    oid = parse_object_id(pid)
    try:
        deleted = repo.delete(oid)
    except RuntimeError as e:
        abort(503, description=str(e))
    if not deleted:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify({"message": f"Product '{pid}' deleted successfully."}), 200


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
@app.errorhandler(503)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
