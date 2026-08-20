# Yoru v3.75.4 W14.5N clean native closure

This CI proof intentionally contains no tar/base64 source transport for W14.5.
It follows the proven W11.2 pattern: a disposable MariaDB 11.4 service, a small fail-closed runner, and a semantic source projection whose canonical ContractService/Database methods and MySQL DDL are hash/AST verified.

The already-certified W10 db_backend.py + metrics.py fixture is reconstructed and hash-verified by the runner. The exact W14.5 native test is executed unchanged.

This branch is CI-only and must never replace the stale main application tree or production deployment.
