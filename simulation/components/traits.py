"""
Компонент черт личности агента.

Все float 0.0–1.0. Генерируются при рождении, не меняются.
Генерация и наследование — в factory.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class Traits:
    fearfulness: float = config.TRAIT_MEAN
    sociality: float = config.TRAIT_MEAN
    curiosity: float = config.TRAIT_MEAN
    resilience: float = config.TRAIT_MEAN
    faith: float = config.TRAIT_MEAN
