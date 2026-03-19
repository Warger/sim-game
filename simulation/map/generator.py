"""
Процедурная генерация карты: stamp-based.

Подход: начинаем с grass, штампуем фигуры (озёра, горные хребты,
лесные массивы) как irregular shapes с шумовой границей.
Shore автоматически генерируется вокруг воды.

generate_map(seed) -> TileMap
"""

from __future__ import annotations

import numpy as np
from pyfastnoiselite.pyfastnoiselite import FastNoiseLite, NoiseType as FNLNoiseType
from scipy.ndimage import binary_dilation, label
import pygame

import config
from simulation.map.tile import TileMap, TileType

# ── Tile ID для numpy grid ──────────────────────────────────────────

_GRASS: np.int8 = np.int8(0)
_FOREST: np.int8 = np.int8(1)
_WATER: np.int8 = np.int8(2)
_ROCK: np.int8 = np.int8(3)
_SHORE: np.int8 = np.int8(4)

_ID_TO_TILE = [TileType.GRASS, TileType.FOREST, TileType.WATER, TileType.ROCK, TileType.SHORE]

# ── Параметры штампов ───────────────────────────────────────────────

# Озёра / водоёмы
_LAKE_COUNT = (4, 8)          # min, max кол-во
_LAKE_RADIUS = (20, 80)       # min, max радиус

# Горные хребты
_MOUNTAIN_COUNT = (2, 4)
_MOUNTAIN_LENGTH = (40, 120)  # длина хребта
_MOUNTAIN_WIDTH = (8, 20)     # ширина хребта

# Лесные массивы
_FOREST_COUNT = (6, 12)
_FOREST_RADIUS = (30, 100)

# Шум для границ штампов
_EDGE_NOISE_FREQ = 0.03       # частота шума для неровностей краёв
_EDGE_NOISE_AMP = 0.35        # амплитуда: 0.0 = ровные края, 1.0 = очень рваные

# Центральная зона: bias к grass
_CENTER_GRASS_RADIUS = 0.15   # доля от min(w,h) — зона с пониженной вероятностью штампов


# ── Основная функция ────────────────────────────────────────────────

_NOISE_CHUNK = 500_000  # макс. пикселей за один вызов gen_from_coords


def _noise_2d(fnl: FastNoiseLite, xs_flat: np.ndarray, ys_flat: np.ndarray) -> np.ndarray:
    """gen_from_coords с чанкированием для избежания OOM."""
    n = len(xs_flat)
    if n <= _NOISE_CHUNK:
        zs = np.zeros(n, dtype=np.float32)
        coords = np.ascontiguousarray(
            np.array([xs_flat, ys_flat, zs], dtype=np.float32)
        )
        return np.array(fnl.gen_from_coords(coords))

    result = np.empty(n, dtype=np.float32)
    for start in range(0, n, _NOISE_CHUNK):
        end = min(start + _NOISE_CHUNK, n)
        zs = np.zeros(end - start, dtype=np.float32)
        coords = np.ascontiguousarray(
            np.array([xs_flat[start:end], ys_flat[start:end], zs], dtype=np.float32)
        )
        result[start:end] = fnl.gen_from_coords(coords)
    return result


def generate_map(seed: int = 42) -> TileMap:
    """Генерирует карту MAP_WIDTH × MAP_HEIGHT из config."""
    w, h = config.MAP_WIDTH, config.MAP_HEIGHT
    rng = np.random.default_rng(seed)

    # Начинаем с травы
    grid = np.full((h, w), _GRASS, dtype=np.int8)

    # ── Штампуем горные хребты ──────────────────────────────────────
    n_mountains = rng.integers(_MOUNTAIN_COUNT[0], _MOUNTAIN_COUNT[1] + 1)
    for _ in range(n_mountains):
        _stamp_ridge(grid, w, h, rng, seed, _ROCK)

    # ── Штампуем озёра ──────────────────────────────────────────────
    n_lakes = rng.integers(_LAKE_COUNT[0], _LAKE_COUNT[1] + 1)
    for _ in range(n_lakes):
        _stamp_blob(grid, w, h, rng, seed, _WATER,
                    _LAKE_RADIUS[0], _LAKE_RADIUS[1])

    # ── Штампуем лесные массивы ─────────────────────────────────────
    n_forests = rng.integers(_FOREST_COUNT[0], _FOREST_COUNT[1] + 1)
    for _ in range(n_forests):
        _stamp_blob(grid, w, h, rng, seed, _FOREST,
                    _FOREST_RADIUS[0], _FOREST_RADIUS[1])

    # ── Мелкие оазисы: пруд + роща, рассыпаны по карте ─────────────
    _scatter_oases(grid, w, h, rng, seed)

    # ── Гарантия воды в каждом секторе 100×100 ──────────────────────
    _ensure_water_coverage(grid, w, h, rng)

    # ── Start zone ──────────────────────────────────────────────────
    _ensure_start_zone_np(grid, w, h)

    # ── Shore вокруг воды (после start zone, чтобы покрыть всю воду) ─
    _ensure_shores_np(grid)

    # ── Connectivity ────────────────────────────────────────────────
    _ensure_connectivity_np(grid, w, h)

    # ── Конвертация в TileMap ───────────────────────────────────────
    return _grid_to_tilemap(grid, w, h)


