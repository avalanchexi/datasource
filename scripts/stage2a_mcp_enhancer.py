#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deprecated shim for the legacy Stage 2a entry point.

Stage 2a has been replaced by `scripts/stage2_mcp_enhancer.py`. This file is kept
only for backward-compatibility so older automation or docs do not break.
"""

from stage2_mcp_enhancer import main


if __name__ == "__main__":
    print("[WARN] stage2a_mcp_enhancer.py 已弃用，请改用 stage2_mcp_enhancer.py")
    main()
