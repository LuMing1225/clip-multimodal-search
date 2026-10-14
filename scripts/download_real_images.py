# -*- coding: utf-8 -*-
"""
真实商品图片下载脚本
从必应图片搜索按关键词批量下载真实商品图片
覆盖6个类别: 家具/服饰/数码/家居/美妆/运动，每类50张，共300张
"""
import os
import re
import json
import time
import random
import hashlib
import requests
from urllib.parse import quote
from pathlib import Path

# ========== 配置 ==========
PROJECT_DIR = r"E:\shixunXM\工单4\05-CLIP电商多模态检索系统"
IMAGE_DIR = os.path.join(PROJECT_DIR, "data", "images")
PRODUCT_JSON = os.path.join(PROJECT_DIR, "data", "products", "products.json")
TEMP_DIR = r"E:\shixunXM\temp_real_images"

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ========== 类别关键词（每类50个）==========
CATEGORIES = {
    "家具": [
        "北欧风蓝色布艺沙发", "现代简约白色茶几", "实木餐桌椅组合", "复古棕色皮沙发",
        "工业风黑色书架", "经典灰色布艺扶手椅", "极简白色书桌", "中式实木衣柜",
        "轻奢大理石边几", "日式原木电视柜", "美式乡村床头柜", "地中海风格斗柜",
        "北欧风懒人沙发", "现代简约餐桌", "实木餐椅", "布艺单人沙发", "玻璃茶几",
        "实木书架", "白色梳妆台", "棕色皮艺床", "北欧风餐椅", "简约现代沙发",
        "实木办公桌", "布艺休闲椅", "大理石餐桌", "原木书架", "白色床头柜",
        "灰色布艺沙发", "实木茶几", "北欧风书桌", "现代简约衣柜", "皮艺单人沙发",
        "实木电视柜", "布艺餐椅", "玻璃边几", "原木餐桌", "白色书架",
        "棕色皮沙发", "北欧风茶几", "简约现代书桌", "实木床头柜", "布艺双人床",
        "大理石边几", "原木衣柜", "灰色扶手椅", "白色茶几", "实木沙发",
    ],
    "服饰": [
        "蓝色碎花连衣裙", "白色纯棉T恤", "黑色修身西装", "灰色连帽卫衣", "棕色皮夹克",
        "红色针织毛衣", "卡其色风衣", "米色羊毛大衣", "深蓝色牛仔裤", "黑色运动短裤",
        "白色衬衫", "黑色小礼服", "灰色西装外套", "粉色连衣裙", "绿色POLO衫",
        "黄色卫衣", "紫色毛衣", "橙色夹克", "棕色风衣", "黑色皮裤",
        "白色运动鞋", "黑色高跟鞋", "棕色马丁靴", "灰色帆布鞋", "白色凉鞋",
        "蓝色牛仔外套", "黑色羽绒服", "米色针织开衫", "红色连衣裙", "绿色夹克",
        "白色卫衣", "黑色T恤", "灰色大衣", "棕色皮衣", "蓝色衬衫",
        "卡其色休闲裤", "黑色阔腿裤", "灰色运动裤", "白色短裤", "棕色休闲鞋",
        "黑色棒球帽", "灰色围巾", "棕色皮带", "黑色手提包", "白色毛线帽",
        "蓝色领带", "红色手套", "绿色袜子", "黄色背包", "紫色发带",
    ],
    "数码": [
        "黑色智能手机", "银色笔记本电脑", "白色无线耳机", "黑色智能手表", "深空灰平板电脑",
        "黑色蓝牙音箱", "白色机械键盘", "黑色游戏鼠标", "银色显示器", "白色充电宝",
        "黑色手机壳", "银色U盘", "白色数据线", "黑色路由器", "银色移动硬盘",
        "黑色头戴式耳机", "白色智能音箱", "黑色相机", "银色摄像机", "白色电子阅读器",
        "黑色游戏手柄", "银色投影仪", "白色扫地机器人", "黑色空气净化器", "银色加湿器",
        "黑色智能门锁", "白色摄像头", "黑色跑步机", "银色筋膜枪", "白色体脂秤",
        "黑色电动牙刷", "银色剃须刀", "白色吹风机", "黑色卷发棒", "银色美容仪",
        "白色kindle", "黑色switch", "银色PS5", "白色Xbox", "黑色VR眼镜",
        "银色无人机", "黑色平衡车", "白色电动滑板", "黑色智能手环", "银色录音笔",
        "白色计算器", "黑色打印机", "银色扫描仪", "白色复印机", "黑色碎纸机",
    ],
    "家居": [
        "白色陶瓷花瓶", "米色棉麻窗帘", "灰色羊毛地毯", "北欧风香薰蜡烛", "原木收纳盒",
        "极简台灯", "几何图案抱枕", "黑色金属相框", "玻璃冷水壶", "陶瓷餐具套装",
        "纯棉四件套", "羽绒被", "乳胶枕头", "蚕丝被", "记忆棉床垫",
        "挂钟", "装饰画", "仿真绿植", "干花花束", "玻璃鱼缸",
        "收纳柜", "置物架", "鞋架", "衣帽架", "杂物篮",
        "浴巾", "毛巾", "浴帘", "马桶垫", "浴室置物架",
        "厨房收纳架", "调料罐", "菜刀套装", "砧板", "锅具套装",
        "保温杯", "马克杯", "玻璃杯", "陶瓷杯", "水壶",
        "晾衣架", "熨衣板", "吸尘器", "拖把", "扫把",
        "垃圾桶", "纸巾盒", "雨伞架", "钥匙挂钩", "门垫",
    ],
    "美妆": [
        "正红色口红", "自然色粉底液", "清新花香香水", "补水面膜", "大地色眼影盘",
        "防晒霜SPF50", "氨基酸洗面奶", "玻尿酸精华液", "蜜桃色腮红", "浓密睫毛膏",
        "黑色眼线笔", "棕色眉笔", "透明唇釉", "散粉定妆", "遮瑕膏",
        "化妆刷套装", "美妆蛋", "睫毛夹", "化妆棉", "卸妆水",
        "洗发水", "护发素", "发膜", "护发精油", "卷发棒",
        "沐浴露", "身体乳", "磨砂膏", "护手霜", "足霜",
        "牙膏", "牙刷", "漱口水", "牙线", "美白牙贴",
        "男士洗面奶", "男士面霜", "男士香水", "剃须刀", "剃须泡沫",
        "美甲套装", "指甲油", "卸甲水", "指甲锉", "死皮推",
        "美容仪", "洁面仪", "卷发器", "直发器", "睫毛增长液",
    ],
    "运动": [
        "蓝色瑜伽垫", "黑色哑铃套装", "白色跑步鞋", "橙色篮球", "黑色羽毛球拍",
        "灰色健身球", "黑色竞速跳绳", "蓝色运动水壶", "黑色护膝", "绿色户外帐篷",
        "瑜伽服", "运动内衣", "健身手套", "运动头带", "护腕",
        "足球", "排球", "网球拍", "乒乓球拍", "高尔夫球杆",
        "自行车", "头盔", "骑行手套", "骑行眼镜", "水壶架",
        "登山杖", "登山包", "冲锋衣", "登山鞋", "睡袋",
        "游泳镜", "泳衣", "泳帽", "浮板", "跟屁虫",
        "滑板", "轮滑鞋", "护具套装", "滑板车", "平衡车",
        "飞盘", "风筝", "毽子", "呼啦圈", "拉力器",
        "蛋白粉", "肌酸", "运动饮料", "能量棒", "代餐奶昔",
    ],
}

