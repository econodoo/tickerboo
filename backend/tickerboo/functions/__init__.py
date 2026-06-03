"""
TickerBoo function plugin system.

Each TB.* function is a FunctionPlugin subclass in its own file
under functions/<category>/. The registry auto-discovers them at startup.

To add a new function:
  1. Create a file in functions/<category>/my_func.py
  2. Subclass FunctionPlugin
  3. Decorate with @register
  4. Restart server — done.
"""
from .registry import registry, register
from .base import FunctionPlugin, Param

__all__ = ["registry", "register", "FunctionPlugin", "Param"]
