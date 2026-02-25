#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu News Bot - 每日新闻摘要推送到飞书
采集 IT、金融、AI 行业新闻，使用 DeepSeek AI 总结，推送到飞书群聊
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict
import feedparser
import requests
from dotenv import load_dotenv
import pytz
from urllib.parse import urlparse

load_dotenv()

# 缩略图缓存
THUMBNAIL_CACHE = {}

# 分类对应的默认图片（根据分类使用不同的图）
CATEGORY_THUMBNAILS = {
    'AI': 'https://images.unsplash.com/photo-1677442136019-21780ecad995?w=400&h=200&fit=crop',
    '科技': 'https://images.unsplash.com/photo-1518770660439-4636190af475?w=400&h=200&fit=crop',
    '创投': 'https://images.unsplash.com/photo-1559136555-9303baea8ebd?w=400&h=200&fit=crop',
}
DEFAULT_THUMBNAIL = 'https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=400&h=200&fit=crop'

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL") or "https://open.feishu.cn/open-apis/bot/v2/hook/2ab18ec8-6c48-4c73-b24d-6d73b78b1b81"

# 简报网页地址（用户需要自己部署，可以GitHub Pages）
REPORT_URL = os.getenv("REPORT_URL") or "https://bo1839.github.io/pushnewstest/"

# 新闻源
RSS_FEEDS = [
    {"name": "36Kr科技", "url": "https://36kr.com/feed", "category": "科技"},
    {"name": "虎嗅", "url": "https://www.huxiu.com/rss", "category": "科技"},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/rss_all.xml", "category": "科技"},
    {"name": "新浪科技", "url": "https://rss.sina.com.cn/tech/roll.xml", "category": "科技"},
    {"name": "36Kr创投", "url": "https://36kr.com/information/VC/feed", "category": "创投"},
    {"name": "36Kr金融", "url": "https://36kr.com/information/financial/feed", "category": "创投"},
    {"name": "创业邦", "url": "https://www.cyzone.cn/rss/", "category": "创投"},
    {"name": "36KrAI", "url": "https://36kr.com/information/AI/feed", "category": "AI"},
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "category": "AI"},
]

BEIJING_TZ = pytz.timezone('Asia/Shanghai')

# 存储目录
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_news_hash(title, url):
    return hashlib.md5(f"{title}_{url}".encode()).hexdigest()

def is_recent(pub_date, hours=48):
    try:
        for fmt in ['%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
            try:
                if '%z' in fmt:
                    parsed = datetime.strptime(pub_date, fmt)
                else:
                    parsed = pytz.utc.localize(datetime.strptime(pub_date, fmt))
                beijing_time = parsed.astimezone(BEIJING_TZ)
                return datetime.now(BEIJING_TZ) - timedelta(hours=hours) < beijing_time
            except:
                continue
        return True
    except:
        return True

def fetch_feed(feed_info):
    try:
        print(f"📥 正在获取：{feed_info['name']}...")
        feed = feedparser.parse(feed_info['url'])
        articles = []
        for entry in feed.entries[:30]:
            title = clean_html(entry.get('title', ''))
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))
            pub_date = entry.get('published', '')
            if not title or not link:
                continue
            
            # 获取缩略图
            thumbnail = None
            try:
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    thumbnail = entry.media_thumbnail[0]['url']
                elif hasattr(entry, 'media_content') and entry.media_content:
                    thumbnail = entry.media_content[0]['url']
                elif 'image' in entry and entry.image:
                    thumbnail = entry.image
                elif 'enclosures' in entry and entry.enclosures:
                    for enc in entry.enclosures:
                        enc_type = str(enc.get('type', ''))
                        if enc_type and 'image' in enc_type.lower():
                            thumbnail = str(enc.get('href', ''))
                            break
            except:
                thumbnail = None
            
            article = {
                'title': title,
                'link': link,
                'summary': summary[:300] if summary else '',
                'pub_date': pub_date,
                'category': feed_info['category'],
                'source': feed_info['name'],
                'hash': get_news_hash(title, link),
                'thumbnail': thumbnail
            }
            articles.append(article)
        print(f"   ✅ 获取到 {len(articles)} 条")
        return articles
    except Exception as e:
        print(f"   ❌ 获取失败：{e}")
        return []

