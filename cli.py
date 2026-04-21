"""
cli.py — Command-line interface for the Inventory Management System.

Talks directly to MongoDB through the same ProductRepository used by the
REST API. Flask is not involved — there are no HTTP requests or responses.

Usage:
    python cli.py list
    python cli.py list --category Electronics --max-price 100
    python cli.py get <id>
    python cli.py create --name "Desk Lamp" --category "Home & Kitchen" --price 29.99 --quantity 50
    python cli.py update <id> --price 24.99
    python cli.py delete <id>
    python cli.py analytics

Run inside Docker:
    docker compose exec api python cli.py list
"""

import argparse
import re
import sys
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId

# Import directly from the existing layers — no Flask involved.
# This is possible because db.py and models.py have no dependency on Flask.
from db import repo, serialize, DatabaseConnectionError, DatabaseOperationError
from models import Product, ProductValidator, ValidationError


# ── Output helpers ────────────────────────────────────────────────────────────
# These functions handle printing to the terminal. Keeping them separate from
# the command functions makes it easy to change the output format later
# without touching any of the logic.

def print_product(p):
    """
    Prints a single product in a readable format.
    Wraps the call in a try/except so that a malformed document returned from
    MongoDB — for example one missing an expected field — produces a clean
    error message rather than a raw Python KeyError traceback.
    """
    try:
        print(f"""
  ID       : {p.get('id', p.get('_id', 'N/A'))}
  Name     : {p['product_name']}
  Category : {p['product_category']}
  Price    : ${p['price']:.2f}
  Quantity : {p['available_quantity']}
  SKU      : {p.get('sku') or '—'}
  Desc     : {p.get('description') or '—'}
  Created  : {p.get('created_at', '—')}
  Updated  : {p.get('updated_at', '—')}
""".rstrip())
    except (KeyError, TypeError) as e:
        print_error(f"Could not display product — unexpected data format: {e}")


