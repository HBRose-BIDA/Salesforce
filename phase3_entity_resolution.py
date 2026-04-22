"""
Phase 3 - Entity Resolution (Read-Only)

Consumes normalized Phase 2 JSON files from ./reports and produces:
1) phase3_candidate_pairs_<run_id>.csv   - deterministic and fuzzy match candidates
2) phase3_clusters_<run_id>.json         - resolved clusters with confidence
3) phase3_resolution_report_<run_id>.txt - run summary/evidence

No Salesforce writes are performed.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import difflib


DEFAULT_INPUT_DIR = Path("reports")
DEFAULT_OUTPUT_DIR = Path("reports")


def detect_normalized_files(input_dir: Path) -> List[Path]:
    return sorted(input_dir.glob("normalized_*.json"))


def canonical_ws(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def digits_only(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def email_domain(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    return email.split("@", 1)[1]


def website_domain(url: str) -> str:
    text = (url or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/", 1)[0]
    return text


def normalize_for_similarity(name: str) -> str:
    text = canonical_ws(name).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return canonical_ws(text)


def token_set(text: str) -> Set[str]:
    return {t for t in normalize_for_similarity(text).split(" ") if t}


def soundex(value: str) -> str:
    """Simple Soundex for fuzzy phonetic matching."""
    s = re.sub(r"[^a-zA-Z]", "", (value or "").upper())
    if not s:
        return ""

    first = s[0]
    mapping = {
        "B": "1", "F": "1", "P": "1", "V": "1",
        "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
        "D": "3", "T": "3",
        "L": "4",
        "M": "5", "N": "5",
        "R": "6",
    }

    encoded = []
    prev = ""
    for ch in s[1:]:
        code = mapping.get(ch, "")
        if code != prev:
            encoded.append(code)
        if code:
            prev = code

    digits = "".join(encoded)
    digits = (digits + "000")[:3]
    return first + digits


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union else 0.0


def load_records(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    obj = payload.get("object", "Unknown")

    out: List[Dict[str, Any]] = []
    for rec in payload.get("records", []):
        norm_name = rec.get("Normalized_Name") or rec.get("Name") or ""
        email = rec.get("Email") or ""
        phone = rec.get("Phone") or rec.get("MobilePhone") or ""
        website = rec.get("Website") or ""

        # Separate person and company resolution streams.
        entity_type = "person" if obj in {"Contact", "Lead"} else "company"

        out.append(
            {
                "uid": f"{obj}:{rec.get('Id', '')}",
                "object": obj,
                "id": rec.get("Id", ""),
                "entity_type": entity_type,
                "name": rec.get("Name", ""),
                "normalized_name": str(norm_name),
                "email": str(email),
                "email_domain": email_domain(str(email)),
                "website_domain": website_domain(str(website)),
                "phone_digits": digits_only(str(phone)),
                "account_number": str(rec.get("AccountNumber") or ""),
                "account_id": str(rec.get("AccountId") or ""),
                "raw": rec,
            }
        )
    return out


def deterministic_pairs(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for r in records:
        et = r["entity_type"]
        # Strong deterministic keys only.
        if r["email"]:
            index[(et, "email", r["email"].lower())].append(r)
        if et == "company" and r["account_number"]:
            index[(et, "account_number", r["account_number"])].append(r)
        if et == "company" and r["website_domain"] and r["normalized_name"]:
            combo = f"{r['website_domain']}|{normalize_for_similarity(r['normalized_name'])}"
            index[(et, "website_name_combo", combo)].append(r)

    pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for (et, key_type, key_value), group in index.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a = group[i]
                b = group[j]
                if a["uid"] == b["uid"]:
                    continue
                pkey = tuple(sorted((a["uid"], b["uid"])))
                existing = pairs.get(pkey)
                evidence = f"{key_type}:{key_value}"
                if not existing:
                    pairs[pkey] = {
                        "left_uid": pkey[0],
                        "right_uid": pkey[1],
                        "left_object": a["object"] if a["uid"] == pkey[0] else b["object"],
                        "right_object": b["object"] if b["uid"] == pkey[1] else a["object"],
                        "left_id": a["id"] if a["uid"] == pkey[0] else b["id"],
                        "right_id": b["id"] if b["uid"] == pkey[1] else a["id"],
                        "left_name": a["normalized_name"] if a["uid"] == pkey[0] else b["normalized_name"],
                        "right_name": b["normalized_name"] if b["uid"] == pkey[1] else a["normalized_name"],
                        "method": "deterministic",
                        "score": 1.0,
                        "confidence": "high",
                        "evidence": evidence,
                        "entity_type": et,
                    }
                else:
                    existing["evidence"] = f"{existing['evidence']}|{evidence}"

    return list(pairs.values())


def fuzzy_pairs(records: List[Dict[str, Any]], min_score: float) -> List[Dict[str, Any]]:
    by_entity: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_entity[r["entity_type"]].append(r)

    pairs: List[Dict[str, Any]] = []

    for entity_type, rows in by_entity.items():
        # Blocking by first character to reduce comparisons.
        blocks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            n = normalize_for_similarity(r["normalized_name"])
            if not n:
                continue
            block_key = n[0]
            blocks[block_key].append(r)

        for block in blocks.values():
            for i in range(len(block)):
                for j in range(i + 1, len(block)):
                    a = block[i]
                    b = block[j]
                    if a["uid"] == b["uid"]:
                        continue

                    name_a = normalize_for_similarity(a["normalized_name"])
                    name_b = normalize_for_similarity(b["normalized_name"])
                    if not name_a or not name_b:
                        continue

                    seq = difflib.SequenceMatcher(None, name_a, name_b).ratio()
                    jac = jaccard(token_set(name_a), token_set(name_b))
                    phonetic = 1.0 if soundex(name_a) == soundex(name_b) and soundex(name_a) else 0.0

                    score = (0.60 * seq) + (0.30 * jac) + (0.10 * phonetic)

                    # Deterministic boosts when extra identifiers agree.
                    evidence = [f"name_seq={seq:.3f}", f"name_jaccard={jac:.3f}"]
                    if phonetic > 0:
                        evidence.append("phonetic=soundex")

                    if a["email"] and b["email"] and a["email"].lower() == b["email"].lower():
                        score = min(1.0, score + 0.15)
                        evidence.append("email_exact")

                    if a["email_domain"] and a["email_domain"] == b["email_domain"]:
                        score = min(1.0, score + 0.03)
                        evidence.append("email_domain_match")

                    if a["website_domain"] and a["website_domain"] == b["website_domain"]:
                        score = min(1.0, score + 0.03)
                        evidence.append("website_domain_match")

                    if a["phone_digits"] and b["phone_digits"] and a["phone_digits"][-10:] == b["phone_digits"][-10:]:
                        score = min(1.0, score + 0.02)
                        evidence.append("phone_match")

                    if score < min_score:
                        continue

                    confidence = "low"
                    if score >= 0.92:
                        confidence = "high"
                    elif score >= 0.84:
                        confidence = "medium"

                    left_uid, right_uid = sorted((a["uid"], b["uid"]))
                    left = a if a["uid"] == left_uid else b
                    right = b if b["uid"] == right_uid else a

                    pairs.append(
                        {
                            "left_uid": left_uid,
                            "right_uid": right_uid,
                            "left_object": left["object"],
                            "right_object": right["object"],
                            "left_id": left["id"],
                            "right_id": right["id"],
                            "left_name": left["normalized_name"],
                            "right_name": right["normalized_name"],
                            "method": "fuzzy",
                            "score": round(score, 4),
                            "confidence": confidence,
                            "evidence": "|".join(evidence),
                            "entity_type": entity_type,
                        }
                    )

    dedup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in pairs:
        key = (p["left_uid"], p["right_uid"])
        existing = dedup.get(key)
        if not existing or p["score"] > existing["score"]:
            dedup[key] = p
    return list(dedup.values())


class UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        pa = self.find(a)
        pb = self.find(b)
        if pa != pb:
            self.parent[pb] = pa


def build_clusters(records: List[Dict[str, Any]], pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    uf = UnionFind()
    uid_to_record = {r["uid"]: r for r in records}

    for p in pairs:
        if p["method"] == "deterministic" or p["score"] >= 0.84:
            uf.union(p["left_uid"], p["right_uid"])

    groups: Dict[str, List[str]] = defaultdict(list)
    for uid in uid_to_record.keys():
        root = uf.find(uid)
        groups[root].append(uid)

    pair_lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in pairs:
        pair_lookup[(p["left_uid"], p["right_uid"])] = p

    clusters: List[Dict[str, Any]] = []
    for member_uids in groups.values():
        if len(member_uids) < 2:
            continue

        member_uids = sorted(member_uids)
        scores = []
        confidences = Counter()
        methods = Counter()

        for i in range(len(member_uids)):
            for j in range(i + 1, len(member_uids)):
                k = (member_uids[i], member_uids[j])
                p = pair_lookup.get(k)
                if p:
                    scores.append(float(p["score"]))
                    confidences[p["confidence"]] += 1
                    methods[p["method"]] += 1

        cluster_score = round(sum(scores) / len(scores), 4) if scores else 0.0
        cluster_conf = "low"
        if cluster_score >= 0.92:
            cluster_conf = "high"
        elif cluster_score >= 0.84:
            cluster_conf = "medium"

        members = []
        objects = Counter()
        for uid in member_uids:
            r = uid_to_record[uid]
            objects[r["object"]] += 1
            members.append(
                {
                    "uid": uid,
                    "object": r["object"],
                    "id": r["id"],
                    "name": r["normalized_name"],
                    "email": r["email"],
                }
            )

        clusters.append(
            {
                "cluster_id": f"C{len(clusters)+1:05d}",
                "member_count": len(members),
                "objects": dict(objects),
                "cluster_score": cluster_score,
                "confidence": cluster_conf,
                "match_methods": dict(methods),
                "members": members,
            }
        )

    clusters.sort(key=lambda c: (c["confidence"], c["cluster_score"], c["member_count"]), reverse=True)
    return clusters


def write_pairs_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "left_uid", "right_uid", "left_object", "right_object", "left_id", "right_id",
        "left_name", "right_name", "method", "score", "confidence", "evidence", "entity_type",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def write_report(path: Path, run_id: str, records: int, pairs: List[Dict[str, Any]], clusters: List[Dict[str, Any]], files: List[str]) -> None:
    method_count = Counter(p["method"] for p in pairs)
    conf_count = Counter(p["confidence"] for p in pairs)
    cluster_conf = Counter(c["confidence"] for c in clusters)

    with path.open("w", encoding="utf-8") as fh:
        fh.write("Phase 3 Entity Resolution Report\n")
        fh.write(f"Run ID: {run_id}\n")
        fh.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        fh.write(f"Input records: {records}\n")
        fh.write(f"Candidate pairs: {len(pairs)}\n")
        fh.write(f"Clusters: {len(clusters)}\n\n")

        fh.write("Pairs by Method\n")
        for k, v in sorted(method_count.items()):
            fh.write(f"- {k}: {v}\n")

        fh.write("\nPairs by Confidence\n")
        for k, v in sorted(conf_count.items()):
            fh.write(f"- {k}: {v}\n")

        fh.write("\nClusters by Confidence\n")
        for k, v in sorted(cluster_conf.items()):
            fh.write(f"- {k}: {v}\n")

        fh.write("\nTop Clusters\n")
        for c in sorted(clusters, key=lambda x: x["cluster_score"], reverse=True)[:20]:
            member_names = ", ".join(m["name"] for m in c["members"][:6])
            fh.write(
                f"- {c['cluster_id']} | members={c['member_count']} | score={c['cluster_score']} | confidence={c['confidence']} | names={member_names}\n"
            )

        fh.write("\nOutput Files\n")
        for f in files:
            fh.write(f"- {f}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 entity resolution using deterministic + fuzzy matching.")
    parser.add_argument("--input-dir", type=str, default=str(DEFAULT_INPUT_DIR), help="Directory containing Phase 2 normalized JSON files.")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 3 outputs.")
    parser.add_argument("--min-fuzzy-score", type=float, default=0.75, help="Minimum fuzzy score to keep candidate pair.")
    parser.add_argument("--run-id", type=str, default="", help="Optional run ID. Defaults to UTC timestamp.")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    files = detect_normalized_files(input_dir)
    if not files:
        raise SystemExit(f"No normalized_*.json files found in {input_dir}")

    records: List[Dict[str, Any]] = []
    for f in files:
        records.extend(load_records(f))

    det_pairs = deterministic_pairs(records)
    fuzzy = fuzzy_pairs(records, min_score=args.min_fuzzy_score)

    # Keep best per pair, with deterministic dominating.
    combined: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in fuzzy:
        combined[(p["left_uid"], p["right_uid"])] = p
    for p in det_pairs:
        combined[(p["left_uid"], p["right_uid"])] = p

    pairs = sorted(combined.values(), key=lambda x: (x["confidence"], x["score"]), reverse=True)
    clusters = build_clusters(records, pairs)

    pairs_csv = output_dir / f"phase3_candidate_pairs_{run_id}.csv"
    clusters_json = output_dir / f"phase3_clusters_{run_id}.json"
    report_txt = output_dir / f"phase3_resolution_report_{run_id}.txt"

    write_pairs_csv(pairs_csv, pairs)
    write_json(
        clusters_json,
        {
            "run_id": run_id,
            "record_count": len(records),
            "pair_count": len(pairs),
            "cluster_count": len(clusters),
            "clusters": clusters,
        },
    )
    write_report(report_txt, run_id, len(records), pairs, clusters, [str(pairs_csv), str(clusters_json), str(report_txt)])

    print("Phase 3 complete.")
    print(f"- Input normalized files: {len(files)}")
    print(f"- Input records: {len(records)}")
    print(f"- Candidate pairs: {len(pairs)}")
    print(f"- Clusters: {len(clusters)}")
    print(f"- Pairs CSV: {pairs_csv}")
    print(f"- Clusters JSON: {clusters_json}")
    print(f"- Evidence report: {report_txt}")
    print("- No Salesforce data was modified.")


if __name__ == "__main__":
    main()
