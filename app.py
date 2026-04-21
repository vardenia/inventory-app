from flask import Flask, jsonify, request, abort
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime
import os
import re

# Import the shared repository instance and serialize helper from db.py,
# along with the custom database exception classes so this file can catch them.
from db import repo, serialize, DatabaseConnectionError, DatabaseOperationError

# Import the data model and validator from models.py.
# ValidationError is the base class — catching it handles MissingFieldError,
# InvalidPriceError, and InvalidQuantityError all in one except block.
from models import Product, ProductValidator, ValidationError

app = Flask(__name__)

APP_VERSION = "1.3.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_object_id(pid):
    """
    Converts the string ID from a URL parameter into a MongoDB ObjectId.

    MongoDB requires ObjectId type for _id lookups — passing a plain string
    would return no results. If the string is not a valid ObjectId format,
    this function aborts the request immediately with a 400 error rather than
    letting an invalid ID reach the database.
    """
    try:
        return ObjectId(pid)
    except (InvalidId, TypeError):
        abort(400, description=f"'{pid}' is not a valid product id.")


# ── Routes ────────────────────────────────────────────────────────────────────
# Each function below handles one API endpoint. The function's only jobs are:
#   1. Parse and validate the incoming request.
#   2. Call the appropriate repository method.
#   3. Return the response.
# No MongoDB queries are written here — all database logic lives in db.py.

# GET /health
@app.route("/health", methods=["GET"])
def health():
    """
    Returns the application version and a live database connectivity status.

    This endpoint is used by monitoring tools and load balancers to check
    whether the application is running and able to reach its database.
    Returns HTTP 200 if healthy, or HTTP 503 if the database is unreachable.
    """
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
    # Only include the error detail in the response if something went wrong.
    if db_error:
        payload["services"]["database"]["error"] = db_error
    return jsonify(payload), 200 if status == "ok" else 503


# GET /products
@app.route("/products", methods=["GET"])
def list_products():
    """
    Returns a list of all products, with optional filtering via query parameters:
      ?search=    Full-text search across product name, category, and description.
      ?category=  Case-insensitive match on product category.
      ?min_price= Return only products at or above this price.
      ?max_price= Return only products at or below this price.

    Filters are combined — all provided filters must match for a product
    to be included in the results.
    """
    # Start with an empty query — if no filters are provided, all products
    # are returned.
    query = {}

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    if search:
        # $text uses the full-text search index created in ProductRepository.__init__.
        query["$text"] = {"$search": search}
    if category:
        # $regex allows case-insensitive partial matching on the category field.
        # re.escape() prevents special characters in the input from being treated
        # as regex syntax, which would be a security risk.
        query["product_category"] = {"$regex": re.escape(category), "$options": "i"}

    # Build the price filter only if at least one bound was provided.
    # Both ValueError and TypeError are caught: ValueError handles non-numeric
    # strings like "abc", and TypeError handles unexpected None values that
    # could occur with certain request encodings.
    price_filter = {}
    if min_price is not None:
        try:
            price_filter["$gte"] = float(min_price)
        except (ValueError, TypeError):
            abort(400, description="min_price must be a number.")
    if max_price is not None:
        try:
            price_filter["$lte"] = float(max_price)
        except (ValueError, TypeError):
            abort(400, description="max_price must be a number.")
    if price_filter:
        query["price"] = price_filter

    try:
        docs = repo.find_all(query)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))

    # serialize() converts each document's ObjectId to a plain string before
    # jsonify() attempts to serialize the list.
    return jsonify([serialize(d) for d in docs]), 200