# ── Scattered oases ─────────────────────────────────────────────────

_OASIS_SPACING = 28           # расстояние между оазисами в тайлах
_OASIS_POND_R = (3, 7)        # радиус пруда
_OASIS_GROVE_R = (6, 14)      # радиус рощи
_OASIS_JITTER = 6             # рандомное смещение позиции


def _scatter_oases(
    grid: np.ndarray, w: int, h: int,
    rng: np.random.Generator, seed: int,
) -> None:
    """Рассыпает мелкие пруды + рощи по сетке, чтобы агенты
    всегда имели ресурсы в пределах ~40 тайлов."""
    margin = 10
    for gy in range(margin, h - margin, _OASIS_SPACING):
        for gx in range(margin, w - margin, _OASIS_SPACING):
            # Jitter позиции
            ox = int(gx + rng.integers(-_OASIS_JITTER, _OASIS_JITTER + 1))
            oy = int(gy + rng.integers(-_OASIS_JITTER, _OASIS_JITTER + 1))
            ox = max(margin, min(w - margin, ox))
            oy = max(margin, min(h - margin, oy))

            # Пропускаем если на rock или water
            if grid[oy, ox] == _ROCK or grid[oy, ox] == _WATER:
                continue

            # Роща (к югу/западу от пруда)
            gr = int(rng.integers(_OASIS_GROVE_R[0], _OASIS_GROVE_R[1] + 1))
            gx_off = int(rng.integers(-gr, gr + 1))
            gy_off = int(rng.integers(-gr, gr + 1))
            fy0, fy1 = max(0, oy + gy_off - gr), min(h, oy + gy_off + gr)
            fx0, fx1 = max(0, ox + gx_off - gr), min(w, ox + gx_off + gr)
            sub = grid[fy0:fy1, fx0:fx1]
            sub[sub == _GRASS] = _FOREST

            # Пруд (маленький)
            pr = int(rng.integers(_OASIS_POND_R[0], _OASIS_POND_R[1] + 1))
            py0, py1 = max(0, oy - pr), min(h, oy + pr)
            px0, px1 = max(0, ox - pr), min(w, ox + pr)
            grid[py0:py1, px0:px1] = _WATER


# ── Гарантия воды в каждом секторе ──────────────────────────────────

_SECTOR_SIZE = 100  # ячейка 100×100 тайлов
_SECTOR_POND_R = 4  # радиус пруда-заполнителя


def _ensure_water_coverage(
    grid: np.ndarray, w: int, h: int,
    rng: np.random.Generator,
) -> None:
    """В каждом секторе 100×100 должна быть хотя бы одна клетка воды."""
    for sy in range(0, h, _SECTOR_SIZE):
        for sx in range(0, w, _SECTOR_SIZE):
            sy1 = min(sy + _SECTOR_SIZE, h)
            sx1 = min(sx + _SECTOR_SIZE, w)
            sector = grid[sy:sy1, sx:sx1]
            if np.any(sector == _WATER):
                continue
            # Нет воды — ставим пруд в случайном месте сектора
            cx = int(rng.integers(sx + _SECTOR_POND_R, max(sx + _SECTOR_POND_R + 1, sx1 - _SECTOR_POND_R)))
            cy = int(rng.integers(sy + _SECTOR_POND_R, max(sy + _SECTOR_POND_R + 1, sy1 - _SECTOR_POND_R)))
            r = _SECTOR_POND_R
            py0, py1 = max(0, cy - r), min(h, cy + r)
            px0, px1 = max(0, cx - r), min(w, cx + r)
            grid[py0:py1, px0:px1] = _WATER


# ── Штамп: blob (озеро, лес) ────────────────────────────────────────

