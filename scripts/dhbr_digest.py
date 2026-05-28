#!/usr/bin/env python3
"""DHBR daily digest: fetch latest articles, pick 3 new ones, summarize, post to Slack."""

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup
from slack_sdk import WebClient

DATA_FILE = Path(__file__).parent.parent / "data" / "seen_articles.json"
SLACK_CHANNEL = "C0985BY63KM"  # #hbrまとめ
DHBR_BASE = "https://dhbr.diamond.jp"
FETCH_COUNT = 10
SELECT_COUNT = 3


def load_seen_urls() -> set:
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return set(data.get("urls", []))
    return set()


def save_seen_urls(urls: set) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps({"urls": sorted(urls)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_articles_from_rss() -> list[dict]:
    """Try to get articles via RSS feed."""
    for feed_path in ["/rss", "/feed", "/rss.xml", "/atom.xml"]:
        try:
            resp = requests.get(
                DHBR_BASE + feed_path,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)
            articles = []
            for item in items:
                title_el = item.find("title") or item.find("atom:title", ns)
                link_el = item.find("link") or item.find("atom:link", ns)
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                url = (
                    link_el.text.strip()
                    if link_el is not None and link_el.text
                    else link_el.get("href", "") if link_el is not None else ""
                )
                if title and url:
                    articles.append({"title": title, "url": url})
            if articles:
                return articles[:FETCH_COUNT]
        except Exception:
            continue
    return []


def fetch_articles_from_html() -> list[dict]:
    """Scrape top page for article links."""
    resp = requests.get(
        DHBR_BASE,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible)"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls: set[str] = set()

    # Try common article link patterns
    selectors = [
        "a[href*='/articles/']",
        "a[href*='/books/']",
        ".article-list a",
        ".news-list a",
        "h2 a",
        "h3 a",
    ]
    for sel in selectors:
        for tag in soup.select(sel):
            href = tag.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = DHBR_BASE + href
            if not href.startswith(DHBR_BASE):
                continue
            title = tag.get_text(strip=True)
            if len(title) < 10 or href in seen_urls:
                continue
            seen_urls.add(href)
            articles.append({"title": title, "url": href})
        if len(articles) >= FETCH_COUNT:
            break

    return articles[:FETCH_COUNT]


def fetch_articles() -> list[dict]:
    articles = fetch_articles_from_rss()
    if not articles:
        articles = fetch_articles_from_html()
    return articles


def fetch_article_body(url: str) -> str:
    """Fetch main body text of an article page."""
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for sel in ["article", ".article-body", ".entry-content", "main", ".content"]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator="\n", strip=True)[:4000]
        return soup.get_text(separator="\n", strip=True)[:4000]
    except Exception:
        return ""


def summarize(client: anthropic.Anthropic, title: str, body: str) -> str:
    """Return ~200-character Japanese summary using Claude."""
    content = f"タイトル: {title}\n\n本文:\n{body}" if body else f"タイトル: {title}"
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[
            {
                "role": "user",
                "content": (
                    "以下の記事を日本語で200字程度に要約してください。"
                    "要約文のみを出力し、前置き・後書き・見出しは不要です。\n\n"
                    + content
                ),
            }
        ],
    )
    return msg.content[0].text.strip()


def post_to_slack(slack: WebClient, items: list[dict]) -> None:
    today = datetime.now().strftime("%Y年%m月%d日")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📚 DHBR 新着記事まとめ（{today}）",
                "emoji": True,
            },
        }
    ]
    for i, art in enumerate(items, 1):
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}. <{art['url']}|{art['title']}>*\n{art['summary']}",
                },
            }
        )

    slack.chat_postMessage(
        channel=SLACK_CHANNEL,
        blocks=blocks,
        text=f"DHBR 新着記事まとめ（{today}）",
        unfurl_links=False,
    )


def main() -> None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not anthropic_key or not slack_token:
        print("ANTHROPIC_API_KEY と SLACK_BOT_TOKEN の両方が必要です", file=sys.stderr)
        sys.exit(1)

    seen_urls = load_seen_urls()

    print("記事を取得中...")
    articles = fetch_articles()
    if not articles:
        print("記事の取得に失敗しました", file=sys.stderr)
        sys.exit(1)

    print(f"取得: {len(articles)} 件")

    new_articles = [a for a in articles if a["url"] not in seen_urls]
    print(f"新規: {len(new_articles)} 件（既読除外後）")

    if len(new_articles) < SELECT_COUNT:
        print(
            f"新規記事が {SELECT_COUNT} 件未満のため投稿をスキップします "
            f"（新規: {len(new_articles)} 件）"
        )
        # Still mark all fetched as seen
        seen_urls.update(a["url"] for a in articles)
        save_seen_urls(seen_urls)
        return

    selected = new_articles[:SELECT_COUNT]
    claude_client = anthropic.Anthropic(api_key=anthropic_key)
    slack_client = WebClient(token=slack_token)

    results = []
    for art in selected:
        print(f"  要約中: {art['title'][:40]}...")
        body = fetch_article_body(art["url"])
        summary = summarize(claude_client, art["title"], body)
        results.append({**art, "summary": summary})

    post_to_slack(slack_client, results)
    print(f"Slack に投稿しました（{len(results)} 件）")

    seen_urls.update(a["url"] for a in articles)
    save_seen_urls(seen_urls)
    print("既読リストを更新しました")


if __name__ == "__main__":
    main()
