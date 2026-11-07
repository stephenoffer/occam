# order tools

`cli/show_order.py` prints orders fetched from the orders API. `pytest` runs the tests.

The client in `clients/orders_generated.py` is generated from `api/orders.schema.json`. After changing the schema, run
`python tools/gen_client.py` from the repository root. CI regenerates the client and fails if the committed file differs.
