# Production error intake

Send the accumulated LIVE errors before the final v3.82 production projection is committed.

For each distinct error, useful context is:
- traceback/log block from the first ERROR line through the final exception;
- triggering command/button/event;
- always vs intermittent;
- whether the bot crashes/restarts or only the action fails;
- approximate occurrence time;
- repeated identical errors may be grouped.

Do **not** send `.env`, Discord token, MySQL password, API keys, or a full live DB export.

Triage buckets:
1. startup/import/schema;
2. MySQL/transaction/concurrency;
3. Discord command/UI/API;
4. background task/restart recovery;
5. permissions/server architecture;
6. gameplay/service logic;
7. dependency/hosting/music;
8. duplicate symptom of an already identified root cause.
