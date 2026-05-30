"""Strategy registry and plugin loader.

New strategies are added *without touching core code*: define a subclass of
:class:`~quantbot.strategies.base.BaseStrategy` and decorate it with
:func:`register_strategy`. The registry then knows it by class name, so the YAML
config can reference it (``class: EMACrossoverStrategy``) and the engine can
instantiate it.

Three discovery mechanisms are supported:

1. **Decorator** — built-in and in-tree strategies self-register on import.
2. **Module path** — ``load_plugins(["my_pkg.my_strategy"])`` imports arbitrary
   modules so their decorated classes register.
3. **Directory** — ``load_plugin_dir("plugins/")`` imports every ``*.py`` file
   in a folder, enabling drop-in strategy files with zero configuration.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from quantbot.core.constants import Timeframe
from quantbot.core.exceptions import StrategyNotFoundError
from quantbot.core.logging import get_logger

if TYPE_CHECKING:
    from typing import Any

    from quantbot.strategies.base import BaseStrategy

_log = get_logger(__name__)


class StrategyRegistry:
    """A name → strategy-class registry."""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseStrategy]] = {}

    def register(
        self, cls: type[BaseStrategy], *, name: str | None = None, replace: bool = False
    ) -> type[BaseStrategy]:
        """Register *cls* under *name* (defaults to the class name)."""
        key = name or cls.__name__
        if key in self._registry and not replace:
            existing = self._registry[key]
            if existing is not cls:
                raise StrategyConfigConflict(key, existing, cls)
            return cls
        self._registry[key] = cls
        _log.debug("strategy_registered", strategy=key)
        return cls

    def unregister(self, name: str) -> None:
        """Remove a strategy from the registry (no error if absent)."""
        self._registry.pop(name, None)

    def get(self, name: str) -> type[BaseStrategy]:
        """Return the strategy class registered under *name*."""
        cls = self._registry.get(name)
        if cls is None:
            raise StrategyNotFoundError(
                f"No strategy registered as {name!r}",
                context={"name": name, "available": self.names()},
            )
        return cls

    def names(self) -> list[str]:
        """All registered strategy names, sorted."""
        return sorted(self._registry)

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    # ------------------------------------------------------------------ creation

    def create(
        self,
        name: str,
        *,
        symbols: list[str] | None = None,
        timeframes: list[Timeframe] | None = None,
        params: dict[str, Any] | None = None,
        instance_name: str | None = None,
    ) -> BaseStrategy:
        """Instantiate a registered strategy by name."""
        cls = self.get(name)
        return cls(
            symbols=symbols,
            timeframes=timeframes,
            params=params,
            instance_name=instance_name,
        )

    def create_from_config(self, entry: dict[str, Any]) -> BaseStrategy:
        """Instantiate a strategy from a YAML config entry.

        Expected keys: ``class`` (or ``strategy``), ``name``, ``symbols``,
        ``timeframes`` (strings), ``params``.
        """
        class_name = entry.get("class") or entry.get("strategy")
        if not class_name:
            raise StrategyNotFoundError("Strategy config entry missing 'class'")
        timeframes = [Timeframe.from_string(tf) for tf in entry.get("timeframes", [])]
        return self.create(
            class_name,
            symbols=list(entry.get("symbols", [])),
            timeframes=timeframes,
            params=entry.get("params", {}),
            instance_name=entry.get("name"),
        )

    # ------------------------------------------------------------------ plugins

    def load_plugins(self, module_paths: list[str]) -> int:
        """Import each dotted *module_path* so its strategies register.

        Returns the number of modules successfully imported.
        """
        loaded = 0
        for path in module_paths:
            try:
                importlib.import_module(path)
                loaded += 1
            except ImportError as exc:
                _log.error("plugin_import_failed", module=path, error=str(exc))
        return loaded

    def load_plugin_dir(self, directory: str | Path) -> int:
        """Import every ``*.py`` file in *directory* as a strategy plugin."""
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        loaded = 0
        for file in sorted(directory.glob("*.py")):
            if file.name.startswith("_"):
                continue
            if self._import_file(file):
                loaded += 1
        _log.info("plugin_dir_loaded", directory=str(directory), count=loaded)
        return loaded

    def _import_file(self, file: Path) -> bool:
        module_name = f"quantbot_plugin_{file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file)
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            return True
        except Exception as exc:  # noqa: BLE001 - a bad plugin must not crash startup
            _log.error("plugin_file_failed", file=str(file), error=str(exc))
            sys.modules.pop(module_name, None)
            return False

    def load_builtins(self) -> int:
        """Import the built-in strategy package so its classes register."""
        before = len(self._registry)
        importlib.import_module("quantbot.strategies.builtin")
        # Importing the package's submodules registers each strategy.
        builtin_pkg = importlib.import_module("quantbot.strategies.builtin")
        pkg_path = Path(builtin_pkg.__file__).parent  # type: ignore[arg-type]
        for file in sorted(pkg_path.glob("*.py")):
            if file.name.startswith("_"):
                continue
            importlib.import_module(f"quantbot.strategies.builtin.{file.stem}")
        return len(self._registry) - before


class StrategyConfigConflict(StrategyNotFoundError):
    """Raised when two different classes register under the same name."""

    def __init__(self, name: str, existing: type, incoming: type) -> None:
        super().__init__(
            f"Strategy name {name!r} already registered to {existing.__name__}; "
            f"cannot register {incoming.__name__}",
            context={"name": name},
        )


#: The process-wide default registry used by the decorator and the engine.
registry = StrategyRegistry()


def register_strategy(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Class decorator registering a strategy with the default registry."""
    return registry.register(cls)


def get_registry() -> StrategyRegistry:
    """Return the process-wide default strategy registry."""
    return registry


__all__ = [
    "StrategyRegistry",
    "get_registry",
    "register_strategy",
    "registry",
]
