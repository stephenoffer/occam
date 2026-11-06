from . import db


def sync_contacts(client, connection):
    records = client.fetch_all("/v2/contacts")
    db.upsert(connection, "contacts", records)
    return len(records)


def sync_companies(client, connection):
    records = client.fetch_all("/v2/companies")
    db.upsert(connection, "companies", records)
    return len(records)


def sync_deals(client, connection, updated_since="1970-01-01"):
    records = client.fetch_all("/v2/deals", rows_key="items", updatedSince=updated_since)
    db.upsert(connection, "deals", records)
    return len(records)


def sync_all(client, connection):
    return {
        "contacts": sync_contacts(client, connection),
        "companies": sync_companies(client, connection),
        "deals": sync_deals(client, connection),
    }
