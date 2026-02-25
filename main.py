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
# 飞书 Webhook（直接从环境变量获取）
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL") or "https://open.feishu.cn/open-apis/bot/v2/hook/2ab18ec8-6c48-4c73-b24d-6d73b78b1b81"

# 丰富的新闻源 - 全面覆盖
RSS_FEEDS = [
    # 科技/IT (6个源)
    {"name": "36Kr科技", "url": "https://36kr.com/feed", "category": "科技"},
    {"name": "虎嗅", "url": "https://www.huxiu.com/rss", "category": "科技"},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/rss_all.xml", "category": "科技"},
    {"name": "新浪科技", "url": "https://rss.sina.com.cn/tech/roll.xml", "category": "科技"},
    {"name": "网易科技", "url": "https://tech.163.com/special/cm_yaowen20200513/", "category": "科技"},
    {"name": "凤凰科技", "url": "https://tech.ifeng.com/rss.xml", "category": "科技"},
    # 创投/金融 (5个源)
    {"name": "36Kr创投", "url": "https://36kr.com/information/VC/feed", "category": "创投"},
    {"name": "36Kr金融", "url": "https://36kr.com/information/financial/feed", "category": "创投"},
    {"name": "创业邦", "url": "https://www.cyzone.cn/rss/", "category": "创投"},
    {"name": "投资界", "url": "https://www.pedaily.cn/rss/", "category": "创投"},
    {"name": "铅笔道", "url": "https://www.pencilnews.cn/rss/", "category": "创投"},
    # AI (4个源)
    {"name": "36KrAI", "url": "https://36kr.com/information/AI/feed", "category": "AI"},
    {"name": "新智元", "url": "https://www.36kr.com/information/AI", "category": "AI"},
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "category": "AI"},
    {"name": "AI科技大本营", "url": "https://www.36kr.com/information/AI", "category": "AI"},
]

BEIJING_TZ = pytz.timezone('Asia/Shanghai')


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
        parsed = None
        for fmt in ['%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
            try:
                if '%z' in fmt:
                    parsed = datetime.strptime(pub_date, fmt)
                else:
                    parsed = datetime.strptime(pub_date, fmt)
                    parsed = pytz.utc.localize(parsed)
                break
            except:
                continue
        if parsed is None:
            return True
        if parsed.tzinfo is None:
            parsed = pytz.utc.localize(parsed)
        beijing_time = parsed.astimezone(BEIJING_TZ)
        now = datetime.now(BEIJING_TZ)
        return now - timedelta(hours=hours) < beijing_time
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
                'summary': summary[:200] if summary else '',
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
        cat = article.get('category', 'IT')
        if cat in categories:
            categories[cat].append(article)
        else:
            categories['科技'].append(article)
    return categories


def build_prompt(articles):
    categories = categorize_news(articles)
    prompt_parts = ["# 今日新闻:\n"]
    for cat_name, cat_articles in categories.items():
        if cat_articles:
            prompt_parts.append(f"\n## {cat_name} ({len(cat_articles)}条):\n")
            for i, article in enumerate(cat_articles[:10], 1):
                prompt_parts.append(f"{i}. 【{article['source']}】{article['title']}\n")
                if article['summary']:
                    prompt_parts.append(f"   {article['summary']}\n")
    prompt = "".join(prompt_parts)
    prompt += """
---
请筛选今天最重要的10条科技/AI/创投新闻，每条用一句话总结，每条后面必须跟原文链接。

输出格式:
### 🤖 AI & 大模型
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3
- 总结4
  原文: 链接4
- 总结5
  原文: 链接5

### 💻 科技前沿
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3
- 总结4
  原文: 链接4
- 总结5
  原文: 链接5

### 💰 创投动态
- 总结1
  原文: 链接1
- 总结2
  原文: 链接2
- 总结3
  原文: 链接3
- 总结4
  原文: 链接4
- 总结5
  原文: 链接5

要求：用中文，每条不超过40字，必须附原文链接
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
            {"role": "system", "content": "你是科技财经新闻分析师，擅长简洁总结。"},
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


def send_to_feishu(content, date_str):
    if not FEISHU_WEBHOOK_URL:
        raise ValueError("未配置 FEISHU_WEBHOOK_URL")
    print("📤 正在推送到飞书...")
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"template": "blue", "title": {"content": f"📰 每日新闻简报 | {date_str}", "tag": "plain_text"}},
            "elements": [
                {"tag": "markdown", "content": content},
                {"tag": "div", "text": {"content": f"🤖 Powered by DeepSeek • {date_str}", "tag": "lark_md"}}
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
    print("📤 发送原始新闻列表...")
    categories = categorize_news(articles)
    content_lines = [f"# 每日新闻简报 | {date_str}\n"]
    for cat_name, cat_articles in categories.items():
        if cat_articles:
            content_lines.append(f"\n## {cat_name}")
            for i, article in enumerate(cat_articles[:5], 1):
                content_lines.append(f"{i}. {article['title']}")
    content = "\n".join(content_lines[:20])
    return send_to_feishu(content, date_str)


def main():
    print("=" * 50)
    print("🚀 Feishu News Bot 启动")
    print(f"⏰ 运行时间: {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
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
        try:
            prompt = build_prompt(articles)
            summary = call_deepseek(prompt)
            date_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
            send_to_feishu(summary, date_str)
        except Exception as e:
            print(f"⚠️ AI总结失败: {e}")
            date_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
            send_fallback(articles, date_str)
        print("\n🎉 任务完成!")
    except Exception as e:
        print(f"\n💥 发生错误: {e}")
        raise


if __name__ == "__main__":
    main()
