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
    # Deals need the updatedSince filter, which fetch_all doesn't take.
    records, cursor = [], None
    while True:
        params = {"limit": 100, "updatedSince": updated_since}
        if cursor:
            params["cursor"] = cursor
        data = client.get_json("/v2/deals", params)
        try:
            records.extend(data["results"])
        except KeyError:
            break
        cursor = data.get("next")
        if not cursor:
            break
    db.upsert(connection, "deals", records)
    return len(records)


def sync_all(client, connection):
    return {
        "contacts": sync_contacts(client, connection),
        "companies": sync_companies(client, connection),
        "deals": sync_deals(client, connection),
    }
