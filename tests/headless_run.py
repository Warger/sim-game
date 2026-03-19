"""
Headless-прогон для быстрого smoke-теста.

Запускает симуляцию на 10 000 тиков без рендера.
Выводит базовую статистику:
    - Финальная популяция
    - Кол-во рождений / смертей
    - Средний возраст при смерти
    - Были ли застрявшие агенты

CLI: python -m tests.headless_run --seed 42

Импортирует:
    config
    simulation.world.World
    simulation.game_loop.GameLoop
    simulation.map.generator
    simulation.factory
"""
