# billing

Invoice service for our customers. Each customer is a tenant; API keys belong to a user in a tenant.

    GET /invoices        list the caller's invoices
    GET /invoices/{id}   one invoice

Every invoice read through the API is recorded in `access_log`. This is a compliance requirement.

Authenticate with the `X-Api-Key` header. Run the tests with `pytest`.
