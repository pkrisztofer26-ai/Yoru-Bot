# Yoru v3.73 AI Scenario Lab PoC — CI fixture

This directory is an isolated CI fixture. The repository `main` branch is intentionally not treated as the current Yoru production/development source tree.

Authority:
- production baseline: v3.72.0 RC4 LIVE STABLE
- Scenario Engine W11.2 native MariaDB gate: PASS
- AI Lab source checkpoint: `YoruBot_v3.73.0_AI_SCENARIO_LAB_DEV_CHECKPOINT_W12.1_PRE_RUN.zip`
- checkpoint SHA-256: `3bed669f0ed2416fc83d4313a278a0253f8ed98486f81cd33876c7333db2b697`

The fixture is DEV-only. `runner.py` does not import Discord, does not open the Yoru database, and cannot authorize production AI. Mechanical gameplay authority remains outside the AI layer.
