# Use a PostgreSQL-backed Python modular monolith

Billzebub will use one Python codebase with a FastAPI HTTP process and a separate worker process, both backed by PostgreSQL; durable jobs will live in PostgreSQL rather than Redis or an external task queue. This keeps Monopoly in-process, gives the ledger transactional constraints, and separates request handling from ingestion without introducing distributed-service infrastructure for a single-user deployment.
