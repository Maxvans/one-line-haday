"""Shared fixtures for One Line HaDay tests.

Loads storage.py directly via importlib, bypassing the
`custom_components.one_line_haday` package __init__ (which imports real
Home Assistant modules like panel_custom that aren't available in a
standalone test environment). Home Assistant's Store helper is stubbed
with an in-memory fake that mimics `async_load` / `async_save`.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "one_line_haday"


class _FakeStore:
    def __init__(self, *_args, **_kwargs):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data


def _install_fake_homeassistant(monkeypatch):
    fake_ha = types.ModuleType("homeassistant")
    fake_core = types.ModuleType("homeassistant.core")
    fake_core.HomeAssistant = object
    fake_helpers = types.ModuleType("homeassistant.helpers")
    fake_storage = types.ModuleType("homeassistant.helpers.storage")
    fake_storage.Store = _FakeStore

    monkeypatch.setitem(sys.modules, "homeassistant", fake_ha)
    monkeypatch.setitem(sys.modules, "homeassistant.core", fake_core)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", fake_helpers)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", fake_storage)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store_module(monkeypatch):
    """Load storage.py in isolation, without importing the package __init__."""
    _install_fake_homeassistant(monkeypatch)

    # Load const.py first since storage.py imports "from .const import ...".
    # Register a lightweight fake parent package so relative imports resolve.
    fake_pkg = types.ModuleType("one_line_haday_test_pkg")
    fake_pkg.__path__ = [str(INTEGRATION_DIR)]
    monkeypatch.setitem(sys.modules, "one_line_haday_test_pkg", fake_pkg)

    const_mod = _load_module("one_line_haday_test_pkg.const", INTEGRATION_DIR / "const.py")
    sys.modules["one_line_haday_test_pkg.const"] = const_mod

    storage_spec = importlib.util.spec_from_file_location(
        "one_line_haday_test_pkg.storage", INTEGRATION_DIR / "storage.py"
    )
    storage_mod = importlib.util.module_from_spec(storage_spec)
    storage_mod.__package__ = "one_line_haday_test_pkg"
    sys.modules["one_line_haday_test_pkg.storage"] = storage_mod
    storage_spec.loader.exec_module(storage_mod)
    return storage_mod


@pytest.fixture
def store(store_module):
    return store_module.OneLineHaDayStore(hass=None)
