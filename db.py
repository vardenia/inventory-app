from pymongo import MongoClient, TEXT
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
from bson import ObjectId
import os


# Read the MongoDB connection string from the environment.
# When running in Docker, MONGO_URI is set in docker-compose.yml to point to
# the mongo service. The default here allows the app to run outside Docker too.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["inventory"]


# ── Custom exceptions ─────────────────────────────────────────────────────────
# Using specific exception classes instead of the generic RuntimeError means
# app.py can catch database errors precisely, without accidentally catching
# unrelated errors from elsewhere in the application.

class DatabaseConnectionError(Exception):
    """
    Raised when the application cannot reach the MongoDB server at all.
    Maps to a 503 Service Unavailable response in app.py.
    """
    pass

class DatabaseOperationError(Exception):
    """
    Raised when a query reaches the MongoDB server but is rejected or fails.
    Also maps to a 503 Service Unavailable response in app.py.
    """
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def serialize(doc):
    """
    Converts a MongoDB document into a JSON-serializable dictionary.

    MongoDB stores a special ObjectId type for the _id field, which cannot be
    directly converted to JSON. This function converts it to a plain string and
    renames it to 'id' so API responses are clean and standard.

    Operates on a shallow copy of the document so the original is never
    mutated. Without this, calling serialize() on a document would permanently
    remove its _id field, which could cause bugs if the same object were used
    again elsewhere.
    """
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


# ── ProductRepository ─────────────────────────────────────────────────────────

