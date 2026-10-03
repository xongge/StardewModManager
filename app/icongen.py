"""纯 Python 生成应用图标（不依赖 Qt / Pillow）。

用法：
    python -m app.icongen icon.ico        # 生成多尺寸 ico
    python -m app.icongen icon.png 256    # 生成单张 png

设计：深色圆角方块 + 绿色叶片 + 金色星光。
"""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

UNIT = 256.0  # 设计稿坐标系
SS = 3        # 超采样倍数

# 颜色
BG_TOP = (20, 26, 35)
BG_BOTTOM = (34, 48, 63)
BORDER = (60, 74, 92)
LEAF_TOP = (109, 226, 164)
LEAF_BOTTOM = (39, 141, 96)
STEM = (46, 158, 107)
SPARK = (255, 209, 102)


# ---------------------------------------------------------------- 几何
def rounded_rect(w: float, h: float, r: float, seg: int = 20):
    pts = []
    corners = [(w - r, r, -90.0), (w - r, h - r, 0.0), (r, h - r, 90.0), (r, r, 180.0)]
    for cx, cy, start in corners:
        for i in range(seg + 1):
            a = math.radians(start + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def quad(p0, p1, p2, n: int = 28):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def star(cx, cy, r_out, r_in, points=4, rot=-90.0):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180.0 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _move(poly, dx, dy):
    return [(x + dx, y + dy) for x, y in poly]


# ---------------------------------------------------------------- 光栅化
def rasterize(poly, W: int, H: int) -> bytearray:
    mask = bytearray(W * H)
    if len(poly) < 3:
        return mask
    ys = [p[1] for p in poly]
    ymin = max(0, int(math.floor(min(ys))))
    ymax = min(H - 1, int(math.ceil(max(ys))))
    n = len(poly)
    for y in range(ymin, ymax + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if y1 == y2:
                continue
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                t = (yc - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
        if len(xs) < 2:
            continue
        xs.sort()
        base = y * W
        for i in range(0, len(xs) - 1, 2):
            xa = max(0, int(math.ceil(xs[i] - 0.5)))
            xb = min(W - 1, int(math.floor(xs[i + 1] - 0.5)))
            for x in range(xa, xb + 1):
                mask[base + x] = 1
    return mask


def _coverage(mask: bytearray, W: int, H: int):
    """把超采样掩码按 SS×SS 归约成 0..1 覆盖率。"""
    cov = [0.0] * (W * H)
    inv = 1.0 / (SS * SS)
    for oy in range(H):
        row = oy * SS * W * SS
        for ox in range(W):
            s = 0
            for dy in range(SS):
                base = row + dy * W * SS + ox * SS
                for dx in range(SS):
                    s += mask[base + dx]
            cov[oy * W + ox] = s * inv
    return cov


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def render_rgba(size: int) -> bytearray:
    """渲染 size×size 的 RGBA 像素。"""
    W = H = size
    s = size / UNIT
    SW, SH = W * SS, H * SS

    def sc(poly):
        return [(x * s * SS, y * s * SS) for x, y in poly]

    outer = sc(rounded_rect(UNIT, UNIT, 58))
    inner = sc(rounded_rect(UNIT - 2.6, UNIT - 2.6, 56))
    inner = _move(inner, 1.3 * s * SS, 1.3 * s * SS)

    leaf_bottom = (128.0, 196.0)
    leaf_top = (128.0, 54.0)
    leaf = quad(leaf_bottom, (46.0, 150.0), leaf_top) + quad(
        leaf_top, (210.0, 150.0), leaf_bottom
    )[1:]
    stem = rounded_rect(11.0, 34.0, 5.5)
    stem = _move(stem, 122.5, 186.0)
    spark = star(191.0, 79.0, 24.0, 8.0)

    cov_outer = _coverage(rasterize(outer, SW, SH), W, H)
    cov_inner = _coverage(rasterize(inner, SW, SH), W, H)
    cov_leaf = _coverage(rasterize(sc(leaf), SW, SH), W, H)
    cov_stem = _coverage(rasterize(sc(stem), SW, SH), W, H)
    cov_spark = _coverage(rasterize(sc(spark), SW, SH), W, H)

    out = bytearray(W * H * 4)
    for y in range(H):
        t = y / max(1, H - 1)
        bg = _lerp(BG_TOP, BG_BOTTOM, t)
        leaf_col = _lerp(LEAF_TOP, LEAF_BOTTOM, t)
        for x in range(W):
            i = y * W + x
            o = i * 4
            a_out = cov_outer[i]
            if a_out <= 0.002:
                continue
            # 背景（外框 + 内层渐变）
            r, g, b = BORDER
            a_bg = a_out
            ci = cov_inner[i]
            if ci > 0:
                r = int(r * (1 - ci) + bg[0] * ci)
                g = int(g * (1 - ci) + bg[1] * ci)
                b = int(b * (1 - ci) + bg[2] * ci)
            # 茎
            cs = cov_stem[i]
            if cs > 0:
                r = int(r * (1 - cs) + STEM[0] * cs)
                g = int(g * (1 - cs) + STEM[1] * cs)
                b = int(b * (1 - cs) + STEM[2] * cs)
            # 叶
            cl = cov_leaf[i]
            if cl > 0:
                r = int(r * (1 - cl) + leaf_col[0] * cl)
                g = int(g * (1 - cl) + leaf_col[1] * cl)
                b = int(b * (1 - cl) + leaf_col[2] * cl)
            # 星光
            cp = cov_spark[i]
            if cp > 0:
                r = int(r * (1 - cp) + SPARK[0] * cp)
                g = int(g * (1 - cp) + SPARK[1] * cp)
                b = int(b * (1 - cp) + SPARK[2] * cp)
            out[o] = max(0, min(255, r))
            out[o + 1] = max(0, min(255, g))
            out[o + 2] = max(0, min(255, b))
            out[o + 3] = max(0, min(255, int(round(a_out * 255))))
    return out


# ---------------------------------------------------------------- 编码
def to_png(w: int, h: int, rgba: bytes) -> bytes:
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def png_bytes(size: int) -> bytes:
    return to_png(size, size, bytes(render_rgba(size)))


def save_ico(path, sizes=(16, 32, 48, 64, 128, 256)) -> Path:
    images = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in zip(sizes, images):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path = Path(path)
    path.write_bytes(header + entries + blobs)
    return path


def save_png(path, size: int = 256) -> Path:
    path = Path(path)
    path.write_bytes(png_bytes(size))
    return path


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 1
    target = Path(argv[0])
    if target.suffix.lower() == ".png":
        size = int(argv[1]) if len(argv) > 1 else 256
        save_png(target, size)
        print(f"已生成 {target} ({size}x{size})")
    else:
        save_ico(target)
        print(f"已生成 {target} (16/32/48/64/128/256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
