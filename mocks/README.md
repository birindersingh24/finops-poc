# Mock FOCUS 1.2 billing data for a FinOps agent

Three months (2026-07-01 to 2026-09-30) of daily cloud billing for a fictional company, Acme Payments, on **AWS, Azure and Google Cloud**, in the FOCUS 1.2 Cost and Usage format. Eight cost problems are planted in it, and `anomalies.json` records exactly where they are.

| File | What it is |
|---|---|
| `focus_mock_costandusage.csv` | 2,598 rows × 57 FOCUS 1.2 columns, about $25.3k total `EffectiveCost` |
| `anomalies.json` | Answer key: type, provider, account, resource IDs, dates, excess cost |
| `checks.sql` | Seven DuckDB queries that find the problems; each one is a candidate agent tool |
| `generate_focus_mock.py` | The generator. Change dates, length or seed. Standard library only |

## The planted problems

| ID | Type | Where | When | Excess / waste |
|---|---|---|---|---|
| A1 | Spend spike | AWS Lambda `order-events-processor` (retry loop, ~25x invocations) | Aug 10–12 | $423 |
| A2 | Sustained increase | Azure Log Analytics (debug logging left on, ~6x ingestion) | Aug 25 onward | $7,199 |
| A3 | Spend spike | GCP BigQuery `orders_dw` (query lost its partition filter) | Sep 9–10 | $675 |
| A4 | Idle resource | AWS ALB `alb-staging-old` (hourly charges, ~0 traffic) | Whole period | $54 |
| A5 | Orphaned resource | Azure disk `disk-legacy-01` (its VM was deleted) | Jul 31 onward | $71 |
| A6 | Underused commitment | AWS reserved instance for 4 × m5.xlarge, only 2 still running | Aug 20 onward | $315 |
| A7 | Untagged spend | Azure `data-dev` subscription, GCP sandbox GPU VM | Whole period | $3,858 (unallocated) |
| A8 | Forgotten expensive resource | GCP A100 VM `gpu-notebook-tmp`, running 24/7 | Aug 31 onward | $3,460 |

Everything else is normal noise: weekday/weekend cycles, slow growth, ±5–15% jitter, an 8% negotiated discount on Azure, and a mix of hourly, per-GB and per-request meters.

## Run it

```bash
python generate_focus_mock.py                          # defaults: 2026-07-01, 92 days, seed 42
python generate_focus_mock.py --days 120 --seed 7 --parquet
duckdb < checks.sql                                    # run the detection queries
```

Planted problems scale with `--days`, so any window of 30 days or more contains all eight. A different `--seed` changes only the noise.

## Validation

Checked with the FinOps Foundation's official validator (`focus-validator` 2.2.1, rule model 1.2.0.1):

- **359 checks pass**
- **210 are skipped**, because the validator can't evaluate them automatically
- **9 fail**, all traced to three rules that are wrong in the validator's own rule file:

| Rule | Bug in the validator | Contradicts |
|---|---|---|
| `CommitmentDiscountStatus-C-004-C` | Condition is inverted: it demands a status on rows with **no** commitment | `-C-003-C`, which this data passes |
| `CapacityReservationStatus-C-004-C` | Malformed condition, so it fires on every row | `-C-003-C`, which this data passes |
| `InvoiceId-C-004-C` | No condition, so it demands an empty `InvoiceId` on every row | `-C-005-C`, which this data passes |

The other six failures are parent rules that fail because one of these three failed.

The validator also lists `Active/Expired/Pending` as the allowed `CommitmentDiscountStatus` values. The FOCUS spec defines `Used/Unused`, and the validator's own `ConsumedQuantity` rules refer to `"Unused"`, so this data follows the spec.

To rerun the validator, run it from inside its source folder (it loads `focus_validator/rules/currency_codes.csv` by relative path). If pyarrow complains, upgrade NumPy to 2.x:

```bash
focus-validator --data-file /path/to/focus_mock_costandusage.csv --validate-version 1.2 \
  --applicability-criteria ALL --output-type console
```

## Using it for the agent

- **Tools.** Wrap each query in `checks.sql` as a tool. The agent decides which checks to run, and the LLM explains the rows that come back and suggests fixes. The numbers come from SQL, not from the model.
- **Evaluation.** Score the agent's findings against `anomalies.json`: did it find each ID, and how close is its dollar estimate? Running `checks.sql` on its own finds 8 of 8, which is your baseline.
- **Multi-cloud.** Every query is written once and covers all three providers, because they share one schema. Adding a real provider later means converting its export to FOCUS, not changing the agent.

## Caveats

- All IDs, names and prices are fictional, shaped like each provider's real exports. Regions are Tokyo for all three. Currency is USD.
- Billing data alone can't show whether a disk is attached. A5 uses a `vm` tag as a stand-in; real tools ask the cloud's API.
- A7's amount is spend nobody owns, not waste, and it overlaps A8 (the GPU VM is also untagged).
- In the spike check, A2's first week also appears. It's the same incident, caught earlier by a different check.
