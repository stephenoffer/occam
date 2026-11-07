# Contributing

- Branch from `main`, keep pull requests to one change, and get one review from someone on the
  store systems rota.
- Money is whole pence in every variable, field and file (ADR 0001). Format it only at the edge,
  with `till.money.fmt` on the till side.
- Every change ships with tests. `python -m pytest` must pass; the tills run Python 3.10, so don't
  use anything newer.
- Tills are updated store by store over about a week, so for a while some stores run the old
  version and some the new one. Plan changes with that in mind.
- Receipts are 40 columns. Check anything you add to the receipt fits.
- Store managers read `docs/cashup.md`. If you change what the cash-up shows, update it.
