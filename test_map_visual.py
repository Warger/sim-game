"""
Тестовая визуализация карты — запустить и увидеть цветные тайлы.

Управление:
    WASD / стрелки — перемещение камеры
    +/- или колёсико мыши — зум
    ESC — выход
"""

import sys
import pygame

import config
from simulation.map.generator import generate_map, render

TILE_SIZE_MIN = 2
TILE_SIZE_MAX = 32
TILE_SIZE_DEFAULT = 12

SCREEN_W = 1280
SCREEN_H = 800

SCROLL_SPEED = 10  # тайлов за нажатие


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42

    print(f"Генерация карты {config.MAP_WIDTH}×{config.MAP_HEIGHT}, seed={seed} ...")
    tile_map = generate_map(seed)
    print("Готово. Запуск Pygame.")

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(f"Map Preview — seed {seed}")
    clock = pygame.time.Clock()

    # Камера начинает в центре карты
    tile_size = TILE_SIZE_DEFAULT
    cam_x = config.MAP_WIDTH // 2 - (SCREEN_W // tile_size) // 2
    cam_y = config.MAP_HEIGHT // 2 - (SCREEN_H // tile_size) // 2

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    tile_size = min(tile_size + 2, TILE_SIZE_MAX)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    tile_size = max(tile_size - 2, TILE_SIZE_MIN)
            elif event.type == pygame.MOUSEWHEEL:
                tile_size = max(TILE_SIZE_MIN, min(TILE_SIZE_MAX, tile_size + event.y * 2))

        keys = pygame.key.get_pressed()
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            cam_y -= SCROLL_SPEED
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            cam_y += SCROLL_SPEED
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            cam_x -= SCROLL_SPEED
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            cam_x += SCROLL_SPEED

        # Clamp
        cam_x = max(0, min(cam_x, config.MAP_WIDTH - SCREEN_W // tile_size))
        cam_y = max(0, min(cam_y, config.MAP_HEIGHT - SCREEN_H // tile_size))

        screen.fill((0, 0, 0))
        render(screen, tile_map, cam_x, cam_y, tile_size)

        # HUD: координаты и зум
        font = pygame.font.SysFont("consolas", 16)
        info = f"cam=({cam_x},{cam_y})  zoom={tile_size}px  seed={seed}"
        text_surf = font.render(info, True, (255, 255, 255))
        screen.blit(text_surf, (8, 8))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
