#!/usr/bin/env python3
"""
Generate bowling-ball app icons for the PWA manifest.
Run once from the repo root: python generate_icons.py
Requires only Python stdlib (struct, zlib).
"""
import struct, zlib, os, math


def write_png(path, width, height, get_pixel):
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', crc)

    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            raw += bytes(get_pixel(x, y, width, height))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(png)
    print(f'  Written: {path}')


def bowling_pixel(x, y, w, h):
    cx, cy = w / 2, h / 2
    r = w * 0.44          # ball radius (88% of half-width)
    dx, dy = x - cx, y - cy
    dist = math.sqrt(dx * dx + dy * dy)

    # Anti-alias the ball edge
    aa_width = max(1.0, w / 96)
    edge_alpha = max(0.0, min(1.0, (r - dist) / aa_width))

    if edge_alpha <= 0:
        return (255, 255, 255)   # white background

    # Navy blue base (#1b3a6b)
    base = [27, 58, 107]

    # Subtle highlight (top-left quadrant brighter)
    angle = math.atan2(dy, dx)
    highlight = max(0.0, -math.cos(angle - math.radians(225))) * (1.0 - dist / r) * 0.35
    ball = [min(255, int(c + highlight * 255)) for c in base]

    # Three finger holes — positions relative to ball radius
    holes = [
        (cx - r * 0.18, cy - r * 0.28, r * 0.10),   # left
        (cx + r * 0.18, cy - r * 0.28, r * 0.10),   # right
        (cx,            cy - r * 0.48, r * 0.10),   # top center
    ]
    for hx, hy, hr in holes:
        hdist = math.sqrt((x - hx) ** 2 + (y - hy) ** 2)
        h_aa = max(0.0, min(1.0, (hr - hdist) / aa_width))
        if h_aa > 0:
            # Blend toward dark hole color
            hole_color = [15, 25, 50]
            ball = [int(ball[i] * (1 - h_aa) + hole_color[i] * h_aa) for i in range(3)]

    # Blend with white background at the edge
    if edge_alpha < 1.0:
        ball = [int(ball[i] * edge_alpha + 255 * (1 - edge_alpha)) for i in range(3)]

    return ball


if __name__ == '__main__':
    print('Generating PWA icons...')
    write_png('static/icons/icon-192.png', 192, 192, bowling_pixel)
    write_png('static/icons/icon-512.png', 512, 512, bowling_pixel)
    print('Done.')
