from datetime import datetime


# ── Custom exceptions ─────────────────────────────────────────────────────────
# Rather than raising generic Python errors like ValueError, we define our own
# exception classes. This makes it immediately clear to anyone reading the code
# exactly what kind of problem occurred, and allows app.py to catch validation
# errors specifically without accidentally catching unrelated errors.

class ValidationError(Exception):
    """
    Base class for all validation errors in this application.
    The other three classes below inherit from this, so catching ValidationError
    in app.py handles all three failure types in one place.
    """
    pass

class MissingFieldError(ValidationError):
    """Raised when one or more required fields are absent from the request payload."""
    pass

class InvalidPriceError(ValidationError):
    """Raised when the price field is missing, not a number, or negative."""
    pass

class InvalidQuantityError(ValidationError):
    """Raised when available_quantity is missing, not an integer, or negative."""
    pass


# ── Product ───────────────────────────────────────────────────────────────────

class Product:
    """
    Represents a single inventory product.

    Having a dedicated class for the product means the shape of a product is
    defined in one place. If a new field needs to be added, it is added here
    and flows through the rest of the application automatically.

    Two key methods handle conversion:
      - from_dict() : builds a Product from a raw JSON request payload
      - to_dict()   : converts back to a plain dict for MongoDB storage
    """

    def __init__(self, product_name, product_category, price, available_quantity,
                 description="", sku=""):
        # Store all product fields on the instance.
        # description and sku are optional and default to empty strings.
        self.product_name = product_name
        self.product_category = product_category
        self.price = price
        self.available_quantity = available_quantity
        self.description = description
        self.sku = sku

        # Timestamps are set automatically at creation time.
        # updated_at is overwritten by app.py on every PUT request.
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self):
        """
        Returns a plain dictionary of all product fields.
        This is what gets passed to ProductRepository.create() for insertion
        into MongoDB, which expects a dict rather than a Python object.
        """
        return {
            "product_name": self.product_name,
            "product_category": self.product_category,
            "price": self.price,
            "available_quantity": self.available_quantity,
            "description": self.description,
            "sku": self.sku,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data):
        """
        Builds a Product instance from a raw request dictionary.

        This is a class method rather than a regular method because it creates
        a new Product — it doesn't operate on an existing one. Calling
        Product.from_dict(data) is cleaner and more readable than constructing
        the object manually in every route that needs one.

        Raises MissingFieldError, InvalidPriceError, or InvalidQuantityError
        if required fields are absent or have invalid types.
        """
        return cls(
            product_name=str(data["product_name"]).strip(),
            product_category=str(data["product_category"]).strip(),
            # float() and int() cast the incoming values to the correct types.
            # ProductValidator.validate_create() confirms these are safe to cast
            # before from_dict() is ever called.
            price=float(data["price"]),
            available_quantity=int(data["available_quantity"]),
            description=str(data.get("description", "")).strip(),
            sku=str(data.get("sku", "")).strip(),
        )

    def __repr__(self):
        """
        Returns a readable summary of the product, used when printing or
        debugging. Not called in normal application flow.
        """
        return (f"Product(name={self.product_name!r}, "
                f"category={self.product_category!r}, "
                f"price={self.price}, qty={self.available_quantity})")


# ── ProductValidator ──────────────────────────────────────────────────────────

class ProductValidator:
    """
    Validates raw request payloads before they are used to create or update products.

    All methods are static, meaning they belong to the class itself rather than
    to any instance of it. You call them directly on the class:
      ProductValidator.validate_create(data)

    Keeping validation here rather than inside the route functions means the
    rules are defined in one place and can be updated without touching app.py.
    It also means this class has no dependency on Flask and could be reused in
    any other Python context.
    """

    # Fields that must be present in every POST /products request.
    REQUIRED_FIELDS = ["product_name", "product_category", "price", "available_quantity"]

    # Fields that are permitted in a PUT /products/{id} request.
    # Any field the client sends that is not in this set is silently ignored,
    # preventing clients from overwriting internal fields like created_at.
    ALLOWED_UPDATE_FIELDS = {"product_name", "product_category", "price",
                             "available_quantity", "description", "sku"}

    @staticmethod
    def validate_create(data):
        """
        Validates a POST /products request payload.

        Checks in order:
          1. All required fields are present.
          2. price can be converted to a float.
          3. available_quantity can be converted to an integer.
          4. Both values are non-negative.

        Raises a specific exception subclass for each type of failure so the
        caller can tell exactly what went wrong.
        """
        # Check for missing required fields before attempting any type casting.
        missing = [f for f in ProductValidator.REQUIRED_FIELDS if f not in data]
        if missing:
            raise MissingFieldError(f"Missing required fields: {missing}")

        # Validate price type and value separately so the error message is specific.
        try:
            price = float(data["price"])
        except (ValueError, TypeError):
            raise InvalidPriceError("price must be a number.")

        try:
            qty = int(data["available_quantity"])
        except (ValueError, TypeError):
            raise InvalidQuantityError("available_quantity must be an integer.")

        if price < 0:
            raise InvalidPriceError("price must be non-negative.")
        if qty < 0:
            raise InvalidQuantityError("available_quantity must be non-negative.")

    @staticmethod
    def validate_update(data):
        """
        Validates a PUT /products/{id} request payload.

        Unlike validate_create, no fields are strictly required — the client
        only needs to send the fields they want to change. However, at least
        one recognized field must be present, and numeric fields must be valid
        if included.

        This method checks that values are valid but intentionally does not
        coerce them to their final types (float, int). Type coercion is left
        to the caller in app.py so that this method remains a pure checking
        function with no side effects.

        Returns the filtered dict of allowed fields so app.py does not need to
        filter them separately.
        """
        # Filter the incoming data down to only the fields we allow to be updated.
        allowed_updates = {k: v for k, v in data.items()
                           if k in ProductValidator.ALLOWED_UPDATE_FIELDS}

        # Reject the request if none of the recognized fields were sent.
        if not allowed_updates:
            raise MissingFieldError(
                f"Request must include at least one updatable field: "
                f"{sorted(ProductValidator.ALLOWED_UPDATE_FIELDS)}"
            )

        if "price" in allowed_updates:
            try:
                price = float(allowed_updates["price"])
            except (ValueError, TypeError):
                raise InvalidPriceError("price must be a number.")
            if price < 0:
                raise InvalidPriceError("price must be non-negative.")

        if "available_quantity" in allowed_updates:
            try:
                qty = int(allowed_updates["available_quantity"])
            except (ValueError, TypeError):
                raise InvalidQuantityError("available_quantity must be an integer.")
            if qty < 0:
                raise InvalidQuantityError("available_quantity must be non-negative.")

        return allowed_updates
