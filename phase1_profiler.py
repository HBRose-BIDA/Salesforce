"""
Phase 1 — Ingestion and Profiling
----------------------------------
Connects to Salesforce, discovers the schema for each target object,
pulls all records, saves a raw snapshot, then prints a scorecard showing:
  - Total record count per object
  - Field population rate (% not blank)
  - Field cardinality (how many distinct values exist per field)

READ-ONLY. Makes no changes to Salesforce.

Usage:
    python phase1_profiler.py
    python phase1_profiler.py --objects Account Contact Lead
    python phase1_profiler.py --objects Account --snapshot-dir snapshots
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceAuthenticationFailed


CONFIG_PATH = Path(__file__).with_name("config.json")

# Fields that are always useful anchors regardless of object
ANCHOR_FIELDS = {"Id", "Name", "CreatedDate", "LastModifiedDate", "OwnerId"}

# Default objects to profile if not specified on command line
DEFAULT_OBJECTS = ["Account", "Contact", "Lead"]

# Field types worth profiling for cardinality (classification/category fields)
CATEGORY_FIELD_TYPES = {"picklist", "multipicklist", "string", "textarea", "reference"}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect(config: Dict[str, Any]) -> Salesforce:
    domain = config.get("domain")
    if not domain:
        login_url = (config.get("login_url") or "").lower()
        domain = "test" if ("test.salesforce.com" in login_url or ".sandbox." in login_url) else "login"

    try:
        return Salesforce(
            username=config["username"],
            password=config["password"],
            security_token=config["security_token"],
            domain=domain,
            version=config.get("api_version"),
        )
    except SalesforceAuthenticationFailed as exc:
        raise SystemExit(f"Authentication failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------

def discover_schema(sf: Salesforce, object_name: str) -> List[Dict[str, Any]]:
    """Return field metadata list for the given object."""
    sf_object = getattr(sf, object_name, None)
    if sf_object is None:
        print(f"  [WARNING] Object '{object_name}' not found in this org. Skipping.")
        return []
    description = sf_object.describe()
    return description.get("fields", [])


def select_fields(fields_meta: List[Dict[str, Any]]) -> List[str]:
    """
    Choose fields to pull:
      - Always include anchor fields.
      - Include all picklist, classification, and short text fields.
      - Exclude long text areas and binary fields (too large to profile usefully).
    """
    excluded_types = {"base64", "encryptedstring", "anytype", "complexvalue"}
    selected = []
    for field in fields_meta:
        name = field["name"]
        ftype = field["type"]
        length = field.get("length") or 0

        if name in ANCHOR_FIELDS:
            selected.append(name)
            continue

        if ftype in excluded_types:
            continue

        # Skip very long text areas
        if ftype in ("textarea",) and length > 1000:
            continue

        selected.append(name)

    return selected


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_object(sf: Salesforce, object_name: str, fields: List[str]) -> List[Dict[str, Any]]:
    """Pull all records for the given object and field list."""
    field_list = ", ".join(fields)
    soql = f"SELECT {field_list} FROM {object_name}"
    response = sf.query_all(soql)
    records = response.get("records", [])
    for rec in records:
        rec.pop("attributes", None)
    return records


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def snapshot(records: List[Dict[str, Any]], object_name: str, run_id: str, snapshot_dir: Path) -> Path:
    """Save raw records to a timestamped JSON file."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", object_name)
    file_path = snapshot_dir / f"{safe_name}_{run_id}.json"
    with file_path.open("w", encoding="utf-8") as fh:
        json.dump({"object": object_name, "run_id": run_id, "record_count": len(records), "records": records}, fh, indent=2, default=str)
    return file_path


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

