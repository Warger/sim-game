"""
SimLogger — структурированное логирование прогонов в JSON Lines.

Папка прогона: logs/run_{seed}_{timestamp}/
    meta.json       — параметры запуска
    events.jsonl    — одно событие на строку
    agents.jsonl    — снимок всех агентов каждые N тиков
    stats.jsonl     — агрегированные метрики каждые N тиков
    deaths.jsonl    — детальная запись каждой смерти
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.identity import Identity
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits


def _json_line(obj: dict) -> str:
    """Сериализует dict в одну JSON-строку."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class _BufferedWriter:
    """Буферизированный писатель JSONL — собирает строки и пишет пачкой."""

    __slots__ = ("_file", "_buf", "_capacity")

    def __init__(self, path, capacity: int) -> None:
        self._file = open(path, "w", encoding="utf-8")
        self._buf: list[str] = []
        self._capacity = capacity

    def write_line(self, line: str) -> None:
        self._buf.append(line)
        if len(self._buf) >= self._capacity:
            self.flush()

    def flush(self) -> None:
        if self._buf:
            self._file.write("\n".join(self._buf))
            self._file.write("\n")
            self._buf.clear()

    def close(self) -> None:
        self.flush()
        self._file.close()


def _stage(body: Body) -> str:
    """Определяет стадию жизни по возрасту."""
    if body.is_child:
        return "child"
    if body.age >= config.ADULT_END_TICKS:
        return "elder"
    return "adult"


