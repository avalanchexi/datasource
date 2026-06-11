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
                "summary": {"percent_covered": 73.2, "num_statements": 40}
            },
            "scripts/stage3_pring_analyzer.py": {
                "summary": {"percent_covered": 50.0, "num_statements": 30}
            },
        }
    }
    out = merge_audit.coverage_by_module(payload)
    assert out == {"datasource.utils.coercion": 73.2}


def test_coverage_by_module_skips_zero_statement_files():
    # coverage 给零语句文件(空 __init__.py、纯 docstring 桩)记 100%,
    # 这是空洞证据,不能作为 runtime_used 依据
    payload = {
        "files": {
            "src/datasource/utils/coercion.py": {
                "summary": {"percent_covered": 73.2, "num_statements": 40}
            },
            "src/datasource/calculators/pring/leading_indicator.py": {
                "summary": {"percent_covered": 100.0, "num_statements": 0}
            },
        }
    }
    out = merge_audit.coverage_by_module(payload)
    assert out == {"datasource.utils.coercion": 73.2}


def test_extract_dynamic_import_targets_fstring_and_literal():
    src = textwrap.dedent(
        """
        from importlib import import_module

        def load(module_name):
            return import_module(
                f"datasource.providers.stage2_structured.{module_name}"
            )

        plain = import_module("datasource.manager")
        """
    )
    known = {
        "datasource.manager": None,
        "datasource.providers.stage2_structured": None,
        "datasource.providers.stage2_structured.stooq": None,
        "datasource.providers.stage2_structured.registry": None,
        "datasource.providers.other": None,
    }
    out = import_graph.extract_dynamic_import_targets(src, known)
    assert "datasource.providers.stage2_structured.stooq" in out
    assert "datasource.providers.stage2_structured.registry" in out
    assert "datasource.providers.stage2_structured" in out
    assert "datasource.manager" in out
    assert "datasource.providers.other" not in out