def profile_coverage(records: List[Dict[str, Any]], fields: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    For each field: count populated (non-null, non-blank) vs blank records.
    Returns dict keyed by field name.
    """
    total = len(records)
    coverage: Dict[str, Dict[str, Any]] = {}

    for field in fields:
        populated = 0
        for rec in records:
            value = rec.get(field)
            if value is not None and str(value).strip() != "":
                populated += 1
        pct = round(populated / total * 100, 1) if total > 0 else 0.0
        coverage[field] = {
            "populated": populated,
            "blank": total - populated,
            "total": total,
            "pct_populated": pct,
        }

    return coverage


def profile_cardinality(records: List[Dict[str, Any]], fields: List[str], fields_meta: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    For picklist and short text fields: count distinct values and list them.
    This reveals how many variants of a category exist.
    """
    meta_map = {f["name"]: f for f in fields_meta}
    cardinality: Dict[str, Dict[str, Any]] = {}

    for field in fields:
        meta = meta_map.get(field, {})
        ftype = meta.get("type", "")
        if ftype not in CATEGORY_FIELD_TYPES:
            continue

        counter: Counter = Counter()
        for rec in records:
            value = rec.get(field)
            if value is not None and str(value).strip() != "":
                counter[str(value).strip()] += 1

        if not counter:
            continue

        cardinality[field] = {
            "distinct_count": len(counter),
            "field_type": ftype,
            "top_values": counter.most_common(20),
        }

    return cardinality


# ---------------------------------------------------------------------------
# Scorecard output
# ---------------------------------------------------------------------------

class _Tee:
    """Writes to both stdout and a file simultaneously."""

    def __init__(self, file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = file_path.open("w", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        self._file.write(text)

    def flush(self) -> None:
        sys.stdout.flush()
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def print_scorecard(object_name: str, total: int, coverage: Dict[str, Dict[str, Any]], cardinality: Dict[str, Dict[str, Any]], out: Any = None) -> None:
    def p(text: str = "") -> None:
        line = text + "\n"
        if out:
            out.write(line)
        else:
            sys.stdout.write(line)

    p(f"\n{'=' * 60}")
    p(f"  OBJECT: {object_name}   ({total} records)")
    p(f"{'=' * 60}")

    # Coverage — show fields with < 100% population, sorted by pct ascending
    low_coverage = sorted(
        [(f, v) for f, v in coverage.items() if v["pct_populated"] < 100],
        key=lambda x: x[1]["pct_populated"]
    )

    print(f"\n  Field Coverage  ({len(low_coverage)} fields not 100% populated)")
    print(f"  {'Field':<45} {'Populated':>10}  {'Blank':>8}  {'% Full':>7}")
    print(f"  {'-'*45} {'-'*10}  {'-'*8}  {'-'*7}")
    for field, stats in low_coverage[:40]:
        print(f"  {field:<45} {stats['populated']:>10}  {stats['blank']:>8}  {stats['pct_populated']:>6.1f}%")

    # Cardinality — show fields with more than 1 distinct value
    multi_value_fields = sorted(
        [(f, v) for f, v in cardinality.items() if v["distinct_count"] > 1],
        key=lambda x: x[1]["distinct_count"],
        reverse=True,
    )

    print(f"\n  Field Cardinality  ({len(multi_value_fields)} fields with multiple distinct values)")
    print(f"  (High numbers on category fields signal inconsistency risk)")
    print()
    for field, stats in multi_value_fields[:30]:
        top = ", ".join(f'"{v}"({c})' for v, c in stats["top_values"][:5])
        print(f"  {field:<45} {stats['distinct_count']:>4} distinct  [{stats['field_type']}]")
        print(f"    top values: {top}")


def print_summary(results: List[Dict[str, Any]], out: Any = None) -> None:
    def p(text: str = "") -> None:
        line = text + "\n"
        if out:
            out.write(line)
        else:
            sys.stdout.write(line)

    p(f"\n{'=' * 60}")
    p("  PHASE 1 SUMMARY")
    p(f"{'=' * 60}")
    for r in results:
        snapshot_note = f"  snapshot -> {r['snapshot_path']}" if r.get("snapshot_path") else ""
        p(f"  {r['object']:<20} {r['total']:>6} records  |  {r['fields_pulled']} fields pulled{snapshot_note}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: Salesforce schema discovery and field profiling.")
    parser.add_argument(
        "--objects",
        nargs="+",
        default=DEFAULT_OBJECTS,
        help=f"Salesforce objects to profile. Default: {' '.join(DEFAULT_OBJECTS)}",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=str,
        default="",
        help="Directory to save raw record snapshots (optional).",
    )
    args = parser.parse_args()

    config_path = CONFIG_PATH
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)

    print("Connecting to Salesforce...")
    sf = connect(config)
    print(f"Connected as: {config['username']}\n")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir: Optional[Path] = Path(args.snapshot_dir) if args.snapshot_dir else Path("reports")
    report_path = snapshot_dir / f"phase1_scorecard_{run_id}.txt"
    tee = _Tee(report_path)
    summary_results: List[Dict[str, Any]] = []
    tee.write(f"Phase 1 Profiling Report\nRun ID: {run_id}\nOrg user: {config['username']}\nObjects: {', '.join(args.objects)}\n")

    for object_name in args.objects:
        print(f"Discovering schema for: {object_name}")
        fields_meta = discover_schema(sf, object_name)
        if not fields_meta:
            continue

        fields = select_fields(fields_meta)
        print(f"  {len(fields_meta)} total fields in schema, pulling {len(fields)} selected fields")

        records = fetch_object(sf, object_name, fields)
        print(f"  Fetched {len(records)} records")

        snap_path: Optional[Path] = None
        if snapshot_dir:
            snap_path = snapshot(records, object_name, run_id, snapshot_dir)
            print(f"  Snapshot saved: {snap_path}")

        coverage = profile_coverage(records, fields)
        cardinality = profile_cardinality(records, fields, fields_meta)
        print_scorecard(object_name, len(records), coverage, cardinality, out=tee)

        summary_results.append({
            "object": object_name,
            "total": len(records),
            "fields_pulled": len(fields),
            "snapshot_path": str(snap_path) if snap_path else None,
        })

    print_summary(summary_results, out=tee)
    tee.write(f"\nRun ID: {run_id}\n")
    tee.write("Phase 1 complete. No changes made to Salesforce.\n")
    tee.close()
    sys.stdout.write(f"\nReport saved: {report_path}\n")


if __name__ == "__main__":
    main()
