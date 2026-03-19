# Архитектура и модули — MVP 1

## Три принципа против легаси

**1. Симуляция не знает про рендер.**
Никакого Pygame внутри агентов или систем. Симуляция производит данные — рендер их читает. Эту границу нельзя нарушать никогда.

**2. Системы не знают друг про друга.**
NeedsSystem не вызывает DecisionSystem. Все системы общаются только через компоненты в World. Порядок систем задаётся снаружи, в GameLoop.

**3. Конфиг — отдельно, магических чисел нет.**
Никаких `0.3`, `1.5`, `120000` прямо в коде. Всё в `config.py`. Тюнинг симуляции = правка одного файла.

---

## Структура проекта

```
/
├── main.py                  # Точка входа: --headless, --seed, --debug, --ticks
├── config.py                # Все числовые параметры симуляции
│
├── simulation/              # Ядро — не знает про Pygame
│   ├── world.py             # World: хранит все entity и компоненты
│   │
│   ├── components/          # Только данные, никакой логики
│   │   ├── needs.py         # hunger, thirst, energy, health, mood, social, safety
│   │   ├── traits.py        # fearfulness, sociality, curiosity, resilience, faith
│   │   ├── body.py          # age, sex, is_child, is_pregnant, pregnancy_timer
│   │   ├── position.py      # x, y, current_action, action_timer, target_pos
│   │   ├── memory.py        # known_tiles, resource_locations, last_successful
│   │   └── identity.py      # name, parent_ids, guardian_id
│   │
│   ├── systems/             # Логика — читает и пишет компоненты
│   │   ├── time_system.py         # Тики, день/ночь
│   │   ├── needs_system.py        # Убывание потребностей, критические пороги
│   │   ├── decision_system.py     # Utility AI + curiosity → выбор действия
│   │   ├── movement_system.py     # A* патфайндинг, движение
│   │   ├── action_system.py       # Выполнение: eating, drinking, sleeping
│   │   ├── memory_system.py       # Обновление known_tiles по радиусу обзора
│   │   ├── social_system.py       # Фоновая социализация при близости
│   │   ├── reproduction_system.py # Условия размножения, беременность, рождение
│   │   ├── death_system.py        # Условия смерти, усыновление, лог смерти
│   │   └── event_system.py        # Генерация и рассылка событий, реакции
│   │
│   ├── map/
│   │   ├── tile.py          # Типы тайлов, свойства, цвета
│   │   ├── generator.py     # Процедурная генерация (opensimplex + seed)
│   │   └── pathfinder.py    # A* с кешированием путей
│   │
│   ├── factory.py           # Создание агентов (стартовые + новорождённые)
│   ├── namegen.py           # Процедурная генерация имён
│   └── game_loop.py         # Порядок систем за 1 тик
│
├── renderer/                # Всё про Pygame — не знает про логику
│   ├── renderer.py          # Viewport, тайлы (цветные квадраты), агенты (точки)
│   ├── camera.py            # WASD, зум, конвертация координат
│   ├── hud.py               # Панель агента, лог поселения, контроли
│   └── debug_overlay.py     # Overlay: действие и потребности над агентом
│
├── storage/
│   ├── logger.py            # Пишет events.jsonl, agents.jsonl, stats.jsonl, deaths.jsonl
│   ├── save.py              # Сохранение/загрузка состояния симуляции
│   └── offline.py           # Расчёт офлайн тиков (будущее)
│
├── tools/
│   ├── batch_run.py         # Запуск N симуляций параллельно
│   ├── analyze.py           # Анализ логов, отчёт, автофлаги
│   ├── inspect_agent.py     # Таймлайн конкретного агента
│   └── compare_runs.py      # Сравнение двух наборов прогонов
│
└── tests/
    ├── test_needs.py
    ├── test_decision.py
    ├── test_reproduction.py
    └── headless_run.py      # Прогон 10 000 тиков, вывод базовой статистики
```

---

## World — единственный источник правды

```
World
  ├── entities: set[int]
  ├── components: dict[type, dict[int, Component]]
  ├── map: TileMap
  └── event_queue: list[Event]   — события текущего тика
```

Ни одна система не хранит данные у себя. Всё через World.

---

## GameLoop — единственное место порядка

