"""
HUD — интерфейсные панели поверх карты.

1. Панель агента (правая, 280px) — при клике на агента.
2. Лог поселения (нижняя полоса, 120px) — последние события.

Клавиша H — toggle hud on/off.
Вся отрисовка через Pygame, никакой логики симуляции.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import pygame

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.identity import Identity
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits

# ── Константы HUD ────────────────────────────────────────────────────

PANEL_WIDTH = 280
PANEL_BG = (30, 30, 40, 220)
PANEL_BORDER = (80, 80, 100)

LOG_HEIGHT = 120
LOG_BG = (20, 20, 30, 200)

BAR_WIDTH = 140
BAR_HEIGHT = 12

COLOR_GREEN = (60, 180, 60)
COLOR_YELLOW = (200, 180, 40)
COLOR_RED = (200, 50, 50)
COLOR_TRAIT_BAR = (90, 130, 200)
COLOR_TEXT = (220, 220, 220)
COLOR_DIM = (150, 150, 160)
COLOR_HEADER = (255, 255, 255)
COLOR_SECTION = (180, 200, 255)

# Типы событий, показываемые в логе поселения
_LOG_EVENT_TYPES = {"death", "birth", "socialized", "need_critical"}

# Сокращения причин смерти
_CAUSE_RU: Dict[str, str] = {
    "thirst": "жажда",
    "hunger": "голод",
    "old_age": "старость",
    "orphaned": "сиротство",
}


def _stage_label(body: Body) -> str:
    if body.is_child:
        return "child"
    if body.age >= config.ADULT_END_TICKS:
        return "elder"
    return "adult"


def _bar_color(value: float) -> Tuple[int, int, int]:
    if value > 0.5:
        return COLOR_GREEN
    if value > 0.2:
        return COLOR_YELLOW
    return COLOR_RED


class HUD:
    """HUD — панель агента + лог поселения."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self.selected_eid: Optional[int] = None
        self.following: bool = False  # камера следует за выбранным агентом

        # Лог поселения — последние 8 строк
        self._settlement_log: List[str] = []
        self._max_log_lines = 8

        # Скорость (для отображения)
        self.speed_label: str = "×1"

        # Rect кнопки Follow (обновляется в draw)
        self._follow_btn_rect: Optional[pygame.Rect] = None

        self._font: pygame.font.Font | None = None
        self._font_small: pygame.font.Font | None = None
        self._font_header: pygame.font.Font | None = None

    def _ensure_fonts(self) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 13)
            self._font_small = pygame.font.SysFont("consolas", 11)
            self._font_header = pygame.font.SysFont("consolas", 15, bold=True)

    def toggle(self) -> None:
        self.enabled = not self.enabled

    def get_follow_pos(self, world: World) -> Optional[Tuple[int, int]]:
        """Returns (tile_x, tile_y) of followed agent, or None."""
        if not self.following or self.selected_eid is None:
            return None
        pos = world.get_component(self.selected_eid, Position)
        if pos is None:
            self.following = False
            return None
        return (pos.tile_x, pos.tile_y)

    # ── Выбор агента по клику ────────────────────────────────────────

    def handle_click(
        self,
        world: World,
        screen_x: int,
        screen_y: int,
        cam_x: int,
        cam_y: int,
        tile_size: int,
        screen_w: int,
        screen_h: int,
    ) -> None:
        """Обрабатывает клик мышью: выбор/снятие агента."""
        # Клик на кнопку Follow
        if self._follow_btn_rect is not None and self._follow_btn_rect.collidepoint(screen_x, screen_y):
            self.following = not self.following
            return

        # Клик в панель агента — игнорировать
        if self.selected_eid is not None and screen_x > screen_w - PANEL_WIDTH:
            return

        # Клик в лог — игнорировать
        if screen_y > screen_h - LOG_HEIGHT:
            return

        best_eid: Optional[int] = None
        best_dist = float("inf")

        for eid, pos in world.get_all_with(Position):
            sx = int(pos.float_x - cam_x) * tile_size + tile_size // 2
            sy = int(pos.float_y - cam_y) * tile_size + tile_size // 2
            dist = math.hypot(sx - screen_x, sy - screen_y)
            if dist < config.AGENT_DOT_RADIUS + 6 and dist < best_dist:
                best_dist = dist
                best_eid = eid

        if best_eid != self.selected_eid:
            self.following = False
        self.selected_eid = best_eid

    # ── Сбор событий для лога ────────────────────────────────────────

    def collect_events(self, world: World) -> None:
        """Вызывается каждый тик — собирает события для лога поселения."""
        for ev in world.event_queue:
            ev_type = ev.get("type", "")
            if ev_type not in _LOG_EVENT_TYPES:
                continue

            line = self._format_event(ev, world)
            if line:
                self._settlement_log.insert(0, line)
                if len(self._settlement_log) > self._max_log_lines:
                    self._settlement_log = self._settlement_log[:self._max_log_lines]

    @staticmethod
    def _format_event(ev: dict, world: World) -> Optional[str]:
        tick = ev.get("tick", 0)
        ev_type = ev.get("type", "")

        if ev_type == "death":
            name = ev.get("name", "?")
            cause = _CAUSE_RU.get(ev.get("cause", ""), ev.get("cause", "?"))
            age = ev.get("age_years", "?")
            return f"tick {tick} — {name} умер(ла) ({cause}, {age} лет)"

        if ev_type == "birth":
            name = ev.get("name", "?")
            return f"tick {tick} — родился {name}"

        if ev_type == "socialized":
            eid = ev.get("eid")
            identity = world.get_component(eid, Identity) if eid is not None else None
            name = identity.name if identity else "?"
            return f"tick {tick} — {name} социализация"

        if ev_type == "need_critical":
            eid = ev.get("eid")
            identity = world.get_component(eid, Identity) if eid is not None else None
            name = identity.name if identity else "?"
            need = ev.get("need", "?")
            return f"tick {tick} — {name} крит. {need}"

        return None

    # ── Главная отрисовка ────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, world: World) -> None:
        if not self.enabled:
            return

        self._ensure_fonts()
        screen_w = surface.get_width()
        screen_h = surface.get_height()

        # Время в верхнем левом углу (всегда видно)
        self._draw_time_indicator(surface, world)

        # Панель агента
        if self.selected_eid is not None:
            if self.selected_eid in world.entities:
                self._draw_agent_panel(surface, world, screen_w, screen_h)
            else:
                self.selected_eid = None

        # Лог поселения
        self._draw_settlement_log(surface, world, screen_w, screen_h)

    # ── Панель агента (правая сторона) ───────────────────────────────

    def _draw_agent_panel(
        self,
        surface: pygame.Surface,
        world: World,
        screen_w: int,
        screen_h: int,
    ) -> None:
        eid = self.selected_eid
        if eid is None:
            return

        font = self._font
        font_s = self._font_small
        font_h = self._font_header

        # Фон панели
        panel_x = screen_w - PANEL_WIDTH
        panel_rect = pygame.Rect(panel_x, 0, PANEL_WIDTH, screen_h - LOG_HEIGHT)
        bg_surf = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
        bg_surf.fill(PANEL_BG)
        surface.blit(bg_surf, panel_rect)
        pygame.draw.rect(surface, PANEL_BORDER, panel_rect, 1)

        y = 10

        # ── Заголовок: имя, возраст, пол, стадия ────────────────────
        identity = world.get_component(eid, Identity)
        body = world.get_component(eid, Body)

        name = identity.name if identity else f"Agent #{eid}"
        name_surf = font_h.render(name, True, COLOR_HEADER)
        surface.blit(name_surf, (panel_x + 10, y))

        # Кнопка Follow справа от имени
        follow_label = "Unfollow" if self.following else "Follow"
        follow_color = (100, 180, 100) if self.following else (80, 80, 100)
        follow_text = font_s.render(follow_label, True, COLOR_TEXT)
        fw = follow_text.get_width() + 10
        fh = 16
        fx = panel_x + PANEL_WIDTH - fw - 10
        fy = y + 2
        self._follow_btn_rect = pygame.Rect(fx, fy, fw, fh)
        pygame.draw.rect(surface, follow_color, self._follow_btn_rect)
        pygame.draw.rect(surface, PANEL_BORDER, self._follow_btn_rect, 1)
        surface.blit(follow_text, (fx + 5, fy + 1))

        y += 22

        if body:
            age_years = round(body.age / config.TICKS_PER_YEAR, 1)
            sex_str = "M" if body.sex == "male" else "F"
            stage = _stage_label(body)
            info = f"{sex_str}  {age_years} лет  [{stage}]"
            surface.blit(font.render(info, True, COLOR_DIM), (panel_x + 10, y))
            y += 18

            if body.is_pregnant:
                pct = round(body.pregnancy_timer / config.PREGNANCY_DURATION_TICKS * 100)
                surface.blit(
                    font.render(f"Беременна: {pct}%", True, COLOR_YELLOW),
                    (panel_x + 10, y),
                )
                y += 18

        y += 6

        # ── NEEDS ────────────────────────────────────────────────────
        surface.blit(font.render("--- NEEDS ---", True, COLOR_SECTION), (panel_x + 10, y))
        y += 18

        needs = world.get_component(eid, Needs)
        if needs:
            for need_name in ("hunger", "thirst", "energy", "health", "mood", "social", "safety"):
                val = getattr(needs, need_name, 0.0)
                y = self._draw_bar(
                    surface, panel_x + 10, y,
                    need_name, val, _bar_color(val), font_s,
                )
        y += 6

        # ── TRAITS ───────────────────────────────────────────────────
        surface.blit(font.render("--- TRAITS ---", True, COLOR_SECTION), (panel_x + 10, y))
        y += 18

        traits = world.get_component(eid, Traits)
        if traits:
            for trait_name in config.TRAIT_NAMES:
                val = getattr(traits, trait_name, 0.5)
                y = self._draw_bar(
                    surface, panel_x + 10, y,
                    trait_name, val, COLOR_TRAIT_BAR, font_s,
                )
        y += 6

        # ── CURRENT ──────────────────────────────────────────────────
        surface.blit(font.render("--- CURRENT ---", True, COLOR_SECTION), (panel_x + 10, y))
        y += 18

        pos = world.get_component(eid, Position)
        if pos:
            action_str = pos.current_action or "idle"
            surface.blit(font_s.render(f"Action: {action_str}", True, COLOR_TEXT), (panel_x + 10, y))
            y += 16
            if pos.target_x is not None and pos.target_y is not None:
                surface.blit(
                    font_s.render(f"Target: ({pos.target_x}, {pos.target_y})", True, COLOR_DIM),
                    (panel_x + 10, y),
                )
                y += 16
            surface.blit(
                font_s.render(f"Pos: ({pos.tile_x}, {pos.tile_y})", True, COLOR_DIM),
                (panel_x + 10, y),
            )
            y += 16
            if pos.action_timer > 0:
                surface.blit(
                    font_s.render(f"Timer: {pos.action_timer}", True, COLOR_DIM),
                    (panel_x + 10, y),
                )
                y += 16
            # Шаг + время
            tick_in_day = world.tick % config.TICKS_PER_DAY
            hour = tick_in_day // config.TICKS_PER_HOUR
            surface.blit(
                font_s.render(f"Step: {world.tick:,}  ({hour:02d}:00)", True, COLOR_DIM),
                (panel_x + 10, y),
            )
            y += 16
        y += 6

        # ── LOG ──────────────────────────────────────────────────────
        surface.blit(font.render("--- LOG ---", True, COLOR_SECTION), (panel_x + 10, y))
        y += 18

        mem = world.get_component(eid, Memory)
        if mem and mem.personal_log:
            entries = mem.personal_log[-10:]
            for entry in reversed(entries):
                tick = entry.get("tick", 0)
                etype = entry.get("type", "?")
                need = entry.get("need", "")
                delta = entry.get("delta", 0.0)
                sign = "+" if delta >= 0 else ""
                line = f"t{tick}: {etype}"
                if need:
                    line += f" (Δ{need} {sign}{delta:.2f})"
                text_surf = font_s.render(line, True, COLOR_DIM)
                surface.blit(text_surf, (panel_x + 10, y))
                y += 14
                if y > panel_rect.bottom - 20:
                    break

    # ── Индикатор времени (верхний левый угол) ───────────────────────

    def _draw_time_indicator(
        self,
        surface: pygame.Surface,
        world: World,
    ) -> None:
        """Рисует время суток, день и шаг в верхнем левом углу."""
        font = self._font
        font_h = self._font_header

        tick_in_day = world.tick % config.TICKS_PER_DAY
        hour = tick_in_day // config.TICKS_PER_HOUR
        minute = (tick_in_day % config.TICKS_PER_HOUR) * 60 // config.TICKS_PER_HOUR
        day = world.tick // config.TICKS_PER_DAY
        is_night = tick_in_day >= config.NIGHT_START_TICK

        # Фон
        bg_w = 220
        bg_h = 44
        bg_surf = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        bg_surf.fill((20, 20, 30, 210))
        surface.blit(bg_surf, (6, 6))
        pygame.draw.rect(surface, PANEL_BORDER, (6, 6, bg_w, bg_h), 1)

        # Строка 1: время + день/ночь
        if is_night:
            time_label = "NIGHT"
            time_color = (130, 140, 200)
        else:
            time_label = "DAY"
            time_color = (240, 210, 100)

        time_str = f"{hour:02d}:{minute:02d}  [{time_label}]"
        surface.blit(font_h.render(time_str, True, time_color), (14, 10))

        # Строка 2: день + тик + скорость
        info_str = f"Day {day}  |  Tick {world.tick:,}  |  {self.speed_label}"
        surface.blit(font.render(info_str, True, COLOR_DIM), (14, 30))

    # ── Лог поселения (нижняя полоса) ────────────────────────────────

    def _draw_settlement_log(
        self,
        surface: pygame.Surface,
        world: World,
        screen_w: int,
        screen_h: int,
    ) -> None:
        font = self._font
        font_s = self._font_small

        log_rect = pygame.Rect(0, screen_h - LOG_HEIGHT, screen_w, LOG_HEIGHT)
        bg_surf = pygame.Surface((log_rect.width, log_rect.height), pygame.SRCALPHA)
        bg_surf.fill(LOG_BG)
        surface.blit(bg_surf, log_rect)
        pygame.draw.line(surface, PANEL_BORDER, (0, log_rect.top), (screen_w, log_rect.top), 1)

        # ── Счётчики ────────────────────────────────────────────────
        population = len(world.entities)
        day = world.tick // config.TICKS_PER_DAY
        tick_in_day = world.tick % config.TICKS_PER_DAY
        hour = tick_in_day // config.TICKS_PER_HOUR
        is_night = tick_in_day >= config.NIGHT_START_TICK
        time_icon = "Night" if is_night else "Day"
        header = f"Pop: {population}  |  Day {day} {hour:02d}:00 [{time_icon}]  |  Tick: {world.tick:,}  |  {self.speed_label}"
        surface.blit(font.render(header, True, COLOR_HEADER), (10, log_rect.top + 4))

        # ── Строки событий ──────────────────────────────────────────
        y = log_rect.top + 22
        for line in self._settlement_log:
            if y > screen_h - 6:
                break
            surface.blit(font_s.render(line, True, COLOR_DIM), (10, y))
            y += 14

    # ── Вспомогательные ──────────────────────────────────────────────

    @staticmethod
    def _draw_bar(
        surface: pygame.Surface,
        x: int,
        y: int,
        label: str,
        value: float,
        color: Tuple[int, int, int],
        font: pygame.font.Font,
    ) -> int:
        """Рисует label + bar + число. Возвращает y следующей строки."""
        value = max(0.0, min(1.0, value))

        # Label (фиксированная ширина)
        label_surf = font.render(f"{label:>12s}", True, COLOR_TEXT)
        surface.blit(label_surf, (x, y))

        bar_x = x + 100
        # Фон бара
        pygame.draw.rect(surface, (50, 50, 60), (bar_x, y + 2, BAR_WIDTH, BAR_HEIGHT))
        # Заполненная часть
        fill_w = int(value * BAR_WIDTH)
        if fill_w > 0:
            pygame.draw.rect(surface, color, (bar_x, y + 2, fill_w, BAR_HEIGHT))
        # Рамка
        pygame.draw.rect(surface, (80, 80, 90), (bar_x, y + 2, BAR_WIDTH, BAR_HEIGHT), 1)
        # Число
        num_surf = font.render(f"{value:.2f}", True, COLOR_DIM)
        surface.blit(num_surf, (bar_x + BAR_WIDTH + 6, y))

        return y + BAR_HEIGHT + 4
