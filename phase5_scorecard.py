"""
Phase 5 - Scorecard and Trend Reporting (Read-Only)

Consumes Phase 1-4 artifacts in ./reports and produces:
1) phase5_scorecard_<run_id>.txt
2) phase5_scorecard_<run_id>.json
3) phase5_trend_<run_id>.csv

No Salesforce writes are performed.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_DIR = Path("reports")


def extract_timestamp(name: str) -> str:
    match = re.search(r"(\d{8}T\d{6}Z)", name)
    return match.group(1) if match else ""


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def parse_phase1_report(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    run_id = extract_timestamp(path.name)

    object_counts: Dict[str, int] = {}
    object_fields: Dict[str, int] = {}

    # Example: Account 13 records | 69 fields pulled
    for line in text.splitlines():
        m = re.search(r"^\s*(\w+)\s+(\d+)\s+records\s+\|\s+(\d+)\s+fields pulled", line)
        if m:
            obj = m.group(1)
            object_counts[obj] = safe_int(m.group(2))
            object_fields[obj] = safe_int(m.group(3))

    total_records = sum(object_counts.values())
    avg_fields = round(sum(object_fields.values()) / len(object_fields), 2) if object_fields else 0.0

    return {
        "phase": "phase1",
        "run_id": run_id,
        "source": str(path),
        "object_counts": object_counts,
        "object_fields": object_fields,
        "total_records": total_records,
        "avg_fields_pulled": avg_fields,
    }


def parse_phase2_report(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    run_id = extract_timestamp(path.name)

    total_changes = 0
    m = re.search(r"Total changed values:\s*(\d+)", text)
    if m:
        total_changes = safe_int(m.group(1))

    by_object: Dict[str, int] = {}
    in_section = False
    for line in text.splitlines():
        if line.strip() == "Changes by Object":
            in_section = True
            continue
        if in_section:
            if not line.strip():
                break
            m2 = re.search(r"^-\s*(.+?):\s*(\d+)\s*$", line.strip())
            if m2:
                by_object[m2.group(1)] = safe_int(m2.group(2))

    return {
        "phase": "phase2",
        "run_id": run_id,
        "source": str(path),
        "total_changed_values": total_changes,
        "changes_by_object": by_object,
    }


def parse_phase3_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_id = payload.get("run_id") or extract_timestamp(path.name)

    clusters = payload.get("clusters", [])
    confidence_counts: Dict[str, int] = defaultdict(int)
    for c in clusters:
        confidence_counts[str(c.get("confidence", "unknown"))] += 1

    return {
        "phase": "phase3",
        "run_id": run_id,
        "source": str(path),
        "record_count": safe_int(payload.get("record_count")),
        "pair_count": safe_int(payload.get("pair_count")),
        "cluster_count": safe_int(payload.get("cluster_count")),
        "clusters_by_confidence": dict(confidence_counts),
    }


def parse_phase4_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_id = payload.get("run_id") or extract_timestamp(path.name)

    conflicts = payload.get("conflicts", [])
    by_severity: Dict[str, int] = defaultdict(int)
    for c in conflicts:
        by_severity[str(c.get("severity", "unknown"))] += 1

    return {
        "phase": "phase4",
        "run_id": run_id,
        "source": str(path),
        "cluster_count": safe_int(payload.get("cluster_count")),
        "conflict_count": safe_int(payload.get("conflict_count")),
        "conflicts_by_severity": dict(by_severity),
    }


def latest_metric(rows: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    candidates = [r for r in rows if key in r]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r.get("run_id", ""))[-1]


def build_kpis(phase1: List[Dict[str, Any]], phase2: List[Dict[str, Any]], phase3: List[Dict[str, Any]], phase4: List[Dict[str, Any]]) -> Dict[str, Any]:
    latest_p1 = sorted(phase1, key=lambda x: x.get("run_id", ""))[-1] if phase1 else None
    latest_p2 = sorted(phase2, key=lambda x: x.get("run_id", ""))[-1] if phase2 else None
    latest_p3 = sorted(phase3, key=lambda x: x.get("run_id", ""))[-1] if phase3 else None
    latest_p4 = sorted(phase4, key=lambda x: x.get("run_id", ""))[-1] if phase4 else None

    total_records = safe_int(latest_p1.get("total_records")) if latest_p1 else 0
    changed_values = safe_int(latest_p2.get("total_changed_values")) if latest_p2 else 0
    pair_count = safe_int(latest_p3.get("pair_count")) if latest_p3 else 0
    cluster_count = safe_int(latest_p3.get("cluster_count")) if latest_p3 else 0
    conflict_count = safe_int(latest_p4.get("conflict_count")) if latest_p4 else 0

    change_rate = round((changed_values / total_records) * 100, 2) if total_records else 0.0
    pair_rate = round((pair_count / total_records) * 100, 2) if total_records else 0.0
    cluster_rate = round((cluster_count / total_records) * 100, 2) if total_records else 0.0
    conflict_rate = round((conflict_count / max(1, cluster_count)) * 100, 2) if cluster_count else 0.0

    return {
        "latest_phase_runs": {
            "phase1": latest_p1.get("run_id") if latest_p1 else None,
            "phase2": latest_p2.get("run_id") if latest_p2 else None,
            "phase3": latest_p3.get("run_id") if latest_p3 else None,
            "phase4": latest_p4.get("run_id") if latest_p4 else None,
        },
        "kpis": {
            "total_records_profiled": total_records,
            "normalized_value_changes": changed_values,
            "candidate_pair_count": pair_count,
            "cluster_count": cluster_count,
            "conflict_count": conflict_count,
            "normalization_change_rate_pct": change_rate,
            "candidate_pair_rate_pct": pair_rate,
            "cluster_rate_pct": cluster_rate,
            "conflict_per_cluster_rate_pct": conflict_rate,
        },
        "pipeline_health": {
            "phase1_ready": bool(latest_p1),
            "phase2_ready": bool(latest_p2),
            "phase3_ready": bool(latest_p3),
            "phase4_ready": bool(latest_p4),
            "overall_ready": bool(latest_p1 and latest_p2 and latest_p3 and latest_p4),
        },
    }


def flatten_trend_rows(phase_name: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    trend: List[Dict[str, Any]] = []
    for row in sorted(rows, key=lambda x: x.get("run_id", "")):
        base = {
            "phase": phase_name,
            "run_id": row.get("run_id", ""),
            "source": row.get("source", ""),
        }

        if phase_name == "phase1":
            trend.append({**base, "metric": "total_records", "value": row.get("total_records", 0)})
            trend.append({**base, "metric": "avg_fields_pulled", "value": row.get("avg_fields_pulled", 0)})
        elif phase_name == "phase2":
            trend.append({**base, "metric": "total_changed_values", "value": row.get("total_changed_values", 0)})
        elif phase_name == "phase3":
            trend.append({**base, "metric": "record_count", "value": row.get("record_count", 0)})
            trend.append({**base, "metric": "pair_count", "value": row.get("pair_count", 0)})
            trend.append({**base, "metric": "cluster_count", "value": row.get("cluster_count", 0)})
        elif phase_name == "phase4":
            trend.append({**base, "metric": "cluster_count", "value": row.get("cluster_count", 0)})
            trend.append({**base, "metric": "conflict_count", "value": row.get("conflict_count", 0)})

    return trend


def write_trend_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["phase", "run_id", "metric", "value", "source"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def write_scorecard_txt(path: Path, run_id: str, payload: Dict[str, Any], trend_rows: List[Dict[str, Any]]) -> None:
    latest = payload["latest"]
    k = payload["summary"]["kpis"]
    h = payload["summary"]["pipeline_health"]

    with path.open("w", encoding="utf-8") as fh:
        fh.write("Phase 5 Scorecard and Trends\n")
        fh.write(f"Run ID: {run_id}\n")
        fh.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        fh.write("Latest Phase Runs\n")
        for p, rid in payload["summary"]["latest_phase_runs"].items():
            fh.write(f"- {p}: {rid}\n")

        fh.write("\nKPI Snapshot\n")
        fh.write(f"- Total records profiled: {k['total_records_profiled']}\n")
        fh.write(f"- Normalized value changes: {k['normalized_value_changes']}\n")
        fh.write(f"- Candidate pairs: {k['candidate_pair_count']}\n")
        fh.write(f"- Clusters: {k['cluster_count']}\n")
        fh.write(f"- Conflicts: {k['conflict_count']}\n")
        fh.write(f"- Normalization change rate %: {k['normalization_change_rate_pct']}\n")
        fh.write(f"- Candidate pair rate %: {k['candidate_pair_rate_pct']}\n")
        fh.write(f"- Cluster rate %: {k['cluster_rate_pct']}\n")
        fh.write(f"- Conflict per cluster rate %: {k['conflict_per_cluster_rate_pct']}\n")

        fh.write("\nPipeline Health\n")
        fh.write(f"- Phase 1 ready: {h['phase1_ready']}\n")
        fh.write(f"- Phase 2 ready: {h['phase2_ready']}\n")
        fh.write(f"- Phase 3 ready: {h['phase3_ready']}\n")
        fh.write(f"- Phase 4 ready: {h['phase4_ready']}\n")
        fh.write(f"- Overall ready: {h['overall_ready']}\n")

        fh.write("\nLatest Artifact Sources\n")
        for phase_name, row in latest.items():
            if row:
                fh.write(f"- {phase_name}: {row.get('source')}\n")

        fh.write("\nTrend Rows\n")
        fh.write(f"- Total rows: {len(trend_rows)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 scorecard and trend aggregator.")
    parser.add_argument("--dir", type=str, default=str(DEFAULT_DIR), help="Directory containing phase artifacts.")
    parser.add_argument("--run-id", type=str, default="", help="Optional run ID override.")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        raise SystemExit(f"Directory not found: {folder}")

    p1_files = sorted(folder.glob("phase1_scorecard_*.txt"), key=lambda p: extract_timestamp(p.name))
    p2_files = sorted(folder.glob("phase2_normalization_report_*.txt"), key=lambda p: extract_timestamp(p.name))
    p3_files = sorted(folder.glob("phase3_clusters_*.json"), key=lambda p: extract_timestamp(p.name))
    p4_files = sorted(folder.glob("phase4_conflicts_*.json"), key=lambda p: extract_timestamp(p.name))

    phase1 = [parse_phase1_report(p) for p in p1_files]
    phase2 = [parse_phase2_report(p) for p in p2_files]
    phase3 = [parse_phase3_json(p) for p in p3_files]
    phase4 = [parse_phase4_json(p) for p in p4_files]

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    latest = {
        "phase1": phase1[-1] if phase1 else None,
        "phase2": phase2[-1] if phase2 else None,
        "phase3": phase3[-1] if phase3 else None,
        "phase4": phase4[-1] if phase4 else None,
    }

    summary = build_kpis(phase1, phase2, phase3, phase4)

    trend_rows = []
    trend_rows.extend(flatten_trend_rows("phase1", phase1))
    trend_rows.extend(flatten_trend_rows("phase2", phase2))
    trend_rows.extend(flatten_trend_rows("phase3", phase3))
    trend_rows.extend(flatten_trend_rows("phase4", phase4))
    trend_rows = sorted(trend_rows, key=lambda r: (r["run_id"], r["phase"], r["metric"]))

    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest": latest,
        "summary": summary,
        "artifact_counts": {
            "phase1_runs": len(phase1),
            "phase2_runs": len(phase2),
            "phase3_runs": len(phase3),
            "phase4_runs": len(phase4),
        },
    }

    txt_path = folder / f"phase5_scorecard_{run_id}.txt"
    json_path = folder / f"phase5_scorecard_{run_id}.json"
    csv_path = folder / f"phase5_trend_{run_id}.csv"

    write_scorecard_txt(txt_path, run_id, payload, trend_rows)
    write_json(json_path, payload)
    write_trend_csv(csv_path, trend_rows)

    print("Phase 5 complete.")
    print(f"- Phase 1 runs found: {len(phase1)}")
    print(f"- Phase 2 runs found: {len(phase2)}")
    print(f"- Phase 3 runs found: {len(phase3)}")
    print(f"- Phase 4 runs found: {len(phase4)}")
    print(f"- Scorecard TXT: {txt_path}")
    print(f"- Scorecard JSON: {json_path}")
    print(f"- Trend CSV: {csv_path}")


if __name__ == "__main__":
    main()
