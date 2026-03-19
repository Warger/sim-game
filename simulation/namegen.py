"""
Процедурная генерация имён из слогов.

Имя генерируется при рождении, фиксируется навсегда.
Отображается во всём UI и логах.
"""

from __future__ import annotations

import random as _stdlib_random

_SYLLABLES = [
    "a", "ba", "da", "el", "en", "fa", "ga", "ha", "il", "ka",
    "la", "ma", "na", "no", "ra", "ri", "sa", "ta", "to", "va",
    "al", "an", "ar", "do", "er", "ir", "is", "le", "li", "lo",
    "mi", "ne", "ni", "nu", "ol", "on", "or", "re", "ro", "si",
    "so", "su", "te", "ti", "ul", "un", "ur", "ve", "vi", "za",
]


def generate_name(rng: _stdlib_random.Random | None = None) -> str:
    """Генерирует случайное имя из 2-3 слогов."""
    r = rng or _stdlib_random
    n_syllables = r.choice([2, 2, 3])
    name = "".join(r.choice(_SYLLABLES) for _ in range(n_syllables))
    return name.capitalize()
