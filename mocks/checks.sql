-- FinOps checks over FOCUS 1.2 data, in DuckDB.
-- Each query is a candidate tool for the agent: it returns findings, the LLM explains them.
-- Run:  duckdb < checks.sql      (from the folder holding the CSV)

CREATE OR REPLACE VIEW focus AS
SELECT * FROM read_csv('focus_mock_costandusage.csv', header = true, auto_detect = true);

CREATE OR REPLACE VIEW daily_service_cost AS
SELECT ProviderName, SubAccountName, ServiceName,
       CAST(ChargePeriodStart AS DATE) AS day,
       SUM(EffectiveCost) AS cost
FROM focus
WHERE ChargeCategory = 'Usage'
GROUP BY ALL;

-- 1. Spend spikes: a day's cost per service vs its trailing 14-day median.
--    A sustained increase also shows up here for its first few days.
SELECT 'spike' AS check, ProviderName, SubAccountName, ServiceName, day,
       ROUND(cost, 2) AS cost, ROUND(baseline, 2) AS baseline, ROUND(cost / baseline, 1) AS ratio
FROM (
    SELECT *, MEDIAN(cost) OVER (
        PARTITION BY ProviderName, SubAccountName, ServiceName ORDER BY day
        ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING) AS baseline
    FROM daily_service_cost
)
WHERE baseline > 0 AND cost > 3 * baseline AND cost - baseline > 50
ORDER BY day;

-- 2. Sustained increases: average of the last 14 days vs the median of all earlier days.
--    The median keeps a recent step change from inflating its own baseline.
SELECT 'sustained_increase' AS check, ProviderName, SubAccountName, ServiceName,
       ROUND(AVG(cost) FILTER (WHERE day > last_day - 14), 2) AS recent_avg,
       ROUND(MEDIAN(cost) FILTER (WHERE day <= last_day - 14), 2) AS earlier_median
FROM daily_service_cost, (SELECT MAX(day) AS last_day FROM daily_service_cost)
GROUP BY ALL
HAVING recent_avg > 2 * earlier_median AND recent_avg - earlier_median > 20;

-- 3. Idle resources: billed by the hour while the traffic meter is near zero.
SELECT 'idle' AS check, ProviderName, SubAccountName, ResourceName, ResourceType,
       ROUND(SUM(EffectiveCost), 2) AS cost,
       ROUND(SUM(ConsumedQuantity) FILTER (WHERE ConsumedUnit <> 'Hours')
             / COUNT(DISTINCT CAST(ChargePeriodStart AS DATE)), 3) AS traffic_per_day,
       ANY_VALUE(ConsumedUnit) FILTER (WHERE ConsumedUnit <> 'Hours') AS traffic_unit
FROM focus
WHERE ResourceId IS NOT NULL AND ChargeCategory = 'Usage'
GROUP BY ALL
HAVING SUM(EffectiveCost) FILTER (WHERE ConsumedUnit = 'Hours') > 0
   AND traffic_per_day IS NOT NULL AND traffic_per_day < 1;

-- 4. Orphaned disks: still billing after the VM named in their 'vm' tag stopped billing.
--    Real tools ask the cloud API whether the disk is attached. The tag stands in for that here.
WITH vm_last AS (
    SELECT ResourceName AS vm, MAX(CAST(ChargePeriodStart AS DATE)) AS vm_last_day
    FROM focus WHERE ResourceType = 'Virtual machine' GROUP BY 1
)
SELECT 'orphaned' AS check, d.ResourceName AS disk, v.vm, v.vm_last_day,
       MIN(CAST(d.ChargePeriodStart AS DATE)) AS orphaned_since,
       ROUND(SUM(d.EffectiveCost), 2) AS cost_since
FROM focus d
JOIN vm_last v ON json_extract_string(d.Tags, '$.vm') = v.vm
WHERE d.ResourceType = 'Disk' AND CAST(d.ChargePeriodStart AS DATE) > v.vm_last_day
GROUP BY ALL;

-- 5. Commitment utilization per commitment and month.
SELECT 'commitment' AS check, ProviderName, CommitmentDiscountName,
       DATE_TRUNC('month', CAST(ChargePeriodStart AS DATE)) AS month,
       ROUND(SUM(EffectiveCost) FILTER (WHERE CommitmentDiscountStatus = 'Used'), 2) AS used,
       ROUND(COALESCE(SUM(EffectiveCost) FILTER (WHERE CommitmentDiscountStatus = 'Unused'), 0), 2) AS unused,
       ROUND(100 * used / (used + unused), 1) AS utilization_pct
FROM focus
WHERE ChargeCategory = 'Usage' AND CommitmentDiscountId IS NOT NULL
GROUP BY ALL
ORDER BY month;

-- 6. Untagged spend: resource charges with no 'team' tag (unallocated, not necessarily waste).
SELECT 'untagged' AS check, ProviderName, SubAccountName, ResourceName,
       ROUND(SUM(EffectiveCost), 2) AS cost
FROM focus
WHERE ResourceId IS NOT NULL AND json_extract_string(Tags, '$.team') IS NULL
GROUP BY ALL
ORDER BY cost DESC;

-- 7. New expensive resources: first billed after the window started, averaging over $50/day.
SELECT 'new_expensive' AS check, ProviderName, SubAccountName, ResourceName, first_day,
       ROUND(avg_daily, 2) AS avg_daily, json_extract_string(Tags, '$.team') AS team
FROM (
    SELECT ProviderName, SubAccountName, ResourceName, Tags,
           MIN(CAST(ChargePeriodStart AS DATE)) AS first_day,
           SUM(EffectiveCost) / COUNT(DISTINCT CAST(ChargePeriodStart AS DATE)) AS avg_daily
    FROM focus WHERE ResourceId IS NOT NULL GROUP BY ALL
)
WHERE first_day > (SELECT MIN(CAST(ChargePeriodStart AS DATE)) FROM focus) AND avg_daily > 50
ORDER BY avg_daily DESC;
