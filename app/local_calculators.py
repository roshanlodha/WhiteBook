"""Legacy local calculator module.

Clinical score calculators are intentionally not hardcoded here. Named clinical
calculators should come from the MedCalc package and are enabled only in
calculator mode.
"""

from __future__ import annotations

from typing import Any, Callable

LOCAL_CALCULATORS: dict[str, Callable[..., Any]] = {}
