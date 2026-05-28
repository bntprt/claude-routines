#!/usr/bin/env python3
"""DHBR daily digest: fetch popular articles, skip seen ones, summarize, post to Slack."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup
from slack_sdk import WebClient

DATA_FILE = Path(__file__).parent.parent / "data" / "seen_articles.json"
SLACK_CHANNEL = "C0985BY63KM"  # #hbrまとめ
DHBR_BASE = "https://dhbr.diamond.jp"
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


def _get_soup(path: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(
            DHBR_BASE + path,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _extract_links(soup: BeautifulSoup, seen: set) -> list[dict]:
    """Extract article links from a BeautifulSoup object, deduplicating by URL."""
    articles = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("/"):
            href = DHBR_BASE + href
        if not href.startswith(DHBR_BASE):
            continue
        title = tag.get_text(strip=True)
        if len(title) < 10 or href in seen:
            continue
        seen.add(href)
        articles.append({"title": title, "url": href})
    return articles


def fetch_popular_articles() -> list[dict]:
    """
    Fetch popular articles from dhbr.diamond.jp.

    Strategy (in priority order):
    1. Dedicated ranking/popular page (/ranking, /popular, etc.)
    2. Ranking / popular sections on the top page (identified by heading keywords)
    3. Top-page general article links as last resort
    """
    seen_in_fetch: set[str] = set()

    # 1. Try dedicated ranking pages
    for path in ["/ranking", "/rankings", "/popular", "/hotarticles"]:
        soup = _get_soup(path)
        if soup is None:
            continue
        candidates = _extract_links(soup, seen_in_fetch)
        if candidates:
            print(f"  人気記事を {path} から取得しました")
            return candidates[:20]

    # 2. Scrape top page: look for sections whose heading contains ranking keywords
    soup = _get_soup("/")
    if soup is None:
        print("トップページの取得に失敗しました", file=sys.stderr)
        return []

    ranking_keywords = ["人気", "ランキング", "ranking", "popular", "よく読まれ", "アクセス"]
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = heading.get_text(strip=True).lower()
        if not any(kw in text for kw in ranking_keywords):
            continue
        # Gather links from the section following this heading
        section = heading.find_parent(["section", "div", "article", "aside", "nav"])
        if section is None:
            continue
        candidates = _extract_links(section, seen_in_fetch)
        if candidates:
            print(f"  人気記事セクション「{heading.get_text(strip=True)}」を検出しました")
            return candidates[:20]

    # 3. Fall back: all article links on the top page
    print("  ランキングセクションが見つからなかったためトップページ全体を使用します")
    return _extract_links(soup, seen_in_fetch)[:20]


def fetch_article_body(url: str) -> str:
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
                "text": f"🏆 DHBR 人気記事まとめ（{today}）",
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
        text=f"DHBR 人気記事まとめ（{today}）",
        unfurl_links=False,
    )


def main() -> None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not anthropic_key or not slack_token:
        print("ANTHROPIC_API_KEY と SLACK_BOT_TOKEN の両方が必要です", file=sys.stderr)
        sys.exit(1)

    seen_urls = load_seen_urls()

    print("人気記事を取得中...")
    popular = fetch_popular_articles()
    if not popular:
        print("記事の取得に失敗しました", file=sys.stderr)
        sys.exit(1)

    print(f"取得: {len(popular)} 件")

    # 重複（過去に投稿済み）を除外
    unseen = [a for a in popular if a["url"] not in seen_urls]
    print(f"未投稿: {len(unseen)} 件（投稿済み除外後）")

    if len(unseen) < SELECT_COUNT:
        print(
            f"未投稿の人気記事が {SELECT_COUNT} 件未満のため投稿をスキップします "
            f"（未投稿: {len(unseen)} 件）"
        )
        seen_urls.update(a["url"] for a in popular)
        save_seen_urls(seen_urls)
        return

    selected = unseen[:SELECT_COUNT]
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

    # 今回取得した全 URL を既読に追加
    seen_urls.update(a["url"] for a in popular)
    save_seen_urls(seen_urls)
    print("既読リストを更新しました")


if __name__ == "__main__":
    main()
