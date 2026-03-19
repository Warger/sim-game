"""
Запуск N симуляций параллельно на разных seed.

CLI:
    python tools/batch_run.py --seeds 20 --ticks 50000 --parallel 4 --out logs/batch_001
    python tools/batch_run.py --seed-list 0 7 42 99 --ticks 50000 --parallel 4

Каждая симуляция запускается headless. Результаты складываются
в отдельные папки. По завершении выводит сводку и сохраняет batch_summary.json.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Добавляем корень проекта в sys.path для импорта
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config
from simulation.factory import create_starter_population
from simulation.game_loop import GameLoop
from simulation.map.generator import generate_map
from simulation.world import World
from storage.logger import SimLogger


# ── Результат одного прогона ──────────────────────────────────────────

class RunResult:
    """Данные одного завершённого (или упавшего) прогона."""
    __slots__ = (
        "seed", "success", "ticks_run", "final_population",
        "total_births", "total_deaths", "elapsed", "error", "log_dir",
        "map_gen_time", "pop_gen_time", "sim_time",
    )

    def __init__(
        self,
        seed: int,
        *,
        success: bool = True,
        ticks_run: int = 0,
        final_population: int = 0,
        total_births: int = 0,
        total_deaths: int = 0,
        elapsed: float = 0.0,
        error: Optional[str] = None,
        log_dir: str = "",
        map_gen_time: float = 0.0,
        pop_gen_time: float = 0.0,
        sim_time: float = 0.0,
    ) -> None:
        self.seed = seed
        self.success = success
        self.ticks_run = ticks_run
        self.final_population = final_population
        self.total_births = total_births
        self.total_deaths = total_deaths
        self.elapsed = elapsed
        self.error = error
        self.log_dir = log_dir
        self.map_gen_time = map_gen_time
        self.pop_gen_time = pop_gen_time
        self.sim_time = sim_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "success": self.success,
            "ticks_run": self.ticks_run,
            "final_population": self.final_population,
            "total_births": self.total_births,
            "total_deaths": self.total_deaths,
            "elapsed_seconds": round(self.elapsed, 2),
            "map_gen_seconds": round(self.map_gen_time, 2),
            "pop_gen_seconds": round(self.pop_gen_time, 2),
            "sim_seconds": round(self.sim_time, 2),
            "error": self.error,
            "log_dir": self.log_dir,
        }


# ── Воркер ────────────────────────────────────────────────────────────

_worker_id: int = -1
_worker_cum = None     # multiprocessing.Array — кумулятивные тики воркера
_worker_run = None     # multiprocessing.Array — тики текущего рана воркера
_worker_seeds = None   # multiprocessing.Array — текущий seed воркера (-1 = idle)


def _init_worker(cum_arr, run_arr, seeds_arr, id_counter) -> None:
    """Инициализатор воркера — назначает ID и сохраняет shared arrays."""
    global _worker_id, _worker_cum, _worker_run, _worker_seeds
    _worker_cum = cum_arr
    _worker_run = run_arr
    _worker_seeds = seeds_arr
    with id_counter.get_lock():
        _worker_id = id_counter.value
        id_counter.value += 1


def _run_single(args: tuple) -> RunResult:
    """Запускает одну симуляцию. Вызывается в дочернем процессе."""
    seed, total_ticks, stop_on_extinction, out_dir = args

    t0 = time.time()
    if _worker_run is not None:
        _worker_run[_worker_id] = 0
        _worker_seeds[_worker_id] = seed
    try:
        t_map_start = time.time()
        tile_map = generate_map(seed=seed)
        t_map_elapsed = time.time() - t_map_start

        t_pop_start = time.time()
        world = World(tile_map)
        create_starter_population(world)
        t_pop_elapsed = time.time() - t_pop_start

        logger = SimLogger(seed, config_snapshot=config.get_config_snapshot())
        # Переопределяем папку логов, если указан --out
        if out_dir:
            import shutil
            old_dir = logger.run_dir
            new_dir = Path(out_dir) / f"seed_{seed}"
            new_dir.mkdir(parents=True, exist_ok=True)
            # Закрываем файлы ПЕРЕД перемещением (Windows держит блокировку)
            logger._events_f.close()
            logger._agents_f.close()
            logger._stats_f.close()
            logger._deaths_f.close()
            # Переносим уже созданные файлы
            for f in old_dir.iterdir():
                shutil.move(str(f), str(new_dir / f.name))
            old_dir.rmdir()
            logger.run_dir = new_dir
            # Переоткрываем файлы в новой папке (через _BufferedWriter)
            from storage.logger import _BufferedWriter
            buf = config.LOG_BUFFER_SIZE
            logger._events_f = _BufferedWriter(new_dir / "events.jsonl", buf)
            logger._agents_f = _BufferedWriter(new_dir / "agents.jsonl", buf)
            logger._stats_f = _BufferedWriter(new_dir / "stats.jsonl", buf)
            logger._deaths_f = _BufferedWriter(new_dir / "deaths.jsonl", buf)

        game_loop = GameLoop(logger=logger)

        ticks_run = 0
        unreported = 0
        for _ in range(total_ticks):
            game_loop.tick(world)
            ticks_run += 1
            unreported += 1

            # Обновляем счётчики тиков воркера каждые 10 тиков
            if _worker_cum is not None and unreported >= 10:
                _worker_cum[_worker_id] += unreported
                _worker_run[_worker_id] += unreported
                unreported = 0

            if stop_on_extinction and len(world.entities) == 0:
                break

        # Сбрасываем неотправленный остаток реальных тиков
        if _worker_cum is not None and unreported > 0:
            _worker_cum[_worker_id] += unreported
            _worker_run[_worker_id] += unreported

        log_dir = logger.close(world)
        elapsed = time.time() - t0
        sim_time = elapsed - t_map_elapsed - t_pop_elapsed

        return RunResult(
            seed,
            success=True,
            ticks_run=ticks_run,
            final_population=len(world.entities),
            total_births=logger._total_births,
            total_deaths=logger._total_deaths,
            elapsed=elapsed,
            log_dir=log_dir,
            map_gen_time=t_map_elapsed,
            pop_gen_time=t_pop_elapsed,
            sim_time=sim_time,
        )

    except Exception:
        elapsed = time.time() - t0
        return RunResult(
            seed,
            success=False,
            elapsed=elapsed,
            error=traceback.format_exc(),
        )


# ── Прогресс-бар ─────────────────────────────────────────────────────

def _format_time(seconds: int) -> str:
    """Форматирует секунды в читаемый вид."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}h{m:02d}m{s:02d}s"


