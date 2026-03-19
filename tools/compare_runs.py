"""
Сравнение двух наборов прогонов (before/after).

CLI:
    python tools/compare_runs.py \
        --before logs/batch_001 \
        --after logs/batch_002 \
        --label "before: default config / after: faster decay"

Читает analysis_report.json из обеих папок.
Если отчёт отсутствует — запускает analyze.py автоматически.

Выводит дельту по ключевым метрикам и сохраняет
logs/comparison_{timestamp}.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Добавляем корень проекта в sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Загрузка отчётов ──────────────────────────────────────────────────

def _ensure_report(batch_dir: Path) -> Dict[str, Any]:
    """Загружает analysis_report.json, при отсутствии запускает analyze.py."""
    report_path = batch_dir / "analysis_report.json"
    if not report_path.exists():
        print(f"Report not found in {batch_dir}, running analyze.py...")
        from tools.analyze import analyze_batch
        analyze_batch(batch_dir)
        if not report_path.exists():
            print(f"Failed to generate report for {batch_dir}")
            sys.exit(1)
    return json.loads(report_path.read_text(encoding="utf-8"))


# ── Вспомогательные ────────────────────────────────────────────────────

def _arrow(before: float, after: float) -> str:
    """Стрелка направления изменения."""
    if after > before:
        return "\u2191"  # ↑
    if after < before:
        return "\u2193"  # ↓
    return "="


def _delta_str(before: float, after: float, fmt: str = ".1f", is_pct: bool = False) -> str:
    """Форматирует значение before → after с дельтой."""
    diff = after - before
    sign = "+" if diff >= 0 else ""
    arrow = _arrow(before, after)

    suffix = "%" if is_pct else ""
    return (f"{before:{fmt}}{suffix} \u2192 {after:{fmt}}{suffix}  "
            f"{arrow} {sign}{diff:{fmt}}{suffix}")


def _severity_marker(before: float, after: float, threshold: float = 0.5) -> str:
    """Маркер серьёзности изменения потребности."""
    if after < 0.3:
        return " \U0001f534"  # 🔴
    if after < threshold:
        return " \u26a0"      # ⚠
    return ""


# ── Сравнение секций ──────────────────────────────────────────────────

_NEED_NAMES = ("hunger", "thirst", "energy", "health", "mood", "social", "safety")


def _compare_survival(
    before: Dict[str, Any], after: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("SURVIVAL")

    b_pct = before.get("survival_pct", 0)
    a_pct = after.get("survival_pct", 0)
    lines.append(f"  Survived:       {_delta_str(b_pct, a_pct, '.0f', is_pct=True)}")

    b_ext = before.get("median_extinction_tick")
    a_ext = after.get("median_extinction_tick")
    if b_ext is not None or a_ext is not None:
        b_val = b_ext or 0
        a_val = a_ext or 0
        lines.append(f"  Median ext.:    {_delta_str(b_val, a_val, ',.0f')} ticks")

    b_causes = before.get("extinction_causes", {})
    a_causes = after.get("extinction_causes", {})
    if b_causes or a_causes:
        all_causes = sorted(set(list(b_causes.keys()) + list(a_causes.keys())))
        parts = []
        for c in all_causes:
            bc = b_causes.get(c, 0)
            ac = a_causes.get(c, 0)
            if bc != ac:
                parts.append(f"{c}: {bc}\u2192{ac}")
            else:
                parts.append(f"{c}: {bc}")
        lines.append(f"  Causes:         {', '.join(parts)}")

    lines.append("")
    return lines


def _compare_population(
    before: Dict[str, Any], after: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("POPULATION")

    b_avg = before.get("avg_final", 0)
    a_avg = after.get("avg_final", 0)
    lines.append(f"  Avg final:      {_delta_str(b_avg, a_avg)}")

    b_peak = before.get("peak_population", 0)
    a_peak = after.get("peak_population", 0)
    lines.append(f"  Peak:           {_delta_str(b_peak, a_peak, '.0f')}")

    lines.append("")
    return lines


def _compare_needs(
    before: Dict[str, Any], after: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("NEEDS")

    for n in _NEED_NAMES:
        b_data = before.get(n, {})
        a_data = after.get(n, {})
        b_mean = b_data.get("mean", 0) if isinstance(b_data, dict) else 0
        a_mean = a_data.get("mean", 0) if isinstance(a_data, dict) else 0
        marker = _severity_marker(b_mean, a_mean)
        lines.append(f"  {n + ':':<10}    {_delta_str(b_mean, a_mean, '.2f')}{marker}")

    lines.append("")
    return lines


def _compare_behaviour(
    before: Dict[str, Any], after: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("BEHAVIOUR")

    all_actions = sorted(set(list(before.keys()) + list(after.keys())))
    for action in all_actions:
        b_pct = before.get(action, 0)
        a_pct = after.get(action, 0)
        if b_pct == a_pct == 0:
            continue
        lines.append(f"  {action + ':':<14}  {_delta_str(b_pct, a_pct, '.0f', is_pct=True)}")

    lines.append("")
    return lines


def _compare_flags(
    before: Dict[str, List[int]], after: Dict[str, List[int]],
) -> List[str]:
    lines: List[str] = []
    lines.append("FLAGS DIFF")

    all_flags = sorted(set(list(before.keys()) + list(after.keys())))

    new_flags = []
    resolved_flags = []
    unchanged_flags = []
    changed_flags = []

    for flag in all_flags:
        b_seeds = set(before.get(flag, []))
        a_seeds = set(after.get(flag, []))

        if not b_seeds and a_seeds:
            new_flags.append((flag, sorted(a_seeds)))
        elif b_seeds and not a_seeds:
            resolved_flags.append((flag, sorted(b_seeds)))
        elif b_seeds == a_seeds:
            unchanged_flags.append((flag, sorted(a_seeds)))
        else:
            changed_flags.append((flag, sorted(b_seeds), sorted(a_seeds)))

    if new_flags:
        for flag, seeds in new_flags:
            seed_str = ", ".join(str(s) for s in seeds)
            lines.append(f"  NEW:        {flag} (seeds {seed_str})")
    if resolved_flags:
        for flag, seeds in resolved_flags:
            lines.append(f"  RESOLVED:   {flag}")
    if changed_flags:
        for flag, b_seeds, a_seeds in changed_flags:
            b_str = ", ".join(str(s) for s in b_seeds)
            a_str = ", ".join(str(s) for s in a_seeds)
            lines.append(f"  CHANGED:    {flag} seeds [{b_str}] \u2192 [{a_str}]")
    if unchanged_flags:
        parts = []
        for flag, seeds in unchanged_flags:
            seed_str = ", ".join(str(s) for s in seeds)
            parts.append(f"{flag} (seeds {seed_str})")
        lines.append(f"  UNCHANGED:  {'; '.join(parts)}")

    if not any([new_flags, resolved_flags, changed_flags, unchanged_flags]):
        lines.append("  (no flags in either run)")

    lines.append("")
    return lines


# ── Вердикт ────────────────────────────────────────────────────────────

def _generate_verdict(
    b_report: Dict[str, Any], a_report: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("VERDICT")

    issues: List[str] = []

    # Выживаемость
    b_surv = b_report.get("survival", {}).get("survival_pct", 0)
    a_surv = a_report.get("survival", {}).get("survival_pct", 0)
    if a_surv < b_surv - 10:
        issues.append(f"Выживаемость упала: {b_surv}% \u2192 {a_surv}%")
    elif a_surv > b_surv + 10:
        issues.append(f"\u2705 Выживаемость улучшилась: {b_surv}% \u2192 {a_surv}%")

    # Потребности
    b_needs = b_report.get("needs", {})
    a_needs = a_report.get("needs", {})
    for n in _NEED_NAMES:
        b_mean = b_needs.get(n, {}).get("mean", 0) if isinstance(b_needs.get(n), dict) else 0
        a_mean = a_needs.get(n, {}).get("mean", 0) if isinstance(a_needs.get(n), dict) else 0
        if a_mean < 0.3 and b_mean >= 0.3:
            issues.append(f"\U0001f534 {n} стала критической: {b_mean:.2f} \u2192 {a_mean:.2f}")
        elif a_mean < 0.3:
            issues.append(f"\u26a0 {n} остаётся критической: {a_mean:.2f}")

    # Новые красные флаги
    b_flags = b_report.get("flags", {})
    a_flags = a_report.get("flags", {})
    red_flags = ("EXTINCTION_EARLY", "NO_BIRTHS", "STUCK_AGENTS")
    for flag in red_flags:
        if flag not in b_flags and flag in a_flags:
            seeds = a_flags[flag]
            issues.append(f"\U0001f534 Новый флаг {flag} в {len(seeds)} прогонах")

    # Популяция
    b_pop = b_report.get("population", {}).get("avg_final", 0)
    a_pop = a_report.get("population", {}).get("avg_final", 0)
    if b_pop > 0 and a_pop < b_pop * 0.5:
        issues.append(f"Популяция сократилась более чем вдвое: {b_pop:.1f} \u2192 {a_pop:.1f}")

    if not issues:
        lines.append("  \u2705 Значимых изменений не обнаружено.")
    else:
        for issue in issues:
            lines.append(f"  {issue}")

    # Рекомендации
    recs = _recommendations(b_report, a_report)
    if recs:
        lines.append("")
        lines.append("  Рекомендации:")
        for rec in recs:
            lines.append(f"    - {rec}")

    lines.append("")
    return lines


def _recommendations(
    b_report: Dict[str, Any], a_report: Dict[str, Any],
) -> List[str]:
    recs: List[str] = []
    a_needs = a_report.get("needs", {})
    a_flags = a_report.get("flags", {})

    thirst_mean = a_needs.get("thirst", {}).get("mean", 1.0) if isinstance(a_needs.get("thirst"), dict) else 1.0
    if thirst_mean < 0.3 or "THIRST_CRISIS" in a_flags:
        recs.append('Проверь NEED_DECAY["thirst"] и DEHYDRATION_DEATH_TICKS')

    hunger_mean = a_needs.get("hunger", {}).get("mean", 1.0) if isinstance(a_needs.get("hunger"), dict) else 1.0
    if hunger_mean < 0.3:
        recs.append('Проверь NEED_DECAY["hunger"] и STARVATION_DEATH_TICKS')

    if "NO_BIRTHS" in a_flags:
        recs.append("Проверь BIRTH_CHANCE_PER_TICK и REPRODUCTION_MIN_NEEDS")

    if "STUCK_AGENTS" in a_flags:
        recs.append("Проверь патфайндинг и TILE_PASSABLE")

    if "OVERGROWTH" in a_flags:
        recs.append("Проверь BIRTH_CHANCE_PER_TICK — возможно слишком высокий")

    return recs


# ── Главная ────────────────────────────────────────────────────────────

def compare_runs(
    before_dir: Path,
    after_dir: Path,
    label_before: str = "before",
    label_after: str = "after",
) -> Tuple[str, Dict[str, Any]]:
    """Сравнивает два набора прогонов. Возвращает (текст, json_report)."""
    b_report = _ensure_report(before_dir)
    a_report = _ensure_report(after_dir)

    b_runs = b_report.get("num_runs", "?")
    a_runs = a_report.get("num_runs", "?")

    output: List[str] = []
    output.append("=== Comparison ===")
    output.append(f"before: {label_before} ({b_runs} runs)")
    output.append(f"after:  {label_after} ({a_runs} runs)")
    output.append("")

    output.extend(_compare_survival(
        b_report.get("survival", {}), a_report.get("survival", {}),
    ))
    output.extend(_compare_population(
        b_report.get("population", {}), a_report.get("population", {}),
    ))
    output.extend(_compare_needs(
        b_report.get("needs", {}), a_report.get("needs", {}),
    ))
    output.extend(_compare_behaviour(
        b_report.get("behaviour", {}), a_report.get("behaviour", {}),
    ))
    output.extend(_compare_flags(
        b_report.get("flags", {}), a_report.get("flags", {}),
    ))
    output.extend(_generate_verdict(b_report, a_report))

    text = "\n".join(output)

    # JSON для сохранения
    comparison_json = {
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        "before": {
            "dir": str(before_dir),
            "label": label_before,
            "report": b_report,
        },
        "after": {
            "dir": str(after_dir),
            "label": label_after,
            "report": a_report,
        },
    }

    return text, comparison_json


def _save_comparison(comparison: Dict[str, Any]) -> Path:
    """Сохраняет comparison_{timestamp}.json в logs/."""
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = comparison.get("timestamp", time.strftime("%Y%m%d_%H%M%S"))
    path = logs_dir / f"comparison_{ts}.json"
    path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ── CLI ────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Сравнение двух наборов прогонов (before/after).",
    )
    parser.add_argument(
        "--before", type=str, required=True,
        help="Папка первого batch (например logs/batch_001)",
    )
    parser.add_argument(
        "--after", type=str, required=True,
        help="Папка второго batch (например logs/batch_002)",
    )
    parser.add_argument(
        "--label", type=str, default="",
        help='Метки: "before: описание / after: описание"',
    )
    return parser.parse_args(argv)


def _parse_label(label: str) -> Tuple[str, str]:
    """Разбирает строку 'before: xxx / after: yyy'."""
    if not label:
        return "before", "after"
    if "/" in label:
        parts = label.split("/", 1)
        lbl_b = parts[0].strip()
        lbl_a = parts[1].strip()
        # Убираем префиксы "before:" / "after:"
        for prefix in ("before:", "after:"):
            if lbl_b.lower().startswith(prefix):
                lbl_b = lbl_b[len(prefix):].strip()
            if lbl_a.lower().startswith(prefix):
                lbl_a = lbl_a[len(prefix):].strip()
        return lbl_b or "before", lbl_a or "after"
    return label, label


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    before_dir = Path(args.before)
    after_dir = Path(args.after)

    if not before_dir.exists():
        print(f"Directory not found: {before_dir}")
        sys.exit(1)
    if not after_dir.exists():
        print(f"Directory not found: {after_dir}")
        sys.exit(1)

    label_before, label_after = _parse_label(args.label)

    text, comparison = compare_runs(
        before_dir, after_dir, label_before, label_after,
    )
    print(text)

    path = _save_comparison(comparison)
    print(f"Comparison saved: {path}")


if __name__ == "__main__":
    main()
