"""
Точка входа — MVP 1.

Создаёт World с картой, спавнит агентов.
--headless: симуляция без окна, вывод статистики в консоль.
--replay: воспроизведение записанного прогона.
Иначе: Pygame окно + симуляция тикает каждый кадр.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pygame

import config
from simulation.map.generator import generate_map, render as render_map
from simulation.world import World
from simulation.factory import create_starter_population
from simulation.components import Body, Identity, Memory, Needs, Position, Traits
from simulation.game_loop import GameLoop
from simulation.systems.time_system import is_night
from storage.logger import SimLogger
from renderer.hud import HUD
from renderer.debug_overlay import DebugOverlay


def _configure_logging(level: int) -> None:
    """Map log-level 0-10 to Python logging config.

    0     — no output
    1-3   — WARNING (errors, critical events)
    4-5   — INFO (daily reports, events)
    6-7   — DEBUG (decisions, paths)
    8-10  — DEBUG + verbose (every tick)
    """
    if level <= 0:
        py_level = logging.CRITICAL + 1  # silence everything
    elif level <= 3:
        py_level = logging.WARNING
    elif level <= 5:
        py_level = logging.INFO
    else:
        py_level = logging.DEBUG

    logging.basicConfig(
        level=py_level,
        format="%(name)s: %(message)s",
        force=True,
    )


def print_daily_report(world: World, game_loop: GameLoop) -> None:
    """Печатает средние потребности по всем агентам."""
    agents = list(world.get_all_with(Needs))
    if not agents:
        return

    count = len(agents)
    day = world.tick // config.TICKS_PER_DAY

    sums = {
        "hunger": 0.0, "thirst": 0.0, "energy": 0.0,
        "health": 0.0, "mood": 0.0, "social": 0.0, "safety": 0.0,
    }
    for _, needs in agents:
        for key in sums:
            sums[key] += getattr(needs, key)

    avgs = {k: v / count for k, v in sums.items()}
    night_str = "night" if is_night(world) else "day"

    # Статистика памяти
    memories = list(world.get_all_with(Memory))
    if memories:
        total_known = sum(len(m.known_tiles) for _, m in memories)
        avg_known = total_known / len(memories)
        know_food = sum(1 for _, m in memories if m.resource_locations.get("food"))
        know_water = sum(1 for _, m in memories if m.resource_locations.get("water"))
        mem_str = f" | tiles_known: {avg_known:.0f} | food: {know_food}/{len(memories)} | water: {know_water}/{len(memories)}"
    else:
        mem_str = ""

    # Статистика социализации
    social_sys = game_loop.social_system
    social_count = social_sys.daily_social_count
    socialized_agents = len(social_sys.daily_socialized_agents)
    unsocialized = count - socialized_agents
    social_str = f" | social_events: {social_count} | unsocialized: {unsocialized}/{count}"

    # Статистика размножения
    repro_sys = game_loop.reproduction_system
    pregnant_count = sum(
        1 for _, b in world.get_all_with(Body) if b.is_pregnant
    )
    repro_str = f" | pregnant: {pregnant_count} | births: {repro_sys.daily_births}"

    parts = " | ".join(f"{k}: {v:.2f}" for k, v in avgs.items())
    if config.LOG_LEVEL >= 4:
        print(f"[Day {day:>4} | {night_str}] {parts}  ({count} agents){mem_str}{social_str}{repro_str}")


# ═══════════════════════════════════════════════════════════════════════
# Replay mode
# ═══════════════════════════════════════════════════════════════════════


def _read_jsonl(path: Path) -> List[dict]:
    """Читает JSON Lines файл."""
    records: List[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_snapshots(agents_path: Path) -> Dict[int, List[dict]]:
    """Группирует записи agents.jsonl по тику.

    Возвращает {tick: [record, ...]} отсортированный по тику.
    """
    records = _read_jsonl(agents_path)
    by_tick: Dict[int, List[dict]] = {}
    for rec in records:
        t = rec.get("tick", 0)
        by_tick.setdefault(t, []).append(rec)
    return dict(sorted(by_tick.items()))


def _find_nearest_tick(snapshot_ticks: List[int], target: int) -> int:
    """Находит ближайший snapshot-тик к target."""
    if not snapshot_ticks:
        return 0
    best = snapshot_ticks[0]
    best_dist = abs(best - target)
    for t in snapshot_ticks:
        d = abs(t - target)
        if d < best_dist:
            best = t
            best_dist = d
    return best


def _populate_world_from_snapshot(
    world: World,
    agents: List[dict],
    tick: int,
) -> None:
    """Загружает агентов из snapshot-записей в World (без симуляции)."""
    # Очищаем старые данные
    world.entities.clear()
    world.components.clear()
    world.tick = tick

    for rec in agents:
        eid = rec.get("id", 0)
        world.entities.add(eid)
        # Обновляем _next_id чтобы не было конфликтов
        if eid >= world._next_id:
            world._next_id = eid + 1

        # Position
        tile = rec.get("tile", [0, 0])
        pos = Position(
            float_x=float(tile[0]),
            float_y=float(tile[1]),
            tile_x=int(tile[0]),
            tile_y=int(tile[1]),
            current_action=rec.get("current_action"),
        )
        world.add_component(eid, pos)

        # Body
        age_years = rec.get("age_years", 0.0)
        age_ticks = int(age_years * config.TICKS_PER_YEAR)
        stage = rec.get("stage", "adult")
        body = Body(
            age=age_ticks,
            sex=rec.get("sex", "male"),
            is_child=(stage == "child"),
        )
        world.add_component(eid, body)

        # Identity
        identity = Identity(name=rec.get("name", ""))
        world.add_component(eid, identity)

        # Needs
        needs_data = rec.get("needs")
        if needs_data:
            needs = Needs(
                hunger=needs_data.get("hunger", 1.0),
                thirst=needs_data.get("thirst", 1.0),
                energy=needs_data.get("energy", 1.0),
                health=needs_data.get("health", 1.0),
                mood=needs_data.get("mood", 1.0),
                social=needs_data.get("social", 1.0),
                safety=needs_data.get("safety", 1.0),
            )
            world.add_component(eid, needs)

        # Traits
        traits_data = rec.get("traits")
        if traits_data:
            traits = Traits(
                fearfulness=traits_data.get("fearfulness", 0.5),
                sociality=traits_data.get("sociality", 0.5),
                curiosity=traits_data.get("curiosity", 0.5),
                resilience=traits_data.get("resilience", 0.5),
                faith=traits_data.get("faith", 0.5),
            )
            world.add_component(eid, traits)

        # Memory (пустая — в snapshot не пишется)
        world.add_component(eid, Memory())


def run_replay(run_dir: str, start_tick: int) -> None:
    """Режим replay — просмотр записанного прогона."""
    run_path = Path(run_dir)
    agents_path = run_path / "agents.jsonl"
    meta_path = run_path / "meta.json"

    if not agents_path.exists():
        print(f"Error: {agents_path} not found")
        sys.exit(1)

    # Читаем meta для seed
    seed = 42
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        seed = meta.get("seed", 42)

    # Загружаем snapshots
    print(f"Loading snapshots from {agents_path}...")
    snapshots = _load_snapshots(agents_path)
    snapshot_ticks = list(snapshots.keys())

    if not snapshot_ticks:
        print("Error: no snapshots found in agents.jsonl")
        sys.exit(1)

    total_ticks = snapshot_ticks[-1]
    print(f"Loaded {len(snapshot_ticks)} snapshots, ticks {snapshot_ticks[0]}..{total_ticks}")

    # Начальный тик
    current_tick = _find_nearest_tick(snapshot_ticks, start_tick)
    current_idx = snapshot_ticks.index(current_tick)

    # Создаём карту и мир
    tile_map = generate_map(seed=seed)
    world = World(tile_map)
    _populate_world_from_snapshot(world, snapshots[current_tick], current_tick)

    # ── Pygame ────────────────────────────────────────────────────────
    tile_size = 12
    viewport_w = config.VIEWPORT_WIDTH
    viewport_h = config.VIEWPORT_HEIGHT
    screen_w = viewport_w * tile_size
    screen_h = viewport_h * tile_size

    pygame.init()
    screen = pygame.display.set_mode((screen_w, screen_h))
    pygame.display.set_caption(f"Replay — {run_path.name}")

    cam_x = tile_map.width // 2 - viewport_w // 2
    cam_y = tile_map.height // 2 - viewport_h // 2

    hud = HUD()
    hud.speed_label = "REPLAY"
    debug_overlay = DebugOverlay()

    clock = pygame.time.Clock()
    running = True

    # Шрифты для таймлайна
    font_tl = None

    # ── Переключаемый шаг (в снапшотах) ─────────────────────────────
    snap_interval = snapshot_ticks[1] - snapshot_ticks[0] if len(snapshot_ticks) > 1 else 100
    STEP_OPTIONS = [1, 2, 5, 10]  # кол-во снапшотов за шаг
    step_idx = 0  # default = 1 снапшот
    step_snaps = STEP_OPTIONS[step_idx]
    step_ticks = step_snaps * snap_interval  # для отображения

    # ── Скорость камеры ─────────────────────────────────────────────
    cam_speed = 3  # тайлов за кадр

    def goto_snapshot(idx: int) -> None:
        nonlocal current_idx, current_tick
        idx = max(0, min(len(snapshot_ticks) - 1, idx))
        current_idx = idx
        current_tick = snapshot_ticks[current_idx]
        saved_eid = hud.selected_eid
        _populate_world_from_snapshot(world, snapshots[current_tick], current_tick)
        # Сохраняем выбор агента, если он ещё жив в этом снапшоте
        if saved_eid is not None and world.get_component(saved_eid, Position):
            hud.selected_eid = saved_eid
        else:
            hud.selected_eid = None

    def _jump_snaps(delta: int) -> None:
        """Прыжок на delta снапшотов (+ вперёд, - назад)."""
        goto_snapshot(current_idx + delta)

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F3:
                    debug_overlay.toggle()
                elif event.key == pygame.K_h:
                    hud.toggle()
                elif event.key == pygame.K_RIGHTBRACKET:
                    # ] — увеличить шаг
                    step_idx = min(len(STEP_OPTIONS) - 1, step_idx + 1)
                    step_snaps = STEP_OPTIONS[step_idx]
                    step_ticks = step_snaps * snap_interval
                elif event.key == pygame.K_LEFTBRACKET:
                    # [ — уменьшить шаг
                    step_idx = max(0, step_idx - 1)
                    step_snaps = STEP_OPTIONS[step_idx]
                    step_ticks = step_snaps * snap_interval
                elif event.key == pygame.K_RIGHT:
                    # ▶ вперёд на step_snaps снапшотов
                    _jump_snaps(step_snaps)
                elif event.key == pygame.K_LEFT:
                    # ◀ назад на step_snaps снапшотов
                    _jump_snaps(-step_snaps)
                elif event.key in (pygame.K_PAGEDOWN, pygame.K_DOWN):
                    # ▶▶ прыжок на 1 день вперёд
                    day_snaps = max(1, config.TICKS_PER_DAY // snap_interval)
                    _jump_snaps(day_snaps)
                elif event.key in (pygame.K_PAGEUP, pygame.K_UP):
                    # ◀◀ прыжок на 1 день назад
                    day_snaps = max(1, config.TICKS_PER_DAY // snap_interval)
                    _jump_snaps(-day_snaps)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                # Проверяем клики по кнопкам таймлайна
                tl_y = screen_h - 150  # над логом
                if not _handle_timeline_click(
                    mx, my, tl_y, screen_w,
                    current_idx, snapshot_ticks, goto_snapshot,
                    step_snaps=step_snaps,
                    snap_interval=snap_interval,
                    jump_snaps_fn=_jump_snaps,
                ):
                    hud.handle_click(
                        world, mx, my, cam_x, cam_y,
                        tile_size, screen_w, screen_h,
                    )

        # ── Камера (WASD) ────────────────────────────────────────────
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            cam_y = max(0, cam_y - cam_speed)
        if keys[pygame.K_s]:
            cam_y = min(tile_map.height - viewport_h, cam_y + cam_speed)
        if keys[pygame.K_a]:
            cam_x = max(0, cam_x - cam_speed)
        if keys[pygame.K_d]:
            cam_x = min(tile_map.width - viewport_w, cam_x + cam_speed)

        # Follow: центрируем камеру на выбранном агенте
        follow_pos = hud.get_follow_pos(world)
        if follow_pos is not None:
            cam_x = follow_pos[0] - viewport_w // 2
            cam_y = follow_pos[1] - viewport_h // 2
            cam_x = max(0, min(tile_map.width - viewport_w, cam_x))
            cam_y = max(0, min(tile_map.height - viewport_h, cam_y))

        # ── Рисуем ────────────────────────────────────────────────────
        render_map(screen, tile_map, cam_x, cam_y, tile_size)

        # Агенты
        for eid, pos in world.get_all_with(Position):
            sx = int(pos.float_x - cam_x) * tile_size + tile_size // 2
            sy = int(pos.float_y - cam_y) * tile_size + tile_size // 2
            if 0 <= sx < screen_w and 0 <= sy < screen_h:
                # Цвет по состоянию
                color = _agent_color(world, eid)
                pygame.draw.circle(screen, color, (sx, sy), config.AGENT_DOT_RADIUS)

                # Имя над агентом
                identity = world.get_component(eid, Identity)
                if identity and font_tl is None:
                    font_tl = pygame.font.SysFont("consolas", 11)
                if identity and font_tl:
                    name_surf = font_tl.render(identity.name, True, (200, 200, 200))
                    screen.blit(name_surf, (sx - name_surf.get_width() // 2, sy - 16))

        # Debug overlay
        debug_overlay.draw(screen, world, cam_x, cam_y, tile_size)

        # Таймлайн
        _draw_timeline(
            screen, current_tick, total_ticks, current_idx,
            len(snapshot_ticks), screen_w, screen_h,
            step_ticks=step_ticks,
        )

        # HUD (поверх всего)
        hud.draw(screen, world)

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()


def _agent_color(world: World, eid: int) -> Tuple[int, int, int]:
    """Определяет цвет агента по состоянию."""
    needs = world.get_component(eid, Needs)
    pos = world.get_component(eid, Position)

    if pos and pos.current_action == "sleeping":
        return config.AGENT_COLOR_SLEEPING

    if needs:
        # Проверяем критические потребности
        for need_name, threshold in config.CRITICAL_THRESHOLD.items():
            val = getattr(needs, need_name, 1.0)
            if val <= threshold * 0.5:
                return config.AGENT_COLOR_DYING
            if val <= threshold:
                return config.AGENT_COLOR_CRITICAL

    return config.AGENT_COLOR_NORMAL


def _draw_timeline(
    surface: pygame.Surface,
    current_tick: int,
    total_ticks: int,
    current_idx: int,
    total_snapshots: int,
    screen_w: int,
    screen_h: int,
    step_ticks: int = 100,
) -> None:
    """Рисует панель управления таймлайном над логом."""
    font = pygame.font.SysFont("consolas", 13, bold=True)
    font_s = pygame.font.SysFont("consolas", 12)

    tl_y = screen_h - 150  # над логом (LOG_HEIGHT=120 + 30px)
    tl_h = 28

    # Фон
    bg = pygame.Surface((screen_w, tl_h), pygame.SRCALPHA)
    bg.fill((25, 25, 35, 230))
    surface.blit(bg, (0, tl_y))

    # Кнопки
    btn_w = 36
    btn_h = 22
    btn_y = tl_y + 3
    buttons = ["<<", "<", None, ">", ">>"]  # None = текст посередине
    start_x = screen_w // 2 - 180

    x = start_x
    for label in buttons:
        if label is None:
            # Текст тика + время суток
            day = current_tick // config.TICKS_PER_DAY
            tick_in_day = current_tick % config.TICKS_PER_DAY
            hour = tick_in_day // config.TICKS_PER_HOUR
            is_night = tick_in_day >= config.NIGHT_START_TICK
            time_icon = "N" if is_night else "D"
            text = (f"Day {day} {hour:02d}:00 [{time_icon}]  "
                    f"tick {current_tick:,}/{total_ticks:,}  [{current_idx + 1}/{total_snapshots}]")
            text_surf = font_s.render(text, True, (200, 200, 220))
            surface.blit(text_surf, (x + 4, btn_y + 3))
            x += text_surf.get_width() + 16
            continue

        btn_rect = pygame.Rect(x, btn_y, btn_w, btn_h)
        pygame.draw.rect(surface, (60, 60, 80), btn_rect)
        pygame.draw.rect(surface, (100, 100, 120), btn_rect, 1)
        lbl = font.render(label, True, (220, 220, 230))
        surface.blit(lbl, (x + (btn_w - lbl.get_width()) // 2, btn_y + 2))
        x += btn_w + 6

    # Подсказки + текущий шаг
    help_text = f"←/→: ±{step_ticks}t  [/]: step  ↑/↓: ±1 day  WASD: cam  F3: debug  H: hud"
    help_surf = font_s.render(help_text, True, (100, 100, 120))
    surface.blit(help_surf, (10, tl_y + 7))

    # Индикатор шага справа
    step_text = f"step: {step_ticks}t"
    step_surf = font_s.render(step_text, True, (180, 180, 80))
    surface.blit(step_surf, (screen_w - step_surf.get_width() - 10, tl_y + 7))


def _handle_timeline_click(
    mx: int,
    my: int,
    tl_y: int,
    screen_w: int,
    current_idx: int,
    snapshot_ticks: List[int],
    goto_fn,
    step_snaps: int = 1,
    snap_interval: int = 100,
    jump_snaps_fn=None,
) -> bool:
    """Обрабатывает клик по кнопкам таймлайна. Возвращает True если попал."""
    tl_h = 28
    if not (tl_y <= my <= tl_y + tl_h):
        return False

    btn_w = 36
    btn_y = tl_y + 3
    start_x = screen_w // 2 - 180

    # Определяем позиции кнопок (4 кнопки, текст между 2-й и 3-й)
    btn_rects = []
    x = start_x
    for i, label in enumerate(["<<", "<", None, ">", ">>"]):
        if label is None:
            x += 200  # примерная ширина текста
            continue
        btn_rects.append((pygame.Rect(x, btn_y, btn_w, 22), label))
        x += btn_w + 6

    for rect, label in btn_rects:
        if rect.collidepoint(mx, my):
            if jump_snaps_fn:
                day_snaps = max(1, config.TICKS_PER_DAY // snap_interval)
                if label == ">>":
                    jump_snaps_fn(day_snaps)
                elif label == "<<":
                    jump_snaps_fn(-day_snaps)
                elif label == ">":
                    jump_snaps_fn(step_snaps)
                elif label == "<":
                    jump_snaps_fn(-step_snaps)
            else:
                if label == ">":
                    goto_fn(current_idx + 1)
                elif label == "<":
                    goto_fn(current_idx - 1)
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="Settlement simulation — MVP 1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--ticks", type=int, default=0,
                        help="Headless: кол-во тиков для прогона (0 = бесконечно)")
    parser.add_argument("--log", action="store_true",
                        help="Включить структурированное логирование в logs/")
    parser.add_argument("--snap", type=int, default=5,
                        help="Интервал снапшотов в тиках (default: 5)")
    parser.add_argument("--replay", type=str, default=None,
                        help="Путь к папке прогона для воспроизведения")
    parser.add_argument("--tick", type=int, default=0,
                        help="Replay: начальный тик")
    parser.add_argument("--log-level", type=int, default=5,
                        help="Уровень логирования 0-10 (default: 5)")
    args = parser.parse_args()

    config.DEBUG = args.debug
    config.LOG_SNAPSHOT_INTERVAL = args.snap
    config.LOG_STATS_INTERVAL = args.snap
    config.LOG_LEVEL = args.log_level

    # Настройка Python logging на основе log-level
    _configure_logging(args.log_level)

    # ── Replay mode ──────────────────────────────────────────────────
    if args.replay:
        run_replay(args.replay, args.tick)
        return

    rng = random.Random(args.seed)

    # ── Создание мира ──────────────────────────────────────────────
    tile_map = generate_map(seed=args.seed)
    world = World(tile_map)
    eids = create_starter_population(world, rng=rng)

    # ── Логгер ────────────────────────────────────────────────────
    logger = None
    if args.headless or args.log:
        logger = SimLogger(seed=args.seed, config_snapshot=config.get_config_snapshot())

    game_loop = GameLoop(logger=logger)

    if config.LOG_LEVEL >= 1:
        print(f"Created {len(eids)} agents. Seed={args.seed}")
    if logger and config.LOG_LEVEL >= 1:
        print(f"Logging to: {logger.run_dir}")

    # ── Headless ───────────────────────────────────────────────────
    if args.headless:
        ticks = args.ticks if args.ticks > 0 else config.TICKS_PER_YEAR
        for _ in range(ticks):
            game_loop.tick(world)
            if world.tick % config.TICKS_PER_DAY == 0:
                print_daily_report(world, game_loop)
        print_daily_report(world, game_loop)
        if logger:
            log_path = logger.close(world)
            print(f"Logs saved to: {log_path}")
        return

    # ── Pygame ─────────────────────────────────────────────────────
    tile_size = 12
    viewport_w = config.VIEWPORT_WIDTH
    viewport_h = config.VIEWPORT_HEIGHT
    screen_w = viewport_w * tile_size
    screen_h = viewport_h * tile_size

    pygame.init()
    screen = pygame.display.set_mode((screen_w, screen_h))
    pygame.display.set_caption("Settlement Sim — MVP 1")

    cam_x = tile_map.width // 2 - viewport_w // 2
    cam_y = tile_map.height // 2 - viewport_h // 2

    hud = HUD()
    debug_overlay = DebugOverlay()

    clock = pygame.time.Clock()
    running = True
    font_name = None
    paused = False
    speed_multiplier = 1
    speed_labels = {1: "x1", 100: "x100", 1000: "x1K", 10000: "x10K"}

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_d:
                    debug_overlay.toggle()
                elif event.key == pygame.K_h:
                    hud.toggle()
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                    hud.speed_label = "PAUSED" if paused else speed_labels[speed_multiplier]
                elif event.key == pygame.K_1:
                    speed_multiplier = 1
                    hud.speed_label = speed_labels[1]
                elif event.key == pygame.K_2:
                    speed_multiplier = 100
                    hud.speed_label = speed_labels[100]
                elif event.key == pygame.K_3:
                    speed_multiplier = 1000
                    hud.speed_label = speed_labels[1000]
                elif event.key == pygame.K_4:
                    speed_multiplier = 10000
                    hud.speed_label = speed_labels[10000]
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hud.handle_click(
                    world, event.pos[0], event.pos[1],
                    cam_x, cam_y, tile_size, screen_w, screen_h,
                )

        # Тики симуляции
        if not paused:
            for _tick_i in range(speed_multiplier):
                game_loop.tick(world)
                if not world.entities:
                    break

        # Собираем события для HUD
        hud.collect_events(world)

        # Curiosity tracking для debug overlay
        debug_overlay.notify_curiosity_agents(world)

        # Ежедневный отчёт в консоль
        if world.tick % config.TICKS_PER_DAY == 0:
            print_daily_report(world, game_loop)

        # Follow: центрируем камеру на выбранном агенте
        follow_pos = hud.get_follow_pos(world)
        if follow_pos is not None:
            cam_x = follow_pos[0] - viewport_w // 2
            cam_y = follow_pos[1] - viewport_h // 2
            cam_x = max(0, min(tile_map.width - viewport_w, cam_x))
            cam_y = max(0, min(tile_map.height - viewport_h, cam_y))

        # Рисуем карту
        render_map(screen, tile_map, cam_x, cam_y, tile_size)

        # Рисуем агентов
        for eid, pos in world.get_all_with(Position):
            sx = int(pos.float_x - cam_x) * tile_size + tile_size // 2
            sy = int(pos.float_y - cam_y) * tile_size + tile_size // 2
            if 0 <= sx < screen_w and 0 <= sy < screen_h:
                color = _agent_color(world, eid)
                pygame.draw.circle(screen, color, (sx, sy), config.AGENT_DOT_RADIUS)

                # Имя над агентом
                identity = world.get_component(eid, Identity)
                if identity:
                    if font_name is None:
                        font_name = pygame.font.SysFont("consolas", 11)
                    name_surf = font_name.render(identity.name, True, (200, 200, 200))
                    screen.blit(name_surf, (sx - name_surf.get_width() // 2, sy - 16))

        # Debug overlay
        debug_overlay.draw(screen, world, cam_x, cam_y, tile_size)

        # HUD
        hud.draw(screen, world)

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()

    if logger:
        log_path = logger.close(world)
        print(f"Logs saved to: {log_path}")


if __name__ == "__main__":
    main()
