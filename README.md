# Inventory Management System

A RESTful inventory management API built with Python Flask and MongoDB. The system provides full product lifecycle management, real-time full-text search, aggregated analytics, a health check endpoint, and a command-line interface — all running in Docker.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Endpoint Documentation](#api-endpoint-documentation)
- [CLI Documentation](#cli-documentation)
- [Summary](#summary)

---

## Overview

The system is built around a three-layer architecture that separates each area of responsibility into its own file:

- **`models.py`** — defines the `Product` data model and `ProductValidator` class, which enforces a schema on all incoming data before it reaches the database
- **`db.py`** — contains the `ProductRepository` class, which handles all MongoDB queries and database error handling
- **`app.py`** — Flask routes that handle HTTP requests, call the repository, and return responses

This separation means database logic, validation logic, and HTTP logic are each isolated from the others. The CLI (`cli.py`) imports directly from `db.py` and `models.py`, bypassing Flask entirely and talking straight to MongoDB.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API framework | Python Flask |
| Database | MongoDB 7 |
| Database driver | PyMongo |
| Containerization | Docker + Docker Compose |
| Language | Python 3.12 |

---

## Project Structure

```
inventory-app/
  app.py              ← Flask routes
  db.py               ← ProductRepository class + database connection
  models.py           ← Product class, ProductValidator, custom exceptions
  cli.py              ← Command-line interface
  seed.py             ← Populates the database with 23 sample products
  requirements.txt    ← Python dependencies
  Dockerfile          ← API container image
  docker-compose.yml  ← Orchestrates API + MongoDB containers
```

---

## Getting Started

### Prerequisites

- Docker Desktop installed and running
- Ports `5000` (API) and `27017` (MongoDB) free on your machine
- A Mac/Linux terminal or Git Bash on Windows for curl examples. Alternatively, use [Postman](https://www.postman.com)

### Start the application

```bash
# 1. Clone the repository
git clone https://github.com/vardenia/inventory-app.git
cd inventory-app

# 2. Build and start both containers
docker compose up --build -d

# 3. Wait ~15 seconds for MongoDB to initialize, then seed sample data
docker compose exec api python seed.py

# 4. Confirm everything is running
curl http://localhost:5000/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "1.3.0",
  "checked_at": "2024-11-01T12:00:00Z",
  "services": {
    "database": { "status": "ok" }
  }
}
```

### Stop the application

```bash
docker compose down        # stop containers (data persists)
docker compose down -v     # stop and delete all data
```

---

## API Endpoint Documentation

Base URL: `http://localhost:5000`

All request and response bodies use JSON.

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Application and database health check |
| GET | `/products` | List all products (supports filtering) |
| GET | `/products/{id}` | Fetch a single product |
| POST | `/products` | Create a new product |
| PUT | `/products/{id}` | Update an existing product |
| DELETE | `/products/{id}` | Delete a product |
| GET | `/products/analytics` | Aggregated inventory metrics |

---

### GET /health

Returns the application version and a live MongoDB connectivity check.

```bash
curl http://localhost:5000/health
```

```json
{
  "status": "ok",
  "version": "1.3.0",
  "checked_at": "2024-11-01T12:00:00Z",
  "services": {
    "database": { "status": "ok" }
  }
}
```

Returns `200` when healthy, `503` if the database is unreachable.

---

### GET /products

Returns all products. Supports the following optional query parameters:

| Parameter | Description |
|-----------|-------------|
| `?search=` | Full-text search across name, category, and description |
| `?category=` | Case-insensitive category filter |
| `?min_price=` | Return products at or above this price |
| `?max_price=` | Return products at or below this price |

```bash
# All products
curl http://localhost:5000/products

# Full-text search
curl "http://localhost:5000/products?search=wireless"

# Filter by category and price
curl "http://localhost:5000/products?category=electronics&max_price=100"
```

---

### GET /products/{id}

Fetch a single product by its MongoDB ObjectId.

```bash
curl http://localhost:5000/products/64abc123def456789012
```

```json
{
  "id": "64abc123def456789012",
  "product_name": "Wireless Noise-Canceling Headphones",
  "product_category": "Electronics",
  "price": 249.99,
  "available_quantity": 120,
  "description": "Over-ear headphones with 30-hour battery life and ANC.",
  "sku": "EL-HP-002",
  "created_at": "2024-11-01T12:00:00Z",
  "updated_at": "2024-11-01T12:00:00Z"
}
```

---

### POST /products

Create a new product. `product_name`, `product_category`, `price`, and `available_quantity` are required. `description` and `sku` are optional.

```bash
curl -X POST http://localhost:5000/products \
  -H 'Content-Type: application/json' \
  -d '{
    "product_name": "Desk Lamp",
    "product_category": "Home & Kitchen",
    "price": 29.99,
    "available_quantity": 50,
    "description": "LED desk lamp with adjustable brightness.",
    "sku": "HK-DL-006"
  }'
```

Returns `201 Created` with the new product including its generated `id`.

---

### PUT /products/{id}

Partially update a product. Only the fields included in the request body are changed — all other fields remain as they are.

```bash
curl -X PUT http://localhost:5000/products/64abc123def456789012 \
  -H 'Content-Type: application/json' \
  -d '{
    "price": 24.99,
    "available_quantity": 75
  }'
```

Returns `200 OK` with the updated product.

---

### DELETE /products/{id}

Permanently delete a product.

```bash
curl -X DELETE http://localhost:5000/products/64abc123def456789012
```

```json
{ "message": "Product '64abc123def456789012' deleted successfully." }
```

---

### GET /products/analytics

Returns aggregated metrics calculated from the products collection.

```bash
curl http://localhost:5000/products/analytics
```

```json
{
  "generated_at": "2024-11-01T12:00:00Z",
  "summary": {
    "total_products": 23,
    "average_price": 142.36,
    "total_inventory_value": 98432.50,
    "total_units_in_stock": 2513,
    "most_popular_category": "Electronics"
  },
  "category_breakdown": [
    { "category": "Electronics", "product_count": 5 },
    { "category": "Clothing", "product_count": 5 }
  ],
  "price_by_category": [
    { "category": "Electronics", "avg_price": 495.99, "min_price": 39.99, "max_price": 1399.00 }
  ],
  "low_stock_alert": [
    { "id": "...", "product_name": "Hydration Running Vest", "available_quantity": 3, "price": 89.99 }
  ]
}
```

---

### Error Responses

All errors return a consistent JSON body:

```json
{ "error": "Product '64abc123def456789012' not found." }
```

| Status Code | Meaning |
|-------------|---------|
| `400` | Bad request — missing or invalid fields |
| `404` | Product not found |
| `503` | Database unreachable or operation failed |
| `500` | Unexpected server error |

---

## CLI Documentation

The CLI talks directly to MongoDB through the same `ProductRepository` used by the API. Flask is not involved — commands run from the terminal without any HTTP requests.

All CLI commands are run inside the Docker container:

```bash
docker compose exec api python cli.py <command> [options]
```

---

### list

List all products, with optional filtering.

```bash
# All products
docker compose exec api python cli.py list

# Filter by category
docker compose exec api python cli.py list --category Electronics

# Full-text search
docker compose exec api python cli.py list --search wireless

# Filter by price range
docker compose exec api python cli.py list --min-price 50 --max-price 200
```

---

### get

Fetch a single product by ID.

```bash
docker compose exec api python cli.py get 64abc123def456789012
```

---

### create

Create a new product. `--name`, `--category`, `--price`, and `--quantity` are required.

```bash
docker compose exec api python cli.py create \
  --name "Desk Lamp" \
  --category "Home & Kitchen" \
  --price 29.99 \
  --quantity 50 \
  --description "LED desk lamp with adjustable brightness." \
  --sku "HK-DL-006"
```

---

### update

Partially update a product. Only the flags provided are changed.

```bash
docker compose exec api python cli.py update 64abc123def456789012 \
  --price 24.99 \
  --quantity 75
```

---

### delete

Delete a product. Prompts for confirmation before deleting.

```bash
# With confirmation prompt
docker compose exec api python cli.py delete 64abc123def456789012

# Skip confirmation (useful for scripting)
docker compose exec api python cli.py delete 64abc123def456789012 --yes
```

---

### analytics

Display aggregated inventory metrics.

```bash
docker compose exec api python cli.py analytics
```

Sample output:
```
── Summary ──────────────────────────────────
  Total products       : 23
  Average price        : $142.36
  Total inventory value: $98432.50
  Total units in stock : 2513

── Products by Category ─────────────────────
  Electronics               5 product(s)
  Clothing                  5 product(s)
  Home & Kitchen            5 product(s)

── Low Stock Alert (≤10 units) ──────────────
  Hydration Running Vest         3 remaining
  Smart Coffee Maker             7 remaining
```

---

## Summary

### Inventory management system with integrated analytics and full-text search

The system manages products across five categories (Electronics, Clothing, Home & Kitchen, Sports & Outdoors, Books) with full CRUD support via both the REST API and the CLI.

**Analytics** are provided by `GET /products/analytics`, which runs four MongoDB aggregation pipelines to calculate totals, averages, per-category breakdowns, and low-stock alerts — all computed inside MongoDB rather than in application code for efficiency.

**Full-text search** is powered by a MongoDB TEXT index created at startup on `product_name`, `product_category`, and `description`. It is accessible via the `?search=` query parameter:

```bash
curl "http://localhost:5000/products?search=wireless headphones"
```

---

### Ability to add, delete, and update products

All three operations are supported via the REST API and the CLI:

| Operation | API | CLI |
|-----------|-----|-----|
| Add | `POST /products` | `python cli.py create --name ... --price ...` |
| Update | `PUT /products/{id}` | `python cli.py update <id> --price ...` |
| Delete | `DELETE /products/{id}` | `python cli.py delete <id>` |

Updates are partial — only the fields provided are changed. All other fields remain untouched.

---

### Aggregated product metrics

`GET /products/analytics` returns:

- **Total product count** across the entire inventory
- **Average price** across all products
- **Total inventory value** — sum of `price × quantity` for all products
- **Most popular category** — the category with the highest product count
- **Category breakdown** — product count per category, sorted by popularity
- **Price statistics per category** — average, minimum, and maximum price per category
- **Low stock alert** — products with 10 or fewer units remaining, sorted by urgency

---

### MongoDB + Python Flask

The application uses **MongoDB 7** as its database and **Python Flask** as its REST API framework, connected via the **PyMongo** driver. Both services run in Docker containers orchestrated by Docker Compose.

MongoDB's document model stores each product as a flexible JSON-like document. Its aggregation pipeline is used for all analytics calculations, and its TEXT index powers full-text search — both without any additional infrastructure.

Flask handles HTTP routing, request parsing, and response formatting. All database logic is kept out of Flask route functions and lives instead in the `ProductRepository` class in `db.py`, following the Repository pattern.