class ProductRepository:
    """
    Handles all MongoDB operations for the products collection.

    This class follows the Repository pattern: all database logic lives here,
    and the rest of the application (app.py) never writes a MongoDB query
    directly. This separation means:
      - If the database ever changes, only this file needs to be updated.
      - Tests can pass in a mock collection instead of a real database,
        making every method testable without MongoDB running.

    The collection is passed in at construction (dependency injection) rather
    than being created internally, which is what enables that testability.
    """

    def __init__(self, collection):
        """
        Stores the collection and creates the full-text search index.

        The index is created here rather than as a separate setup step so the
        application is always ready to handle search queries immediately on
        startup. PyMongo silently skips index creation if it already exists,
        so calling this on every restart is safe.
        """
        self.collection = collection

        # A TEXT index on these three fields enables MongoDB's $text operator,
        # which powers the ?search= query parameter on GET /products.
        # Without this index, full-text search would require scanning every
        # document in the collection on every request.
        self.collection.create_index(
            [("product_name", TEXT), ("product_category", TEXT), ("description", TEXT)],
            name="full_text_search"
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def ping(self):
        """
        Sends a ping command to the MongoDB server to verify the connection.

        Returns a tuple of (status, error_message) rather than raising an
        exception, because the health endpoint is specifically designed to
        report on database status — a failed ping is an expected outcome
        that should be reported, not an error that should crash the request.
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
        """
        Returns all documents in the collection that match the given query.

        The query is built in app.py based on the request's query parameters
        (?search=, ?category=, ?min_price=, ?max_price=) and passed in here.
        Passing the query in rather than building it here keeps database logic
        and HTTP logic in their respective layers.
        """
        try:
            return list(self.collection.find(query))
        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Please try again later.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while retrieving products.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while retrieving products.")

    def find_by_id(self, oid):
        """
        Returns a single document matching the given ObjectId, or None if
        no document with that ID exists. app.py handles the None case by
        returning a 404 response.
        """
        try:
            return self.collection.find_one({"_id": oid})
        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Please try again later.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while retrieving the product.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while retrieving the product.")

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, product_dict):
        """
        Inserts a new document into the collection.

        MongoDB automatically generates an _id field on insertion and adds it
        to the dict in place. We convert it to a plain string 'id' field here
        so the returned dict is immediately JSON-serializable.
        """
        try:
            result = self.collection.insert_one(product_dict)
            product_dict["id"] = str(result.inserted_id)
            product_dict.pop("_id", None)
            return product_dict
        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Unable to create product.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while creating the product.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while creating the product.")

    def update(self, oid, updates):
        """
        Applies a partial update to a single document using MongoDB's $set operator.

        $set updates only the fields provided, leaving all other fields
        unchanged. This is what makes the PUT endpoint a partial update —
        the client only needs to send the fields they want to change.

        Returns the updated document after the change is applied, or None if
        no document with the given ID was found.
        """
        try:
            return self.collection.find_one_and_update(
                {"_id": oid},
                {"$set": updates},
                # return_document=True returns the document after the update
                # is applied, so the API response reflects the new values.
                return_document=True
            )
        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Unable to update product.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while updating the product.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while updating the product.")

    def delete(self, oid):
        """
        Permanently deletes the document with the given ObjectId.

        Returns True if a document was found and deleted, or False if no
        document with that ID existed. app.py uses this to decide whether
        to return a 200 or a 404.
        """
        try:
            result = self.collection.delete_one({"_id": oid})
            return result.deleted_count > 0
        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Unable to delete product.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while deleting the product.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while deleting the product.")

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_analytics(self):
        """
        Runs four aggregation pipelines against the products collection and
        returns their results as a tuple: (summary, categories, price_by_category, low_stock).

        Aggregation pipelines do the computation inside MongoDB rather than
        fetching all documents into Python and calculating there. This is
        significantly more efficient because only the final result is sent
        over the network, not every product document.

        Each pipeline is a list of stages that MongoDB executes in sequence:
          $match   - filters documents
          $group   - aggregates values across documents
          $sort    - orders the results
          $project - selects which fields to include
        """
        try:
            # Calculates overall totals and averages across all products.
            pipeline_summary = [
                {
                    "$group": {
                        "_id": None,  # null _id means group all documents together
                        "total_products": {"$sum": 1},
                        "average_price": {"$avg": "$price"},
                        "total_inventory_value": {
                            "$sum": {"$multiply": ["$price", "$available_quantity"]}
                        },
                        "total_units": {"$sum": "$available_quantity"},
                    }
                }
            ]

            # Groups products by category and counts how many are in each.
            # Sorted descending so the most popular category is first in the list.
            pipeline_categories = [
                {"$group": {"_id": "$product_category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]

            # Calculates average, minimum, and maximum price per category.
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

            # Finds products with 10 or fewer units remaining, sorted by
            # quantity ascending so the most critical items appear first.
            pipeline_low_stock = [
                {"$match": {"available_quantity": {"$lte": 10}}},
                {"$project": {
                    "product_name": 1, "product_category": 1,
                    "available_quantity": 1, "price": 1
                }},
                {"$sort": {"available_quantity": 1}},
            ]

            summary_result = list(self.collection.aggregate(pipeline_summary))
            # aggregate() always returns a list; use the first item or an empty
            # dict if the collection has no documents yet.
            summary = summary_result[0] if summary_result else {}
            summary.pop("_id", None)

            categories = list(self.collection.aggregate(pipeline_categories))
            price_by_category = list(self.collection.aggregate(pipeline_price_by_cat))
            low_stock = list(self.collection.aggregate(pipeline_low_stock))

            return summary, categories, price_by_category, low_stock

        except ConnectionFailure:
            raise DatabaseConnectionError("Database unreachable. Unable to retrieve analytics.")
        except OperationFailure:
            raise DatabaseOperationError("Database operation failed while retrieving analytics.")
        except PyMongoError:
            raise DatabaseConnectionError("Unexpected database error while retrieving analytics.")


# ── Module-level repository instance ─────────────────────────────────────────
# A single ProductRepository is created here when this module is first imported.
# Every route in app.py shares this one instance, which means a single
# connection pool is reused across all requests rather than a new connection
# being opened on every call.
repo = ProductRepository(_db["products"])
