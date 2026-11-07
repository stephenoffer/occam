"""Department codes printed on shelf labels and used for sales analysis."""

DEPARTMENTS = {
    "PNT": "Paint & decorating",
    "FIX": "Fixings",
    "TLS": "Tools",
    "GDN": "Garden",
    "ELC": "Electrical",
    "PLB": "Plumbing",
}


def department_name(code: str) -> str:
    """The display name for a department code, or the code itself for one we don't know."""
    return DEPARTMENTS.get(code, code)
