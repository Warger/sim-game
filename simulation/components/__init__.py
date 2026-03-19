"""
Пакет компонентов ECS.

Компоненты — только данные, никакой логики.
Каждый компонент — dataclass с полями, привязанный к entity через World.
"""

from simulation.components.needs import Needs
from simulation.components.traits import Traits
from simulation.components.body import Body
from simulation.components.position import Position
from simulation.components.memory import Memory
from simulation.components.identity import Identity

__all__ = ["Needs", "Traits", "Body", "Position", "Memory", "Identity"]