# GET /products/analytics
# This route must be registered before GET /products/<pid> below. Flask matches
# routes in registration order, and without this ordering the word 'analytics'
# would be treated as a product ID, producing a confusing 400 error.
@app.route("/products/analytics", methods=["GET"])
def analytics():
    """
    Returns aggregated metrics calculated from the products collection:
      - Overall totals and averages (count, average price, inventory value).
      - Product count broken down by category.
      - Price statistics (avg, min, max) per category.
      - Products with 10 or fewer units remaining, sorted by urgency.

    All computation happens inside MongoDB via aggregation pipelines rather
    than in Python, keeping the response fast regardless of collection size.
    """
    try:
        summary, categories, price_by_category, low_stock = repo.get_analytics()
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))

    # The most popular category is simply the first item returned by the
    # categories pipeline, which is already sorted by count descending.
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
    """Fetches and returns a single product by its ID."""
    oid = parse_object_id(pid)
    try:
        doc = repo.find_by_id(oid)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))
    if not doc:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(doc)), 200


# POST /products
@app.route("/products", methods=["POST"])
def create_product():
    """
    Creates a new product from the JSON request body.

    Required fields: product_name, product_category, price, available_quantity.
    Optional fields: description, sku.

    Validation and object construction are intentionally in separate try blocks.
    This guarantees that if validate_create() passes, the product variable is
    always assigned before the database call attempts to use it. Combining them
    in one block would risk an UnboundLocalError if from_dict() raised an
    exception that wasn't a ValidationError.
    """
    data = request.get_json(force=True, silent=True) or {}

    # Step 1: validate the raw payload first.
    # ValidationError is the base class for MissingFieldError,
    # InvalidPriceError, and InvalidQuantityError. Catching the base class
    # here handles all three without needing separate except blocks.
    try:
        ProductValidator.validate_create(data)
    except ValidationError as e:
        abort(400, description=str(e))

    # Step 2: build the Product object only after validation has passed.
    # Separating this from Step 1 ensures product is always bound before
    # the database call below attempts to use it.
    try:
        product = Product.from_dict(data)
    except ValidationError as e:
        abort(400, description=str(e))

    try:
        created = repo.create(product.to_dict())
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))

    return jsonify(created), 201


# PUT /products/<id>
@app.route("/products/<pid>", methods=["PUT"])
def update_product(pid):
    """
    Partially updates an existing product.

    Only the fields included in the request body are changed — all other
    fields remain as they are. This is handled by MongoDB's $set operator
    in ProductRepository.update().
    """
    oid = parse_object_id(pid)
    data = request.get_json(force=True, silent=True) or {}

    try:
        # validate_update() returns only the fields that are allowed to be
        # updated, filtering out anything else the client may have sent.
        updates = ProductValidator.validate_update(data)
    except ValidationError as e:
        abort(400, description=str(e))

    # Cast numeric fields to the correct Python types after validation has
    # confirmed they are safe to convert. validate_update() checks that these
    # values are valid but intentionally leaves coercion to the caller so that
    # the validator remains a pure checking function with no side effects.
    if "price" in updates:
        updates["price"] = float(updates["price"])
    if "available_quantity" in updates:
        updates["available_quantity"] = int(updates["available_quantity"])

    # Always stamp updated_at with the current time on any successful update.
    updates["updated_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        result = repo.update(oid, updates)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))

    if not result:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify(serialize(result)), 200


# DELETE /products/<id>
@app.route("/products/<pid>", methods=["DELETE"])
def delete_product(pid):
    """Permanently deletes a product by its ID."""
    oid = parse_object_id(pid)
    try:
        deleted = repo.delete(oid)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        abort(503, description=str(e))
    if not deleted:
        abort(404, description=f"Product '{pid}' not found.")
    return jsonify({"message": f"Product '{pid}' deleted successfully."}), 200


# ── Error handlers ────────────────────────────────────────────────────────────
# These functions intercept abort() calls made anywhere in the application and
# format the error as a consistent JSON response. Without these, Flask would
# return an HTML error page, which is not appropriate for a JSON API.

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
@app.errorhandler(503)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


if __name__ == "__main__":
    # debug=True enables auto-reload on code changes and an interactive error
    # page in the browser. It must never be enabled in production as it allows
    # arbitrary code execution by anyone who triggers an error.
    # Controlled here via an environment variable so it is off by default.
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
