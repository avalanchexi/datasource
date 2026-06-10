"""Tests for the batch-0 one-off audit tools (import_graph / merge_audit)."""

import textwrap

import import_graph
import merge_audit


def test_module_name_for_maps_src_paths():
    p = import_graph.SRC / "datasource" / "utils" / "coercion.py"
    assert import_graph.module_name_for(p) == "datasource.utils.coercion"
    init = import_graph.SRC / "datasource" / "utils" / "__init__.py"
    assert import_graph.module_name_for(init) == "datasource.utils"
    outside = import_graph.ROOT / "scripts" / "stage1_data_collector.py"
    assert import_graph.module_name_for(outside) is None


def test_extract_import_candidates_absolute_and_relative():
    src = textwrap.dedent(
        """
        import datasource.manager
        from datasource.utils import coercion
        from . import json_io
        from ..models import base
        """
    )
    cands = import_graph.extract_import_candidates(
        src, module_name="datasource.utils.coercion", is_package=False
    )
    assert "datasource.manager" in cands
    assert "datasource.utils" in cands
    assert "datasource.utils.coercion" in cands
    assert "datasource.utils.json_io" in cands
    assert "datasource.models.base" in cands


def test_reachability_includes_ancestor_packages():
    known = {
        "datasource": None,
        "datasource.utils": None,
        "datasource.utils.coercion": None,
        "datasource.orphan": None,
    }
    edges = {
        "datasource": [],
        "datasource.utils": [],
        "datasource.utils.coercion": [],
        "datasource.orphan": [],
    }
    entries = {"scripts/x.py": ["datasource.utils.coercion"]}
    seen = import_graph.reachable_from_entries(known, edges, entries)
    assert seen == {"datasource", "datasource.utils", "datasource.utils.coercion"}


def test_classify_tiers():
    assert merge_audit.classify(True, 85.0) == "runtime_used"
    assert merge_audit.classify(True, 20.0) == "runtime_used"
    assert merge_audit.classify(True, 5.0) == "imported_only"
    # --source 模式下 coverage 会给未导入文件记 0%,必须归入静态档
    assert merge_audit.classify(True, 0.0) == "reachable_not_run"
    assert merge_audit.classify(True, None) == "reachable_not_run"
    assert merge_audit.classify(False, None) == "unreachable"
    assert merge_audit.classify(False, 0.0) == "unreachable"


def test_coverage_by_module_maps_file_keys():
    payload = {
        "files": {
            "src/datasource/utils/coercion.py": {
                "summary": {"percent_covered": 73.2}
            },
            "scripts/stage3_pring_analyzer.py": {
                "summary": {"percent_covered": 50.0}
            },
        }
    }
    out = merge_audit.coverage_by_module(payload)
    assert out == {"datasource.utils.coercion": 73.2}
