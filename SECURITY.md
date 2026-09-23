# Security policy

Report vulnerabilities privately to the repository maintainers through GitHub's private vulnerability reporting feature when it is enabled. Do not include bot tokens, Telegram session strings, production user IDs, message content, or database dumps in public issues. If private reporting is unavailable, contact the maintainer through an established private channel before disclosing exploit details.

The supported release is the current `main` branch. A fix is considered verified only after the relevant regression test, CI checks, migration test where applicable, and an operational check for controls that require live infrastructure. The [ASVS matrix](docs/asvs_4_0_3_v1_v10_matrix.csv), [threat model](docs/threat_model_asvs.md), and [on-call runbook](docs/oncall_runbook.md) record known boundaries and work still requiring runtime evidence.

The bot is an auxiliary information source. It may miss, delay, or misclassify a threat. Users should verify the current situation through official channels and must not depend on this bot as their only safety signal.
