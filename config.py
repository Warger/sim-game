"""
Все числовые параметры MVP 1.
Единственный источник констант для всей симуляции.
"""

# ── Временная система ────────────────────────────────────────────────

TICKS_PER_HOUR = 40
HOURS_PER_DAY = 24
TICKS_PER_DAY = TICKS_PER_HOUR * HOURS_PER_DAY          # 960
DAYS_PER_WEEK = 2              # сжатый календарь: неделя = 2 дня
WEEKS_PER_YEAR = 26
DAYS_PER_YEAR = DAYS_PER_WEEK * WEEKS_PER_YEAR            # 52
TICKS_PER_YEAR = TICKS_PER_DAY * DAYS_PER_YEAR            # 49_920

# Время суток (индекс внутри дня 0..TICKS_PER_DAY-1)
DAY_START_TICK = 0
DAY_END_TICK = 639        # 16 часов дня
NIGHT_START_TICK = 640
NIGHT_END_TICK = 959      # 8 часов ночи

# Скорость симуляции (множители)
SPEED_NORMAL = 1
SPEED_FAST = 100
SPEED_FASTER = 1_000
SPEED_HEADLESS = 10_000
DEFAULT_SPEED = SPEED_NORMAL

# ── Карта ────────────────────────────────────────────────────────────

MAP_WIDTH = 1000
MAP_HEIGHT = 1000

VIEWPORT_WIDTH = 80       # тайлов
VIEWPORT_HEIGHT = 50

# Цвета тайлов (RGB)
TILE_COLORS = {
    "grass":  (90, 138, 60),
    "forest": (45, 90, 27),
    "water":  (58, 110, 168),
    "rock":   (107, 107, 107),
    "shore":  (200, 168, 75),
}

# Проходимость
TILE_PASSABLE = {
    "grass":  True,
    "forest": True,
    "water":  False,
    "rock":   False,
    "shore":  True,
}

# Ресурсы
MAX_AGENTS_PER_RESOURCE_TILE = 8   # макс. агентов кормящихся от 1 тайла

# ── Агент — движение ─────────────────────────────────────────────────

AGENT_BASE_SPEED = 3.0             # тайлов/тик
AGENT_VISION_RADIUS = 30           # тайлов
VISION_UPDATE_INTERVAL = 20        # тиков между полными обновлениями видимости

# Steering
STEERING_SEPARATION_RADIUS = 2.0   # тайлов
STEERING_SEPARATION_WEIGHT = 0.5

# ── Потребности — decay за тик ───────────────────────────────────────

NEED_DECAY = {
    "hunger":   0.0005,
    "thirst":   0.0008,
    "energy":   0.001,
    "health":   0.0,       # убывает только у стариков (см. ELDER_HEALTH_DECAY)
    "mood":     0.00025,
    "social":   0.0005,
    "safety":   0.0005,
    "activity": 0.0008,    # потребность в занятости, decay ~= thirst
}

# Критические пороги
CRITICAL_THRESHOLD = {
    "hunger": 0.2,
    "thirst": 0.2,
    "energy": 0.1,
    "health": 0.1,
}

# Тиков при 0 до смерти
DEATH_TICKS_AT_ZERO = {
    "hunger": 1400,
    "thirst": 1200,
}

# ── Потребности — восполнение ─────────────────────────────────────────

# Длительность действий (тики)
ACTION_DURATION = {
    "eating":       80,       # ~2 часа
    "drinking":     40,       # ~1 час
    "sleeping":     320,      # ~8 часов
    "local_wander": 160,      # ~4 часа (activity: быт, позже — работа)
}

# Все три восстанавливают потребность до 1.0

# ── Utility AI — веса ────────────────────────────────────────────────

UTILITY_BASE_WEIGHT = {
    "thirst":   1.5,
    "hunger":   1.3,
    "health":   1.2,
    "energy":   1.1,
    "activity": 1.0,      # потребность в занятости (конкурент sleep)
    "safety":   1.0,
    "social":   0.8,      # домножается на sociality trait
    "mood":     0.7,
}

UTILITY_NIGHT_MODIFIER = {
    "thirst":   1.0,
    "hunger":   1.0,
    "health":   1.0,
    "energy":   2.0,
    "activity": 0.3,      # ночью не хочется заниматься делами
    "safety":   1.0,
    "social":   0.5,
    "mood":     0.5,
}