def fetch_article_thumbnail(url):
    """爬取文章网页，提取第一张或第二张有效图片作为缩略图"""
    if url in THUMBNAIL_CACHE:
        return THUMBNAIL_CACHE[url]
    
    def is_valid_image(img_url):
        """判断是否是有效的图片 URL"""
        if not img_url or not img_url.startswith('http'):
            return False
        lower_url = img_url.lower()
        # 过滤 logo、icon、小图等
        skip_words = ['logo', 'icon', 'avatar', 'header', 'nav', 'thumb', 'button', 'bg', 'cover', 'sponsor', 'ad', 'banner']
        if any(x in lower_url for x in skip_words):
            return False
        # 过滤 Base64
        if img_url.startswith('data:'):
            return False
        return True
    
    # 特殊处理：有 API 的网站
    # 机器之心：https://www.jiqizhixin.com/api/v1/articles/{slug}
    if 'jiqizhixin.com/articles/' in url:
        match = re.search(r'jiqizhixin\.com/articles/([\w-]+)', url)
        if match:
            article_slug = match.group(1)
            try:
                api_url = f'https://www.jiqizhixin.com/api/v1/articles/{article_slug}'
                resp = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    cover_url = data.get('cover_image_url')
                    if cover_url and is_valid_image(cover_url):
                        THUMBNAIL_CACHE[url] = cover_url
                        return cover_url
            except:
                pass
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        # 检查是否被拦截
        if response.status_code != 200:
            return None
            
        # 尝试多种编码
        response.encoding = response.apparent_encoding or 'utf-8'
        html = response.text
        
        if len(html) < 1000:
            return None
        
        all_images = []
        data_src_patterns = [
            r'data-src=["\']([^"\']+)["\']',
            r'data-original=["\']([^"\']+)["\']',
            r'data-img=["\']([^"\']+)["\']',
        ]
        
        # 1. 优先提取 og:image (文章主图)
        og_patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ]
        
        for pattern in og_patterns:
            og_match = re.search(pattern, html, re.IGNORECASE)
            if og_match:
                img_url = og_match.group(1)
                if is_valid_image(img_url):
                    THUMBNAIL_CACHE[url] = img_url
                    return img_url
        
        # 2. 提取文章内容区域的所有图片
        content_patterns = [
            r'<article[^>]*>(.*?)</article>',
            r'<main[^>]*>(.*?)</main>',
            r'<div[^>]+class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>',
            r'<div[^>]+id=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>',
            r'<section[^>]+class=["\'][^"\']*article[^"\']*["\'][^>]*>(.*?)</section>',
        ]
        
        content_html = ""
        for pattern in content_patterns:
            content_match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if content_match:
                content_html = content_match.group(1)
                break
        
        # 从内容区域提取图片 (src 和 data-src)
        if content_html:
            # 提取普通 src
            img_pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
            matches = re.findall(img_pattern, content_html, re.IGNORECASE)
            for match in matches:
                if is_valid_image(match):
                    all_images.append(match)
            
            # 提取 data-src, data-original 等
            for pattern in data_src_patterns:
                matches = re.findall(pattern, content_html, re.IGNORECASE)
                for match in matches:
                    if is_valid_image(match):
                        all_images.append(match)
        
        # 如果内容区域没有找到，从整个页面提取
        if not all_images:
            img_pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
            matches = re.findall(img_pattern, html, re.IGNORECASE)
            for match in matches:
                if is_valid_image(match):
                    all_images.append(match)
            
            # 提取 data-src
            for pattern in data_src_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if is_valid_image(match):
                        all_images.append(match)
        
        # 3. 去重，保持顺序
        if all_images:
            seen = set()
            unique_images = []
            for img in all_images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            
            # 返回第一张或第二张图片
            if len(unique_images) >= 2:
                # 对于某些网站，第一张可能是 logo，尝试第二张
                selected = unique_images[1]
                THUMBNAIL_CACHE[url] = selected
                return selected
            elif unique_images:
                THUMBNAIL_CACHE[url] = unique_images[0]
                return unique_images[0]
        
        return None
    except Exception:
        return None

