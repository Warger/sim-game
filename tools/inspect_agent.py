"""
Детальный таймлайн конкретного агента.

CLI:
    python tools/inspect_agent.py --run logs/run_42_xxx --agent "Aria"
    python tools/inspect_agent.py --run logs/run_42_xxx --agent-id 3

Читает events.jsonl и agents.jsonl из папки прогона, строит:
    - Биографическую сводку (рождение, смерть, дети)
    - Таймлайн потребностей по снимкам
    - Ключевые события (смерти рядом, социализация, критические потребности)
    - Лог решений (если DEBUG=True — из deaths.jsonl personal_log)
    - Последние события перед смертью
"""

from __future__ import annotations

import argparse
import json
import sys
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
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ── Поиск агента ──────────────────────────────────────────────────────

def _find_agent_id(
    agents: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    name: Optional[str],
    agent_id: Optional[int],
) -> Tuple[int, str]:
    """Возвращает (agent_id, name). Выходит при ошибке."""
    if agent_id is not None:
        # Ищем имя по id
        for a in agents:
            if a.get("id") == agent_id:
                return agent_id, a.get("name", f"agent_{agent_id}")
        # Может быть в events
        for e in events:
            if e.get("agent_id") == agent_id or e.get("eid") == agent_id:
                n = e.get("name", "")
                if n:
                    return agent_id, n
        return agent_id, f"agent_{agent_id}"

    if name is not None:
        # Ищем id по имени в agents.jsonl
        for a in agents:
            if a.get("name", "").lower() == name.lower():
                return a["id"], a["name"]
        # Ищем в events.jsonl
        for e in events:
            if e.get("name", "").lower() == name.lower():
                eid = e.get("agent_id") or e.get("eid")
                if eid is not None:
                    return eid, e["name"]
        print(f"Agent '{name}' not found in logs.")
        sys.exit(1)

    print("Specify --agent or --agent-id")
    sys.exit(1)


# ── Сбор данных агента ────────────────────────────────────────────────

def _agent_snapshots(
    agents: List[Dict[str, Any]], aid: int,
) -> List[Dict[str, Any]]:
    """Все снимки агента, отсортированные по tick."""
    snaps = [a for a in agents if a.get("id") == aid]
    snaps.sort(key=lambda x: x.get("tick", 0))
    return snaps


def _agent_events(
    events: List[Dict[str, Any]], aid: int, name: str,
) -> List[Dict[str, Any]]:
    """Все события, связанные с агентом."""
    result = []
    for e in events:
        # Прямое участие
        if e.get("agent_id") == aid or e.get("eid") == aid:
            result.append(e)
            continue
        # Родитель
        if e.get("mother_id") == aid or e.get("father_id") == aid:
            result.append(e)
            continue
        # Упоминание по имени в других полях
        if e.get("partner") == name or e.get("target") == name:
            result.append(e)
            continue
    result.sort(key=lambda x: x.get("tick", 0))
    return result


def _find_children(
    events: List[Dict[str, Any]], aid: int,
) -> List[Dict[str, Any]]:
    """Рождения где агент — мать или отец."""
    children = []
    for e in events:
        if e.get("type") != "birth":
            continue
        if e.get("mother_id") == aid or e.get("father_id") == aid:
            children.append(e)
    children.sort(key=lambda x: x.get("tick", 0))
    return children


def _find_death(
    events: List[Dict[str, Any]],
    deaths: List[Dict[str, Any]],
    aid: int,
) -> Optional[Dict[str, Any]]:
    """Находит запись смерти агента."""
    # Сначала в deaths.jsonl (более подробная)
    for d in deaths:
        if d.get("eid") == aid or d.get("agent_id") == aid:
            return d
    # Fallback в events.jsonl
    for e in events:
        if e.get("type") == "death" and (
            e.get("agent_id") == aid or e.get("eid") == aid
        ):
            return e
    return None


def _find_birth(
    events: List[Dict[str, Any]], aid: int,
) -> Optional[Dict[str, Any]]:
    """Находит запись рождения агента."""
    for e in events:
        if e.get("type") == "birth" and (
            e.get("agent_id") == aid or e.get("eid") == aid
        ):
            return e
    return None


# ── Форматирование ────────────────────────────────────────────────────