# Curiosity: вероятность случайного действия = curiosity * CURIOSITY_FACTOR
CURIOSITY_FACTOR = 0.2

# Wander: макс. радиус случайного блуждания (тайлов)
WANDER_RADIUS = 75
ACTIVITY_WANDER_RADIUS = 15          # радиус local_wander (быт рядом с домом)

# ── Социализация ──────────────────────────────────────────────────────

SOCIAL_INTERACTION_RADIUS = 8      # тайлов (было 3)
SOCIAL_SUCCESS_MOOD_BONUS = 0.5
SOCIAL_SUCCESS_SOCIAL_BONUS = 0.8
SOCIAL_COOLDOWN_TICKS = 40         # тиков между социализациями (~1 час)

# ── Обмен знаниями о ресурсах ────────────────────────────────────────
ASK_RESOURCE_RADIUS = 10           # тайлов — макс. дистанция чтобы спросить
ASK_RESOURCE_COOLDOWN_TICKS = 80   # тиков между попытками спросить (~2 часа)

# ── Жизненный цикл ───────────────────────────────────────────────────

CHILD_END_AGE_YEARS = 6
ADULT_END_AGE_YEARS = 55
MAX_LIFE_YEARS = 70

CHILD_END_TICKS = CHILD_END_AGE_YEARS * TICKS_PER_YEAR    # 648_960
ADULT_END_TICKS = ADULT_END_AGE_YEARS * TICKS_PER_YEAR    # 2_745_600
MAX_LIFE_TICKS = MAX_LIFE_YEARS * TICKS_PER_YEAR          # 3_494_400

# Health decay для стариков (базовый: health 1.0→0.0 за MAX_LIFE - ADULT_END)
ELDER_HEALTH_DECAY = 1.0 / (MAX_LIFE_TICKS - ADULT_END_TICKS)

# Индивидуальный разброс: при рождении агент получает коэффициент
# personal_decay = ELDER_HEALTH_DECAY * normal(1.0, σ)
# >1 — умрёт раньше, <1 — проживёт дольше
ELDER_DECAY_COEFF_STD = 0.15

# ── Рождение ──────────────────────────────────────────────────────────

PREGNANCY_DURATION_TICKS = 13_140  # ~9 месяцев
# BIRTH_CHANCE_PER_TICK — подбирается через batch runner, начальное значение:
BIRTH_CHANCE_PER_TICK = 0.0005
REPRODUCTION_PROXIMITY_RADIUS = 3   # тайлов между партнёрами
REPRODUCTION_MIN_NEEDS = 0.3        # все потребности > этого порога
TRAIT_INHERITANCE_SIGMA = 0.05      # σ гауссова шума при наследовании черт

# ── Смерть ────────────────────────────────────────────────────────────

DEATH_BODY_TICKS = 168                       # тиков тело на карте
ORPHAN_DEATH_TICKS = 960                     # тиков до смерти сироты (~1 день)

# Пороги смерти
STARVATION_DEATH_TICKS = DEATH_TICKS_AT_ZERO["hunger"]   # 700
DEHYDRATION_DEATH_TICKS = DEATH_TICKS_AT_ZERO["thirst"]  # 300
ELDER_DEATH_AGE_TICKS = ADULT_END_TICKS                   # старость начинается

# ── Черты (traits) ────────────────────────────────────────────────────

TRAIT_NAMES = ("fearfulness", "sociality", "curiosity", "resilience", "faith")
TRAIT_MEAN = 0.5
TRAIT_STD = 0.15


# ── События — base_impact ────────────────────────────────────────────

EVENT_IMPACT = {
    "death_nearby":         {"mood": -0.2, "safety": -0.2},
    "birth_nearby":         {"mood": +0.15},
    "faint_nearby":         {"safety": -0.1},
    "social_success":       {"mood": +0.2, "social": +0.2},
}

# proximity_modifier = 1.0 / (1.0 + distance / PROXIMITY_SCALE)
PROXIMITY_SCALE = 10.0

# ── Восстановление safety / mood ────────────────────────────────

SOCIAL_PROXIMITY_RESTORE = 0.0005   # social/тик при наличии соседа рядом (фон)