def fetch_all_news():
    all_articles = []
    seen_hashes = set()
    for feed_info in RSS_FEEDS:
        articles = fetch_feed(feed_info)
        for article in articles:
            if article['hash'] not in seen_hashes:
                seen_hashes.add(article['hash'])
                if is_recent(article['pub_date'], 48):
                    all_articles.append(article)
    
    # 爬取每篇文章的第一张图片
    print(f"\n🖼️ 正在获取文章缩略图...")
    for i, article in enumerate(all_articles):
        if not article.get('thumbnail'):
            thumbnail = fetch_article_thumbnail(article['link'])
            if thumbnail:
                article['thumbnail'] = thumbnail
            if (i + 1) % 10 == 0:
                print(f"   已处理 {i + 1}/{len(all_articles)} 篇")
            time.sleep(0.3)  # 避免请求过快
    
    print(f"\n📊 共获取 {len(all_articles)} 篇新闻")
    return all_articles

def categorize_news(articles):
    categories = {'AI': [], '科技': [], '创投': []}
    for article in articles:
        cat = article.get('category', '科技')
        if cat in categories:
            categories[cat].append(article)
        else:
            categories['科技'].append(article)
    return categories

def build_prompt(articles):
    """构建提示词，包含链接"""
    categories = categorize_news(articles)
    prompt_parts = ["# 今日新闻:\n"]
    for cat_name, cat_articles in categories.items():
        if cat_articles:
            prompt_parts.append(f"\n## {cat_name} ({len(cat_articles)}条):\n")
            for i, article in enumerate(cat_articles[:15], 1):
                prompt_parts.append(f"{i}. 【{article['source']}】{article['title']}\n")
                prompt_parts.append(f"   链接: {article['link']}\n")
                if article['summary']:
                    prompt_parts.append(f"   摘要: {article['summary'][:150]}...\n")
                prompt_parts.append("\n")
    prompt = "".join(prompt_parts)
    prompt += """
---
请筛选今天最重要的新闻，每类5条，每条用简洁的中文总结（不超过40字），每条后面必须跟原文链接。

输出格式（Markdown）:
### 🤖 AI & 大模型
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3

### 💻 科技前沿
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3

### 💰 创投动态
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3

要求：每条新闻必须附原文链接，格式如"原文: xxx"
"""
    return prompt

def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY:
        raise ValueError("未配置 DEEPSEEK_API_KEY")
    print("🤖 正在调用 DeepSeek AI...")
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是科技财经新闻分析师，擅长简洁总结，每条新闻后必须附原文链接。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 4000
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        result = response.json()
        if "choices" in result and len(result["choices"]) > 0:
            summary = result["choices"][0]["message"]["content"]
            print(f"   ✅ 总结完成")
            return summary
        else:
            raise Exception(f"API返回异常: {result}")
    except Exception as e:
        print(f"   ❌ DeepSeek API 调用失败: {e}")
        raise

