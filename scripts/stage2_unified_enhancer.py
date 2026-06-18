#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 2 Unified Enhancer thin entrypoint."""

from __future__ import annotations

import asyncio
import sys

from datasource.engines.stage2.cli import main


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
