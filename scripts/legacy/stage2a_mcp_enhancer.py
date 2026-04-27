#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Archived shim for the legacy Stage 2a entry point.

Stage 2a/MCP is no longer an active runtime path. Use
`scripts/stage2_unified_enhancer.py` plus `scripts/stage2_5_injector.py`.
This file remains under `scripts/legacy/` only for historical diagnostics.
"""

from stage2_mcp_enhancer import main


if __name__ == "__main__":
    print("[WARN] stage2a_mcp_enhancer.py 已归档；请使用 stage2_unified_enhancer.py + stage2_5_injector.py")
    main()
