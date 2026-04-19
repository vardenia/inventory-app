from pymongo import MongoClient, TEXT
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
from bson import ObjectId
import os


MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["inventory"]


def serialize(doc):
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    return doc


class ProductRepository:
    """
    Handles all MongoDB operations for the products collection.

    Accepts a MongoDB collection at construction so it can be swapped out
    for a mock collection during testing without touching any other code.

    All methods raise RuntimeError on database failure, keeping Flask-specific
    logic (abort, HTTP status codes) out of this layer entirely.
    """

    def __init__(self, collection):
        self.collection = collection
        self.collection.create_index(
            [("product_name", TEXT), ("product_category", TEXT), ("description", TEXT)],
            name="full_text_search"
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def ping(self):
        """
        Ping the MongoDB server.
        Returns (status: str, error: str|None).
        """
        try:
            _client.admin.command("ping")
            return "ok", None
        except ConnectionFailure as e:
            return "unavailable", f"Connection failure: {str(e)}"
        except PyMongoError as e:
            return "unavailable", f"Database error: {str(e)}"

    # ── Read ──────────────────────────────────────────────────────────────────

    def find_all(self, query):
        """Return all documents matching query. Raises RuntimeError on failure."""
        try:
            return list(self.collection.find(query))
        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Please try again later.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while retrieving products.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while retrieving products.")

    def find_by_id(self, oid):
        """
        Return a single document by ObjectId, or None if not found.
        Raises RuntimeError on failure.
        """
        try:
            return self.collection.find_one({"_id": oid})
        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Please try again later.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while retrieving the product.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while retrieving the product.")

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, product_dict):
        """
        Insert a new product document.
        Returns the inserted dict with its generated id field.
        Raises RuntimeError on failure.
        """
        try:
            result = self.collection.insert_one(product_dict)
            product_dict["id"] = str(result.inserted_id)
            product_dict.pop("_id", None)
            return product_dict
        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Unable to create product.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while creating the product.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while creating the product.")

    def update(self, oid, updates):
        """
        Apply a $set update to the product with the given ObjectId.
        Returns the updated document, or None if no document matched.
        Raises RuntimeError on failure.
        """
        try:
            return self.collection.find_one_and_update(
                {"_id": oid},
                {"$set": updates},
                return_document=True
            )
        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Unable to update product.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while updating the product.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while updating the product.")

    def delete(self, oid):
        """
        Delete the product with the given ObjectId.
        Returns True if a document was deleted, False if none matched.
        Raises RuntimeError on failure.
        """
        try:
            result = self.collection.delete_one({"_id": oid})
            return result.deleted_count > 0
        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Unable to delete product.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while deleting the product.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while deleting the product.")

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_analytics(self):
        """
        Run four aggregation pipelines and return their results as a tuple:
          (summary, categories, price_by_category, low_stock)
        Raises RuntimeError on failure.
        """
        try:
            pipeline_summary = [
                {
                    "$group": {
                        "_id": None,
                        "total_products": {"$sum": 1},
                        "average_price": {"$avg": "$price"},
                        "total_inventory_value": {
                            "$sum": {"$multiply": ["$price", "$available_quantity"]}
                        },
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
                {"$project": {
                    "product_name": 1, "product_category": 1,
                    "available_quantity": 1, "price": 1
                }},
                {"$sort": {"available_quantity": 1}},
            ]

            summary_result = list(self.collection.aggregate(pipeline_summary))
            summary = summary_result[0] if summary_result else {}
            summary.pop("_id", None)

            categories = list(self.collection.aggregate(pipeline_categories))
            price_by_category = list(self.collection.aggregate(pipeline_price_by_cat))
            low_stock = list(self.collection.aggregate(pipeline_low_stock))

            return summary, categories, price_by_category, low_stock

        except ConnectionFailure:
            raise RuntimeError("Database unreachable. Unable to retrieve analytics.")
        except OperationFailure:
            raise RuntimeError("Database operation failed while retrieving analytics.")
        except PyMongoError:
            raise RuntimeError("Unexpected database error while retrieving analytics.")


# ── Module-level repository instance ─────────────────────────────────────────
# Instantiated once when the module is first imported by app.py.
# Routes call repo.find_all(), repo.create(), etc. directly.
repo = ProductRepository(_db["products"])
