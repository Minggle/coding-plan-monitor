"""生成应用图标：蓝色圆底 + 进度环 + 字母 C，输出 assets/icon.ico 与 assets/icon.png。

用法：python scripts/make_icon.py（需 pillow）
"""

import math
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024          # 超采样画布
BG = "#3569d4"       # 与托盘图标一致的品牌蓝
TRACK = (255, 255, 255, 90)
ARC = "#ffffff"

os.makedirs("assets", exist_ok=True)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆形底
m = int(SIZE * 0.02)
d.ellipse([m, m, SIZE - m, SIZE - m], fill=BG)

# 进度环：轨道 + 70% 弧（12 点起顺时针）
ring_w = int(SIZE * 0.075)
rm = int(SIZE * 0.10)
bbox = [rm, rm, SIZE - rm, SIZE - rm]
d.arc(bbox, 0, 360, fill=TRACK, width=ring_w)
d.arc(bbox, -90, -90 + 360 * 0.7, fill=ARC, width=ring_w)
# 弧线端点圆头
ang = math.radians(-90 + 360 * 0.7)
cx = SIZE / 2 + (SIZE / 2 - rm) * math.cos(ang)
cy = SIZE / 2 + (SIZE / 2 - rm) * math.sin(ang)
r = ring_w / 2
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ARC)
d.ellipse([SIZE / 2 - r, rm - r, SIZE / 2 + r, rm + r], fill=ARC)

# 中心字母 C
font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", int(SIZE * 0.42))
d.text((SIZE / 2, SIZE / 2), "C", font=font, fill="#ffffff", anchor="mm")

img.save("assets/icon.png")
img.save(
    "assets/icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("icon generated -> assets/icon.png, assets/icon.ico")