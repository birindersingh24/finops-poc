#!/usr/bin/env python3
"""
Mock FOCUS 1.2 Cost and Usage data for AWS, Azure and Google Cloud, with
planted FinOps problems and a ground-truth answer key.

    python generate_focus_mock.py                    # 2026-07-01, 92 days, seed 42
    python generate_focus_mock.py --days 120 --seed 7 --parquet

Writes:
    focus_mock_costandusage.csv   FOCUS 1.2 Cost and Usage dataset (57 columns)
    anomalies.json                what was planted, where, when, and its excess cost

Standard library only. --parquet also needs pyarrow.
All names, IDs and prices are fictional but shaped like the real providers' exports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal as D
from typing import Callable, Optional

# ---------------------------------------------------------------- FOCUS 1.2 columns
COLUMNS = [
    "AvailabilityZone", "BilledCost", "BillingAccountId", "BillingAccountName", "BillingAccountType",
    "BillingCurrency", "BillingPeriodEnd", "BillingPeriodStart", "CapacityReservationId",
    "CapacityReservationStatus", "ChargeCategory", "ChargeClass", "ChargeDescription", "ChargeFrequency",
    "ChargePeriodEnd", "ChargePeriodStart", "CommitmentDiscountCategory", "CommitmentDiscountId",
    "CommitmentDiscountName", "CommitmentDiscountQuantity", "CommitmentDiscountStatus",
    "CommitmentDiscountType", "CommitmentDiscountUnit", "ConsumedQuantity", "ConsumedUnit", "ContractedCost",
    "ContractedUnitPrice", "EffectiveCost", "InvoiceId", "InvoiceIssuerName", "ListCost", "ListUnitPrice",
    "PricingCategory", "PricingCurrency", "PricingCurrencyContractedUnitPrice", "PricingCurrencyEffectiveCost",
    "PricingCurrencyListUnitPrice", "PricingQuantity", "PricingUnit", "ProviderName", "PublisherName",
    "RegionId", "RegionName", "ResourceId", "ResourceName", "ResourceType", "ServiceCategory", "ServiceName",
    "ServiceSubcategory", "SkuId", "SkuMeter", "SkuPriceDetails", "SkuPriceId", "SubAccountId",
    "SubAccountName", "SubAccountType", "Tags",
]

# ---------------------------------------------------------------- providers
PROVIDERS = {
    "aws": dict(
        name="AWS", billing_account_id="100000000001", billing_account_name="Acme Payments (AWS)",
        billing_account_type="Management Account", invoice_prefix="AWS-JP-", discount=D("0"),
        region=("ap-northeast-1", "Asia Pacific (Tokyo)"), sub_type="Account",
        subs={"acme-prod": "210000000001", "acme-staging": "210000000002"},
    ),
    "azure": dict(
        name="Microsoft", billing_account_name="Acme Payments (Azure)",
        billing_account_id="/providers/Microsoft.Billing/billingAccounts/acme-mca/billingProfiles/BP-7Q2X",
        billing_account_type="Billing Profile", invoice_prefix="G0", discount=D("0.08"),  # negotiated 8% off list
        region=("japaneast", "Japan East"), sub_type="Subscription",
        subs={"payments-prod": "/subscriptions/3f2b9c4e-1a7d-4c1b-9e2a-5d6f7a8b9c01",
              "data-dev": "/subscriptions/8a1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d02"},
    ),
    "gcp": dict(
        name="Google Cloud", billing_account_id="01A2B3-C4D5E6-F7A8B9", billing_account_name="Acme Payments (GCP)",
        billing_account_type="Billing Account", invoice_prefix="GCP-", discount=D("0"),
        region=("asia-northeast1", "Tokyo"), sub_type="Project",
        subs={"acme-analytics-prod": "acme-analytics-prod", "acme-ml-sandbox": "acme-ml-sandbox"},
    ),
}

# AWS reserved instance covering the four api servers
RI_ID = "arn:aws:ec2:ap-northeast-1:210000000001:reserved-instances/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
RI_NAME = "ri-m5.xlarge-api-1yr"
RI_COUNT = 4
RI_RATE = D("0.156")          # effective hourly rate, 1 year no upfront
M5_LIST = D("0.248")          # on-demand m5.xlarge, Tokyo


# ---------------------------------------------------------------- model
@dataclass
class Ctx:
    i: int                    # day index
    d: date
    rng: random.Random

    @property
    def weekend(self) -> bool:
        return self.d.weekday() >= 5

    def j(self, pct: float = 0.05) -> D:          # jitter multiplier
        return D(str(round(self.rng.uniform(1 - pct, 1 + pct), 4)))

    def growth(self, per_day: float = 0.001) -> D:
        return D(str(round(1 + per_day * self.i, 4)))

    def busy(self, weekend_factor: str = "0.6") -> D:
        return D(weekend_factor) if self.weekend else D(1)


@dataclass
class Meter:
    label: str                                  # used for SkuId / SkuPriceId generation
    meter: str                                  # SkuMeter
    consumed_unit: str
    pricing_unit: str
    list_price: D                               # per pricing unit
    qty: Callable[[Ctx], D]                     # baseline consumed quantity for the day
    description: str
    to_pricing: D = D(1)                        # pricing quantity = consumed * to_pricing
    boost: Optional[Callable[[int], D]] = None  # planted multiplier by day index
    anomaly: Optional[str] = None               # anomaly id the boost belongs to
    qplaces: str = "0.0001"


@dataclass
class Resource:
    provider: str
    sub: str
    service: str
    category: str
    subcategory: str
    rid: str
    name: str
    rtype: str
    az: Optional[str]
    tags: Optional[dict]
    meters: list
    first_day: int = 0
    last_day: int = 10 ** 9
    ri_covered: bool = False
    waste: Optional[tuple] = None   # (anomaly_id, from_day): all cost from that day is waste


def code(label: str, n: int = 10, alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789") -> str:
    h = hashlib.sha256(label.encode()).digest()
    return "".join(alphabet[b % len(alphabet)] for b in h[:n])


def sku_ids(provider: str, label: str) -> tuple:
    if provider == "aws":
        sku = code("aws:" + label)
        return sku, f"{sku}.{code('awsp:' + label, 10)}"
    if provider == "azure":
        sku = "DZH" + code("az:" + label, 9)
        return sku, f"{sku}/{code('azp:' + label, 4, '0123456789')}"
    sku = "-".join(code("gcp:" + label, 12, "0123456789ABCDEF")[k:k + 4] for k in (0, 4, 8))
    return sku, f"{sku}/{code('gcpp:' + label, 6, '0123456789abcdef')}"


def num(x) -> str:
    if x is None:
        return ""
    if isinstance(x, D):
        s = "0" if x == 0 else format(x.normalize(), "f")
        return s if "." in s else s + ".0"   # keep decimal columns from being read as integers
    return str(x)


def ts(d: date) -> str:
    return d.isoformat() + "T00:00:00Z"


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


# ---------------------------------------------------------------- inventory
def inventory(days: int) -> tuple:
    """Resources plus the planted-problem timeline, scaled to the window length."""
    t = {
        "lambda_spike": round(days * 0.435),      # 3-day retry storm
        "legacy_vm_last": round(days * 0.326) - 1,
        "ri_last": round(days * 0.54) - 1,         # api-3 / api-4 retired after this day
        "logs_from": round(days * 0.6),            # debug logging left on
        "gpu_from": round(days * 0.663),           # GPU notebook never shut down
        "bq_spike": round(days * 0.76),            # 2-day runaway query
    }
    hours24 = lambda c: D(24)
    prod_tags = lambda app, team="payments": {"team": team, "env": "prod", "app": app, "cost-center": "cc-1042"}
    R = []

    # ---------- AWS
    for k in range(1, 5):
        R.append(Resource(
            "aws", "acme-prod", "Amazon Elastic Compute Cloud", "Compute", "Virtual Machines",
            f"arn:aws:ec2:ap-northeast-1:210000000001:instance/i-0a1b2c3d4e5f6000{k}", f"api-{k}", "Instance",
            "ap-northeast-1a" if k % 2 else "ap-northeast-1c", prod_tags("checkout-api"),
            [Meter("ec2-m5.xlarge", "BoxUsage:m5.xlarge", "Hours", "Hours", M5_LIST, hours24,
                   "$0.248 per On Demand Linux m5.xlarge Instance Hour")],
            last_day=(t["ri_last"] if k >= 3 else 10 ** 9), ri_covered=True))
    R.append(Resource(
        "aws", "acme-staging", "Amazon Elastic Compute Cloud", "Compute", "Virtual Machines",
        "arn:aws:ec2:ap-northeast-1:210000000002:instance/i-0b2c3d4e5f6a70011", "batch-runner", "Instance",
        "ap-northeast-1a", {"team": "platform", "env": "staging", "app": "batch"},
        [Meter("ec2-t3.large", "BoxUsage:t3.large", "Hours", "Hours", D("0.1088"), hours24,
               "$0.1088 per On Demand Linux t3.large Instance Hour")]))
    R.append(Resource(
        "aws", "acme-prod", "Amazon Relational Database Service", "Databases", "Relational Databases",
        "arn:aws:rds:ap-northeast-1:210000000001:db:payments-db", "payments-db", "DB Instance",
        "ap-northeast-1a", prod_tags("ledger"),
        [Meter("rds-r5.large-pg", "InstanceUsage:db.r5.large", "Hours", "Hours", D("0.30"), hours24,
               "RDS db.r5.large PostgreSQL Single-AZ instance hour")]))
    R.append(Resource(
        "aws", "acme-prod", "Amazon Simple Storage Service", "Storage", "Object Storage",
        "arn:aws:s3:::acme-prod-logs", "acme-prod-logs", "Bucket", None, prod_tags("logging", "platform"),
        [Meter("s3-standard", "TimedStorage-ByteHrs", "GB-Months", "GB-Months", D("0.025"),
               lambda c: (D(20000) + D(60) * c.i) / D((next_month(c.d) - month_start(c.d)).days),
               "$0.025 per GB-Month of S3 Standard storage", qplaces="0.000001")]))
    lam_boost = lambda i: D(25) if t["lambda_spike"] <= i < t["lambda_spike"] + 3 else D(1)
    lam_req = lambda c: (D(3000000) * c.busy() * c.growth() * c.j()).quantize(D(1))
    R.append(Resource(
        "aws", "acme-prod", "AWS Lambda", "Compute", "Serverless Compute",
        "arn:aws:lambda:ap-northeast-1:210000000001:function:order-events-processor", "order-events-processor",
        "Function", None, prod_tags("orders"),
        [Meter("lambda-requests", "Request", "Requests", "1000000 Requests", D("0.20"), lam_req,
               "$0.20 per 1M requests", to_pricing=D("0.000001"), boost=lam_boost, anomaly="A1"),
         Meter("lambda-duration", "Lambda-GB-Second", "GB-Seconds", "GB-Seconds", D("0.0000166667"),
               lambda c: (lam_req(c) * D("0.1")).quantize(D(1)),
               "$0.0000166667 per GB-second", boost=lam_boost, anomaly="A1")]))
    R.append(Resource(
        "aws", "acme-prod", "Amazon Virtual Private Cloud", "Networking", "Network Infrastructure",
        "arn:aws:ec2:ap-northeast-1:210000000001:natgateway/nat-0c4d5e6f7a8b9c0d1", "nat-prod-1a", "NAT Gateway",
        "ap-northeast-1a", prod_tags("network", "platform"),
        [Meter("nat-hours", "NatGateway-Hours", "Hours", "Hours", D("0.062"), hours24, "$0.062 per NAT Gateway Hour"),
         Meter("nat-bytes", "NatGateway-Bytes", "GB", "GB", D("0.062"),
               lambda c: (D(150) * c.busy("0.7") * c.growth() * c.j(0.1)).quantize(D("0.0001")),
               "$0.062 per GB Data Processed by NAT Gateways")]))
    R.append(Resource(
        "aws", "acme-prod", "Elastic Load Balancing", "Networking", "Application Networking",
        "arn:aws:elasticloadbalancing:ap-northeast-1:210000000001:loadbalancer/app/alb-api-prod/50dc6c495c0c9188",
        "alb-api-prod", "Load Balancer", None, prod_tags("checkout-api"),
        [Meter("alb-hours", "LoadBalancerUsage", "Hours", "Hours", D("0.0243"), hours24,
               "$0.0243 per Application LoadBalancer-hour"),
         Meter("alb-lcu", "LCUUsage", "LCU-Hours", "LCU-Hours", D("0.008"),
               lambda c: (D(60) * c.busy() * c.growth() * c.j(0.1)).quantize(D("0.0001")),
               "$0.008 per LCU-hour")]))
    R.append(Resource(
        "aws", "acme-staging", "Elastic Load Balancing", "Networking", "Application Networking",
        "arn:aws:elasticloadbalancing:ap-northeast-1:210000000002:loadbalancer/app/alb-staging-old/7a1f3e9b2c4d5e6f",
        "alb-staging-old", "Load Balancer", None, {"team": "platform", "env": "staging", "app": "checkout-api"},
        [Meter("alb-hours", "LoadBalancerUsage", "Hours", "Hours", D("0.0243"), hours24,
               "$0.0243 per Application LoadBalancer-hour"),
         Meter("alb-lcu", "LCUUsage", "LCU-Hours", "LCU-Hours", D("0.008"),
               lambda c: (D("0.02") * c.j(0.5)).quantize(D("0.0001")), "$0.008 per LCU-hour")],
        waste=("A4", 0)))

    # ---------- Azure
    az = "/subscriptions/3f2b9c4e-1a7d-4c1b-9e2a-5d6f7a8b9c01/resourcegroups/rg-payments/providers"
    azdev = "/subscriptions/8a1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d02/resourcegroups/rg-data-dev/providers"
    for k in (1, 2):
        R.append(Resource(
            "azure", "payments-prod", "Virtual Machines", "Compute", "Virtual Machines",
            f"{az}/microsoft.compute/virtualmachines/vm-payments-0{k}", f"vm-payments-0{k}", "Virtual machine", None,
            prod_tags("payments-api"),
            [Meter("vm-d4sv5", "D4s v5", "Hours", "Hours", D("0.232"), hours24, "Virtual Machines Dsv5 Series D4s v5")]))
        R.append(Resource(
            "azure", "payments-prod", "Managed Disks", "Storage", "Block Storage",
            f"{az}/microsoft.compute/disks/disk-payments-0{k}", f"disk-payments-0{k}", "Disk", None,
            dict(prod_tags("payments-api"), vm=f"vm-payments-0{k}"),
            [Meter("disk-p10", "P10 LRS Disk", "Hours", "Hours", D("0.027"), hours24, "Premium SSD Managed Disks P10 LRS")]))
    R.append(Resource(
        "azure", "payments-prod", "Virtual Machines", "Compute", "Virtual Machines",
        f"{az}/microsoft.compute/virtualmachines/vm-legacy-01", "vm-legacy-01", "Virtual machine", None,
        prod_tags("legacy-settlement"),
        [Meter("vm-d2sv5", "D2s v5", "Hours", "Hours", D("0.116"), hours24, "Virtual Machines Dsv5 Series D2s v5")],
        last_day=t["legacy_vm_last"]))
    R.append(Resource(
        "azure", "payments-prod", "Managed Disks", "Storage", "Block Storage",
        f"{az}/microsoft.compute/disks/disk-legacy-01", "disk-legacy-01", "Disk", None,
        dict(prod_tags("legacy-settlement"), vm="vm-legacy-01"),
        [Meter("disk-p20", "P20 LRS Disk", "Hours", "Hours", D("0.0521"), hours24, "Premium SSD Managed Disks P20 LRS")],
        waste=("A5", t["legacy_vm_last"] + 1)))
    R.append(Resource(
        "azure", "payments-prod", "SQL Database", "Databases", "Relational Databases",
        f"{az}/microsoft.sql/servers/sql-payments/databases/sqldb-payments", "sqldb-payments", "SQL database", None,
        prod_tags("ledger"),
        [Meter("sql-s4", "S4 DTUs", "Hours", "Hours", D("0.4032"), hours24, "SQL Database Single Standard S4")]))
    R.append(Resource(
        "azure", "payments-prod", "Log Analytics", "Management and Governance", "Observability",
        f"{az}/microsoft.operationalinsights/workspaces/law-payments-prod", "law-payments-prod",
        "Log Analytics workspace", None, prod_tags("observability", "platform"),
        [Meter("la-ingest", "Analytics Logs Data Ingestion", "GB", "GB", D("3.45"),
               lambda c: (D(12) * c.busy("0.8") * c.growth() * c.j(0.08)).quantize(D("0.0001")),
               "Log Analytics Analytics Logs data ingestion per GB",
               boost=lambda i: D(6) if i >= t["logs_from"] else D(1), anomaly="A2")]))
    R.append(Resource(
        "azure", "data-dev", "Virtual Machines", "Compute", "Virtual Machines",
        f"{azdev}/microsoft.compute/virtualmachines/vm-dev-sandbox", "vm-dev-sandbox", "Virtual machine", None, None,
        [Meter("vm-d2sv5", "D2s v5", "Hours", "Hours", D("0.116"), hours24, "Virtual Machines Dsv5 Series D2s v5")]))
    R.append(Resource(
        "azure", "data-dev", "Storage Accounts", "Storage", "Object Storage",
        f"{azdev}/microsoft.storage/storageaccounts/stdevdatalake01", "stdevdatalake01", "Storage account", None, None,
        [Meter("blob-hot", "Hot LRS Data Stored", "GB-Months", "GB-Months", D("0.0196"),
               lambda c: D(3000) / D((next_month(c.d) - month_start(c.d)).days),
               "Blob Storage Hot LRS data stored", qplaces="0.000001")]))

    # ---------- Google Cloud
    gce = "//compute.googleapis.com/projects/acme-analytics-prod/zones/asia-northeast1-a/instances"
    for k in (1, 2):
        R.append(Resource(
            "gcp", "acme-analytics-prod", "Compute Engine", "Compute", "Virtual Machines",
            f"{gce}/etl-worker-{k}", f"etl-worker-{k}", "Instance", "asia-northeast1-a",
            {"team": "data", "env": "prod", "app": "etl", "cost-center": "cc-2201"},
            [Meter("gce-n2-std-4", "N2 Instance Core and Ram running in Tokyo", "Hours", "Hours", D("0.2508"),
                   hours24, "N2 Predefined Instance (n2-standard-4) running in Tokyo")]))
    bq_boost = lambda i: D(60) if t["bq_spike"] <= i < t["bq_spike"] + 2 else D(1)
    R.append(Resource(
        "gcp", "acme-analytics-prod", "BigQuery", "Databases", "Data Warehouses",
        "//bigquery.googleapis.com/projects/acme-analytics-prod/datasets/orders_dw", "orders_dw", "Dataset", None,
        {"team": "data", "env": "prod", "app": "reporting", "cost-center": "cc-2201"},
        [Meter("bq-analysis", "Analysis", "TiB", "TiB", D("6.25"),
               lambda c: (D("0.8") * c.busy("0.25") * c.growth() * c.j(0.15)).quantize(D("0.0001")),
               "BigQuery on-demand analysis in asia-northeast1", boost=bq_boost, anomaly="A3")]))
    R.append(Resource(
        "gcp", "acme-analytics-prod", "Cloud Storage", "Storage", "Object Storage",
        "//storage.googleapis.com/projects/_/buckets/acme-analytics-raw", "acme-analytics-raw", "Bucket", None,
        {"team": "data", "env": "prod", "app": "etl", "cost-center": "cc-2201"},
        [Meter("gcs-standard", "Standard Storage Tokyo", "GB-Months", "GB-Months", D("0.023"),
               lambda c: D(8000) / D((next_month(c.d) - month_start(c.d)).days),
               "Standard Storage Tokyo per GB-month", qplaces="0.000001")]))
    R.append(Resource(
        "gcp", "acme-ml-sandbox", "Compute Engine", "Compute", "Virtual Machines",
        "//compute.googleapis.com/projects/acme-ml-sandbox/zones/asia-northeast1-c/instances/gpu-notebook-tmp",
        "gpu-notebook-tmp", "Instance", "asia-northeast1-c", {"env": "sandbox", "created-by": "notebook-launcher"},
        [Meter("gce-a2-highgpu-1g", "A2 Instance with 1 NVIDIA A100 running in Tokyo", "Hours", "Hours", D("4.65"),
               hours24, "A2 High-GPU Instance (a2-highgpu-1g) running in Tokyo")],
        first_day=t["gpu_from"], waste=("A8", t["gpu_from"])))
    return R, t


# ---------------------------------------------------------------- row builders
def base_row(p: dict, d: date, sub: Optional[str]) -> dict:
    r = dict.fromkeys(COLUMNS)
    ms = month_start(d)
    r.update(
        BillingAccountId=p["billing_account_id"], BillingAccountName=p["billing_account_name"],
        BillingAccountType=p["billing_account_type"], BillingCurrency="USD", PricingCurrency="USD",
        BillingPeriodStart=ts(ms), BillingPeriodEnd=ts(next_month(d)),
        InvoiceId=f"{p['invoice_prefix']}{ms.strftime('%Y%m')}", InvoiceIssuerName=p["name"],
        ProviderName=p["name"], PublisherName=p["name"], RegionId=p["region"][0], RegionName=p["region"][1],
    )
    if sub:
        r.update(SubAccountId=p["subs"][sub], SubAccountName=sub, SubAccountType=p["sub_type"])
    return r


def set_prices(r: dict, list_price: D, contracted_price: D, pq: D, unit: str) -> None:
    r.update(
        ListUnitPrice=list_price, ContractedUnitPrice=contracted_price, PricingQuantity=pq, PricingUnit=unit,
        ListCost=list_price * pq, ContractedCost=contracted_price * pq,
        PricingCurrencyListUnitPrice=list_price, PricingCurrencyContractedUnitPrice=contracted_price,
    )


def generate(start: date, days: int, seed: int) -> tuple:
    resources, t = inventory(days)
    rows, excess, waste = [], {}, {}
    end = start + timedelta(days=days)

    for i in range(days):
        d = start + timedelta(days=i)
        ri_hours_used = D(0)
        for res in resources:
            if not (res.first_day <= i <= res.last_day):
                continue
            p = PROVIDERS[res.provider]
            for m in res.meters:
                ctx = Ctx(i, d, random.Random(f"{seed}|{res.rid}|{m.label}|{i}"))
                q_base = m.qty(ctx).quantize(D(m.qplaces))
                q = (q_base * (m.boost(i) if m.boost else D(1))).quantize(D(m.qplaces))
                pq = q * m.to_pricing
                contracted_price = (m.list_price * (1 - p["discount"])).normalize()
                sku, skup = sku_ids(res.provider, m.label)
                r = base_row(p, d, res.sub)
                r.update(
                    AvailabilityZone=res.az, ChargeCategory="Usage", ChargeFrequency="Usage-Based",
                    ChargeDescription=m.description, ChargePeriodStart=ts(d), ChargePeriodEnd=ts(d + timedelta(days=1)),
                    ConsumedQuantity=q, ConsumedUnit=m.consumed_unit, PricingCategory="Standard",
                    ResourceId=res.rid, ResourceName=res.name, ResourceType=res.rtype,
                    ServiceCategory=res.category, ServiceSubcategory=res.subcategory, ServiceName=res.service,
                    SkuId=sku, SkuPriceId=skup, SkuMeter=m.meter,
                    Tags=json.dumps(res.tags, sort_keys=True) if res.tags is not None else None,
                )
                set_prices(r, m.list_price, contracted_price, pq, m.pricing_unit)
                if res.ri_covered:
                    eff = RI_RATE * q
                    r.update(BilledCost=D(0), EffectiveCost=eff, PricingCategory="Committed",
                             CommitmentDiscountId=RI_ID, CommitmentDiscountName=RI_NAME,
                             CommitmentDiscountType="Reserved Instance", CommitmentDiscountCategory="Usage",
                             CommitmentDiscountStatus="Used", CommitmentDiscountQuantity=q,
                             CommitmentDiscountUnit="Hours")
                    ri_hours_used += q
                else:
                    r.update(BilledCost=r["ContractedCost"], EffectiveCost=r["ContractedCost"])
                r["PricingCurrencyEffectiveCost"] = r["EffectiveCost"]
                rows.append(r)

                if m.anomaly and q != q_base:
                    extra = contracted_price * (q - q_base) * m.to_pricing
                    excess[m.anomaly] = excess.get(m.anomaly, D(0)) + extra
                if res.waste and i >= res.waste[1]:
                    waste[res.waste[0]] = waste.get(res.waste[0], D(0)) + r["EffectiveCost"]

        # unused reserved-instance hours for the day
        unused = D(RI_COUNT * 24) - ri_hours_used
        if unused > 0:
            p = PROVIDERS["aws"]
            sku, skup = sku_ids("aws", "ri-m5.xlarge")
            r = base_row(p, d, "acme-prod")
            r.update(ChargeCategory="Usage", ChargeFrequency="Recurring", PricingCategory="Committed",
                     ChargeDescription="Unused Reserved Instance hours: m5.xlarge Linux",
                     ChargePeriodStart=ts(d), ChargePeriodEnd=ts(d + timedelta(days=1)),
                     ServiceCategory="Compute", ServiceSubcategory="Virtual Machines",
                     ServiceName="Amazon Elastic Compute Cloud", SkuId=sku, SkuPriceId=skup, SkuMeter="HeavyUsage:m5.xlarge",
                     CommitmentDiscountId=RI_ID, CommitmentDiscountName=RI_NAME,
                     CommitmentDiscountType="Reserved Instance", CommitmentDiscountCategory="Usage",
                     CommitmentDiscountStatus="Unused", CommitmentDiscountQuantity=unused,
                     CommitmentDiscountUnit="Hours", BilledCost=D(0))
            set_prices(r, RI_RATE, RI_RATE, unused, "Hours")
            r["EffectiveCost"] = r["PricingCurrencyEffectiveCost"] = r["ListCost"]
            rows.append(r)
            waste["A6"] = waste.get("A6", D(0)) + r["EffectiveCost"]

    # monthly reserved-instance fee, covering the days of each month inside the window
    m0 = month_start(start)
    while m0 < end:
        lo, hi = max(m0, start), min(next_month(m0), end)
        hours = D(RI_COUNT * 24 * (hi - lo).days)
        p = PROVIDERS["aws"]
        sku, skup = sku_ids("aws", "ri-m5.xlarge")
        r = base_row(p, m0, "acme-prod")
        r.update(ChargeCategory="Purchase", ChargeFrequency="Recurring", PricingCategory="Standard",
                 ChargeDescription=f"Reserved Instance fee: {RI_COUNT} x m5.xlarge Linux, 1 year, No Upfront",
                 ChargePeriodStart=ts(lo), ChargePeriodEnd=ts(hi),
                 ServiceCategory="Compute", ServiceSubcategory="Virtual Machines",
                 ServiceName="Amazon Elastic Compute Cloud", SkuId=sku, SkuPriceId=skup, SkuMeter="HeavyUsage:m5.xlarge",
                 CommitmentDiscountId=RI_ID, CommitmentDiscountName=RI_NAME, CommitmentDiscountType="Reserved Instance",
                 CommitmentDiscountCategory="Usage", CommitmentDiscountQuantity=hours, CommitmentDiscountUnit="Hours",
                 EffectiveCost=D(0), PricingCurrencyEffectiveCost=D(0))
        set_prices(r, RI_RATE, RI_RATE, hours, "Hours")
        r["BilledCost"] = r["ContractedCost"]
        rows.append(r)
        m0 = next_month(m0)

    rows.sort(key=lambda r: (r["ChargePeriodStart"], r["ProviderName"], r["ResourceId"] or "", r["SkuId"] or ""))
    untagged = D(0)
    untagged_resources = set()
    for r in rows:
        tags = json.loads(r["Tags"]) if r["Tags"] else {}
        if r["ResourceId"] and "team" not in tags:
            untagged += r["EffectiveCost"]
            untagged_resources.add(r["ResourceId"])
    waste["A7"] = untagged
    return rows, labels(start, t, days, excess, waste, untagged_resources)


# ---------------------------------------------------------------- answer key
def labels(start: date, t: dict, days: int, excess: dict, waste: dict, untagged_resources: set) -> list:
    day = lambda i: (start + timedelta(days=i)).isoformat()
    last = day(days - 1)
    usd = lambda x: float(round(x, 2))
    return [
        dict(id="A1", type="spend_spike", provider="AWS", sub_account="acme-prod", service="AWS Lambda",
             resource_ids=["arn:aws:lambda:ap-northeast-1:210000000001:function:order-events-processor"],
             start=day(t["lambda_spike"]), end=day(t["lambda_spike"] + 2), excess_cost_usd=usd(excess.get("A1", 0)),
             story="A retry loop re-queued failed order events, so invocations ran about 25x normal for 3 days.",
             signal="Daily cost per service far above its trailing median, then back to normal."),
        dict(id="A2", type="sustained_increase", provider="Microsoft", sub_account="payments-prod",
             service="Log Analytics",
             resource_ids=["/subscriptions/3f2b9c4e-1a7d-4c1b-9e2a-5d6f7a8b9c01/resourcegroups/rg-payments/providers/microsoft.operationalinsights/workspaces/law-payments-prod"],
             start=day(t["logs_from"]), end=last, excess_cost_usd=usd(excess.get("A2", 0)),
             story="Debug-level logging was enabled during an incident and never turned off; ingestion is about 6x.",
             signal="Recent average daily cost per service several times the earlier baseline, and it stays high."),
        dict(id="A3", type="spend_spike", provider="Google Cloud", sub_account="acme-analytics-prod", service="BigQuery",
             resource_ids=["//bigquery.googleapis.com/projects/acme-analytics-prod/datasets/orders_dw"],
             start=day(t["bq_spike"]), end=day(t["bq_spike"] + 1), excess_cost_usd=usd(excess.get("A3", 0)),
             story="A scheduled query lost its partition filter and scanned the full orders table every hour for 2 days.",
             signal="Daily cost per service far above its trailing median."),
        dict(id="A4", type="idle_resource", provider="AWS", sub_account="acme-staging", service="Elastic Load Balancing",
             resource_ids=["arn:aws:elasticloadbalancing:ap-northeast-1:210000000002:loadbalancer/app/alb-staging-old/7a1f3e9b2c4d5e6f"],
             start=day(0), end=last, excess_cost_usd=usd(waste.get("A4", 0)),
             story="An old staging load balancer kept running after its service moved; it serves almost no traffic.",
             signal="Hourly charges every day while the traffic meter (LCU-Hours) stays near zero."),
        dict(id="A5", type="orphaned_resource", provider="Microsoft", sub_account="payments-prod", service="Managed Disks",
             resource_ids=["/subscriptions/3f2b9c4e-1a7d-4c1b-9e2a-5d6f7a8b9c01/resourcegroups/rg-payments/providers/microsoft.compute/disks/disk-legacy-01"],
             start=day(t["legacy_vm_last"] + 1), end=last, excess_cost_usd=usd(waste.get("A5", 0)),
             story="vm-legacy-01 was deleted but its P20 disk was not, so the disk is billed with nothing attached.",
             signal="A disk keeps billing after the VM named in its 'vm' tag stops appearing. "
                    "(Real tools check attachment state through the cloud API; the tag stands in for that here.)"),
        dict(id="A6", type="underused_commitment", provider="AWS", sub_account="acme-prod",
             service="Amazon Elastic Compute Cloud", resource_ids=[RI_ID],
             start=day(t["ri_last"] + 1), end=last, excess_cost_usd=usd(waste.get("A6", 0)),
             story="api-3 and api-4 were retired, but the reserved instance still pays for 4 instances; half is unused.",
             signal="Rows with CommitmentDiscountStatus = 'Unused'; utilization per commitment drops to 50%."),
        dict(id="A7", type="untagged_spend", provider="Microsoft, Google Cloud", sub_account="data-dev, acme-ml-sandbox",
             service="several", resource_ids=sorted(untagged_resources), start=day(0), end=last,
             excess_cost_usd=usd(waste.get("A7", 0)),
             story="The data-dev subscription has no tags at all, and the sandbox GPU VM has no team tag.",
             signal="Resource-level spend where Tags is null or has no 'team' key. "
                    "The amount is unallocated spend, not waste."),
        dict(id="A8", type="forgotten_expensive_resource", provider="Google Cloud", sub_account="acme-ml-sandbox",
             service="Compute Engine",
             resource_ids=["//compute.googleapis.com/projects/acme-ml-sandbox/zones/asia-northeast1-c/instances/gpu-notebook-tmp"],
             start=day(t["gpu_from"]), end=last, excess_cost_usd=usd(waste.get("A8", 0)),
             story="An A100 notebook VM was started for an experiment and never shut down; it runs 24/7.",
             signal="A new resource with high daily cost, in a sandbox project, without an owner tag."),
    ]


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2026-07-01", help="first day (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, default=92, help="number of days (minimum 30)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="focus_mock_costandusage.csv")
    ap.add_argument("--labels", default="anomalies.json")
    ap.add_argument("--parquet", action="store_true", help="also write a .parquet file (needs pyarrow)")
    a = ap.parse_args()
    if a.days < 30:
        ap.error("--days must be at least 30 so every planted problem fits in the window")

    rows, answer_key = generate(date.fromisoformat(a.start), a.days, a.seed)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: num(v) for k, v in r.items()})
    with open(a.labels, "w") as f:
        json.dump(answer_key, f, indent=2)

    if a.parquet:
        import pyarrow as pa
        import pyarrow.csv as pacsv
        import pyarrow.parquet as pq
        pq.write_table(pacsv.read_csv(a.out), a.out.rsplit(".", 1)[0] + ".parquet")

    total = sum(r["EffectiveCost"] for r in rows)
    print(f"{len(rows):,} rows, {a.days} days, total EffectiveCost ${total:,.2f} -> {a.out}")
    for x in answer_key:
        print(f"  {x['id']} {x['type']:<29} {x['provider']:<22} {x['start']} .. {x['end']}  ${x['excess_cost_usd']:,.2f}")


if __name__ == "__main__":
    main()
