# Architecture

Four layers, top to bottom: entrypoints, services, domain, core. A layer may import from layers below it and never from layers above it. Domain packages don't import each other: anything that needs two of them belongs in a service.

Services take a raw document, pull out its fields and business date, open a document scope for the audit trail and call into the domain. Domain code doesn't know about documents, it's handed the values it needs.

Some domain behavior is data-driven rather than wired up in code. The main example is the adjustment schedule, see `adjustments.md`.