def _stamp_blob(
    grid: np.ndarray,
    w: int, h: int,
    rng: np.random.Generator,
    seed: int,
    tile_id: np.int8,
    radius_min: int,
    radius_max: int,
) -> None:
    """Штампует irregular blob на grid."""
    margin = radius_max
    cx = int(rng.integers(margin, w - margin))
    cy = int(rng.integers(margin, h - margin))
    radius = int(rng.integers(radius_min, radius_max + 1))

    aspect = float(rng.uniform(0.6, 1.6))
    angle = float(rng.uniform(0, np.pi))

    # Bounding box
    r_ext = int(radius * max(aspect, 1.0) * 1.5) + 1
    y0, y1 = max(0, cy - r_ext), min(h, cy + r_ext)
    x0, x1 = max(0, cx - r_ext), min(w, cx + r_ext)

    # Локальные координаты (только bounding box)
    lxs = np.arange(x0, x1, dtype=np.float32) - cx
    lys = np.arange(y0, y1, dtype=np.float32) - cy
    local_x, local_y = np.meshgrid(lxs, lys)

    # Поворот для эллипса
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    rx = local_x * cos_a + local_y * sin_a
    ry = -local_x * sin_a + local_y * cos_a

    dist = np.sqrt((rx / radius) ** 2 + (ry / (radius * aspect)) ** 2)

    # Шум для неровной границы
    fnl = FastNoiseLite()
    fnl.noise_type = FNLNoiseType.NoiseType_OpenSimplex2
    fnl.seed = seed + int(rng.integers(0, 100000))
    fnl.frequency = _EDGE_NOISE_FREQ

    abs_xs = np.arange(x0, x1, dtype=np.float32)
    abs_ys = np.arange(y0, y1, dtype=np.float32)
    ax, ay = np.meshgrid(abs_xs, abs_ys)
    noise = _noise_2d(fnl, ax.ravel(), ay.ravel()).reshape(local_x.shape)

    threshold = 1.0 + noise * _EDGE_NOISE_AMP
    mask = dist < threshold

    sub = grid[y0:y1, x0:x1]
    if tile_id == _FOREST:
        mask &= (sub == _GRASS)
    sub[mask] = tile_id


# ── Штамп: ridge (горный хребет) ─────────────────────────────────────

