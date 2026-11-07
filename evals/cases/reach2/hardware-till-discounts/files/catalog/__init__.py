"""Product catalogue shared by the tills and stock control."""

from catalog.departments import DEPARTMENTS, department_name
from catalog.products import Product, ProductNotFound, load_catalog

__all__ = ["DEPARTMENTS", "Product", "ProductNotFound", "department_name", "load_catalog"]
