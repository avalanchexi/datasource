"""DEPRECATED shim (refactor batch A, 2026-06): use scripts/stage4_report_generator.py.

Kept one release cycle for backward compatibility; removal planned in batch B.
Import target unchanged: datasource.generators.simple_report.
"""

from datasource.generators.simple_report import generate_report

__all__ = ["generate_report"]
