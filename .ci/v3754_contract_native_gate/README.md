# Yoru v3.75.4 W14.5N isolated native closure

This branch exists only to certify the canonical v3.75.4 Phase 3+4 memory/contract runtime with a disposable MariaDB 11.4 / InnoDB service.

It must not replace or merge into the stale `main` application tree.

The embedded tarball is a deterministic execution projection containing the current runtime Python modules required by the W13.1–W14.5 contract/memory suite, the exact W13.1–W14.5 tests and static release-contract scripts, `VERSION`, and production `requirements.txt`. Non-executed binary visual assets and historical release documents are intentionally excluded from this proof branch.

Closure requires: source projection verification; native MariaDB `4/4 PASS`; production-dependency Phase 3+4 tests `86/86 PASS`; all W13.1–W14.5 static release contracts PASS; compileall PASS. Only then may the workflow emit `PHASE4_CLOSURE_GATE=PASS`.

The native suite refuses non-disposable database names and never discovers production credentials.
