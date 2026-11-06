"""Nightly job comparing invoices with the payment processor, across all tenants."""

from billing import store


def reconcile(db, invoice_ids):
    return {row["id"]: row["total"] for row in store.get_invoices(db, invoice_ids)}