STYLES = ["Nordic", "Modern", "Classic", "Minimalist", "Industrial", "Vintage"]
COLORS_MAP = {
    "家具": ["蓝色", "白色", "黑色", "灰色", "棕色", "米色"],
    "服饰": ["蓝色", "白色", "黑色", "灰色", "红色", "绿色"],
    "数码": ["黑色", "白色", "银色", "深空灰", "金色", "蓝色"],
    "家居": ["白色", "米色", "灰色", "原木色", "黑色", "蓝色"],
    "美妆": ["红色", "粉色", "自然色", "黑色", "透明", "金色"],
    "运动": ["黑色", "蓝色", "白色", "灰色", "橙色", "绿色"],
}
MATERIALS_MAP = {
    "家具": ["布艺", "实木", "金属", "皮革", "玻璃", "陶瓷"],
    "服饰": ["棉麻", "皮革", "牛仔", "羊毛", "针织", "羽绒"],
    "数码": ["金属", "塑料", "玻璃", "硅胶", "碳纤维", "铝合金"],
    "家居": ["陶瓷", "棉麻", "玻璃", "金属", "木质", "塑料"],
    "美妆": ["液体", "膏状", "粉状", "喷雾", "精油", "凝胶"],
    "运动": ["橡胶", "皮革", "金属", "塑料", "棉质", "碳纤维"],
}