def parse_summary_with_links(summary_text, all_articles):
    """解析AI总结，提取每条新闻和链接
    关键：使用真实URL匹配 - 将AI总结的标题与实际获取的新闻进行匹配
    """
    from difflib import SequenceMatcher
    
    news_items = []
    current_category = ""
    
    # 构建真实链接映射 - 按标题关键词匹配
    def find_best_match(title, articles):
        """从实际新闻中找到最匹配的链接"""
        title_lower = title.lower()
        best_match = None
        best_ratio = 0
        
        for article in articles:
            article_title = article['title'].lower()
            # 计算相似度
            ratio = SequenceMatcher(None, title_lower, article_title).ratio()
            # 也检查关键词匹配
            title_words = set(title_lower.split())
            article_words = set(article_title.split())
            if title_words & article_words:
                word_ratio = len(title_words & article_words) / max(len(title_words), len(article_words))
                ratio = max(ratio, word_ratio)
            
            if ratio > best_ratio and ratio > 0.3:  # 阈值0.3
                best_ratio = ratio
                best_match = article
        
        return best_match
    
    lines = summary_text.split('\n')
    for line in lines:
        line = line.strip()
        # 检测分类标题
        if '🤖' in line or ('AI' in line and '大模型' in line):
            current_category = "AI"
            continue
        elif '💻' in line or '科技' in line:
            current_category = "科技"
            continue
        elif '💰' in line or '创投' in line or '金融' in line:
            current_category = "创投"
            continue
        
        # 提取新闻和链接
        if line.startswith('- ') or line.startswith('• '):
            content = line[2:].strip()
            # 查找原文链接（AI提供的可能是假的）
            ai_link = ""
            if '原文:' in content:
                parts = content.rsplit('原文:', 1)
                content = parts[0].strip()
                ai_link = parts[1].strip() if len(parts) > 1 else ""
            
            if content and current_category:
                # 尝试从真实新闻中找到匹配
                matched_article = find_best_match(content, all_articles)
                real_link = matched_article['link'] if matched_article else ai_link
                
                news_items.append({
                    'category': current_category,
                    'title': content,
                    'link': real_link,  # 优先使用真实链接
                    'source': matched_article['source'] if matched_article else ''
                })
    
    return news_items

def generate_html_report(date_str, news_items, all_articles):
    """生成 HTML 简报"""
    # 读取模板
    template_path = os.path.join(TEMPLATE_DIR, 'report.html')
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    else:
        # 使用默认模板
        template = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>每日新闻简报</title>
