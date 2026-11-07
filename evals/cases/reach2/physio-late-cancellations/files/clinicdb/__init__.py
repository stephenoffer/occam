"""The clinic database: schema, connections and seed data."""

from clinicdb.connect import open_db, init_schema

__all__ = ["open_db", "init_schema"]
