"""Validate complete ASVS tracking, not application compliance certification."""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def validate_matrix(root: Path = ROOT) -> dict[str, int]:
    catalog = json.loads((root / "docs/asvs_5_0_0_catalog.json").read_text(encoding="utf-8"))
    with (root / "docs/asvs_5_0_0_matrix.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [row["catalog_id"] for row in rows]
    if len(ids) != 345 or len(set(ids)) != len(ids) or set(ids) != set(catalog["requirements"]):
        raise ValueError("ASVS requirements missing, duplicated or unknown")
    permitted = {"VERIFIED_DOCUMENTATION", "PARTIAL", "GAP", "UNTESTED", "N/A"}
    for row in rows:
        rid = row["catalog_id"]
        if row["requirement_id"] != "v5.0.0-" + rid[1:] or int(row["level"]) != catalog["requirements"][rid]:
            raise ValueError("ASVS version or level mismatch")
        if row["status"] not in permitted or not all(
            row[key].strip()
            for key in (
                "rationale",
                "evidence",
                "owner_role",
                "next_step",
            )
        ):
            raise ValueError("ASVS status lacks required evidence or owner")
        if row["status"] == "N/A" and row["applicable"] != "NO":
            raise ValueError("N/A requires an explicit applicability decision")
        for evidence in row["evidence"].split(";"):
            path = (root / evidence).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError("ASVS evidence must reference a real repository file")
    return dict(Counter(row["status"] for row in rows))


if __name__ == "__main__":
    print(json.dumps(validate_matrix(), sort_keys=True))
