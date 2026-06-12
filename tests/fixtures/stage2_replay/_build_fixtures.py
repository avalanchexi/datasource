"""Build the stage2 replay fixture pack from real recorded runs.

Donor runs (verified 2026-06-12):
  - 20260527: structured_success / manual_required / skipped_existing, 18 indicators.
  - 20260424: borrow ONE search_success record to cover the search lane
    (structured-era runs have ~0 search_success).

Idempotent: rerun to regenerate. fail loud on any coverage/shape gap.
"""

import json
import os
import shutil
from collections import Counter
from pathlib import Path

MAIN = Path(os.environ.get("MAIN", "/mnt/d/cursor/datasource"))
PRIMARY = MAIN / "data/runs/20260527/websearch_results"
SEARCH_DONOR = MAIN / "data/runs/20260424/websearch_results"
INPUT = MAIN / "data/runs/20260527/market_data.json"

HERE = Path(__file__).resolve().parent
REC = HERE / "recorded"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _put_unique(mapping, key, value, source):
    if key in mapping:
        raise SystemExit(f"FAIL: duplicate indicator_key {key} in {source}")
    mapping[key] = value


def _check_path(path, description):
    if not path.exists():
        raise SystemExit(f"FAIL: missing {description}: {path}")


def _structured_payload(rec):
    """Pull replayable structured payload from a record; fail loud if unusable."""
    ext = rec.get("extraction") or {}
    src_url = ext.get("source_url") or rec.get("source_url")
    src_tier = ext.get("source_tier") or rec.get("source_tier")
    key = rec["task"]["indicator_key"]
    if not src_url or not src_tier:
        raise SystemExit(f"FAIL: structured record {key} missing source_url/source_tier; pick another run")
    payload = {
        k: ext[k]
        for k in (
            "value", "unit", "recent_5d", "total_120d", "trend",
            "metric_basis", "window_evidence", "is_estimated",
        )
        if k in ext
    }
    if not payload:
        raise SystemExit(f"FAIL: structured record {key} has empty payload; pick another run")
    return {
        "behavior": "success",
        "payload": payload,
        "source": ext.get("source") or rec.get("source") or "replay-fixture",
        "source_url": src_url,
        "source_tier": src_tier,
        "confidence": ext.get("confidence", 0.9),
    }


def main():
    _check_path(PRIMARY, "primary replay directory")
    _check_path(SEARCH_DONOR, "search donor replay directory")
    _check_path(INPUT, "market data input")

    REC.mkdir(parents=True, exist_ok=True)
    for old in REC.glob("*.json"):
        old.unlink()

    # 1) market_data input
    shutil.copy2(INPUT, HERE / "market_data_input.json")

    # 2) primary records (20260527) keyed by indicator
    primary = {}
    for f in sorted(PRIMARY.glob("*.json")):
        rec = _load(f)
        _put_unique(primary, rec["task"]["indicator_key"], (f, rec), PRIMARY)

    rtypes = {k: r["result_type"] for k, (_, r) in primary.items()}
    structured_keys = sorted(k for k, t in rtypes.items() if t == "structured_success")
    manual_keys = sorted(k for k, t in rtypes.items() if t == "manual_required")
    skip_keys = sorted(k for k, t in rtypes.items() if t == "skipped_existing")
    if not (structured_keys and manual_keys and skip_keys):
        raise SystemExit(f"FAIL: primary run missing a result_type: {Counter(rtypes.values())}")

    # 3) search lane: prefer replacing a manual indicator with a donor search_success;
    #    if no overlap exists, append one donor search record that is not structured.
    donor_search = {}
    for f in sorted(SEARCH_DONOR.glob("*.json")):
        rec = _load(f)
        if rec.get("result_type") == "search_success":
            _put_unique(donor_search, rec["task"]["indicator_key"], rec, SEARCH_DONOR)
    search_key = next((k for k in manual_keys if k in donor_search), None)
    if search_key is None:
        # fallback: any donor search_success indicator not already structured
        search_key = next((k for k in sorted(donor_search) if k not in structured_keys), None)
    if search_key is None:
        raise SystemExit("FAIL: no borrowable search_success record from 20260424")

    # 4) write recorded/ : all primary except an overlapped borrowed indicator, plus donor search
    written = {}
    for key, (f, rec) in primary.items():
        if key == search_key:
            continue
        (REC / f.name).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        written[key] = rec
    srec = donor_search[search_key]
    (REC / f"borrowed_search_{search_key.replace('=', '_')}.json").write_text(
        json.dumps(srec, ensure_ascii=False, indent=2), encoding="utf-8")
    written[search_key] = srec

    # 5) PARSE_ERROR lane: pick one structured indicator (the last, kept out of oracle) -> fake parse_error
    parse_error_key = structured_keys[-1]

    # 6) structured_responses.json: success for structured keys (except parse_error_key), parse_error for it
    structured_responses = {}
    for key in structured_keys:
        if key == search_key:  # search_key was manual, won't be here, but guard anyway
            continue
        if key == parse_error_key:
            structured_responses[key] = {"behavior": "parse_error"}
        else:
            structured_responses[key] = _structured_payload(written[key])
    (HERE / "structured_responses.json").write_text(
        json.dumps(structured_responses, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7) tasks.jsonl from real task objects (sorted by task_id for stable order)
    tasks = [rec["task"] for rec in written.values()]
    tasks.sort(key=lambda t: str(t.get("task_id")))
    (HERE / "tasks.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")

    # 8) coverage guard: four result_types must be reachable
    final_rtypes = {k: (r.get("result_type")) for k, r in written.items()}
    have = set(final_rtypes.values())
    needed = {"structured_success", "search_success", "manual_required", "skipped_existing"}
    missing = needed - have
    if missing:
        raise SystemExit(f"FAIL: result_type coverage gap: missing={missing} have={Counter(final_rtypes.values())}")

    meta = {"search_key": search_key, "parse_error_key": parse_error_key,
            "structured_keys": structured_keys, "manual_keys": manual_keys, "skip_keys": skip_keys}
    (HERE / "fixture_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK", {"tasks": len(tasks), **{k: v for k, v in meta.items() if k.endswith("_key")},
                 "coverage": dict(Counter(final_rtypes.values()))})


if __name__ == "__main__":
    main()
