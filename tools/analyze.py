"""
Анализ логов после batch-прогонов.

CLI:
    python tools/analyze.py --runs logs/batch_001
    python tools/analyze.py --runs logs/batch_001 --jump 31400

Читает все папки run_* внутри --runs, анализирует:
    meta.json, stats.jsonl, deaths.jsonl, events.jsonl, agents.jsonl

Генерирует консольный отчёт и сохраняет analysis_report.json.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Добавляем корень проекта в sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config


# ── Чтение данных ──────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Читает JSON Lines файл. Пропускает пустые и битые строки."""
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _read_meta(path: Path) -> Dict[str, Any]:
    """Читает meta.json."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ── Данные одного прогона ──────────────────────────────────────────────

class RunData:
    """Загруженные данные одного run_* каталога."""

    __slots__ = (
        "run_dir", "seed", "meta",
        "stats", "deaths", "events", "agents",
        "ticks_run", "final_population", "total_births", "total_deaths",
    )

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.meta = _read_meta(run_dir / "meta.json")
        self.stats = _read_jsonl(run_dir / "stats.jsonl")
        self.deaths = _read_jsonl(run_dir / "deaths.jsonl")
        self.events = _read_jsonl(run_dir / "events.jsonl")
        self.agents = _read_jsonl(run_dir / "agents.jsonl")

        self.seed = self.meta.get("seed", -1)

        final = self.meta.get("final", {})
        self.ticks_run = final.get("total_ticks", 0)
        self.final_population = final.get("final_population", 0)
        self.total_births = final.get("total_births", 0)
        self.total_deaths = final.get("total_deaths", 0)

        # Если meta не содержит final, попробуем восстановить из stats
        if self.ticks_run == 0 and self.stats:
            self.ticks_run = self.stats[-1].get("tick", 0)
        if self.final_population == 0 and self.stats:
            self.final_population = self.stats[-1].get("population", 0)


def _load_runs(runs_dir: Path) -> List[RunData]:
    """Загружает все run_* каталоги."""
    run_dirs = sorted(runs_dir.glob("run_*"))
    if not run_dirs:
        print(f"No run_* directories found in {runs_dir}")
        sys.exit(1)
    runs = []
    for d in run_dirs:
        if d.is_dir():
            runs.append(RunData(d))
    runs.sort(key=lambda r: r.seed)
    return runs


# ── Вспомогательные ────────────────────────────────────────────────────

def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


# ── Анализ выживаемости ────────────────────────────────────────────────

def _analyze_survival(runs: List[RunData]) -> Dict[str, Any]:
    survived = [r for r in runs if r.final_population > 0]
    extinct = [r for r in runs if r.final_population == 0]

    extinction_ticks = [r.ticks_run for r in extinct]
    median_extinction = _median(extinction_ticks) if extinction_ticks else None

    # Причины вымирания: последняя смерть каждого вымершего прогона
    cause_counter: Counter = Counter()
    for r in extinct:
        if r.deaths:
            last_cause = r.deaths[-1].get("cause", "unknown")
            cause_counter[last_cause] += 1
        elif r.total_births == 0:
            cause_counter["no_births"] += 1
        else:
            cause_counter["unknown"] += 1

    return {
        "survived_count": len(survived),
        "extinct_count": len(extinct),
        "total": len(runs),
        "survival_pct": round(len(survived) / len(runs) * 100) if runs else 0,
        "median_extinction_tick": int(median_extinction) if median_extinction else None,
        "extinction_causes": dict(cause_counter.most_common()),
    }


# ── Анализ популяции ──────────────────────────────────────────────────

def _analyze_population(runs: List[RunData]) -> Dict[str, Any]:
    all_final = [r.final_population for r in runs]

    # Пик популяции
    peak_pop = 0
    peak_tick = 0
    peak_seed = -1
    for r in runs:
        for s in r.stats:
            pop = s.get("population", 0)
            if pop > peak_pop:
                peak_pop = pop
                peak_tick = s.get("tick", 0)
                peak_seed = r.seed

    return {
        "avg_final": round(_mean(all_final), 1),
        "min_final": min(all_final) if all_final else 0,
        "max_final": max(all_final) if all_final else 0,
        "peak_population": peak_pop,
        "peak_tick": peak_tick,
        "peak_seed": peak_seed,
    }


# ── Анализ потребностей ────────────────────────────────────────────────

_NEED_NAMES = ("hunger", "thirst", "energy", "health", "mood", "social", "safety")


def _analyze_needs(runs: List[RunData]) -> Dict[str, Dict[str, float]]:
    """Средние значения потребностей и стандартное отклонение."""
    # Собираем средние по каждому прогону, потом avg/std по прогонам
    per_run_avgs: Dict[str, List[float]] = {n: [] for n in _NEED_NAMES}

    for r in runs:
        need_sums: Dict[str, float] = {n: 0.0 for n in _NEED_NAMES}
        count = 0
        for s in r.stats:
            avg_needs = s.get("avg_needs")
            if avg_needs and s.get("population", 0) > 0:
                for n in _NEED_NAMES:
                    need_sums[n] += avg_needs.get(n, 0.0)
                count += 1
        if count > 0:
            for n in _NEED_NAMES:
                per_run_avgs[n].append(need_sums[n] / count)

    result = {}
    for n in _NEED_NAMES:
        vals = per_run_avgs[n]
        result[n] = {
            "mean": round(_mean(vals), 2),
            "std": round(_std(vals), 2),
        }
    return result


# ── Анализ поведения ───────────────────────────────────────────────────

def _analyze_behaviour(runs: List[RunData]) -> Dict[str, float]:
    """Распределение действий (% от всех)."""
    total_actions: Counter = Counter()
    for r in runs:
        for s in r.stats:
            dist = s.get("action_distribution", {})
            for action, cnt in dist.items():
                total_actions[action] += cnt

    grand_total = sum(total_actions.values())
    if grand_total == 0:
        return {}

    return {
        action: round(cnt / grand_total * 100, 1)
        for action, cnt in total_actions.most_common()
    }


# ── Автофлаги ──────────────────────────────────────────────────────────

FLAG_LEVELS = {
    "EXTINCTION_EARLY": "red",
    "NO_BIRTHS": "red",
    "STUCK_AGENTS": "red",
    "LOW_POPULATION": "yellow",
    "THIRST_CRISIS": "yellow",
    "GROWTH_UNSTABLE": "yellow",
    "OVERGROWTH": "orange",
    "STABLE": "green",
}

FLAG_EMOJI = {
    "red": "\U0001f534",      # 🔴
    "yellow": "\U0001f7e1",   # 🟡
    "orange": "\U0001f7e0",   # 🟠
    "green": "\U0001f7e2",    # 🟢
}

FLAG_DESC = {
    "EXTINCTION_EARLY": "вымерли до тика 10 000",
    "NO_BIRTHS": "0 рождений за 20 000 тиков",
    "STUCK_AGENTS": "агент на одном тайле 500+ тиков",
    "LOW_POPULATION": "популяция < 5 дольше 5 000 тиков",
    "THIRST_CRISIS": "avg thirst < 0.3 дольше 1 000 тиков",
    "GROWTH_UNSTABLE": "популяция резко растёт и падает циклично",
    "OVERGROWTH": "популяция удвоилась за 5 000 тиков",
    "STABLE": "популяция 8-20 дольше 30 000 тиков",
}


def _detect_flags(runs: List[RunData]) -> Dict[str, List[int]]:
    """Возвращает {flag_name: [seeds]}."""
    flags: Dict[str, List[int]] = defaultdict(list)

    for r in runs:
        seed = r.seed
        pops = [(s.get("tick", 0), s.get("population", 0)) for s in r.stats]

        # EXTINCTION_EARLY
        if r.final_population == 0 and r.ticks_run < 10_000:
            flags["EXTINCTION_EARLY"].append(seed)

        # NO_BIRTHS
        birth_count = sum(1 for e in r.events if e.get("type") == "birth")
        if birth_count == 0 and r.ticks_run >= 20_000:
            flags["NO_BIRTHS"].append(seed)

        # STUCK_AGENTS: ищем агентов с неизменной позицией 500+ тиков
        _check_stuck_agents(r, flags, seed)

        # LOW_POPULATION: популяция < 5 дольше 5 000 тиков подряд
        _check_low_population(pops, flags, seed)

        # THIRST_CRISIS: avg thirst < 0.3 дольше 1 000 тиков
        _check_thirst_crisis(r, flags, seed)

        # GROWTH_UNSTABLE: популяция резко растёт и падает циклично
        _check_growth_unstable(pops, flags, seed)

        # OVERGROWTH: популяция удвоилась за 5 000 тиков
        _check_overgrowth(pops, flags, seed)

        # STABLE: популяция 8-20 дольше 30 000 тиков
        _check_stable(pops, flags, seed)

    return dict(flags)


def _check_stuck_agents(r: RunData, flags: Dict[str, List[int]], seed: int) -> None:
    """Проверяет есть ли агенты с одинаковыми координатами 500+ тиков."""
    # Группируем snapshots по agent id
    agent_positions: Dict[int, List[Tuple[int, list]]] = defaultdict(list)
    for snap in r.agents:
        aid = snap.get("id")
        tick = snap.get("tick", 0)
        tile = snap.get("tile")
        if aid is not None and tile is not None:
            agent_positions[aid].append((tick, tile))

    snapshot_interval = config.LOG_SNAPSHOT_INTERVAL
    stuck_threshold_snaps = max(1, 500 // snapshot_interval)

    for aid, positions in agent_positions.items():
        positions.sort(key=lambda x: x[0])
        if len(positions) < stuck_threshold_snaps:
            continue
        consecutive = 1
        for i in range(1, len(positions)):
            if positions[i][1] == positions[i - 1][1]:
                consecutive += 1
                if consecutive >= stuck_threshold_snaps:
                    flags["STUCK_AGENTS"].append(seed)
                    return
            else:
                consecutive = 1


def _check_low_population(
    pops: List[Tuple[int, int]], flags: Dict[str, List[int]], seed: int,
) -> None:
    if len(pops) < 2:
        return
    interval = pops[1][0] - pops[0][0] if len(pops) > 1 else config.LOG_STATS_INTERVAL
    if interval <= 0:
        interval = config.LOG_STATS_INTERVAL
    threshold_snaps = max(1, 5_000 // interval)

    consecutive = 0
    for _, pop in pops:
        if 0 < pop < 5:
            consecutive += 1
            if consecutive >= threshold_snaps:
                flags["LOW_POPULATION"].append(seed)
                return
        else:
            consecutive = 0


def _check_thirst_crisis(
    r: RunData, flags: Dict[str, List[int]], seed: int,
) -> None:
    stats_with_needs = [
        s for s in r.stats
        if s.get("avg_needs") and s.get("population", 0) > 0
    ]
    if len(stats_with_needs) < 2:
        return
    interval = (
        stats_with_needs[1].get("tick", 0) - stats_with_needs[0].get("tick", 0)
    )
    if interval <= 0:
        interval = config.LOG_STATS_INTERVAL
    threshold_snaps = max(1, 1_000 // interval)

    consecutive = 0
    for s in stats_with_needs:
        thirst = s["avg_needs"].get("thirst", 1.0)
        if thirst < 0.3:
            consecutive += 1
            if consecutive >= threshold_snaps:
                flags["THIRST_CRISIS"].append(seed)
                return
        else:
            consecutive = 0


def _check_growth_unstable(
    pops: List[Tuple[int, int]], flags: Dict[str, List[int]], seed: int,
) -> None:
    """Ищет 3+ цикла рост-падение (>30% амплитуда) за прогон."""
    if len(pops) < 10:
        return
    values = [p for _, p in pops if p > 0]
    if len(values) < 10:
        return

    # Находим локальные экстремумы
    direction_changes = 0
    going_up = values[1] > values[0]
    for i in range(2, len(values)):
        now_up = values[i] > values[i - 1]
        if now_up != going_up:
            # Проверяем амплитуду
            window = values[max(0, i - 5): i + 1]
            if window:
                amplitude = (max(window) - min(window)) / max(max(window), 1)
                if amplitude > 0.3:
                    direction_changes += 1
            going_up = now_up

    if direction_changes >= 6:  # 3 полных цикла = 6 смен направления
        flags["GROWTH_UNSTABLE"].append(seed)


def _check_overgrowth(
    pops: List[Tuple[int, int]], flags: Dict[str, List[int]], seed: int,
) -> None:
    if len(pops) < 2:
        return
    interval = pops[1][0] - pops[0][0] if len(pops) > 1 else config.LOG_STATS_INTERVAL
    if interval <= 0:
        interval = config.LOG_STATS_INTERVAL
    window_snaps = max(1, 5_000 // interval)

    for i in range(window_snaps, len(pops)):
        pop_now = pops[i][1]
        pop_before = pops[i - window_snaps][1]
        if pop_before > 0 and pop_now >= pop_before * 2:
            flags["OVERGROWTH"].append(seed)
            return


def _check_stable(
    pops: List[Tuple[int, int]], flags: Dict[str, List[int]], seed: int,
) -> None:
    if len(pops) < 2:
        return
    interval = pops[1][0] - pops[0][0] if len(pops) > 1 else config.LOG_STATS_INTERVAL
    if interval <= 0:
        interval = config.LOG_STATS_INTERVAL
    threshold_snaps = max(1, 30_000 // interval)

    consecutive = 0
    for _, pop in pops:
        if 8 <= pop <= 20:
            consecutive += 1
            if consecutive >= threshold_snaps:
                flags["STABLE"].append(seed)
                return
        else:
            consecutive = 0


# ── Флаги на конкретный тик ────────────────────────────────────────────

def _flags_at_tick(r: RunData, target_tick: int) -> List[str]:
    """Какие флаги были бы активны к данному тику."""
    active: List[str] = []

    # Обрезаем данные до target_tick
    pops = [
        (s.get("tick", 0), s.get("population", 0))
        for s in r.stats if s.get("tick", 0) <= target_tick
    ]
    events_before = [e for e in r.events if e.get("tick", 0) <= target_tick]

    # Проверяем те же условия на урезанных данных
    final_pop = pops[-1][1] if pops else 0
    last_tick = pops[-1][0] if pops else 0

    if final_pop == 0 and last_tick < 10_000:
        active.append("EXTINCTION_EARLY")

    births = sum(1 for e in events_before if e.get("type") == "birth")
    if births == 0 and last_tick >= 20_000:
        active.append("NO_BIRTHS")

    # LOW_POPULATION
    interval = config.LOG_STATS_INTERVAL
    if len(pops) > 1:
        interval = pops[1][0] - pops[0][0] or interval
    threshold = max(1, 5_000 // interval)
    consec = 0
    for _, p in pops:
        if 0 < p < 5:
            consec += 1
        else:
            consec = 0
    if consec >= threshold:
        active.append("LOW_POPULATION")

    # THIRST_CRISIS
    stats_before = [s for s in r.stats if s.get("tick", 0) <= target_tick]
    consec = 0
    threshold_t = max(1, 1_000 // interval)
    for s in stats_before:
        avg = s.get("avg_needs", {})
        if avg and s.get("population", 0) > 0 and avg.get("thirst", 1.0) < 0.3:
            consec += 1
        else:
            consec = 0
    if consec >= threshold_t:
        active.append("THIRST_CRISIS")

    # STUCK_AGENTS
    agents_before = [a for a in r.agents if a.get("tick", 0) <= target_tick]
    agent_positions: Dict[int, List[Tuple[int, list]]] = defaultdict(list)
    for snap in agents_before:
        aid = snap.get("id")
        tile = snap.get("tile")
        if aid is not None and tile is not None:
            agent_positions[aid].append((snap.get("tick", 0), tile))
    snap_interval = config.LOG_SNAPSHOT_INTERVAL
    stuck_snaps = max(1, 500 // snap_interval)
    for aid, positions in agent_positions.items():
        positions.sort(key=lambda x: x[0])
        consec_pos = 1
        for i in range(1, len(positions)):
            if positions[i][1] == positions[i - 1][1]:
                consec_pos += 1
                if consec_pos >= stuck_snaps:
                    active.append("STUCK_AGENTS")
                    break
            else:
                consec_pos = 1
        if "STUCK_AGENTS" in active:
            break

    # GROWTH_UNSTABLE
    values = [p for _, p in pops if p > 0]
    if len(values) >= 10:
        direction_changes = 0
        going_up = values[1] > values[0]
        for i in range(2, len(values)):
            now_up = values[i] > values[i - 1]
            if now_up != going_up:
                window = values[max(0, i - 5): i + 1]
                if window:
                    amplitude = (max(window) - min(window)) / max(max(window), 1)
                    if amplitude > 0.3:
                        direction_changes += 1
                going_up = now_up
        if direction_changes >= 6:
            active.append("GROWTH_UNSTABLE")

    # OVERGROWTH
    window_snaps = max(1, 5_000 // interval)
    for i in range(window_snaps, len(pops)):
        pop_now = pops[i][1]
        pop_before = pops[i - window_snaps][1]
        if pop_before > 0 and pop_now >= pop_before * 2:
            active.append("OVERGROWTH")
            break

    # STABLE
    consec = 0
    threshold_s = max(1, 30_000 // interval)
    for _, p in pops:
        if 8 <= p <= 20:
            consec += 1
        else:
            consec = 0
    if consec >= threshold_s:
        active.append("STABLE")

    return active


# ── Timeline jump ──────────────────────────────────────────────────────

def _jump_to_tick(runs: List[RunData], runs_dir: Path, target_tick: int) -> None:
    """Выводит состояние агентов ближайшего snapshot к target_tick."""
    print(f"\n{'=' * 60}")
    print(f"  TIMELINE JUMP  ->  tick {target_tick:,}")
    print(f"{'=' * 60}")

    for r in runs:
        # Находим ближайший snapshot tick
        snap_ticks = sorted({s.get("tick", 0) for s in r.agents})
        if not snap_ticks:
            continue

        closest_tick = min(snap_ticks, key=lambda t: abs(t - target_tick))
        agents_at_tick = [
            a for a in r.agents if a.get("tick") == closest_tick
        ]
        if not agents_at_tick:
            continue

        print(f"\n--- seed {r.seed} | snapshot tick {closest_tick:,} "
              f"(delta {closest_tick - target_tick:+,}) ---")

        # Таблица агентов
        print(f"  {'Name':<12} {'Age':>6} {'Stage':<7} {'Action':<12} "
              f"{'Hng':>5} {'Thr':>5} {'Eng':>5} {'Hlt':>5} {'Moo':>5} "
              f"{'Soc':>5} {'Saf':>5} {'Pos'}")

        for a in sorted(agents_at_tick, key=lambda x: x.get("id", 0)):
            name = a.get("name", "?")[:11]
            age = f"{a.get('age_years', 0):.1f}y"
            stage = a.get("stage", "?")
            action = (a.get("current_action") or "idle")[:11]
            needs = a.get("needs", {})
            tile = a.get("tile", [0, 0])

            print(f"  {name:<12} {age:>6} {stage:<7} {action:<12} "
                  f"{needs.get('hunger', 0):5.2f} {needs.get('thirst', 0):5.2f} "
                  f"{needs.get('energy', 0):5.2f} {needs.get('health', 0):5.2f} "
                  f"{needs.get('mood', 0):5.2f} {needs.get('social', 0):5.2f} "
                  f"{needs.get('safety', 0):5.2f} "
                  f"[{tile[0]},{tile[1]}]")

        # Флаги на этот тик
        active_flags = _flags_at_tick(r, closest_tick)
        if active_flags:
            flag_str = ", ".join(
                f"{FLAG_EMOJI.get(FLAG_LEVELS.get(f, ''), '')} {f}"
                for f in active_flags
            )
            print(f"  Flags: {flag_str}")

        run_name = r.run_dir.name
        print(f"\n  Для визуального просмотра запусти:")
        print(f"  python main.py --replay {runs_dir / run_name} --tick {target_tick}")

    print()


# ── Форматирование отчёта ──────────────────────────────────────────────

def _format_report(
    runs: List[RunData],
    survival: Dict[str, Any],
    population: Dict[str, Any],
    needs: Dict[str, Dict[str, float]],
    behaviour: Dict[str, float],
    flags: Dict[str, List[int]],
    max_ticks: int,
) -> str:
    """Форматирует консольный отчёт."""
    lines: List[str] = []

    lines.append(f"=== Batch Analysis: {len(runs)} runs, "
                 f"{max_ticks:,} ticks ===")
    lines.append("")

    # SURVIVAL
    lines.append("SURVIVAL")
    lines.append(f"  Survived to end:   {survival['survived_count']}/{survival['total']} "
                 f"({survival['survival_pct']}%)")
    if survival["median_extinction_tick"] is not None:
        lines.append(f"  Median extinction: tick {survival['median_extinction_tick']:,}")
    causes = survival["extinction_causes"]
    if causes:
        cause_str = ", ".join(f"{c}\u00d7{n}" for c, n in causes.items())
        lines.append(f"  Extinction causes: {cause_str}")
    lines.append("")

    # POPULATION
    lines.append("POPULATION")
    lines.append(f"  Avg final:         {population['avg_final']:.1f} agents")
    lines.append(f"  Min/Max at end:    {population['min_final']} / {population['max_final']}")
    if population["peak_population"] > 0:
        lines.append(f"  Peak population:   {population['peak_population']} "
                     f"(tick {population['peak_tick']:,}, seed {population['peak_seed']})")
    lines.append("")

    # NEEDS
    lines.append("NEEDS (avg across all runs)")
    for n in _NEED_NAMES:
        m = needs[n]["mean"]
        s = needs[n]["std"]
        marker = "\u2713" if m >= 0.5 else "\u26a0"
        lines.append(f"  {n + ':':<10} {m:.2f} \u00b1 {s:.2f}  {marker}")
    lines.append("")

    # BEHAVIOUR
    if behaviour:
        lines.append("BEHAVIOUR")
        parts = [f"{action}: {pct:.0f}%" for action, pct in behaviour.items()]
        # По 4 на строку
        for i in range(0, len(parts), 4):
            lines.append("  " + "  ".join(parts[i:i + 4]))
        lines.append("")

    # FLAGS
    lines.append("FLAGS")
    # Сортируем: red, orange, yellow, green
    order = {"red": 0, "orange": 1, "yellow": 2, "green": 3}
    sorted_flags = sorted(
        flags.items(),
        key=lambda kv: order.get(FLAG_LEVELS.get(kv[0], ""), 99),
    )
    if not sorted_flags:
        lines.append("  (none)")
    for flag_name, seeds in sorted_flags:
        level = FLAG_LEVELS.get(flag_name, "")
        emoji = FLAG_EMOJI.get(level, "?")
        desc = FLAG_DESC.get(flag_name, "")
        seed_str = ", ".join(str(s) for s in sorted(seeds))
        lines.append(f"  {emoji} {flag_name} in seeds: [{seed_str}] \u2014 {desc}")
    lines.append("")

    return "\n".join(lines)


# ── Сохранение report.json ─────────────────────────────────────────────

def _save_report(
    runs_dir: Path,
    survival: Dict[str, Any],
    population: Dict[str, Any],
    needs: Dict[str, Dict[str, float]],
    behaviour: Dict[str, float],
    flags: Dict[str, List[int]],
    max_ticks: int,
    num_runs: int,
) -> Path:
    report = {
        "num_runs": num_runs,
        "max_ticks": max_ticks,
        "survival": survival,
        "population": population,
        "needs": needs,
        "behaviour": behaviour,
        "flags": {k: sorted(v) for k, v in flags.items()},
    }
    path = runs_dir / "analysis_report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ── Главная функция анализа ────────────────────────────────────────────

def analyze_batch(runs_dir: Path, jump_tick: Optional[int] = None) -> None:
    """Анализирует batch прогонов и выводит отчёт."""
    runs = _load_runs(runs_dir)
    print(f"Loaded {len(runs)} runs from {runs_dir}\n")

    max_ticks = max(r.ticks_run for r in runs) if runs else 0

    survival = _analyze_survival(runs)
    population = _analyze_population(runs)
    needs = _analyze_needs(runs)
    behaviour = _analyze_behaviour(runs)
    flags = _detect_flags(runs)

    report_text = _format_report(
        runs, survival, population, needs, behaviour, flags, max_ticks,
    )
    print(report_text)

    report_path = _save_report(
        runs_dir, survival, population, needs, behaviour, flags,
        max_ticks, len(runs),
    )
    print(f"Report saved: {report_path}")

    if jump_tick is not None:
        _jump_to_tick(runs, runs_dir, jump_tick)


# ── CLI ────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Анализ логов batch-прогонов симуляции.",
    )
    parser.add_argument(
        "--runs", type=str, required=True,
        help="Папка с run_* каталогами (например logs/batch_001)",
    )
    parser.add_argument(
        "--jump", type=int, default=None, metavar="TICK",
        help="Перейти к указанному тику: показать состояние агентов",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    runs_dir = Path(args.runs)
    if not runs_dir.exists():
        print(f"Directory not found: {runs_dir}")
        sys.exit(1)
    analyze_batch(runs_dir, jump_tick=args.jump)


if __name__ == "__main__":
    main()