def print_error(message):
    """
    Prints an error message to stderr and exits with a non-zero code.

    Writing errors to stderr rather than stdout is standard CLI practice —
    it means error messages and normal output can be separated if the CLI
    output is piped into another program.

    Exiting with code 1 signals to the shell that the command failed,
    which is important if the CLI is used inside a script.
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def parse_id(id_string):
    """
    Converts a string to a MongoDB ObjectId.
    Exits with a clear error if the format is invalid, rather than letting
    an unhelpful exception bubble up to the user.
    """
    try:
        return ObjectId(id_string)
    except (InvalidId, TypeError):
        print_error(f"'{id_string}' is not a valid product ID.")


# ── Command functions ─────────────────────────────────────────────────────────
# One function per CLI command. Each function receives the parsed arguments
# from argparse, calls the appropriate repository method, and prints the result.
# This mirrors the structure of app.py's route functions — same repo calls,
# different input/output mechanism.

def cmd_list(args):
    """
    Lists all products, with optional filtering.
    Builds the same query dict that the GET /products route builds,
    then passes it directly to repo.find_all().
    """
    query = {}

    if args.category:
        # Case-insensitive regex match, consistent with the API behavior.
        # re.escape() prevents special characters in the input from being
        # treated as regex syntax.
        query["product_category"] = {"$regex": re.escape(args.category), "$options": "i"}

    if args.min_price is not None or args.max_price is not None:
        price_filter = {}
        if args.min_price is not None:
            price_filter["$gte"] = args.min_price
        if args.max_price is not None:
            price_filter["$lte"] = args.max_price
        query["price"] = price_filter

    if args.search:
        # $text uses the full-text search index created in ProductRepository.
        query["$text"] = {"$search": args.search}

    try:
        docs = repo.find_all(query)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    if not docs:
        print("No products found.")
        return

    print(f"\n{len(docs)} product(s) found:")
    for doc in docs:
        # Wrap serialize() in a try/except in case a document is missing its
        # _id field, which would normally never happen but could occur if data
        # was inserted into MongoDB directly, bypassing the application.
        try:
            print_product(serialize(doc))
        except Exception as e:
            print(f"  (Could not display one product: {e})", file=sys.stderr)


def cmd_get(args):
    """Fetches and displays a single product by its ID."""
    oid = parse_id(args.id)
    try:
        doc = repo.find_by_id(oid)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    if not doc:
        print_error(f"No product found with ID '{args.id}'.")

    print_product(serialize(doc))


def cmd_create(args):
    """
    Creates a new product from the command-line arguments.

    Passes the arguments through the same ProductValidator and Product class
    used by the POST /products route, ensuring identical validation rules
    whether the product is created via the API or the CLI.
    """
    data = {
        "product_name": args.name,
        "product_category": args.category,
        "price": args.price,
        "available_quantity": args.quantity,
        "description": args.description or "",
        "sku": args.sku or "",
    }

    try:
        # Validate first, then construct — same order as the POST route.
        ProductValidator.validate_create(data)
        product = Product.from_dict(data)
    except ValidationError as e:
        print_error(str(e))

    try:
        created = repo.create(product.to_dict())
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    print("\nProduct created successfully.")
    print_product(created)


def cmd_update(args):
    """
    Partially updates an existing product.
    Only the flags the user actually provides are included in the update —
    omitted flags are ignored, consistent with the PUT /products route.
    """
    oid = parse_id(args.id)

    # Build the updates dict from only the arguments that were provided.
    # vars(args) converts the argparse Namespace to a plain dict so we can
    # iterate over it. Arguments left as None were not passed by the user.
    raw = vars(args)
    field_map = {
        "name": "product_name",
        "category": "product_category",
        "price": "price",
        "quantity": "available_quantity",
        "description": "description",
        "sku": "sku",
    }
    data = {field_map[k]: raw[k] for k in field_map if raw.get(k) is not None}

    if not data:
        print_error("Provide at least one field to update (--name, --price, --quantity, etc.)")

    try:
        # validate_update() filters the fields and checks numeric constraints.
        updates = ProductValidator.validate_update(data)
    except ValidationError as e:
        print_error(str(e))

    # Coerce types after validation, consistent with the PUT route.
    if "price" in updates:
        updates["price"] = float(updates["price"])
    if "available_quantity" in updates:
        updates["available_quantity"] = int(updates["available_quantity"])

    # Always stamp updated_at with the current time on any successful update.
    updates["updated_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        result = repo.update(oid, updates)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    if not result:
        print_error(f"No product found with ID '{args.id}'.")

    print("\nProduct updated successfully.")
    print_product(serialize(result))


def cmd_delete(args):
    """
    Permanently deletes a product by its ID.
    Prompts for confirmation before deleting unless --yes is passed,
    preventing accidental data loss from a mistyped command.
    """
    oid = parse_id(args.id)

    # Fetch the product first so we can show its name in the confirmation prompt.
    try:
        doc = repo.find_by_id(oid)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    if not doc:
        print_error(f"No product found with ID '{args.id}'.")

    # Skip the confirmation prompt if the user passed --yes.
    # Useful for scripting where interactive prompts would block execution.
    if not args.yes:
        confirm = input(f"Delete '{doc['product_name']}'? This cannot be undone. [y/N] ")
        if confirm.strip().lower() != "y":
            print("Canceled.")
            return

    try:
        deleted = repo.delete(oid)
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    # deleted will be False if the document disappeared between the find and
    # the delete — unlikely but possible if two processes run simultaneously.
    if not deleted:
        print_error(f"Product could not be deleted. It may have already been removed.")

    print(f"Product '{doc['product_name']}' deleted successfully.")


def cmd_analytics(args):
    """
    Displays aggregated metrics from the products collection.
    Calls the same repo.get_analytics() method used by GET /products/analytics.
    """
    try:
        summary, categories, price_by_category, low_stock = repo.get_analytics()
    except (DatabaseConnectionError, DatabaseOperationError) as e:
        print_error(str(e))

    print("\n── Summary ──────────────────────────────────")
    # .get() with a default of 0 handles the case where the collection is
    # empty and the aggregation pipeline returns no results.
    print(f"  Total products       : {summary.get('total_products', 0)}")
    print(f"  Average price        : ${summary.get('average_price', 0):.2f}")
    print(f"  Total inventory value: ${summary.get('total_inventory_value', 0):.2f}")
    print(f"  Total units in stock : {summary.get('total_units', 0)}")

    print("\n── Products by Category ─────────────────────")
    if categories:
        for c in categories:
            print(f"  {c['_id']:<25} {c['count']} product(s)")
    else:
        print("  No products in the database yet.")

    print("\n── Price by Category ────────────────────────")
    if price_by_category:
        for c in price_by_category:
            print(f"  {c['_id']:<25} avg ${c['avg_price']:.2f}  "
                  f"min ${c['min_price']:.2f}  max ${c['max_price']:.2f}")
    else:
        print("  No products in the database yet.")

    print("\n── Low Stock Alert (≤10 units) ──────────────")
    if low_stock:
        for p in low_stock:
            print(f"  {p['product_name']:<30} {p['available_quantity']} remaining")
    else:
        print("  No products below the low stock threshold.")

    print()


# ── Argument parser ───────────────────────────────────────────────────────────
# argparse is Python's built-in library for building CLIs. It parses sys.argv
# (the list of words the user typed), validates them, and provides them to
# the command functions as a structured Namespace object.
#
# Subparsers create subcommands (list, get, create, etc.) so each command
# can have its own set of arguments, similar to how 'git commit' and
# 'git push' have different flags.

def build_parser():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Inventory Management CLI — manage products from the terminal.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    # dest="command" stores the chosen subcommand name on the Namespace object
    # so we can tell which command was run. metavar controls the display name
    # shown in the help text.
    subparsers.required = True

    # ── list ──────────────────────────────────────────────────────────────────
    list_p = subparsers.add_parser("list", help="List all products.")
    list_p.add_argument("--search",    metavar="TEXT",  help="Full-text search across name, category, and description.")
    list_p.add_argument("--category",  metavar="NAME",  help="Filter by category (case-insensitive).")
    list_p.add_argument("--min-price", metavar="PRICE", type=float, dest="min_price", help="Minimum price.")
    list_p.add_argument("--max-price", metavar="PRICE", type=float, dest="max_price", help="Maximum price.")
    list_p.set_defaults(func=cmd_list)

    # ── get ───────────────────────────────────────────────────────────────────
    get_p = subparsers.add_parser("get", help="Fetch a single product by ID.")
    get_p.add_argument("id", help="Product ID.")
    get_p.set_defaults(func=cmd_get)

    # ── create ────────────────────────────────────────────────────────────────
    create_p = subparsers.add_parser("create", help="Create a new product.")
    create_p.add_argument("--name",        required=True,  metavar="TEXT",  help="Product name.")
    create_p.add_argument("--category",    required=True,  metavar="TEXT",  help="Product category.")
    create_p.add_argument("--price",       required=True,  metavar="PRICE", type=float, help="Price.")
    create_p.add_argument("--quantity",    required=True,  metavar="N",     type=int,   help="Available quantity.")
    create_p.add_argument("--description", metavar="TEXT", help="Optional product description.")
    create_p.add_argument("--sku",         metavar="TEXT", help="Optional SKU / internal code.")
    create_p.set_defaults(func=cmd_create)

    # ── update ────────────────────────────────────────────────────────────────
    update_p = subparsers.add_parser("update", help="Update an existing product.")
    update_p.add_argument("id", help="Product ID.")
    update_p.add_argument("--name",        metavar="TEXT",  help="New product name.")
    update_p.add_argument("--category",    metavar="TEXT",  help="New category.")
    update_p.add_argument("--price",       metavar="PRICE", type=float, help="New price.")
    update_p.add_argument("--quantity",    metavar="N",     type=int,   help="New available quantity.")
    update_p.add_argument("--description", metavar="TEXT",  help="New description.")
    update_p.add_argument("--sku",         metavar="TEXT",  help="New SKU.")
    update_p.set_defaults(func=cmd_update)

    # ── delete ────────────────────────────────────────────────────────────────
    delete_p = subparsers.add_parser("delete", help="Delete a product.")
    delete_p.add_argument("id", help="Product ID.")
    delete_p.add_argument("--yes", "-y", action="store_true",
                          help="Skip the confirmation prompt. Useful for scripting.")
    delete_p.set_defaults(func=cmd_delete)

    # ── analytics ─────────────────────────────────────────────────────────────
    analytics_p = subparsers.add_parser("analytics", help="Show aggregated inventory metrics.")
    analytics_p.set_defaults(func=cmd_analytics)

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────
# This block only runs when the file is executed directly (python cli.py ...).
# It does not run when the file is imported, which means importing cli.py in
# a test would not immediately trigger argument parsing.

if __name__ == "__main__":
    try:
        parser = build_parser()
        args = parser.parse_args()
        # Each subparser registers its command function via set_defaults(func=...).
        # args.func points to the correct function for whatever subcommand was
        # typed, so this single line dispatches to the right command.
        args.func(args)
    except KeyboardInterrupt:
        # Catches Ctrl+C cleanly at any point during execution — including during
        # the delete confirmation prompt — so the user sees a simple "Canceled."
        # message instead of a Python traceback.
        print("\nCanceled.")
        sys.exit(0)
