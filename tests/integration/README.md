# Integration tests

The normal test suite remains independent of external services. PostgreSQL live
tests must be opt-in, use a dedicated test database URL, and leave no persistent
fixtures. A missing test URL is reported as a skip, never simulated as a live
database pass. HCX and other external retrieval services remain disconnected.