def download_image(url, save_path, timeout=15):
    """下载单张图片，返回是否成功"""
    try:
        # 处理URL中的HTML实体
        url = url.replace('&amp;', '&').replace('&quot;', '"').replace('\\/', '/')
        dl_headers = dict(HEADERS)
        dl_headers["Referer"] = "https://cn.bing.com/"
        r = requests.get(url, headers=dl_headers, timeout=timeout, stream=True, allow_redirects=True)
        if r.status_code != 200:
            return False
        content = r.content
        if len(content) < 8000:  # 太小的图片可能是缩略图/占位图
            return False
        # 检查是否为有效图片
        if content[:3] == b'\xff\xd8\xff' or content[:8] == b'\x89PNG\r\n\x1a\n' or content[:6] in (b'GIF87a', b'GIF89a'):
            with open(save_path, 'wb') as f:
                f.write(content)
            return True
        return False
    except Exception:
        return False


def search_bing_images(keyword, max_results=8):
    """从必应图片搜索获取图片URL列表"""
    urls = []
    try:
        url = f"https://cn.bing.com/images/search?q={quote(keyword)}&form=HDRSC2&first=1"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return urls
        # 必应HTML中使用 &quot; 实体编码，匹配 murl 原始图片URL
        pattern = r'murl&quot;:&quot;(https?://[^&]+?\.(?:jpg|jpeg|png|webp|gif))'
        matches = re.findall(pattern, r.text, re.IGNORECASE)
        for m in matches[:max_results]:
            clean_url = m.replace('&amp;', '&').replace('\\/', '/')
            urls.append(clean_url)
    except Exception as e:
        print(f"  搜索失败: {e}")
    return urls


def main():
    print("=" * 60)
    print("真实商品图片下载脚本")
    print("=" * 60)

    products = []
    pid = 1
    total_downloaded = 0
    total_failed = 0

    for category, keywords in CATEGORIES.items():
        print(f"\n{'='*40}")
        print(f"类别: {category} ({len(keywords)}个关键词)")
        print(f"{'='*40}")

        for idx, keyword in enumerate(keywords):
            product_code = f"P{pid:03d}"
            save_path = os.path.join(IMAGE_DIR, f"{product_code}.jpg")

            # 如果已存在有效图片，跳过
            if os.path.exists(save_path) and os.path.getsize(save_path) > 5000:
                print(f"  [{idx+1}/{len(keywords)}] {keyword} -> 已存在，跳过")
                # 仍需生成商品元数据
                style = random.choice(STYLES)
                color = random.choice(COLORS_MAP[category])
                material = random.choice(MATERIALS_MAP[category])
                price = round(random.uniform(29, 9999), 2)
                products.append({
                    "product_id": pid,
                    "product_code": product_code,
                    "title": keyword,
                    "description": f"{style}风格{category}商品，{color}{material}材质，{keyword}，品质之选。",
                    "price": price,
                    "category": category,
                    "style": style,
                    "color": color,
                    "material": material,
                    "image_url": f"/api/images/{product_code}.jpg",
                })
                pid += 1
                total_downloaded += 1
                continue

            # 搜索图片
            print(f"  [{idx+1}/{len(keywords)}] 搜索: {keyword}...", end=" ")
            image_urls = search_bing_images(keyword, max_results=8)

            downloaded = False
            for img_url in image_urls:
                if download_image(img_url, save_path):
                    downloaded = True
                    total_downloaded += 1
                    print(f"✓ 下载成功 ({os.path.getsize(save_path)//1024}KB)")
                    break

            if not downloaded:
                total_failed += 1
                print(f"✗ 下载失败 ({len(image_urls)}个URL均不可用)")
                # 下载失败时生成占位图（用Pillow），保证不缺图
                try:
                    from PIL import Image, ImageDraw, ImageFont
                    img = Image.new('RGB', (400, 400), color=(200, 200, 200))
                    draw = ImageDraw.Draw(img)
                    draw.text((100, 190), keyword[:10], fill=(80, 80, 80))
                    img.save(save_path, 'JPEG', quality=85)
                except Exception:
                    pass

            # 生成商品元数据
            style = random.choice(STYLES)
            color = random.choice(COLORS_MAP[category])
            material = random.choice(MATERIALS_MAP[category])
            price = round(random.uniform(29, 9999), 2)
            products.append({
                "product_id": pid,
                "product_code": product_code,
                "title": keyword,
                "description": f"{style}风格{category}商品，{color}{material}材质，{keyword}，品质之选。",
                "price": price,
                "category": category,
                "style": style,
                "color": color,
                "material": material,
                "image_url": f"/api/images/{product_code}.jpg",
            })
            pid += 1

            # 控制请求频率
            time.sleep(random.uniform(0.3, 0.8))

    # 保存products.json
    os.makedirs(os.path.dirname(PRODUCT_JSON), exist_ok=True)
    with open(PRODUCT_JSON, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"下载完成!")
    print(f"  成功: {total_downloaded} 张")
    print(f"  失败: {total_failed} 张")
    print(f"  商品总数: {len(products)}")
    print(f"  元数据: {PRODUCT_JSON}")
    print(f"  图片目录: {IMAGE_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