```python
# game_loop.py
SYSTEMS = [
    TimeSystem,            # сначала время — влияет на ночные веса
    NeedsSystem,           # убываем потребности
    MemorySystem,          # обновляем known_tiles
    DecisionSystem,        # выбираем действие
    MovementSystem,        # двигаемся к цели
    ActionSystem,          # выполняем действие на месте
    SocialSystem,          # фоновая социализация
    ReproductionSystem,
    DeathSystem,
    EventSystem,           # в конце — генерируем и рассылаем события тика
    LoggerSystem,          # последний — пишем лог после всех изменений тика
]
```

Выключить систему для теста = закомментировать одну строку.

---

## Config — все числа здесь

```python
# config.py

MAP_SIZE = (1000, 1000)
VIEWPORT_SIZE = (80, 50)

TICKS_PER_DAY = 24
DAY_START     = 6
NIGHT_START   = 22

# Тики жизненного цикла
CHILD_AGE     = 120_000
ADULT_AGE     = 480_000
TICKS_PER_YEAR = 8_760

# Скорости убывания потребностей за тик
NEED_DECAY = {
    'hunger': 0.0001,
    'thirst': 0.00015,
    'energy': 0.00008,
    'mood':   0.00005,
    'social': 0.00006,
    'safety': 0.0002,
}

# Utility веса
UTILITY_WEIGHTS = {
    'thirst': 1.5, 'hunger': 1.3, 'health': 1.2,
    'energy': 1.1, 'safety': 1.0, 'social': 0.8, 'mood': 0.7,
}
ENERGY_NIGHT_MULTIPLIER = 2.0
SOCIAL_NIGHT_MULTIPLIER = 0.5

# Агенты
VISION_RADIUS  = 10
SOCIAL_RADIUS  = 3
CURIOSITY_CHANCE = 0.3   # множитель к curiosity trait

# Размножение
REPRODUCTION_MIN_NEEDS = 0.3
PREGNANCY_TICKS = 2_760

# Черты
TRAIT_MU             = 0.5
TRAIT_SIGMA          = 0.15
TRAIT_MUTATION_SIGMA = 0.05

# Логирование
LOG_SNAPSHOT_INTERVAL = 100   # тиков между снимками agents.jsonl
LOG_STATS_INTERVAL    = 100

# Цвета тайлов (RGB)
TILE_COLORS = {
    'grass': (90, 138, 60),
    'forest': (45, 90, 27),
    'water': (58, 110, 168),
    'rock': (107, 107, 107),
    'shore': (200, 168, 75),
}
```

---

## Рендер — как рисуются агенты

```
renderer.py
  draw_tile(x, y, tile_type)   → закрашенный квадрат цветом из TILE_COLORS
  draw_agent(agent)            → белая точка + имя + действие над ней
  draw_agent_critical(agent)   → жёлтая / красная / серая точка по состоянию
```

Всё что знает рендер об агенте — его позиция, имя, текущее действие и статус. Никакой логики симуляции внутри рендера.

---

## Как добавлять новое без легаси

### Новая потребность (например: `warmth`)
1. Поле в `components/needs.py`
2. Decay в `config.py → NEED_DECAY`
3. Вес в `config.py → UTILITY_WEIGHTS`
4. Действие в `action_system.py`
5. DecisionSystem подхватит автоматически ✓

### Новый тип события (например: `storm`)
1. Добавить в `event_system.py` с `base_impact`
2. Формула реакции уже работает — агенты реагируют без изменений ✓

### Новая система (например: `disease_system` в MVP 2)
1. Файл `systems/disease_system.py`
2. Строка в `SYSTEMS` в `game_loop.py`
3. Больше ничего не трогается ✓

### Переход в headless
```python
# main.py
if args.headless:
    loop = GameLoop(world)
    loop.run(ticks=args.ticks)
else:
    renderer = Renderer(world)
    renderer.run()
```

---

## Что не надо делать

**Не класть логику в компоненты.** `agent.eat()` — это логика, она в `ActionSystem`. Компонент = только данные.

**Не делать системы зависимыми друг от друга.** Если DecisionSystem нужен результат NeedsSystem — читает компонент Needs через World, не вызывает систему.

**Не делать god-object Agent.** Класс Agent со всеми полями выглядит удобно сейчас. Через 3 этапа (здания, религия, профессии) он будет монстром на 800 строк. ECS решает это заранее.

**Не писать числа прямо в код.** Одно число в двух местах — это баг который ищешь 2 часа.
