"""Run dependency-free function tests and unittest cases without pytest."""
import asyncio
import importlib
import inspect
import sys
import traceback
import unittest
from pathlib import Path


def main():
    passed = failed = 0
    suite = unittest.TestSuite()
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        module = importlib.import_module(f"app.llm.v3.tests.{path.stem}")
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_") or fn.__module__ != module.__name__:
                continue
            try:
                if inspect.iscoroutinefunction(fn):
                    asyncio.run(fn())
                else:
                    fn()
                passed += 1
            except Exception:
                failed += 1
                print(f"FAIL {path.stem}.{name}", flush=True)
                traceback.print_exc()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"Function tests: {passed} passed, {failed} failed", flush=True)
    return int(bool(failed) or not result.wasSuccessful())


if __name__ == "__main__":
    sys.exit(main())
