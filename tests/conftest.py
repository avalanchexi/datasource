import asyncio
import inspect
import sys
from pathlib import Path

# Ensure repo root and src are on sys.path for imports
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def pytest_pyfunc_call(pyfuncitem):
    """Run legacy bare async tests without requiring a project-wide pytest plugin."""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    if pyfuncitem.get_closest_marker("anyio") is not None:
        return None
    if pyfuncitem.get_closest_marker("asyncio") is not None:
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_func(**kwargs))
    return True