class _ProgressState:
    """Состояние прогресс-бара (main-thread only)."""
    __slots__ = ("done_runs",)

    def __init__(self) -> None:
        self.done_runs: int = 0


def _print_progress(
    state: _ProgressState,
    worker_cum,
    worker_run,
    worker_seeds,
    parallel: int,
    ticks_per_run: int,
    total_runs: int,
    start_time: float,
) -> None:
    """Выводит прогресс в одну строку с разбивкой по воркерам."""
    elapsed = time.time() - start_time
    total_done = sum(worker_cum[i] for i in range(parallel))

    # Компактная строка по каждому воркеру: W0:45% W1:62% ...
    parts = []
    for i in range(parallel):
        seed = worker_seeds[i]
        run_ticks = worker_run[i]
        if seed < 0:
            parts.append(f"W{i}:--")
        else:
            pct = min(run_ticks / ticks_per_run, 1.0) if ticks_per_run > 0 else 0
            parts.append(f"W{i}[s{seed}]:{pct*100:.0f}%")
    workers_str = " ".join(parts)

    # ETA
    if state.done_runs > 0 and state.done_runs < total_runs:
        eta = elapsed / state.done_runs * (total_runs - state.done_runs)
        eta_str = f"ETA: {_format_time(int(eta))}"
    elif state.done_runs >= total_runs:
        eta_str = "done"
    elif total_done > 0:
        total_target = total_runs * ticks_per_run
        eta = elapsed / total_done * (total_target - total_done)
        eta_str = f"ETA: ~{_format_time(int(eta))}"
    else:
        eta_str = "ETA: --"

    line = (
        f"{state.done_runs}/{total_runs} runs | "
        f"{total_done:,} ticks | {_format_time(int(elapsed))} | "
        f"{eta_str} | {workers_str}"
    )
    sys.stderr.write(f"\r{line:<120}")
    sys.stderr.flush()


# ── Основная функция ──────────────────────────────────────────────────

def run_batch(
    seeds: List[int],
    ticks: int,
    parallel: int,
    out_dir: str,
    stop_on_extinction: bool = False,
) -> Tuple[List[RunResult], float]:
    """Запускает batch прогонов и возвращает результаты."""
    total = len(seeds)
    print(f"Starting batch: {total} runs, {ticks} ticks each, {parallel} workers")
    print(f"Output: {out_dir or '(default logs/)'}")
    print()

    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    worker_args = [
        (seed, ticks, stop_on_extinction, out_dir) for seed in seeds
    ]

    results: List[RunResult] = []
    start_time = time.time()
    worker_cum = multiprocessing.Array("l", parallel)
    worker_run = multiprocessing.Array("l", parallel)
    worker_seeds = multiprocessing.Array("i", [-1] * parallel)
    worker_id_counter = multiprocessing.Value("i", 0)
    done_event = threading.Event()
    display_lock = threading.Lock()
    state = _ProgressState()

    # Фоновый поток для живого обновления прогресса
    def _progress_loop() -> None:
        while not done_event.is_set():
            with display_lock:
                _print_progress(
                    state, worker_cum, worker_run, worker_seeds,
                    parallel, ticks, total, start_time,
                )
            done_event.wait(timeout=1.0)

    progress_thread = threading.Thread(target=_progress_loop, daemon=True)
    progress_thread.start()

    with multiprocessing.Pool(
        processes=parallel,
        initializer=_init_worker,
        initargs=(worker_cum, worker_run, worker_seeds, worker_id_counter),
    ) as pool:
        for result in pool.imap_unordered(_run_single, worker_args):
            with display_lock:
                state.done_runs += 1
                results.append(result)
                _print_progress(
                    state, worker_cum, worker_run, worker_seeds,
                    parallel, ticks, total, start_time,
                )

                if not result.success:
                    sys.stderr.write(
                        f"\n  [!] Seed {result.seed} failed: "
                        f"{(result.error or '').splitlines()[-1]}\n"
                    )

    done_event.set()
    progress_thread.join()
    sys.stderr.write("\n\n")

    # Сортируем по seed для стабильного порядка
    results.sort(key=lambda r: r.seed)
    wall_clock = time.time() - start_time
    return results, wall_clock


