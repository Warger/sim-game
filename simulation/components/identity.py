"""
Компонент идентичности агента.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Identity:
    name: str = ""
    parent_ids: Optional[Tuple[int, int]] = None
    guardian_id: Optional[int] = None
