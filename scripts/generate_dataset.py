# -*- coding: utf-8 -*-
"""
合成数据集生成脚本
生成 300 件电商商品（家具/服饰/数码/家居/美妆/运动），
用 Pillow 生成占位图（纯色背景+文字标签，400x400），
图片保存到 data/images/，元数据保存到 data/products/products.json。
"""
import json
import os
import random
import sys

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PIL import Image, ImageDraw, ImageFont

import config

random.seed(42)

# 颜色名 -> RGB 背景色
COLOR_RGB = {
    "蓝色": (70, 130, 200), "白色": (240, 240, 240), "黑色": (40, 40, 40),
    "灰色": (150, 150, 150), "棕色": (139, 90, 43), "红色": (200, 60, 60),
    "绿色": (90, 160, 90), "米色": (225, 210, 180),
}

# 各品类商品名模板
CATEGORY_ITEMS = {
    "家具": ["三人沙发", "单人沙发", "实木餐桌", "茶几", "双人床", "书桌", "书柜", "餐椅", "边几", "电视柜"],
    "服饰": ["休闲外套", "纯棉T恤", "牛仔裤", "连衣裙", "针织毛衣", "风衣", "卫衣", "休闲裤", "夹克", "背包"],
    "数码": ["无线耳机", "机械键盘", "蓝牙音箱", "充电宝", "智能手表", "鼠标", "显示器", "U盘", "摄像头", "数据线"],
    "家居": ["台灯", "地毯", "抱枕", "窗帘", "收纳盒", "花瓶", "挂钟", "镜子", "坐垫", "置物架"],
    "美妆": ["口红", "面霜", "精华液", "眼影盘", "洗面奶", "香水", "粉底液", "面膜", "防晒霜", "睫毛膏"],
    "运动": ["瑜伽垫", "哑铃", "跑步鞋", "健身包", "跳绳", "水壶", "护腕", "运动T恤", "弹力带", "篮球"],
}

STYLE_CN = {
    "Nordic": "北欧", "Modern": "现代", "Classic": "古典",
    "Minimalist": "简约", "Industrial": "工业", "Vintage": "复古",
}


def load_font(size: int):
    """加载中文字体（Windows 黑体），失败则用默认字体。"""
    candidates = [
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def gen_image(product: dict, path: str) -> None:
    """生成商品占位图：纯色背景 + 居中文字标签，400x400。"""
    bg = COLOR_RGB.get(product["color"], (200, 200, 200))
    img = Image.new("RGB", (400, 400), bg)
    draw = ImageDraw.Draw(img)
    # 深色背景用白字，浅色背景用黑字，保证可读
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    text_color = (255, 255, 255) if luminance < 140 else (20, 20, 20)
    font_big = load_font(28)
    font_small = load_font(18)
    title = product["title"]
    lines = [title[:10], product["style"], f"{product['color']}·{product['material']}",
             f"¥{product['price']}"]
    y = 110
    for i, line in enumerate(lines):
        f = font_big if i == 0 else font_small
        bbox = draw.textbbox((0, 0), line, font=f)
        w = bbox[2] - bbox[0]
        draw.text(((400 - w) / 2, y), line, fill=text_color, font=f)
        y += 55
    img.save(path, "JPEG", quality=85)


def generate() -> None:
    """主生成流程。"""
    os.makedirs(config.IMAGE_DIR, exist_ok=True)
    os.makedirs(config.PRODUCT_DIR, exist_ok=True)
    products = []
    n = config.SYNTHETIC_PRODUCT_COUNT
    for i in range(1, n + 1):
        category = random.choice(config.PRODUCT_CATEGORIES)
        item = random.choice(CATEGORY_ITEMS[category])
        style = random.choice(config.PRODUCT_STYLES)
        color = random.choice(config.PRODUCT_COLORS)
        material = random.choice(config.PRODUCT_MATERIALS)
        price = round(random.uniform(29.0, 5999.0), 2)
        title = f"{STYLE_CN[style]}{color}{material}{item}"
        desc = f"{style}风格{category}商品，{color}{material}材质，{item}，性价比之选。"
        pid = f"P{i:03d}"
        product = {
            "product_id": i,           # int64 主键
            "product_code": pid,        # 对外展示编号
            "title": title,
            "description": desc,
            "price": price,
            "category": category,
            "style": style,
            "color": color,
            "material": material,
            "image_url": f"/api/images/{pid}.jpg",
        }
        # 生成图片
        img_path = os.path.join(config.IMAGE_DIR, f"{pid}.jpg")
        gen_image(product, img_path)
        products.append(product)

    # 保存元数据
    out = os.path.join(config.PRODUCT_DIR, "products.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"[完成] 生成 {len(products)} 件商品")
    print(f"  - 图片目录: {config.IMAGE_DIR}")
    print(f"  - 元数据: {out}")


if __name__ == "__main__":
    generate()
