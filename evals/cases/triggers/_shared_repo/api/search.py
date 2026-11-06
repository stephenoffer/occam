def search(db, query):
    rows = db.execute("SELECT * FROM products").fetchall()
    return [row for row in rows if query.lower() in row["title"].lower()]
