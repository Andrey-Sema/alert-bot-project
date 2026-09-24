# Roadmap to a verified 9/10

Baseline: `155f4dea` (2026-09-23). Review target: `e3140f1` (2026-09-24).
The current code review score is 5/10, weighted toward missed safety alerts. A green CI run is not proof of live delivery. The scores below are estimates until the acceptance evidence exists.

## Release rule

Work in batches of four items. Each batch has one PR with focused unit, property-based, and integration tests. Merge only after review of the actual diff, green CI, and no unresolved P1 findings. The last two batches also require the listed staging or production evidence. Do not label an item 9/10 merely because its code merged.

| ID | Current → target | What and where | How and why | Acceptance evidence |
| --- | --- | --- | --- | --- |
| N01 | 3 → 9 | Mixed active/clear posts in `core_shared/text_processor.py` and `worker/main.py` | Represent clauses separately; a clear for one place must not suppress a later active threat in the same post. | Labelled examples for clear-only, active-only, mixed order, two languages and punctuation; active part always reaches fanout. |
| N02 | 3 → 9 | Scope delayed-stage cancellation in `worker/main.py` and `worker/broadcaster.py` | Store global and location-scoped clear IDs; cancel a multi-location reminder only if every relevant location has cleared. Preserve event ordering. | Real Redis tests for one location, another location, global clear, mixed posts, out-of-order replay and multi-location alerts. |
| N03 | 3 → 9 | Remove negated clauses from recipient selection in `text_processor.py` and worker matcher path | Derive categories, locations and custom phrases only from non-negated active text. Keep public `parse_message` compatibility. | Property-based and routing tests show a negated zone/category cannot add recipients while an active sibling still can. |
| N04 | 3 → 9 | Complete active-data deletion in `services/privacy.py` | Fence delivery, remove every per-recipient stream and DLQ copy, and preserve safe retry semantics if Redis/DB fails. | Integration test covers first/delayed/pending/DLQ jobs, re-registration, concurrent delivery, and failure recovery; retention of AOF/backups/logs explicitly documented. |
| N05 | 4 → 9 | Delivery backlog and oldest-age metrics | Derive age from pending or undelivered entries, not retained acknowledged Stream entries. | Real Redis/Prometheus scenario: zero pending never fires stale-job alert; an intentionally stuck job fires within the configured window. |
| N06 | 5 → 9 | File-only database credentials in Alembic | Use the same secret loader in migration and runtime; reject missing/oversized files cleanly. | CI boots migrator with only `DATABASE_URL_FILE`, then worker and bot against the migrated schema. |
| N07 | 5 → 9 | Bound source idempotency markers | Define retention based on maximum replay horizon and reclaim markers without losing deduplication during recovery. | 30-day synthetic replay and memory test; old source IDs never duplicate within the supported horizon, marker count is bounded. |
| N08 | 5 → 9 | Custom phrase reconciliation | Increment matcher version only when the phrase set changes; benchmark maximum 5000 phrases. | No rebuild on identical refresh; P95 match latency and memory pass the agreed load budget. |
| N09 | 3 → 9 | Scraper catch-up after Telegram disconnect | Persist a source checkpoint and fetch missed channel history after reconnect, with idempotent outbox publishing. | Inject 10-minute disconnect while posts arrive; every source ID is processed once after recovery. |
| N10 | 3 → 9 | Capacity and rate fairness | Measure Bot API 429, fanout, SQL plans, Redis memory, first-stage priority and repeat load. Tune only from data. | State a tested maximum recipient count N for 1/5/20 posts per minute with P95/P99 first-delivery SLO, zero accepted-job loss, bounded RAM and documented 429 behavior. |
| N11 | 4 → 9 | Database/user security and ASVS | Audit deployed DB role, grants, RLS, network access, secrets and backup policy; map applicable controls to current stable ASVS with reproducible evidence. | Independent security review and DB role probes; no public table access; every applicable ASVS control has owner, method and pass/fail evidence. |
| N12 | 3 → 9 | Operations and real audience | Run live alert, Redis/DB/Telegram fault drills, on-call replay, and 30-day activity reporting. | Administrator confirms test alert, 30 complete UTC days produce MAU and delivered-user counts, drills meet SLO and leave no unexplained loss. |

The first PR implements N01–N04. N05–N08 and N09–N12 follow in separate PRs, rebased onto the updated `main` before review. The final 9/10 rating depends on the external evidence in N09–N12 and a repeat independent audit.
