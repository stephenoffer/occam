FINANCE_ROLES = {"admin", "finance"}


def can_view(user, invoice):
    if invoice["tenant_id"] != user.tenant_id or invoice["deleted_at"] is not None:
        return False
    if invoice["status"] == "draft" and user.role not in FINANCE_ROLES:
        return False
    return True


def invoice_view(user, invoice):
    view = {
        "id": invoice["id"],
        "customer": invoice["customer"],
        "total": invoice["total"],
        "status": invoice["status"],
    }
    if user.role in FINANCE_ROLES:
        view["internal_notes"] = invoice["internal_notes"]
    return view
