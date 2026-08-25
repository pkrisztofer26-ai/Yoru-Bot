# Yoru v3.82.0 Production Integration / Hardening

Status: **PRE-ERROR-INTAKE / NOT DEPLOYED**

Target transition: `v3.72.0 RC4 LIVE` -> `v3.82.0 W21.1`.

This branch is the control plane for the production-integration pass. The repository `main` application source is historical/stale and must not be treated as the modern runtime baseline. The canonical modern source remains the released v3.82.0 W21.1 FULL artifact identified in `SOURCE_IDENTITY.json` until the final hardened source projection is committed.

Current package audit:
- canonical v3.72 production package: 286 files
- v3.82 pre-error-fix production candidate: 325 files
- unchanged: 230
- modified: 56
- added: 39
- removed: 0

Stable byte-identical deployment contracts between v3.72 and v3.82 candidate:
- `requirements.txt`
- `bot.py`
- `app/config.py`
- `app/db_backend.py`
- `app/core/runtime.py`
- `app/core/performance.py`

Schema surface: `112/103/9 -> 162/153/9`; Launch Reset preserve set remains `35 -> 35`.
Command surface: `160 -> 173` canonical slash paths and `424 -> 454` prefix names+aliases, with zero collisions in the release gates.

Hard rules:
1. No production deploy until the live error backlog is ingested and resolved.
2. No Launch Reset as an upgrade mechanism.
3. Take a fresh MySQL/MariaDB export and source archive immediately before cutover.
4. Preserve `.env`, host/runtime config, launch-reset backups, Server Architect snapshots, and the first-deploy `.local` environment.
5. Final deployment replaces canonical source units; it does not merge historical source directories.
