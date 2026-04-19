from datetime import datetime


class Product:
    """
    Represents a single inventory product.

    Encapsulates all product fields and provides two conversion methods:
      - from_dict()  : build a Product from a raw request payload
      - to_dict()    : serialise back to a plain dict for MongoDB insertion
    """

    def __init__(self, product_name, product_category, price, available_quantity,
                 description="", sku=""):
        self.product_name = product_name
        self.product_category = product_category
        self.price = price
        self.available_quantity = available_quantity
        self.description = description
        self.sku = sku
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self):
        """Return a plain dict suitable for inserting into MongoDB."""
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
        Build a Product from a raw request dictionary.
        Raises ValueError if required fields are missing or have invalid types.
        """
        return cls(
            product_name=str(data["product_name"]).strip(),
            product_category=str(data["product_category"]).strip(),
            price=float(data["price"]),
            available_quantity=int(data["available_quantity"]),
            description=str(data.get("description", "")).strip(),
            sku=str(data.get("sku", "")).strip(),
        )

    def __repr__(self):
        return (f"Product(name={self.product_name!r}, "
                f"category={self.product_category!r}, "
                f"price={self.price}, qty={self.available_quantity})")


class ProductValidator:
    """
    Validates raw request payloads before they are used to create or update products.

    Raises ValueError with a descriptive message on any validation failure.
    All methods are static — no instance is needed.
    """

    REQUIRED_FIELDS = ["product_name", "product_category", "price", "available_quantity"]
    ALLOWED_UPDATE_FIELDS = {"product_name", "product_category", "price",
                             "available_quantity", "description", "sku"}

    @staticmethod
    def validate_create(data):
        """
        Validate a POST /products payload.
        Checks required fields, numeric types, and non-negative constraints.
        """
        missing = [f for f in ProductValidator.REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        try:
            price = float(data["price"])
        except (ValueError, TypeError):
            raise ValueError("price must be a number.")

        try:
            qty = int(data["available_quantity"])
        except (ValueError, TypeError):
            raise ValueError("available_quantity must be an integer.")

        if price < 0:
            raise ValueError("price must be non-negative.")
        if qty < 0:
            raise ValueError("available_quantity must be non-negative.")

    @staticmethod
    def validate_update(data):
        """
        Validate a PUT /products/{id} payload.
        Checks that at least one allowed field is present and numeric fields are valid.
        """
        allowed_updates = {k: v for k, v in data.items()
                           if k in ProductValidator.ALLOWED_UPDATE_FIELDS}
        if not allowed_updates:
            raise ValueError(
                f"Request must include at least one updatable field: "
                f"{sorted(ProductValidator.ALLOWED_UPDATE_FIELDS)}"
            )

        if "price" in allowed_updates:
            try:
                price = float(allowed_updates["price"])
            except (ValueError, TypeError):
                raise ValueError("price must be a number.")
            if price < 0:
                raise ValueError("price must be non-negative.")

        if "available_quantity" in allowed_updates:
            try:
                qty = int(allowed_updates["available_quantity"])
            except (ValueError, TypeError):
                raise ValueError("available_quantity must be an integer.")
            if qty < 0:
                raise ValueError("available_quantity must be non-negative.")

        return allowed_updates
