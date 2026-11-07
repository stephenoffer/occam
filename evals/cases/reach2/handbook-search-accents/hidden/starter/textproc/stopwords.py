"""Words too common in the handbook to be worth matching on.

The list is short on purpose: "office", "team" and "policy" look common but are
exactly what people search for, so they stay searchable.
"""

STOPWORDS = frozenset(
    """
    a about after all also an and any are as at be because been before but by can could did do does
    for from had has have he her here his how i if in into is it its just may me more most my no not
    of on or our out over she should so some than that the their them then there these they this those
    to too under up us very was we were what when where which while who why will with would you your
    """.split()
)
