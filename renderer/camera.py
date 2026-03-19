"""
Camera — viewport с перемещением и зумом.

Управление: WASD + колёсико мыши (зум).
Viewport: config.VIEWPORT_WIDTH × config.VIEWPORT_HEIGHT тайлов.

Методы:
    world_to_screen(x, y) → (px, py)  — мировые координаты в экранные
    screen_to_world(px, py) → (x, y)  — экранные в мировые (для кликов)
    is_visible(x, y) → bool            — тайл в зоне видимости?
    update(keys, mouse)                 — обработка ввода

Импортирует:
    pygame
    config (VIEWPORT_WIDTH, VIEWPORT_HEIGHT, MAP_WIDTH, MAP_HEIGHT)

Экспортирует: Camera
"""