class SimLogger:
    """Логгер одного прогона симуляции."""

    def __init__(self, seed: int, config_snapshot: Optional[Dict[str, Any]] = None) -> None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path("logs") / f"run_{seed}_{timestamp}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.seed = seed
        self._start_time = time.time()
        self._total_births = 0
        self._total_deaths = 0

        # Буферизированные писатели
        buf = config.LOG_BUFFER_SIZE
        self._events_f = _BufferedWriter(self.run_dir / "events.jsonl", buf)
        self._agents_f = _BufferedWriter(self.run_dir / "agents.jsonl", buf)
        self._stats_f = _BufferedWriter(self.run_dir / "stats.jsonl", buf)
        self._deaths_f = _BufferedWriter(self.run_dir / "deaths.jsonl", buf)

        # Пишем meta.json сразу
        snapshot = config_snapshot or {}
        meta = {
            "seed": seed,
            "timestamp": timestamp,
            "config": snapshot,
            "start_agent_count": config.START_AGENT_COUNT,
            "map_size": [config.MAP_WIDTH, config.MAP_HEIGHT],
            "log_snapshot_interval": config.LOG_SNAPSHOT_INTERVAL,
            "log_stats_interval": config.LOG_STATS_INTERVAL,
        }
        (self.run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── Events ───────────────────────────────────────────────────────

    def log_event(self, tick: int, event_dict: Dict[str, Any]) -> None:
        """Пишет событие в events.jsonl, добавляя tick."""
        record = {"tick": tick, **event_dict}
        self._events_f.write_line(_json_line(record))

        if event_dict.get("type") == "birth":
            self._total_births += 1
        elif event_dict.get("type") == "death":
            self._total_deaths += 1

    # ── Agent snapshot ───────────────────────────────────────────────

    def log_snapshot(self, world: World) -> None:
        """Пишет снимок всех агентов в agents.jsonl."""
        for eid in world.entities:
            body = world.get_component(eid, Body)
            if body is None:
                continue

            identity = world.get_component(eid, Identity)
            needs = world.get_component(eid, Needs)
            traits = world.get_component(eid, Traits)
            pos = world.get_component(eid, Position)

            record: Dict[str, Any] = {
                "tick": world.tick,
                "id": eid,
                "name": identity.name if identity else "",
                "age_years": round(body.age / config.TICKS_PER_YEAR, 2),
                "sex": body.sex,
                "stage": _stage(body),
            }

            if needs:
                record["needs"] = {
                    "hunger": round(needs.hunger, 4),
                    "thirst": round(needs.thirst, 4),
                    "energy": round(needs.energy, 4),
                    "health": round(needs.health, 4),
                    "mood": round(needs.mood, 4),
                    "social": round(needs.social, 4),
                    "safety": round(needs.safety, 4),
                }

            if traits:
                record["traits"] = {
                    "fearfulness": round(traits.fearfulness, 4),
                    "sociality": round(traits.sociality, 4),
                    "curiosity": round(traits.curiosity, 4),
                    "resilience": round(traits.resilience, 4),
                    "faith": round(traits.faith, 4),
                }

            if pos:
                record["current_action"] = pos.current_action
                record["tile"] = [pos.tile_x, pos.tile_y]

            self._agents_f.write_line(_json_line(record))

    # ── Stats ────────────────────────────────────────────────────────

    def log_stats(self, world: World, game_loop: Any) -> None:
        """Пишет агрегированные метрики в stats.jsonl."""
        agents = list(world.get_all_with(Needs))
        population = len(agents)

        if population == 0:
            record = {
                "tick": world.tick,
                "day": world.tick // config.TICKS_PER_DAY,
                "population": 0,
            }
            self._stats_f.write_line(_json_line(record))
            return

        # Средние потребности
        sums: Dict[str, float] = {
            "hunger": 0.0, "thirst": 0.0, "energy": 0.0,
            "health": 0.0, "mood": 0.0, "social": 0.0, "safety": 0.0,
        }
        for _, needs in agents:
            for key in sums:
                sums[key] += getattr(needs, key)
        avg_needs = {k: round(v / population, 4) for k, v in sums.items()}

        # Распределение действий
        action_counts: Dict[str, int] = {}
        for eid in world.entities:
            pos = world.get_component(eid, Position)
            if pos and pos.current_action:
                action_counts[pos.current_action] = action_counts.get(pos.current_action, 0) + 1

        # Статистика из систем
        repro = game_loop.reproduction_system
        death = game_loop.death_system
        social = game_loop.social_system

        record = {
            "tick": world.tick,
            "day": world.tick // config.TICKS_PER_DAY,
            "population": population,
            "avg_needs": avg_needs,
            "action_distribution": action_counts,
            "births_today": getattr(repro, "daily_births", 0),
            "deaths_today": sum(getattr(death, "daily_deaths", {}).values()),
            "social_events": getattr(social, "daily_social_count", 0),
        }
        self._stats_f.write_line(_json_line(record))

    # ── Deaths ───────────────────────────────────────────────────────

    def log_death(self, tick: int, event_dict: Dict[str, Any],
                  world: World) -> None:
        """Пишет расширенную запись смерти в deaths.jsonl."""
        eid = event_dict.get("eid")
        personal_log = []
        if eid is not None:
            mem = world.get_component(eid, Memory)
            if mem:
                personal_log = list(mem.personal_log)

        record = {
            "tick": tick,
            **event_dict,
            "personal_log": personal_log,
        }
        self._deaths_f.write_line(_json_line(record))

    # ── Close ────────────────────────────────────────────────────────

    def close(self, world: World) -> str:
        """Финальный снимок, итоговая статистика в meta.json, закрытие файлов."""
        # Финальный снимок агентов
        self.log_snapshot(world)

        # Обновляем meta.json итогами
        meta_path = self.run_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["final"] = {
            "total_ticks": world.tick,
            "total_days": world.tick // config.TICKS_PER_DAY,
            "final_population": len(world.entities),
            "total_births": self._total_births,
            "total_deaths": self._total_deaths,
            "elapsed_seconds": round(time.time() - self._start_time, 2),
        }
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Flush и закрываем файлы
        self._events_f.close()
        self._agents_f.close()
        self._stats_f.close()
        self._deaths_f.close()

        return str(self.run_dir)
