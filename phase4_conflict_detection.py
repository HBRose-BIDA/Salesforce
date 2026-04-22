"""
Phase 4 - Conflict Detection (Read-Only)

Consumes:
- Phase 3 cluster file (phase3_clusters_*.json)
- Phase 2 normalized files (normalized_*.json)

Produces:
1) phase4_conflicts_<run_id>.csv          - conflict queue
2) phase4_conflicts_<run_id>.json         - structured conflict payload
3) phase4_conflict_report_<run_id>.txt    - evidence summary

No Salesforce writes are performed.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_DIR = Path("reports")

FIELD_HINTS = (
    "type",
    "category",
    "segment",
    "classification",
    "tier",
    "status",
    "industry",
    "rating",
    "department",
    "title",
)

EXCLUDED_FIELDS = {
    "id",
    "name",
    "normalized_name",
    "createddate",
    "lastmodifieddate",
    "systemmodstamp",
}


def extract_timestamp_from_name(name: str) -> str:
    m = re.search(r"(\d{8}T\d{6}Z)", name)
    return m.group(1) if m else ""


def latest_file(pattern: str, folder: Path) -> Path:
    files = sorted(folder.glob(pattern))
    if not files:
        raise SystemExit(f"No files found for pattern {pattern} in {folder}")
    files = sorted(files, key=lambda p: extract_timestamp_from_name(p.name))
    return files[-1]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_record_index(normalized_files: List[Path]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for file in normalized_files:
        payload = load_json(file)
        obj = payload.get("object", "Unknown")
        for rec in payload.get("records", []):
            uid = f"{obj}:{rec.get('Id', '')}"
            index[uid] = rec
    return index


def discover_check_fields(records: List[Dict[str, Any]]) -> List[str]:
    field_counts = Counter()

    for rec in records:
        for key in rec.keys():
            kl = key.lower()
            if kl in EXCLUDED_FIELDS:
                continue
            if key.startswith("Normalized_"):
                continue
            if any(h in kl for h in FIELD_HINTS):
                field_counts[key] += 1

    # Fields that show up on at least two records in cluster are useful for conflict checks.
    return [f for f, c in field_counts.items() if c >= 2]


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def severity_score(
    distinct_values: int,
    member_count: int,
    cluster_confidence: str,
    field_name: str,
) -> Tuple[float, str]:
    conf_weight = {"high": 1.0, "medium": 0.8, "low": 0.6}.get(cluster_confidence.lower(), 0.6)
    spread = distinct_values / max(1, member_count)

    # Technical criticality by field type, not business semantics.
    fname = field_name.lower()
    criticality = 1.0
    if any(k in fname for k in ("type", "category", "segment", "classification", "tier")):
        criticality = 1.0
    elif any(k in fname for k in ("status", "industry", "rating")):
        criticality = 0.85
    elif any(k in fname for k in ("department", "title")):
        criticality = 0.70

    score = round(100 * conf_weight * spread * criticality, 1)
    label = "low"
    if score >= 70:
        label = "high"
    elif score >= 45:
        label = "medium"

    return score, label


def detect_conflicts(clusters: List[Dict[str, Any]], record_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []

    for cluster in clusters:
        members = cluster.get("members", [])
        if len(members) < 2:
            continue

        member_records = []
        for m in members:
            uid = m.get("uid", "")
            if uid in record_index:
                member_records.append((uid, record_index[uid]))

        if len(member_records) < 2:
            continue

        check_fields = discover_check_fields([r for _, r in member_records])

        for field in check_fields:
            values_to_members: Dict[str, List[str]] = defaultdict(list)
            for uid, rec in member_records:
                v = normalize_value(rec.get(field))
                if v:
                    values_to_members[v].append(uid)

            # conflict exists when 2+ distinct non-empty values are present.
            if len(values_to_members) < 2:
                continue

            distinct_values = sorted(values_to_members.keys())
            score, severity = severity_score(
                distinct_values=len(distinct_values),
                member_count=len(member_records),
                cluster_confidence=cluster.get("confidence", "low"),
                field_name=field,
            )

            evidence_parts = []
            for val, uids in values_to_members.items():
                evidence_parts.append(f"{val} => {','.join(uids)}")

            conflicts.append(
                {
                    "cluster_id": cluster.get("cluster_id", ""),
                    "cluster_confidence": cluster.get("confidence", ""),
                    "cluster_score": cluster.get("cluster_score", 0),
                    "member_count": len(member_records),
                    "field": field,
                    "distinct_value_count": len(distinct_values),
                    "distinct_values": " | ".join(distinct_values),
                    "severity_score": score,
                    "severity": severity,
                    "evidence": " || ".join(evidence_parts),
                }
            )

    conflicts.sort(key=lambda x: (x["severity_score"], x["distinct_value_count"]), reverse=True)
    return conflicts


def write_conflicts_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "cluster_id",
        "cluster_confidence",
        "cluster_score",
        "member_count",
        "field",
        "distinct_value_count",
        "distinct_values",
        "severity_score",
        "severity",
        "evidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def write_report(
    path: Path,
    run_id: str,
    cluster_file: Path,
    normalized_files: List[Path],
    cluster_count: int,
    conflict_rows: List[Dict[str, Any]],
    outputs: List[Path],
) -> None:
    by_severity = Counter(r["severity"] for r in conflict_rows)
    by_field = Counter(r["field"] for r in conflict_rows)

    with path.open("w", encoding="utf-8") as fh:
        fh.write("Phase 4 Conflict Detection Report\n")
        fh.write(f"Run ID: {run_id}\n")
        fh.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        fh.write("Inputs\n")
        fh.write(f"- Cluster file: {cluster_file}\n")
        for nf in normalized_files:
            fh.write(f"- Normalized file: {nf}\n")

        fh.write("\nSummary\n")
        fh.write(f"- Cluster count: {cluster_count}\n")
        fh.write(f"- Conflict count: {len(conflict_rows)}\n")

        fh.write("\nConflicts by Severity\n")
        for sev in ("high", "medium", "low"):
            fh.write(f"- {sev}: {by_severity.get(sev, 0)}\n")

        fh.write("\nTop Conflict Fields\n")
        for field, count in by_field.most_common(20):
            fh.write(f"- {field}: {count}\n")

        fh.write("\nTop Conflicts\n")
        for row in conflict_rows[:30]:
            fh.write(
                f"- {row['cluster_id']} | field={row['field']} | severity={row['severity']} ({row['severity_score']}) | values={row['distinct_values']}\n"
            )

        fh.write("\nOutput Files\n")
        for out in outputs:
            fh.write(f"- {out}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 conflict detection from entity clusters.")
    parser.add_argument("--dir", type=str, default=str(DEFAULT_DIR), help="Directory containing phase files.")
    parser.add_argument("--clusters", type=str, default="", help="Optional explicit phase3_clusters JSON file path.")
    parser.add_argument("--run-id", type=str, default="", help="Optional run ID override.")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        raise SystemExit(f"Directory not found: {folder}")

    cluster_path = Path(args.clusters) if args.clusters else latest_file("phase3_clusters_*.json", folder)
    normalized_files = sorted(folder.glob("normalized_*.json"))
    if not normalized_files:
        raise SystemExit(f"No normalized_*.json files found in {folder}")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    cluster_payload = load_json(cluster_path)
    clusters = cluster_payload.get("clusters", [])

    record_index = load_record_index(normalized_files)
    conflicts = detect_conflicts(clusters, record_index)

    csv_path = folder / f"phase4_conflicts_{run_id}.csv"
    json_path = folder / f"phase4_conflicts_{run_id}.json"
    txt_path = folder / f"phase4_conflict_report_{run_id}.txt"

    write_conflicts_csv(csv_path, conflicts)
    write_json(
        json_path,
        {
            "run_id": run_id,
            "cluster_source": str(cluster_path),
            "cluster_count": len(clusters),
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
        },
    )
    write_report(
        txt_path,
        run_id,
        cluster_path,
        normalized_files,
        len(clusters),
        conflicts,
        [csv_path, json_path, txt_path],
    )

    print("Phase 4 complete.")
    print(f"- Cluster source: {cluster_path}")
    print(f"- Clusters processed: {len(clusters)}")
    print(f"- Conflicts detected: {len(conflicts)}")
    print(f"- Conflict queue CSV: {csv_path}")
    print(f"- Conflict payload JSON: {json_path}")
    print(f"- Evidence report: {txt_path}")
    print("- No Salesforce data was modified.")


if __name__ == "__main__":
    main()