def _format_header(
    name: str, aid: int, meta: Dict[str, Any],
    birth_event: Optional[Dict[str, Any]],
    death_event: Optional[Dict[str, Any]],
    children: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> List[str]:
    lines: List[str] = []
    seed = meta.get("seed", "?")

    lines.append(f"=== Agent: {name} (id={aid}, seed {seed}) ===")
    lines.append("")

    # Born
    born_tick = 0
    if birth_event:
        born_tick = birth_event.get("tick", 0)
        mother = birth_event.get("mother_name") or birth_event.get("mother_id", "?")
        father = birth_event.get("father_name") or birth_event.get("father_id", "?")
        lines.append(f"Born:     tick {born_tick:,}  |  Parents: {mother} + {father}")
    else:
        # Стартовый агент
        if snapshots:
            first = snapshots[0]
            age_years = first.get("age_years", 0)
            lines.append(f"Born:     tick 0 (starter agent, age {age_years:.1f}y)")
        else:
            lines.append("Born:     tick 0 (starter agent)")

    # Died
    if death_event:
        death_tick = death_event.get("tick", 0)
        cause = death_event.get("cause", "unknown")
        age_ticks = death_event.get("age_ticks") or death_event.get("age", 0)
        if age_ticks:
            age_years = age_ticks / config.TICKS_PER_YEAR
            lines.append(f"Died:     tick {death_tick:,}  |  Cause: {cause}  |  "
                         f"Age: {age_years:.1f} years")
        else:
            lines.append(f"Died:     tick {death_tick:,}  |  Cause: {cause}")
    else:
        if snapshots:
            last = snapshots[-1]
            lines.append(f"Alive at: tick {last.get('tick', 0):,}  |  "
                         f"Age: {last.get('age_years', 0):.1f} years")

    # Children
    if children:
        child_parts = []
        for c in children:
            cname = c.get("name", "?")
            ctick = c.get("tick", 0)
            child_parts.append(f"{cname} tick {ctick:,}")
        lines.append(f"Children: {len(children)} ({', '.join(child_parts)})")
    else:
        lines.append("Children: 0")

    lines.append("")
    return lines


def _format_needs_timeline(snapshots: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    lines.append("NEEDS TIMELINE")
    header = (f"  {'tick':>8}  {'hunger':>7} {'thirst':>7} {'energy':>7} "
              f"{'health':>7} {'mood':>7} {'social':>7} {'safety':>7}  action")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for snap in snapshots:
        tick = snap.get("tick", 0)
        needs = snap.get("needs", {})
        action = snap.get("current_action") or "idle"

        vals = []
        for n in ("hunger", "thirst", "energy", "health", "mood", "social", "safety"):
            v = needs.get(n, 0.0)
            # Отмечаем критические
            crit = config.CRITICAL_THRESHOLD.get(n)
            marker = " " if crit is None or v > crit else "!"
            vals.append(f"{v:6.3f}{marker}")

        lines.append(f"  {tick:>8}  {'  '.join(vals)}  {action}")

    lines.append("")
    return lines


def _format_key_events(agent_events: List[Dict[str, Any]], name: str) -> List[str]:
    lines: List[str] = []
    lines.append("KEY EVENTS")

    if not agent_events:
        lines.append("  (no events)")
        lines.append("")
        return lines

    for e in agent_events:
        tick = e.get("tick", 0)
        etype = e.get("type", "?")

        if etype == "birth":
            child_name = e.get("name", "?")
            # Это рождение этого агента или его ребёнка?
            if e.get("mother_id") or e.get("father_id"):
                eid = e.get("agent_id") or e.get("eid")
                lines.append(f"  tick {tick:>7}  birth: {child_name}")
            continue

        if etype == "death":
            eid = e.get("agent_id") or e.get("eid")
            dead_name = e.get("name", "?")
            cause = e.get("cause", "?")
            lines.append(f"  tick {tick:>7}  death: {dead_name} (cause: {cause})")
            continue

        if etype == "faint":
            cause = e.get("cause", "?")
            lines.append(f"  tick {tick:>7}  faint: {cause}")
            continue

        if etype == "social_success" or etype == "social":
            partner = e.get("partner") or e.get("target") or "?"
            lines.append(f"  tick {tick:>7}  socialized with {partner}")
            continue

        if etype == "need_critical":
            need = e.get("need", "?")
            value = e.get("value", 0)
            lines.append(f"  tick {tick:>7}  CRITICAL: {need} = {value:.3f}")
            continue

        if etype == "death_nearby":
            dead = e.get("dead_name") or e.get("name", "?")
            impact = e.get("mood_impact") or e.get("impact", {}).get("mood", 0)
            lines.append(f"  tick {tick:>7}  death nearby ({dead})  mood {impact:+.2f}")
            continue

        if etype == "birth_nearby":
            lines.append(f"  tick {tick:>7}  birth nearby")
            continue

        # Остальные
        lines.append(f"  tick {tick:>7}  {etype}: {_compact_event(e)}")

    lines.append("")
    return lines


def _compact_event(e: Dict[str, Any]) -> str:
    """Краткое описание произвольного события."""
    skip = {"tick", "type", "agent_id", "eid"}
    parts = []
    for k, v in e.items():
        if k in skip:
            continue
        parts.append(f"{k}={v}")
    return ", ".join(parts[:5])


def _format_decision_log(death_record: Optional[Dict[str, Any]]) -> List[str]:
    """Форматирует personal_log из deaths.jsonl (если есть)."""
    lines: List[str] = []

    if not death_record:
        return lines

    personal_log = death_record.get("personal_log", [])
    if not personal_log:
        return lines

    lines.append("DECISION LOG (from personal memory)")
    # Показываем последние 20 записей
    entries = personal_log[-20:]
    for entry in entries:
        if isinstance(entry, dict):
            tick = entry.get("tick", "?")
            desc = entry.get("description") or entry.get("text") or str(entry)
            lines.append(f"  tick {tick:>7}  {desc}")
        elif isinstance(entry, str):
            lines.append(f"  {entry}")

    lines.append("")
    return lines


def _format_death_summary(
    death_event: Optional[Dict[str, Any]],
    agent_events: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> List[str]:
    lines: List[str] = []

    if not death_event:
        lines.append("STATUS: ALIVE (no death record)")
        lines.append("")
        return lines

    death_tick = death_event.get("tick", 0)
    cause = death_event.get("cause", "unknown")

    lines.append("DEATH SUMMARY")
    lines.append(f"  Cause: {cause}")
    lines.append(f"  Tick:  {death_tick:,}")
    lines.append("")

    # Последние 10 событий перед смертью
    events_before = [e for e in agent_events if e.get("tick", 0) <= death_tick]
    last_events = events_before[-10:]
    if last_events:
        lines.append("  Last 10 events before death:")
        for e in last_events:
            tick = e.get("tick", 0)
            etype = e.get("type", "?")
            lines.append(f"    tick {tick:>7}  {etype}: {_compact_event(e)}")
        lines.append("")

    # Финальные потребности (последний снимок)
    final_snap = None
    for s in reversed(snapshots):
        if s.get("tick", 0) <= death_tick:
            final_snap = s
            break

    if final_snap:
        needs = final_snap.get("needs", {})
        parts = []
        for n in ("hunger", "thirst", "energy", "health", "mood", "social", "safety"):
            v = needs.get(n, 0.0)
            parts.append(f"{n}={v:.3f}")
        lines.append(f"  Final needs: {', '.join(parts)}")
        lines.append("")

    return lines


# ── Главная ────────────────────────────────────────────────────────────

def inspect_agent(
    run_dir: Path,
    agent_name: Optional[str] = None,
    agent_id: Optional[int] = None,
) -> str:
    """Анализирует агента и возвращает текстовый отчёт."""
    meta = _read_meta(run_dir / "meta.json")
    events = _read_jsonl(run_dir / "events.jsonl")
    agents = _read_jsonl(run_dir / "agents.jsonl")
    deaths = _read_jsonl(run_dir / "deaths.jsonl")

    aid, name = _find_agent_id(agents, events, agent_name, agent_id)

    snapshots = _agent_snapshots(agents, aid)
    agent_evts = _agent_events(events, aid, name)
    children = _find_children(events, aid)
    birth_event = _find_birth(events, aid)
    death_event = _find_death(events, deaths, aid)

    output: List[str] = []

    # Header
    output.extend(_format_header(
        name, aid, meta, birth_event, death_event, children, snapshots,
    ))

    # Needs timeline
    if snapshots:
        output.extend(_format_needs_timeline(snapshots))

    # Key events
    output.extend(_format_key_events(agent_evts, name))

    # Decision log (из deaths.jsonl personal_log)
    output.extend(_format_decision_log(death_event))

    # Death summary
    output.extend(_format_death_summary(death_event, agent_evts, snapshots))

    return "\n".join(output)


# ── CLI ────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Детальный таймлайн конкретного агента.",
    )
    parser.add_argument(
        "--run", type=str, required=True,
        help="Папка прогона (например logs/run_42_20260101_120000)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--agent", type=str, metavar="NAME",
        help="Имя агента",
    )
    group.add_argument(
        "--agent-id", type=int, metavar="ID",
        help="ID агента",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    run_dir = Path(args.run)
    if not run_dir.exists():
        print(f"Directory not found: {run_dir}")
        sys.exit(1)

    report = inspect_agent(run_dir, agent_name=args.agent, agent_id=args.agent_id)
    print(report)


if __name__ == "__main__":
    main()
