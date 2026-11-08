"""Plugin settings, populated from ``plugin.yaml``'s config_schema at register().

Hermes gives handlers no ``ctx``, so the handful of user-visible knobs are read
once into this module and used as defaults by the engine entry points.
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "trace_width": 0.2,
    "clearance": 0.15,
    "grid": 0.1,
    "effort": "normal",
    "default_board_width": 50.0,
    "default_board_height": 40.0,
}

_VALUES: Dict[str, Any] = dict(DEFAULTS)


def _coerce(key: str, value: Any) -> Any:
    default = DEFAULTS.get(key)
    try:
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, float):
            return float(value)
        if isinstance(default, int):
            return int(value)
    except (TypeError, ValueError):
        return default
    return value


def configure(ctx) -> None:
    for key, default in DEFAULTS.items():
        try:
            _VALUES[key] = _coerce(key, ctx.get_config(key, default=default))
        except Exception:
            _VALUES[key] = default


def get(key: str) -> Any:
    return _VALUES.get(key, DEFAULTS.get(key))


def rules() -> dict:
    return {"trace_width": get("trace_width"), "clearance": get("clearance"),
            "grid": get("grid")}
