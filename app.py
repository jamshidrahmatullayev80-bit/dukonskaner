from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

# Frontend papkasini ko'rsatish
FRONTEND = os.path.join(os.path.dirname(__file__), '..', 'frontend')

app = Flask(__name__, static_folder=FRONTEND, static_url_path='')
CORS(app)

@app.route('/')
def index():
    return send_from_directory(FRONTEND, 'index.html')

DB = "dokon.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode  TEXT UNIQUE NOT NULL,
            name     TEXT NOT NULL,
            price    REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            category TEXT DEFAULT 'Umumiy'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            total   REAL NOT NULL,
            sold_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id    INTEGER REFERENCES sales(id),
            product_id INTEGER REFERENCES products(id),
            quantity   INTEGER NOT NULL,
            price      REAL NOT NULL,
            subtotal   REAL NOT NULL
        )
    """)

    # Demo mahsulotlar (bo'sh bo'lsa qo'shiladi)
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        demo = [
            ("4890001234560", "Coca-Cola 1L",      8500,  50,  "Ichimliklar"),
            ("4890001234561", "Pepsi 0.5L",         5000,  80,  "Ichimliklar"),
            ("4890001234562", "Lipton Choy 100g",  12000,  30,  "Choy/Qahva"),
            ("4890001234563", "Nescafe 3in1 x10",  15000,  25,  "Choy/Qahva"),
            ("4890001234564", "Slivochnoye Non",    3500, 100,  "Non mahsulotlari"),
            ("4890001234565", "Snickers 50g",       4500,  60,  "Shirinliklar"),
            ("4890001234566", "Orbit Yashil",       3000,   8,  "Shirinliklar"),
            ("4890001234567", "Fairy 500ml",       18000,  15,  "Gigiena"),
            ("4890001234568", "Rexona deo 150ml",  22000,   5,  "Gigiena"),
            ("4890001234569", "Makfa Makaron 400g", 7000,  40,  "Oziq-ovqat"),
        ]
        c.executemany(
            "INSERT INTO products (barcode,name,price,quantity,category) VALUES (?,?,?,?,?)",
            demo
        )
    conn.commit()
    conn.close()

# ─────────────────────────────
# MAHSULOTLAR
# ─────────────────────────────
@app.route("/api/products", methods=["GET"])
def get_products():
    conn = get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/products/barcode/<barcode>", methods=["GET"])
def get_by_barcode(barcode):
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE barcode=?", (barcode,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Mahsulot topilmadi"}), 404
    return jsonify(dict(row))

@app.route("/api/products", methods=["POST"])
def add_product():
    d = request.json
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO products (barcode,name,price,quantity,category) VALUES (?,?,?,?,?)",
            (d["barcode"], d["name"], d["price"], d["quantity"], d.get("category","Umumiy"))
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Bu shtrix kod allaqachon mavjud!"}), 400

@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/products/<int:pid>", methods=["PUT"])
def update_product(pid):
    d = request.json
    conn = get_db()
    conn.execute(
        "UPDATE products SET name=?,price=?,quantity=?,category=? WHERE id=?",
        (d["name"], d["price"], d["quantity"], d["category"], pid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─────────────────────────────
# SOTUVLAR
# ─────────────────────────────
@app.route("/api/sales", methods=["POST"])
def create_sale():
    items = request.json.get("items", [])
    if not items:
        return jsonify({"error": "Savat bo'sh"}), 400

    conn = get_db()
    total = 0
    enriched = []

    for item in items:
        row = conn.execute(
            "SELECT * FROM products WHERE barcode=?", (item["barcode"],)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": f"Mahsulot topilmadi: {item['barcode']}"}), 404
        if row["quantity"] < item["quantity"]:
            conn.close()
            return jsonify({"error": f"{row['name']} yetarli emas (zaxira: {row['quantity']})"}), 400
        sub = row["price"] * item["quantity"]
        total += sub
        enriched.append({"id": row["id"], "qty": item["quantity"],
                          "price": row["price"], "sub": sub})

    # Sotuv yaratish
    cur = conn.execute("INSERT INTO sales (total) VALUES (?)", (total,))
    sale_id = cur.lastrowid

    for e in enriched:
        conn.execute(
            "INSERT INTO sale_items (sale_id,product_id,quantity,price,subtotal) VALUES (?,?,?,?,?)",
            (sale_id, e["id"], e["qty"], e["price"], e["sub"])
        )
        conn.execute(
            "UPDATE products SET quantity = quantity - ? WHERE id=?",
            (e["qty"], e["id"])
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "total": total, "sale_id": sale_id})

@app.route("/api/sales", methods=["GET"])
def get_sales():
    conn = get_db()
    sales = conn.execute("SELECT * FROM sales ORDER BY sold_at DESC LIMIT 50").fetchall()
    result = []
    for s in sales:
        items = conn.execute("""
            SELECT p.name, si.quantity, si.subtotal
            FROM sale_items si JOIN products p ON si.product_id=p.id
            WHERE si.sale_id=?
        """, (s["id"],)).fetchall()
        result.append({
            "id": s["id"],
            "total": s["total"],
            "sold_at": s["sold_at"],
            "items": [{"name": i["name"], "quantity": i["quantity"], "subtotal": i["subtotal"]}
                      for i in items]
        })
    conn.close()
    return jsonify(result)

# ─────────────────────────────
# STATISTIKA
# ─────────────────────────────
@app.route("/api/stats", methods=["GET"])
def get_stats():
    conn = get_db()
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_sales    = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    total_revenue  = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
    low_stock      = conn.execute(
        "SELECT name, quantity FROM products WHERE quantity < 10 ORDER BY quantity"
    ).fetchall()
    conn.close()
    return jsonify({
        "total_products": total_products,
        "total_sales": total_sales,
        "total_revenue": total_revenue,
        "low_stock": [dict(r) for r in low_stock]
    })

if __name__ == "__main__":
    init_db()
    print("\n" + "="*50)
    print("  🏪 DO'KON TIZIMI - Backend ishga tushdi!")
    print("  📡 API: http://localhost:5000/api")
    print("  🌐 Frontend: frontend/index.html ni oching")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)