# ── Сводка ────────────────────────────────────────────────────────────

def _print_summary(results: List[RunResult], out_dir: str, wall_clock: float = 0.0) -> Dict[str, Any]:
    """Выводит и возвращает сводку."""
    total = len(results)
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    survived = [r for r in successful if r.final_population > 0]
    extinct = [r for r in successful if r.final_population == 0]

    avg_pop = (
        sum(r.final_population for r in successful) / len(successful)
        if successful else 0.0
    )
    avg_ticks = (
        sum(r.ticks_run for r in successful) / len(successful)
        if successful else 0.0
    )
    cpu_elapsed = sum(r.elapsed for r in results)

    avg_map_gen = (
        sum(r.map_gen_time for r in successful) / len(successful)
        if successful else 0.0
    )
    avg_sim = (
        sum(r.sim_time for r in successful) / len(successful)
        if successful else 0.0
    )

    print(f"=== Batch complete: {total} runs ===")
    if successful:
        print(f"Survived:      {len(survived)}/{len(successful)} ({len(survived)*100//len(successful)}%)")
        print(f"Extinct:       {len(extinct)}/{len(successful)} ({len(extinct)*100//len(successful)}%)")
        print(f"Avg final pop: {avg_pop:.1f}")
        print(f"Avg ticks run: {avg_ticks:,.0f}")
        print(f"Avg map gen:   {avg_map_gen:.1f}s")
        print(f"Avg sim time:  {avg_sim:.1f}s")
    if failed:
        print(f"Failed:        {len(failed)}/{total}")
    print(f"Wall time:     {wall_clock:.1f}s")
    print(f"CPU time:      {cpu_elapsed:.1f}s (sum of all workers)")
    print(f"Logs saved to: {out_dir or 'logs/'}")

    summary = {
        "total_runs": total,
        "successful_runs": len(successful),
        "failed_runs": len(failed),
        "survived": len(survived),
        "extinct": len(extinct),
        "avg_final_population": round(avg_pop, 2),
        "avg_ticks_run": round(avg_ticks, 1),
        "wall_clock_seconds": round(wall_clock, 2),
        "cpu_elapsed_seconds": round(cpu_elapsed, 2),
        "runs": [r.to_dict() for r in results],
    }
    return summary


def _save_summary(summary: Dict[str, Any], out_dir: str) -> None:
    """Сохраняет batch_summary.json."""
    target_dir = Path(out_dir) if out_dir else Path("logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "batch_summary.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Summary saved: {path}")


# ── CLI ───────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Запуск N симуляций параллельно на разных seed.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--seeds", type=int, metavar="N",
        help="Запустить N прогонов на seeds 0..N-1",
    )
    group.add_argument(
        "--seed-list", type=int, nargs="+", metavar="SEED",
        help="Конкретные seeds для запуска",
    )
    parser.add_argument(
        "--ticks", type=int, required=True,
        help="Количество тиков каждого прогона",
    )
    parser.add_argument(
        "--parallel", type=int, default=multiprocessing.cpu_count(),
        help=f"Число параллельных процессов (default: {multiprocessing.cpu_count()})",
    )
    parser.add_argument(
        "--out", type=str, default="",
        help="Папка для логов (default: logs/)",
    )
    parser.add_argument(
        "--stop-on-extinction", action=argparse.BooleanOptionalAction,
        default=True,
        help="Останавливать прогон если популяция = 0 (default: True)",
    )
    parser.add_argument(
        "--snap", type=int, default=5,
        help="Интервал снапшотов в тиках (default: 5)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    config.LOG_SNAPSHOT_INTERVAL = args.snap
    config.LOG_STATS_INTERVAL = args.snap

    if args.seeds is not None:
        seeds = list(range(args.seeds))
    else:
        seeds = args.seed_list

    results, wall_clock = run_batch(
        seeds=seeds,
        ticks=args.ticks,
        parallel=args.parallel,
        out_dir=args.out,
        stop_on_extinction=args.stop_on_extinction,
    )

    summary = _print_summary(results, args.out, wall_clock)
    _save_summary(summary, args.out)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
