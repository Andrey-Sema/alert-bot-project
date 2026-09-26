"""The evidence registry cannot silently drop controls or invent PASS entries."""

import csv
import shutil
from pathlib import Path

import pytest

from alert_bot_project.scripts.validate_asvs import ROOT, validate_matrix


def test_registry_covers_all_official_requirements_without_compliance_claim() -> None:
    summary = validate_matrix()
    assert sum(summary.values()) == 345
    assert summary["GAP"] > 0
    assert summary["UNTESTED"] > 0


@pytest.mark.parametrize("mutation", ["duplicate", "unsupported_pass", "missing_evidence"])
def test_registry_rejects_missing_or_unsubstantiated_controls(tmp_path: Path, mutation: str) -> None:
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    path = tmp_path / "docs/asvs_5_0_0_matrix.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if mutation == "duplicate":
        rows[-1] = rows[0].copy()
    elif mutation == "unsupported_pass":
        rows[0]["status"] = "PASS"
    else:
        rows[0]["evidence"] = "does-not-exist.py"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="ASVS"):
        validate_matrix(tmp_path)
