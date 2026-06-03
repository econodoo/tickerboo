"""
Function registry — auto-discovers and dispatches TB.* plugins.

Usage:
    from tickerboo.functions.registry import register, registry

    @register
    class MyFunc(FunctionPlugin):
        name = "MY_FUNC"
        ...

    # At startup:
    registry.discover()          # scans functions/**/*.py

    # At request time:
    result = await registry.call("MY_FUNC", {"ticker": "VNM", "tf": "1d"})
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import time
from pathlib import Path
from typing import Any

from tickerboo.utils.errors import FunctionNotFoundError, InvalidParamError, TickerBooError

log = logging.getLogger(__name__)


class _Registry:
    """Singleton registry of all function plugins."""

    def __init__(self):
        self._plugins: dict[str, Any] = {}   # name → plugin instance
        self._discovered = False

    def register(self, plugin_class):
        """Register a plugin class. Instantiates it immediately."""
        instance = plugin_class()
        name = instance.name.upper()
        if name in self._plugins:
            log.warning("Overwriting existing plugin: %s", name)
        self._plugins[name] = instance
        return plugin_class

    def discover(self):
        """Walk tickerboo/functions/ and import every module to trigger @register."""
        if self._discovered:
            return

        functions_dir = Path(__file__).parent
        _import_submodules("tickerboo.functions", functions_dir)
        self._discovered = True

        by_cat = {}
        for p in self._plugins.values():
            by_cat.setdefault(p.category, []).append(p.name)
        summary = ", ".join(f"{cat}({len(fns)})" for cat, fns in sorted(by_cat.items()))
        log.info("Discovered %d functions: %s", len(self._plugins), summary)

    def get(self, name: str):
        """Get a plugin by name (case-insensitive)."""
        return self._plugins.get(name.upper())

    def list_all(self, category: str | None = None, tier: str | None = None) -> list[dict]:
        """List all registered functions, optionally filtered."""
        results = []
        for p in sorted(self._plugins.values(), key=lambda x: (x.category, x.name)):
            if category and p.category != category:
                continue
            if tier and p.tier != tier:
                continue
            results.append(p.to_dict())
        return results

    def categories(self) -> dict[str, int]:
        """Return {category: count} dict."""
        cats = {}
        for p in self._plugins.values():
            cats[p.category] = cats.get(p.category, 0) + 1
        return dict(sorted(cats.items()))

    async def call(self, name: str, args: dict, ctx=None) -> dict:
        """
        Dispatch a function call.

        Returns:
            {"status": "ok", "value": ..., "duration_ms": ...}
            or
            {"status": "error"|"no_data", "code": ..., "message": ...}
        """
        plugin = self.get(name)
        if plugin is None:
            raise FunctionNotFoundError(f"Function '{name}' not found. Use GET /functions to list available.")

        # Validate params
        try:
            validated = plugin.validate_params(args)
        except ValueError as e:
            raise InvalidParamError(str(e))

        # Build context if not provided
        if ctx is None:
            from tickerboo.functions.context import ComputeContext
            ctx = ComputeContext(registry=self)

        # Execute
        t0 = time.perf_counter()
        try:
            result = await plugin.compute(ctx, **validated)
        except TickerBooError:
            raise
        except Exception as e:
            log.exception("Plugin %s raised unexpected error", name)
            raise TickerBooError(f"Internal error in {name}: {e}")

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Log usage (fire-and-forget, don't block response)
        _log_call(name, validated, duration_ms)

        return {
            "status": "ok",
            "function": name,
            "value": result,
            "duration_ms": duration_ms,
        }

    @property
    def count(self) -> int:
        return len(self._plugins)


# Singleton
registry = _Registry()


def register(cls):
    """Decorator to register a FunctionPlugin subclass."""
    registry.register(cls)
    return cls


def _import_submodules(package_name: str, package_dir: Path):
    """Recursively import all submodules to trigger @register decorators."""
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=[str(package_dir)],
        prefix=package_name + ".",
    ):
        # Skip __init__, base, registry, context — they're infrastructure
        short = modname.rsplit(".", 1)[-1]
        if short.startswith("_") or short in ("base", "registry", "context"):
            continue
        try:
            importlib.import_module(modname)
        except Exception as e:
            log.warning("Failed to import plugin module %s: %s", modname, e)


def _log_call(name: str, params: dict, duration_ms: float):
    """Store function call analytics (async-safe, best-effort)."""
    import asyncio
    import json as _json

    ticker = params.get("ticker", "?")
    tf = params.get("tf", "")
    log.debug("CALL %s(%s) → %.1f ms", name, ticker, duration_ms)

    # Fire-and-forget DB write
    async def _write():
        try:
            from tickerboo.db.session import execute
            await execute(
                """INSERT INTO function_calls
                   (function_name, ticker, timeframe, params_json, duration_ms)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, ticker if ticker != "?" else None, tf or None,
                 _json.dumps(params), duration_ms),
            )
        except Exception:
            pass  # never block on analytics

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_write())
    except RuntimeError:
        pass  # no event loop, skip