<style>body{font-family:sans-serif;background:#1a1a2e;color:#fff;padding:20px}
.news-card{background:rgba(255,255,255,0.1);margin:10px 0;padding:15px;border-radius:10px}
.category{background:linear-gradient(90deg,#00d2ff,#3a7bd5);padding:3px 10px;border-radius:10px;font-size:12px}
a{color:#00d2ff}</style></head><body>
<h1>📰 每日新闻简报 | {date}</h1>
{news_html}
</body></html>"""
    
    # 生成新闻 HTML
    category_names = {'AI': '🤖 AI & 大模型', '科技': '💻 科技前沿', '创投': '💰 创投动态'}
    news_html = ""
    
    # 按分类分组
    grouped = {'AI': [], '科技': [], '创投': []}
    for item in news_items:
        if item['category'] in grouped:
            grouped[item['category']].append(item)
    
    for cat, items in grouped.items():
        if items:
            news_html += f'<div class="news-section show-all" data-category="{cat}"><h2 style="color:white;margin:20px 0">{category_names.get(cat, cat)}</h2>'
            for item in items:
                news_html += f'''<div class="news-card">
                    <a href="{item['link']}" target="_blank">
                        <span class="category">{cat}</span>
                        <div class="title">{item['title']}</div>
                        <div class="source">{item['source'] or ''}</div>
                    </a>
                </div>'''
            news_html += '</div>'
    
    # 填充模板
    html = template.replace('{date}', date_str)
    html = html.replace('{count}', str(len(news_items)))
    html = html.replace('{news_html}', news_html)
    html = html.replace('{history_html}', '<p>历史功能开发中...</p>')
    
    return html

def save_report(date_str, summary, news_items, all_articles):
    """保存简报到文件"""
    ensure_dir(DATA_DIR)
    
    # 保存JSON数据
    report_data = {
        'date': date_str,
        'summary': summary,
        'news_items': news_items,
        'total_articles': len(all_articles),
        'generated_at': datetime.now(BEIJING_TZ).isoformat()
    }
    
    json_path = os.path.join(DATA_DIR, f'report_{date_str}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    
    # 生成HTML
    html = generate_html_report(date_str, news_items, all_articles)
    html_path = os.path.join(DATA_DIR, f'report_{date_str}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # 更新历史索引
    index_path = os.path.join(DATA_DIR, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    else:
        history = []
    
    # 检查是否已存在相同日期的记录，有则更新，无则添加
    existing_idx = None
    for i, h in enumerate(history):
        if h.get('date') == date_str:
            existing_idx = i
            break
    
    new_record = {
        'date': date_str,
        'count': len(news_items),
        'url': f'report_{date_str}.html'
    }
    
    if existing_idx is not None:
        history[existing_idx] = new_record
    else:
        history.insert(0, new_record)
    
    # 保留最近30天
    history = history[:30]
    
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    # 生成首页 index.html
    generate_index_html(history, news_items, all_articles)
    
    print(f"   💾 已保存简报到 {json_path}")
    return json_path, html_path

def generate_index_html(history, latest_news_items, all_articles):
    """生成首页 index.html，瀑布流布局，带缩略图和简介"""
    category_names = {'AI': '🤖 AI', '科技': '💻 科技', '创投': '💰 创投'}
    
    # 生成历史记录 HTML
    history_html = ""
    for item in history[:10]:
        history_html += f'''<div class="history-item">
            <a href="{item['url']}">{item['date']} ({item['count']}条)</a>
        </div>'''
    
    # 创建首页 HTML
    index_html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日新闻简报</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 16px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px 20px;
            color: white;
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header .date {{ color: #888; font-size: 14px; }}
        
        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
            justify-content: center;
        }}
        .tab {{
            padding: 8px 16px;
            background: rgba(255,255,255,0.1);
            border-radius: 20px;
            color: #888;
            cursor: pointer;
            transition: all 0.3s;
            border: none;
            font-size: 14px;
        }}
        .tab.active {{
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            color: white;
        }}
        
        .news-section {{ display: none; }}
        .news-section.active, .news-section.show-all {{ display: block; }}
        
        /* 瀑布流布局 */
        .news-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 16px;
        }}
        
        .news-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            overflow: hidden;
            transition: all 0.3s;
            border: 1px solid rgba(255,255,255,0.1);
            display: flex;
            flex-direction: column;
        }}
        .news-card:hover {{
            transform: translateY(-4px);
            border-color: rgba(0,210,255,0.3);
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        .news-card a {{
            text-decoration: none;
            color: inherit;
            display: block;
            flex: 1;
            display: flex;
            flex-direction: column;
        }}
        .news-card .thumbnail {{
            width: 100%;
            height: 180px;
            object-fit: cover;
            background: rgba(0,0,0,0.2);
        }}
        .news-card .content {{
            padding: 16px;
            flex: 1;
            display: flex;
            flex-direction: column;
        }}
        .news-card .category {{
            display: inline-block;
            padding: 4px 12px;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            border-radius: 12px;
            font-size: 12px;
            color: white;
            margin-bottom: 12px;
            align-self: flex-start;
        }}
        .news-card .title {{
            font-size: 16px;
            color: white;
            line-height: 1.5;
            margin-bottom: 12px;
            font-weight: 500;
        }}
        .news-card .summary {{
            font-size: 14px;
            color: #aaa;
            line-height: 1.6;
            margin-bottom: 12px;
            flex: 1;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .news-card .source {{
            font-size: 12px;
            color: #666;
            margin-top: auto;
        }}
        
        .history-section {{
            margin-top: 40px;
            padding-top: 30px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}
        .history-section h3 {{
            color: white;
            margin-bottom: 20px;
            font-size: 18px;
        }}
        .history-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 12px;
        }}
        .history-item {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            transition: all 0.3s;
        }}
        .history-item:hover {{
            background: rgba(255,255,255,0.1);
        }}
        .history-item a {{
            text-decoration: none;
            color: #888;
            font-size: 14px;
        }}
        
        @media (max-width: 768px) {{
            .news-grid {{
                grid-template-columns: 1fr;
            }}
            .header h1 {{
                font-size: 24px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📰 每日新闻简报</h1>
            <p class="date">最新更新：{history[0]['date'] if history else '暂无'} • 共 {len(all_articles)} 条</p>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('all')">全部</button>
            <button class="tab" onclick="showTab('AI')">🤖 AI</button>
            <button class="tab" onclick="showTab('科技')">💻 科技</button>
            <button class="tab" onclick="showTab('创投')">💰 创投</button>
        </div>
        
        <div id="news-container">
'''
    
    # 按分类分组最新新闻
    grouped = {'AI': [], '科技': [], '创投': []}
    for article in all_articles:
        cat = article.get('category', '科技')
        if cat in grouped:
            grouped[cat].append(article)
        else:
            grouped['科技'].append(article)
    
    for cat, items in grouped.items():
        if items:
            cat_thumbnail = CATEGORY_THUMBNAILS.get(cat, DEFAULT_THUMBNAIL)
            index_html += f'<div class="news-section show-all" data-category="{cat}"><div class="news-grid">'
            for item in items[:20]:  # 每类最多 20 条
                thumbnail = item.get('thumbnail') or cat_thumbnail
                summary = item.get('summary', '')
                if len(summary) > 100:
                    summary = summary[:100] + '...'
                index_html += f'''<div class="news-card">
                    <a href="{item['link']}" target="_blank">
                        <img class="thumbnail" src="{thumbnail}" alt="" onerror="this.src='{cat_thumbnail}'">
                        <div class="content">
                            <span class="category">{cat}</span>
                            <div class="title">{item['title']}</div>
                            <div class="summary">{summary}</div>
                            <div class="source">{item['source'] or ''}</div>
                        </div>
                    </a>
                </div>'''
            index_html += '</div></div>'
    
    index_html += f'''
        </div>
        
        <div class="history-section">
            <h3>📚 历史消息</h3>
            <div class="history-list">
                {history_html}
            </div>
        </div>
    </div>
    
    <script>
        function showTab(category) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            
            document.querySelectorAll('.news-section').forEach(s => {{
                if (category === 'all') {{
                    s.classList.add('show-all');
                }} else {{
                    s.classList.remove('show-all');
                    s.style.display = s.dataset.category === category ? 'block' : 'none';
                }}
            }});
        }}
        
        document.addEventListener('DOMContentLoaded', function() {{
            document.querySelectorAll('.news-section').forEach(s => {{
                s.classList.add('show-all');
            }});
        }});
    </script>
</body>
</html>'''
    
    index_path = os.path.join(DATA_DIR, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    print(f"   🏠 已更新首页 {index_path}")

def send_to_feishu(summary, date_str, news_items, all_articles):
    """发送到飞书 - 使用真实新闻标题"""
    if not FEISHU_WEBHOOK_URL:
        raise ValueError("未配置 FEISHU_WEBHOOK_URL")
    print("📤 正在推送到飞书...")
    
    # 按分类选取重要新闻（使用真实标题）
    categories = categorize_news(all_articles)
    
    content_lines = [f"📰 **每日新闻简报** | {date_str}\n"]
    
    category_icons = {'AI': '🤖', '科技': '💻', '创投': '💰'}
    category_names = {'AI': 'AI', '科技': '科技', '创投': '创投'}
    
    for cat_name, cat_articles in categories.items():
        if cat_articles:
            icon = category_icons.get(cat_name, '📌')
            name = category_names.get(cat_name, cat_name)
            content_lines.append(f"**{icon} {name}**")
            for article in cat_articles[:5]:  # 每类最多 5 条
                content_lines.append(f"• {article['title']}")
            content_lines.append("")
    
    content = "\n".join(content_lines[:30])
    
    # 构建飞书卡片
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "blue",
                "title": {
                    "content": f"📰 每日新闻简报 | {date_str}",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "content": "🔗 查看完整简报",
                                "tag": "plain_text"
                            },
                            "url": REPORT_URL,
                            "type": "primary"
                        }
                    ]
                },
                {"tag": "div", "text": {"content": f"共 {len(all_articles)}条新闻 • 点击查看详情", "tag": "lark_md"}}
            ]
        }
    }
    
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, headers={"Content-Type": "application/json"}, data=json.dumps(card), timeout=30)
        result = response.json()
        if result.get("code") == 0:
            print("   ✅ 推送成功!")
            return True
        else:
            print(f"   ❌ 推送失败: {result}")
            return False
    except Exception as e:
        print(f"   ❌ 推送异常: {e}")
        return False

def send_fallback(articles, date_str):
    """发送原始新闻列表"""
    print("📤 AI总结失败，发送原始新闻列表...")
    categories = categorize_news(articles)
    
    content_lines = [f"📰 **每日新闻简报** | {date_str}\n"]
    content_lines.append(f"共获取 **{len(articles)}** 篇新闻\n")
    
    for cat_name, cat_articles in categories.items():
        if cat_articles:
            content_lines.append(f"\n**{cat_name}**\n")
            for i, article in enumerate(cat_articles[:5], 1):
                content_lines.append(f"{i}. {article['title']}")
    
    content = "\n".join(content_lines[:25])
    
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"template": "red", "title": {"content": f"📰 每日新闻 | {date_str}", "tag": "plain_text"}},
            "elements": [
                {"tag": "markdown", "content": content},
                {"tag": "action", "actions": [{"tag": "button", "text": {"content": "🔗 查看完整简报", "tag": "plain_text"}, "url": REPORT_URL, "type": "primary"}]},
                {"tag": "div", "text": {"content": f"🤖 DeepSeek", "tag": "lark_md"}}
            ]
        }
    }
    
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, headers={"Content-Type": "application/json"}, data=json.dumps(card), timeout=30)
        result = response.json()
        if result.get("code") == 0:
            print("   ✅ 推送成功!")
            return True
        return False
    except Exception as e:
        print(f"   ❌ 推送异常: {e}")
        return False

def main():
    print("=" * 50)
    print("🚀 Feishu News Bot 启动")
    print(f"⏰ 运行时间: {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📡 新闻源数量: {len(RSS_FEEDS)}")
    print(f"🔗 简报地址: {REPORT_URL}")
    print("=" * 50)
    
    if not DEEPSEEK_API_KEY:
        print("❌ 错误: 请配置 DEEPSEEK_API_KEY")
        return
    if not FEISHU_WEBHOOK_URL:
        print("❌ 错误: 请配置 FEISHU_WEBHOOK_URL")
        return
    
    try:
        articles = fetch_all_news()
        if not articles:
            print("⚠️ 未能获取到新闻")
            return
        
        date_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
        
        try:
            # 获取 AI 总结
            prompt = build_prompt(articles)
            summary = call_deepseek(prompt)
            
            # 解析出新闻和链接（传入 articles 用于匹配真实 URL）
            news_items = parse_summary_with_links(summary, articles)
            
            # 保存简报
            save_report(date_str, summary, news_items, articles)
            
            # 发送飞书（使用真实标题）
            send_to_feishu(summary, date_str, news_items, articles)
            
        except Exception as e:
            print(f"⚠️ AI总结失败: {e}")
            send_fallback(articles, date_str)
        
        print("\n🎉 任务完成!")
    except Exception as e:
        print(f"\n💥 发生错误: {e}")
        raise

if __name__ == "__main__":
    main()
