"""
Renderer — основной цикл отрисовки.

Каждый кадр:
    1. Определяет видимые тайлы через Camera
    2. Рисует тайлы как закрашенные квадраты (цвета из config.TILE_COLORS)
    3. Рисует агентов как точки (config.AGENT_DOT_RADIUS px)
    4. Цвет агента по состоянию: белый → жёлтый → красный → серый
    5. Над точкой: имя (строка 1) + текущее действие (строка 2)
    6. Рисует HUD (панель агента, лог, контроли)
    7. Рисует debug overlay если включён

Клик по агенту → открывает панель агента в HUD.

Знает об агенте только: позицию, имя, действие, статус.
Никакой логики симуляции внутри.

Импортирует:
    pygame
    config (TILE_COLORS, AGENT_DOT_RADIUS, AGENT_COLOR_*)
    simulation.world.World
    renderer.camera.Camera
    renderer.hud.HUD
    renderer.debug_overlay.DebugOverlay

Экспортирует: Renderer
"""