def _stamp_ridge(
    grid: np.ndarray,
    w: int, h: int,
    rng: np.random.Generator,
    seed: int,
    tile_id: np.int8,
) -> None:
    """Штампует elongated горный хребет как толстую кривую."""
    length = int(rng.integers(_MOUNTAIN_LENGTH[0], _MOUNTAIN_LENGTH[1] + 1))
    width = int(rng.integers(_MOUNTAIN_WIDTH[0], _MOUNTAIN_WIDTH[1] + 1))

    margin = width + 10
    sx = int(rng.integers(margin, w - margin))
    sy = int(rng.integers(margin, h - margin))

    angle = float(rng.uniform(0, 2 * np.pi))
    n_segments = max(3, length // 40)
    points = [(float(sx), float(sy))]

    for _ in range(n_segments):
        seg_len = length / n_segments
        angle += float(rng.uniform(-0.6, 0.6))
        nx = points[-1][0] + np.cos(angle) * seg_len
        ny = points[-1][1] + np.sin(angle) * seg_len
        nx = float(np.clip(nx, margin, w - margin))
        ny = float(np.clip(ny, margin, h - margin))
        points.append((nx, ny))

    all_x = [p[0] for p in points]
    all_y = [p[1] for p in points]
    x0 = max(0, int(min(all_x)) - width - 5)
    x1 = min(w, int(max(all_x)) + width + 5)
    y0 = max(0, int(min(all_y)) - width - 5)
    y1 = min(h, int(max(all_y)) + width + 5)

    # Локальные координаты
    lxs = np.arange(x0, x1, dtype=np.float32)
    lys = np.arange(y0, y1, dtype=np.float32)
    local_x, local_y = np.meshgrid(lxs, lys)

    min_dist = np.full(local_x.shape, 1e9, dtype=np.float32)
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        # Расстояние точки до отрезка (vectorized)
        d = _dist_to_segment(local_x, local_y, ax, ay, bx, by)
        np.minimum(min_dist, d, out=min_dist)

    # Нормализуем: 1.0 = граница (half-width)
    half_w = width / 2.0
    dist_norm = min_dist / half_w

    # Шум для неровной границы
    noise_seed = seed + int(rng.integers(0, 100000))
    fnl = FastNoiseLite()
    fnl.noise_type = FNLNoiseType.NoiseType_OpenSimplex2
    fnl.seed = noise_seed
    fnl.frequency = _EDGE_NOISE_FREQ * 1.5  # горы чуть более зернистые

    local_h, local_w = local_x.shape
    noise = _noise_2d(
        fnl, local_x.ravel(), local_y.ravel(),
    ).reshape(local_h, local_w)

    threshold = 1.0 + noise * _EDGE_NOISE_AMP
    mask = dist_norm < threshold

    grid[y0:y1, x0:x1][mask] = tile_id


def _dist_to_segment(
    px: np.ndarray, py: np.ndarray,
    ax: float, ay: float, bx: float, by: float,
) -> np.ndarray:
    """Расстояние от каждой точки (px, py) до отрезка AB. Vectorized."""
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy

    if len_sq < 1e-6:
        return np.sqrt((px - ax) ** 2 + (py - ay) ** 2)

    t = ((px - ax) * dx + (py - ay) * dy) / len_sq
    t = np.clip(t, 0.0, 1.0)

    proj_x = ax + t * dx
    proj_y = ay + t * dy

    return np.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


# ── Shore generation ─────────────────────────────────────────────────

def _ensure_shores_np(grid: np.ndarray) -> None:
    """Passable тайлы рядом с водой → shore. Вода всегда доступна."""
    is_water = grid == _WATER
    dilated = binary_dilation(is_water, structure=np.ones((3, 3), dtype=bool))
    shore_mask = dilated & ~is_water & (grid != _ROCK)
    grid[shore_mask] = _SHORE


# ── Start zone ───────────────────────────────────────────────────────

def _ensure_start_zone_np(grid: np.ndarray, w: int, h: int) -> None:
    """Центр карты: grass + ресурсы со всех сторон.

    Схема (вид сверху, cx/cy = центр):
        FOREST  слева  (запад)
        WATER   справа (восток)  + shore
        FOREST  пятно  юго-восток (для правых/нижних агентов)
        WATER   пруд   северо-запад (для левых/верхних агентов)
    Каждый агент в зоне 20×20 видит хотя бы 1 food + 1 water (vision=10).
    """
    cx, cy = w // 2, h // 2

    # Grass: основная зона 20×20
    grid[cy - 10 : cy + 10, cx - 10 : cx + 10] = _GRASS

    # ── ЗАПАД: основной лес ─────────────────────────
    grid[cy - 6 : cy + 6, cx - 14 : cx - 8] = _FOREST

    # ── ВОСТОК: основное озеро ───────────────────────
    grid[cy - 6 : cy + 6, cx + 10 : cx + 16] = _WATER

    # ── ЮГО-ВОСТОК: малый лес (для правых/нижних агентов) ──
    grid[cy + 2 : cy + 7, cx + 3 : cx + 8] = _FOREST

    # ── СЕВЕРО-ЗАПАД: малый пруд (для левых/верхних агентов) ──
    grid[cy - 7 : cy - 3, cx - 6 : cx - 2] = _WATER
    # Shore вокруг пруда генерируется автоматически в _ensure_shores_np


# ── Connectivity ─────────────────────────────────────────────────────

def _ensure_connectivity_np(grid: np.ndarray, w: int, h: int) -> None:
    """Изолированные проходимые острова → rock."""
    cx, cy = w // 2, h // 2

    passable = (grid == _GRASS) | (grid == _FOREST) | (grid == _SHORE)
    labeled, _ = label(passable, structure=np.ones((3, 3), dtype=np.int32))

    center_label = labeled[cy, cx]
    isolated = passable & (labeled != center_label)
    grid[isolated] = _ROCK


# ── Grid → TileMap ───────────────────────────────────────────────────

def _grid_to_tilemap(grid: np.ndarray, w: int, h: int) -> TileMap:
    """Конвертирует numpy int8 grid в TileMap."""
    tile_map = TileMap(w, h)
    lookup = _ID_TO_TILE

    for y in range(h):
        tile_map.tiles[y] = [lookup[v] for v in grid[y].tolist()]

    return tile_map


# ── Рендер карты (для Pygame) ──────────────────────────────────────


def render(
    surface: pygame.Surface,
    tile_map: TileMap,
    camera_x: int,
    camera_y: int,
    tile_size: int = 12,
) -> None:
    """Рисует видимые тайлы viewport на surface."""
    screen_w, screen_h = surface.get_size()
    cols = screen_w // tile_size + 1
    rows = screen_h // tile_size + 1

    for row in range(rows):
        for col in range(cols):
            wx = camera_x + col
            wy = camera_y + row
            if not tile_map.in_bounds(wx, wy):
                continue
            color = tile_map.get_type(wx, wy).color
            pygame.draw.rect(
                surface,
                color,
                (col * tile_size, row * tile_size, tile_size, tile_size),
            )
