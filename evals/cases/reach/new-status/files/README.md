# orders

Order handling for the shop. `pytest` runs the tests.

Statuses are in `orders/status.py`. The database schema lives in `db/migrations/`, applied by `db/migrate.py` in name order.
Production has run every migration in that folder. Never edit one that has run: add the next numbered file.
