# Integration tests

The normal test suite remains independent of external services. PostgreSQL live
tests are opt-in. ``DATABASE_URL`` identifies the already-loaded, read-only
``mirae_agent`` staging database; ``G2B_TEST_DATABASE_URL`` identifies a separate
disposable ``mirae_agent_test`` database and may be used by tests that create
session-local fixtures. A missing URL is reported as a skip, never simulated as
a live database pass.

HyperCLOVA X tests are also opt-in through ``HCX_ENABLED``, ``HCX_API_KEY``, and
``HCX_API_URL``. The standalone smoke test issues one short request. The full
``/answer`` E2E issues one additional request only after real PostgreSQL evidence
has passed the structured semantic gate and evidence validator. Credentials and
connection strings must remain process-local and are never printed by tests.