SAFETY_PROXIMITY_RADIUS = 8         # тайлов — рядом с другим агентом → восстановление
SAFETY_PROXIMITY_RESTORE = 0.002    # safety/тик при наличии соседа
SAFETY_SLEEP_RESTORE = 0.00025      # safety/тик во сне

MOOD_SLEEP_RESTORE = 0.0005         # mood/тик во сне
MOOD_WELL_FED_THRESHOLD = 0.8       # hunger > порога → mood бонус
MOOD_WELL_FED_RESTORE = 0.00025     # mood/тик при сытости

# ── Дети: опека guardian-а ──────────────────────────────────────

CHILD_GUARDIAN_PROXIMITY = 2        # тайлов — "рядом с опекуном"
CHILD_NEAR_GUARDIAN_DECAY_FACTOR = 0.2   # множитель decay потребностей (1/5)
CHILD_GUARDIAN_FEED_FRACTION = 0.5  # доля восстановления передаваемая ребёнку
CHILD_NEED_SATISFIED = 0.7         # порог "ребёнок сыт/напоен" для родителя
CHILD_PASSIVE_RESTORE = 0.0004     # восстановление thirst/hunger ребёнку за тик (при живом guardian)

# ── Home comfort (привязанность к месту) ────────────────────────

HOME_COMFORT_INITIAL = 0.5
HOME_COMFORT_MAX = 1.0
HOME_COMFORT_DECAY = 0.0001         # пассивный decay/тик
HOME_COMFORT_SUCCESS_BONUS = 0.02   # бонус за успешное eating/drinking/socializing
HOME_COMFORT_FAIL_DROP = 0.15       # штраф за неудачный поиск ресурса
HOME_COMFORT_EXPLORE_THRESHOLD = 0.3  # ниже → режим exploration
HOME_COMFORT_CURIOSITY_FACTOR = 0.3   # curiosity снижает порог миграции
EXPLORE_WANDER_RADIUS = 200         # радиус wander в exploration mode

# ── Память агента ──────────────────────────────────────────────────
MEMORY_KNOWN_TILES_LIMIT = 5000     # макс. запомненных тайлов (LRU-eviction)
MAX_RESOURCE_MEMORY = 50            # макс. запомненных тайлов на тип ресурса

# ── Стартовые параметры ──────────────────────────────────────────────

START_AGENT_COUNT = 10             # 5M + 5F
START_AGE_MIN_YEARS = 18
START_AGE_MAX_YEARS = 35
START_AGE_MIN_TICKS = START_AGE_MIN_YEARS * TICKS_PER_YEAR
START_AGE_MAX_TICKS = START_AGE_MAX_YEARS * TICKS_PER_YEAR
START_NEEDS_MIN = 0.7
START_NEEDS_MAX = 1.0

# ── Визуал (Pygame) ──────────────────────────────────────────────────

AGENT_DOT_RADIUS = 4              # px
AGENT_COLOR_NORMAL = (255, 255, 255)
AGENT_COLOR_CRITICAL = (255, 255, 0)
AGENT_COLOR_DYING = (255, 0, 0)
AGENT_COLOR_SLEEPING = (128, 128, 128)

# ── Тайл-коллизии ────────────────────────────────────────────────────

MAX_AGENTS_PER_TILE = 1

# ── Логирование ─────────────────────────────────────────────────────

LOG_SNAPSHOT_INTERVAL = 100        # тиков между снимками agents.jsonl
LOG_STATS_INTERVAL = 100           # тиков между записями stats.jsonl
LOG_BUFFER_SIZE = 64               # кол-во строк в буфере перед flush

# Уровень логирования 0-10:
#   0     — без вывода
#   1-3   — только ошибки и критические события (смерть)
#   4-5   — ежедневные отчёты + события (default)
#   6-7   — подробный debug (решения, пути)
#   8-10  — всё включая каждый тик
LOG_LEVEL = 5

# ── Отладка ──────────────────────────────────────────────────────────

DEBUG = False


def get_config_snapshot() -> dict:
    """Return all uppercase constants as a dict for logging."""
    return {
        k: v for k, v in globals().items()
        if k.isupper() and not k.startswith('_')
        and isinstance(v, (int, float, str, bool, list, tuple, dict))
    }
