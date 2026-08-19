"""Build the seeded, regenerable sample database (data/sample.db).

Real + regenerable, never fabricated: the same seed always produces the same
database, so eval golden hashes stay stable. Run: uv run python scripts/build_db.py
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "sample.db"
SEED = 20260819


def _rng() -> random.Random:
    return random.Random(SEED)


def _rand_date(rng: random.Random, start: date, end: date) -> str:
    days = (end - start).days
    return (start + timedelta(days=rng.randint(0, days))).isoformat()


def _rand_datetime(rng: random.Random, start: date, end: date) -> str:
    d = _rand_date(rng, start, end)
    return f"{d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"


def build(conn: sqlite3.Connection) -> None:
    rng = _rng()
    cur = conn.cursor()

    cur.executescript(
        """
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS reviews;
        DROP TABLE IF EXISTS inventory;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS categories;

        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT,
            country TEXT,
            signup_date DATE
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            price REAL NOT NULL,
            stock INTEGER
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id),
            status TEXT NOT NULL,
            total_amount REAL NOT NULL,
            created_at DATETIME
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );
        CREATE TABLE payments (
            id INTEGER PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id),
            method TEXT NOT NULL,
            amount REAL NOT NULL,
            paid_at DATETIME
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            customer_id INTEGER REFERENCES customers(id),
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at DATETIME
        );
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            warehouse TEXT NOT NULL,
            quantity INTEGER NOT NULL
        );
        """
    )

    # categories
    cat_names = ["electronics", "clothing", "home", "sports", "books", "toys", "beauty", "food"]
    cur.executemany(
        "INSERT INTO categories (id, name) VALUES (?, ?)",
        [(i, n) for i, n in enumerate(cat_names, start=1)],
    )

    # customers
    cities = ["hong kong", "singapore", "london", "tokyo", "sydney", "toronto", "dubai", "berlin"]
    countries = ["hong kong", "singapore", "uk", "japan", "australia", "canada", "uae", "germany"]
    customers = []
    for i in range(1, 201):
        c = rng.randint(0, len(cities) - 1)
        customers.append(
            (
                i,
                f"customer_{i:03d}",
                f"customer_{i:03d}@example.com",
                cities[c],
                countries[c],
                _rand_date(rng, date(2020, 1, 1), date(2026, 6, 30)),
            )
        )
    cur.executemany(
        "INSERT INTO customers (id, name, email, city, country, signup_date) VALUES (?,?,?,?,?,?)",
        customers,
    )

    # products
    products = []
    for i in range(1, 101):
        products.append(
            (
                i,
                f"product_{i:03d}",
                rng.randint(1, len(cat_names)),
                round(rng.uniform(5, 500), 2),
                rng.randint(0, 500),
            )
        )
    cur.executemany(
        "INSERT INTO products (id, name, category_id, price, stock) VALUES (?,?,?,?,?)",
        products,
    )

    # orders + payments + order_items
    statuses = ["completed", "pending", "cancelled", "shipped", "refunded"]
    methods = ["card", "paypal", "bank_transfer", "wallet", "cod"]
    order_ids = []
    for i in range(1, 2001):
        created = _rand_datetime(rng, date(2024, 1, 1), date(2026, 7, 31))
        status = statuses[rng.randint(0, len(statuses) - 1)]
        amount = round(rng.uniform(10, 800), 2)
        order_ids.append((i, rng.randint(1, 200), status, amount, created))
    cur.executemany(
        "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (?,?,?,?,?)",
        order_ids,
    )
    cur.executemany(
        "INSERT INTO payments (id, order_id, method, amount, paid_at) VALUES (?,?,?,?,?)",
        [
            (i, oid, methods[rng.randint(0, len(methods) - 1)], round(rng.uniform(10, 800), 2), _rand_datetime(rng, date(2024, 1, 1), date(2026, 7, 31)))
            for i, (oid, *_rest) in enumerate(order_ids, start=1)
        ],
    )
    cur.executemany(
        "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES (?,?,?,?,?)",
        [
            (i, oid, rng.randint(1, 100), rng.randint(1, 5), round(rng.uniform(5, 400), 2))
            for i, (oid, *_rest) in enumerate(order_ids, start=1)
        ],
    )

    # reviews + inventory
    cur.executemany(
        "INSERT INTO reviews (id, product_id, customer_id, rating, comment, created_at) VALUES (?,?,?,?,?,?)",
        [
            (i, rng.randint(1, 100), rng.randint(1, 200), rng.randint(1, 5), f"review_{i}", _rand_datetime(rng, date(2024, 1, 1), date(2026, 7, 31)))
            for i in range(1, 501)
        ],
    )
    warehouses = ["hk", "sg", "uk", "jp"]
    cur.executemany(
        "INSERT INTO inventory (id, product_id, warehouse, quantity) VALUES (?,?,?,?)",
        [
            (i, rng.randint(1, 100), warehouses[rng.randint(0, len(warehouses) - 1)], rng.randint(0, 1000))
            for i in range(1, 501)
        ],
    )

    conn.commit()


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        build(conn)
    finally:
        conn.close()
    print(f"built {DB_PATH} ({DB_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
