"""
Phase 2 - Standardization / Normalization (Read-Only)

Consumes Phase 1 snapshot JSON files from ./reports and produces:
1) normalized_<Object>_<run_id>.json (raw records + normalized fields)
2) phase2_normalization_report_<run_id>.txt (scorecard/evidence)
3) phase2_changes_<run_id>.csv (record-level before/after evidence)

This script does not write back to Salesforce.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_INPUT_DIR = Path("reports")
DEFAULT_OUTPUT_DIR = Path("reports")

PERSON_OBJECTS = {"Contact", "Lead"}

# Company suffixes/noise words that often create false differences.
COMPANY_STOP_WORDS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "plc",
    "gmbh",
    "sa",
    "ag",
    "the",
}

NAME_PREFIXES = {"mr", "mrs", "ms", "dr", "prof"}
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

CATEGORY_FIELD_HINTS = (
    "category",
    "segment",
    "classification",
    "type",
    "tier",
)


def read_snapshot(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def detect_snapshot_files(input_dir: Path) -> List[Path]:
    files = sorted(input_dir.glob("*.json"))
    snapshots = []
    for file in files:
        if file.name.startswith("normalized_"):
            continue
        if file.name.startswith("phase"):
            continue
        snapshots.append(file)
    return snapshots


def canonical_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_company_name(name: str) -> str:
    text = canonical_whitespace(name).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = canonical_whitespace(text)

    parts = [p for p in text.split(" ") if p and p not in COMPANY_STOP_WORDS]
    return " ".join(parts).title()


def normalize_person_name(first_name: str, last_name: str) -> Tuple[str, str, str]:
    fn = canonical_whitespace(first_name).lower()
    ln = canonical_whitespace(last_name).lower()

    fn_parts = [p for p in re.sub(r"[^a-z0-9\s]", " ", fn).split() if p]
    ln_parts = [p for p in re.sub(r"[^a-z0-9\s]", " ", ln).split() if p]

    fn_parts = [p for p in fn_parts if p not in NAME_PREFIXES]
    ln_parts = [p for p in ln_parts if p not in NAME_SUFFIXES]

    norm_first = " ".join(fn_parts).title()
    norm_last = " ".join(ln_parts).title()
    norm_full = canonical_whitespace(f"{norm_first} {norm_last}")
    return norm_first, norm_last, norm_full


def normalize_category_value(value: Any, mapping: Dict[str, str]) -> str:
    raw = canonical_whitespace(str(value or ""))
    key = raw.lower()
    if key in mapping:
        return mapping[key]

    # Default canonicalization if no explicit mapping exists.
    key = key.replace("_", " ").replace("-", " ")
    key = canonical_whitespace(key)
    return key.title()


def default_category_mapping() -> Dict[str, str]:
    # Extend over time with org-specific legacy values.
    return {
        "small business": "SMB",
        "smb": "SMB",
        "smallbiz": "SMB",
        "mid market": "Mid-Market",
        "mid-market": "Mid-Market",
        "enterprise": "Enterprise",
        "strategic": "Strategic",
        "unknown": "Unknown",
        "n/a": "Unknown",
        "na": "Unknown",
    }


def discover_category_fields(records: List[Dict[str, Any]]) -> List[str]:
    if not records:
        return []

    sample_keys = records[0].keys()
    fields = []
    for key in sample_keys:
        k = key.lower()
        if any(hint in k for hint in CATEGORY_FIELD_HINTS):
            fields.append(key)
    return fields


def normalize_record(
    obj_name: str,
    record: Dict[str, Any],
    category_fields: List[str],
    category_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    out = dict(record)
    changes: List[Dict[str, str]] = []
    record_id = str(record.get("Id") or "")

    if obj_name in PERSON_OBJECTS:
        first = str(record.get("FirstName") or "")
        last = str(record.get("LastName") or "")
        n_first, n_last, n_full = normalize_person_name(first, last)

        out["Normalized_FirstName"] = n_first
        out["Normalized_LastName"] = n_last
        out["Normalized_Name"] = n_full

        if canonical_whitespace(first) != canonical_whitespace(n_first):
            changes.append(
                {
                    "object": obj_name,
                    "record_id": record_id,
                    "field": "FirstName",
                    "old_value": first,
                    "new_value": n_first,
                    "reason": "person_name_normalization",
                }
            )
        if canonical_whitespace(last) != canonical_whitespace(n_last):
            changes.append(
                {
                    "object": obj_name,
                    "record_id": record_id,
                    "field": "LastName",
                    "old_value": last,
                    "new_value": n_last,
                    "reason": "person_name_normalization",
                }
            )
    else:
        name = str(record.get("Name") or "")
        n_name = normalize_company_name(name)
        out["Normalized_Name"] = n_name

        if canonical_whitespace(name) != canonical_whitespace(n_name):
            changes.append(
                {
                    "object": obj_name,
                    "record_id": record_id,
                    "field": "Name",
                    "old_value": name,
                    "new_value": n_name,
                    "reason": "company_name_normalization",
                }
            )

    for field in category_fields:
        raw = record.get(field)
        if raw is None or str(raw).strip() == "":
            continue

        normalized = normalize_category_value(raw, category_map)
        output_field = f"Normalized_{field}"
        out[output_field] = normalized

        if canonical_whitespace(str(raw)) != canonical_whitespace(normalized):
            changes.append(
                {
                    "object": obj_name,
                    "record_id": record_id,
                    "field": field,
                    "old_value": str(raw),
                    "new_value": normalized,
                    "reason": "category_normalization",
                }
            )

    return out, changes


def build_normalization_report(changes: List[Dict[str, str]]) -> Dict[str, Any]:
    by_object = Counter()
    by_field = Counter()
    by_reason = Counter()
    mapping_counter = Counter()

    for c in changes:
        by_object[c["object"]] += 1
        by_field[f"{c['object']}.{c['field']}"] += 1
        by_reason[c["reason"]] += 1
        mapping_counter[f"{c['field']}: {c['old_value']} -> {c['new_value']}"] += 1

    return {
        "total_changes": len(changes),
        "changes_by_object": dict(by_object),
        "changes_by_field": dict(by_field),
        "changes_by_reason": dict(by_reason),
        "top_mappings": mapping_counter.most_common(50),
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def write_changes_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fields = ["object", "record_id", "field", "old_value", "new_value", "reason"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_report_text(path: Path, run_id: str, report: Dict[str, Any], outputs: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("Phase 2 Normalization Report\n")
        fh.write(f"Run ID: {run_id}\n")
        fh.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        fh.write(f"Total changed values: {report['total_changes']}\n\n")

        fh.write("Changes by Object\n")
        for obj, count in sorted(report["changes_by_object"].items()):
            fh.write(f"- {obj}: {count}\n")

        fh.write("\nChanges by Field\n")
        for field, count in sorted(report["changes_by_field"].items(), key=lambda x: x[1], reverse=True):
            fh.write(f"- {field}: {count}\n")

        fh.write("\nChanges by Reason\n")
        for reason, count in sorted(report["changes_by_reason"].items(), key=lambda x: x[1], reverse=True):
            fh.write(f"- {reason}: {count}\n")

        fh.write("\nTop Value Mappings\n")
        for mapping, count in report["top_mappings"]:
            fh.write(f"- {mapping} (x{count})\n")

        fh.write("\nOutput Files\n")
        for out in outputs:
            fh.write(f"- {out}\n")


def process_snapshot(snapshot_path: Path, run_id: str, output_dir: Path, category_map: Dict[str, str]) -> Tuple[List[Dict[str, str]], str]:
    payload = read_snapshot(snapshot_path)
    object_name = str(payload.get("object") or "Unknown")
    records = payload.get("records") or []

    category_fields = discover_category_fields(records)
    normalized_records: List[Dict[str, Any]] = []
    all_changes: List[Dict[str, str]] = []

    for record in records:
        normalized_record, changes = normalize_record(object_name, record, category_fields, category_map)
        normalized_records.append(normalized_record)
        all_changes.extend(changes)

    output_payload = {
        "object": object_name,
        "source_file": str(snapshot_path),
        "run_id": run_id,
        "record_count": len(records),
        "category_fields_detected": category_fields,
        "records": normalized_records,
    }

    output_file = output_dir / f"normalized_{object_name}_{run_id}.json"
    write_json(output_file, output_payload)
    return all_changes, str(output_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 normalization for Phase 1 Salesforce snapshots.")
    parser.add_argument("--input-dir", type=str, default=str(DEFAULT_INPUT_DIR), help="Directory containing Phase 1 snapshot JSON files.")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Directory for normalized outputs and reports.")
    parser.add_argument("--run-id", type=str, default="", help="Optional run ID. Defaults to UTC timestamp.")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir}")

    snapshots = detect_snapshot_files(input_dir)
    if not snapshots:
        raise SystemExit(f"No snapshot JSON files found in: {input_dir}")

    category_map = default_category_mapping()

    combined_changes: List[Dict[str, str]] = []
    output_files: List[str] = []

    print(f"Phase 2 starting with {len(snapshots)} snapshot files")
    for snapshot in snapshots:
        print(f"- Processing {snapshot.name}")
        changes, out_file = process_snapshot(snapshot, run_id, output_dir, category_map)
        combined_changes.extend(changes)
        output_files.append(out_file)

    report = build_normalization_report(combined_changes)

    csv_path = output_dir / f"phase2_changes_{run_id}.csv"
    txt_path = output_dir / f"phase2_normalization_report_{run_id}.txt"

    write_changes_csv(csv_path, combined_changes)
    write_report_text(txt_path, run_id, report, output_files + [str(csv_path)])

    print(f"\nNormalization complete.")
    print(f"- Total changed values: {report['total_changes']}")
    print(f"- Evidence report: {txt_path}")
    print(f"- Change log CSV: {csv_path}")
    print("- No Salesforce data was modified.")


if __name__ == "__main__":
    main()
