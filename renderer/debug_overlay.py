"""
DebugOverlay — отладочный оверлей поверх агентов.

Показывает над каждым видимым агентом:
    - Топ-2 потребности по urgency с весами
    - Мигающий «?» при curiosity-броске
    - Стрелку к target если есть путь

Включается D или config.DEBUG.
Вся отрисовка через Pygame, никакой логики симуляции.
"""

from __future__ import annotations

import math
from typing import Dict, Set

import pygame

import config
from simulation.world import World
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.systems.time_system import is_night


# Сокращённые имена потребностей для оверлея
_SHORT_NAMES: Dict[str, str] = {
    "hunger": "hu",
    "thirst": "th",
    "energy": "en",
    "health": "hp",
    "mood":   "mo",
    "social": "so",
    "safety": "sa",
}


class DebugOverlay:
    """Отладочный оверлей — рисуется поверх агентов."""

    def __init__(self) -> None:
        self.enabled: bool = config.DEBUG
        self._font: pygame.font.Font | None = None
        # eid -> тик, когда произошёл curiosity бросок
        self._curiosity_flash: Dict[int, int] = {}

    def _get_font(self) -> pygame.font.Font:
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 11)
        return self._font

    def toggle(self) -> None:
        self.enabled = not self.enabled

    # ── Curiosity tracking ───────────────────────────────────────────

    def mark_curiosity(self, eid: int, tick: int) -> None:
        """Вызывается из main loop когда curiosity бросок сработал."""
        self._curiosity_flash[eid] = tick

    def notify_curiosity_agents(self, world: World) -> None:
        """Определяет curiosity по current_action == 'wander' + таймеру == 0.

        Простая эвристика: если агент только что выбрал wander и таймер
        действия равен 0 — считаем это curiosity броском.
        """
        for eid, pos in world.get_all_with(Position):
            if pos.current_action == "wander" and pos.action_timer == 0:
                traits = world.get_component(eid, Traits)
                if traits is not None and traits.curiosity > config.TRAIT_MEAN:
                    self._curiosity_flash[eid] = world.tick

    # ── Главная отрисовка ────────────────────────────────────────────

    def draw(
        self,
        surface: pygame.Surface,
        world: World,
        cam_x: int,
        cam_y: int,
        tile_size: int,
    ) -> None:
        if not self.enabled:
            return

        font = self._get_font()
        night = is_night(world)
        screen_w = surface.get_width()
        screen_h = surface.get_height()

        for eid, pos in world.get_all_with(Position):
            # Экранные координаты центра агента
            sx = int(pos.float_x - cam_x) * tile_size + tile_size // 2
            sy = int(pos.float_y - cam_y) * tile_size + tile_size // 2

            if not (0 <= sx < screen_w and 0 <= sy < screen_h):
                continue

            needs = world.get_component(eid, Needs)
            if needs is None:
                continue

            # ── Топ-2 потребности по urgency ────────────────────────
            weights = self._calc_weights(needs, world, eid, night)
            sorted_w = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
            top2 = sorted_w[:2]

            parts = []
            for need_name, w in top2:
                short = _SHORT_NAMES.get(need_name, need_name[:2])
                parts.append(f"{short}:{w:.2f}")
            text = " ".join(parts)

            text_surf = font.render(text, True, (160, 160, 160))
            # Рисуем над агентом (выше имени/действия)
            text_y = sy - config.AGENT_DOT_RADIUS - 26
            surface.blit(text_surf, (sx - text_surf.get_width() // 2, text_y))

            # ── Curiosity «?» ───────────────────────────────────────
            flash_tick = self._curiosity_flash.get(eid)
            if flash_tick is not None and world.tick - flash_tick < 3:
                q_surf = font.render("?", True, (255, 200, 50))
                q_y = text_y - 14
                # Мигание: рисуем каждый чётный тик
                if (world.tick - flash_tick) % 2 == 0:
                    surface.blit(q_surf, (sx - q_surf.get_width() // 2, q_y))

            # ── Стрелка к target ────────────────────────────────────
            if pos.target_x is not None and pos.target_y is not None:
                tx = int(pos.target_x - cam_x) * tile_size + tile_size // 2
                ty = int(pos.target_y - cam_y) * tile_size + tile_size // 2
                dx = tx - sx
                dy = ty - sy
                dist = math.hypot(dx, dy)
                if dist > 8:
                    # Нормализуем до длины 10px
                    arrow_len = 10
                    nx = dx / dist * arrow_len
                    ny = dy / dist * arrow_len
                    end_x = sx + nx
                    end_y = sy + ny
                    pygame.draw.line(
                        surface,
                        (100, 200, 100),
                        (sx, sy),
                        (int(end_x), int(end_y)),
                        1,
                    )

        # Очистка старых curiosity записей
        expired = [
            eid for eid, t in self._curiosity_flash.items()
            if world.tick - t >= 3
        ]
        for eid in expired:
            del self._curiosity_flash[eid]

    # ── Вспомогательные ──────────────────────────────────────────────

    @staticmethod
    def _calc_weights(
        needs: Needs,
        world: World,
        eid: int,
        night: bool,
    ) -> Dict[str, float]:
        """Пересчитывает utility веса для оверлея (read-only)."""
        traits = world.get_component(eid, Traits)
        weights: Dict[str, float] = {}

        for need_name, base_w in config.UTILITY_BASE_WEIGHT.items():
            current = getattr(needs, need_name, 0.0)
            urgency = 1.0 - current

            night_mod = config.UTILITY_NIGHT_MODIFIER.get(need_name, 1.0)
            modifier = night_mod if night else 1.0

            final = urgency * base_w * modifier

            if need_name == "social" and traits is not None:
                final *= traits.sociality

            weights[need_name] = final

        return weights
