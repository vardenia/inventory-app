# Inventory Management System

A REST API for managing product inventory, built with Python Flask and MongoDB. Supports full CRUD operations, full-text search, and aggregated analytics.

---

## Tech Stack

- **Python Flask** — REST API framework
- **MongoDB** — database
- **Docker** — containerization

---

## Running the App

**Prerequisites:** Docker Desktop installed and running.
Port 5000 (API) and 27017 (MongoDB) free on the host machine.

```bash
# 1. Clone the repository
git clone https://github.com/vardenia/inventory-app.git
cd inventory-app

# 2. Start the containers
docker compose up --build -d

# 3. Seed the database with sample data (Wait ~15 seconds for MongoDB to initialize before running)
docker compose exec api python seed.py
```

The API will be available at `http://localhost:5000`.

---

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/products` | List all products |
| GET | `/products/{id}` | Fetch a product |
| POST | `/products` | Create a product |
| PUT | `/products/{id}` | Update a product |
| DELETE | `/products/{id}` | Delete a product |
| GET | `/products/analytics` | Aggregated metrics |

**Optional query parameters for `GET /products`:**
`?search=`, `?category=`, `?min_price=`, `?max_price=`

---

## Stopping the App

```bash
docker compose down        # stop (data persists)
docker compose down -v     # stop and delete all data
```
