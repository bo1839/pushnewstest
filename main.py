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

load_dotenv()

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
        print(f"📥 正在获取: {feed_info['name']}...")
        feed = feedparser.parse(feed_info['url'])
        articles = []
        for entry in feed.entries[:30]:
            title = clean_html(entry.get('title', ''))
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))
            pub_date = entry.get('published', '')
            if not title or not link:
                continue
            article = {
                'title': title,
                'link': link,
                'summary': summary[:300] if summary else '',
                'pub_date': pub_date,
                'category': feed_info['category'],
                'source': feed_info['name'],
                'hash': get_news_hash(title, link)
            }
            articles.append(article)
        print(f"   ✅ 获取到 {len(articles)} 条")
        return articles
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
        return []

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
    """生成HTML简报"""
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
    
    # 生成新闻HTML
    category_names = {'AI': '🤖 AI & 大模型', '科技': '💻 科技前沿', '创投': '💰 创投动态'}
    news_html = ""
    
    # 按分类分组
    grouped = {'AI': [], '科技': [], '创投': []}
    for item in news_items:
        if item['category'] in grouped:
            grouped[item['category']].append(item)
    
    for cat, items in grouped.items():
        if items:
            news_html += f'<h2>{category_names.get(cat, cat)}</h2>'
            for item in items:
                news_html += f'''<div class="news-card">
                    <span class="category">{cat}</span>
                    <h3><a href="{item['link']}" target="_blank">{item['title']}</a></h3>
                </div>'''
    
    # 填充模板
    html = template.replace('{date}', date_str)
    html = html.replace('{count}', str(len(news_items)))
    html = html.replace('{news_html}', news_html)
    html = html.replace('{news_html}', news_items and news_html or '<p>暂无新闻</p>')
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
    
    # 添加新记录
    history.insert(0, {
        'date': date_str,
        'count': len(news_items),
        'url': f'report_{date_str}.html'
    })
    
    # 保留最近30天
    history = history[:30]
    
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    print(f"   💾 已保存简报到 {json_path}")
    return json_path, html_path

def send_to_feishu(summary, date_str, news_items):
    """发送到飞书 - 美化版本，去掉原文链接"""
    if not FEISHU_WEBHOOK_URL:
        raise ValueError("未配置 FEISHU_WEBHOOK_URL")
    print("📤 正在推送到飞书...")
    
    # 转换总结为飞书卡片格式（不带链接）
    content_lines = []
    current_section = ""
    
    for line in summary.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # 检测分类
        if 'AI' in line and '大模型' in line:
            current_section = 'AI'
            content_lines.append("**🤖 AI & 大模型**\n")
            continue
        elif '科技' in line:
            current_section = '科技'
            content_lines.append("**💻 科技前沿**\n")
            continue
        elif '创投' in line or '金融' in line:
            current_section = '创投'
            content_lines.append("**💰 创投动态**\n")
            continue
        
        # 提取新闻内容，去掉"原文:"部分
        if line.startswith('- ') or line.startswith('• '):
            content = line[2:].strip()
            # 去掉原文链接部分
            if '原文:' in content:
                content = content.split('原文:')[0].strip()
            if content:
                content_lines.append(f"• {content}")
    
    content = "\n".join(content_lines)
    
    # 构建飞书卡片 - 带按钮
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
                                "content": "🔗 查看完整简报（含原文链接）",
                                "tag": "plain_text"
                            },
                            "url": REPORT_URL,
                            "type": "primary"
                        }
                    ]
                },
                {"tag": "div", "text": {"content": f"🤖 Powered by DeepSeek • {len(RSS_FEEDS)}个新闻源", "tag": "lark_md"}}
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
            # 获取AI总结
            prompt = build_prompt(articles)
            summary = call_deepseek(prompt)
            
            # 解析出新闻和链接（传入all_articles用于匹配真实URL）
            news_items = parse_summary_with_links(summary, all_articles)
            
            # 保存简报
            save_report(date_str, summary, news_items, articles)
            
            # 发送飞书（不带链接）
            send_to_feishu(summary, date_str, news_items)
            
        except Exception as e:
            print(f"⚠️ AI总结失败: {e}")
            send_fallback(articles, date_str)
        
        print("\n🎉 任务完成!")
    except Exception as e:
        print(f"\n💥 发生错误: {e}")
        raise

if __name__ == "__main__":
    main()
