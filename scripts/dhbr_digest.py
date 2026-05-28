#!/usr/bin/env python3
"""DHBR daily digest: fetch popular articles, skip seen ones, post to Slack."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

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
    seen_in_fetch: set[str] = set()

    # 1. 専用ランキングページを試す
    for path in ["/ranking", "/rankings", "/popular", "/hotarticles"]:
        soup = _get_soup(path)
        if soup is None:
            continue
        candidates = _extract_links(soup, seen_in_fetch)
        if candidates:
            print(f"  人気記事を {path} から取得しました")
            return candidates[:20]

    # 2. トップページの人気・ランキングセクションを探す
    soup = _get_soup("/")
    if soup is None:
        print("トップページの取得に失敗しました", file=sys.stderr)
        return []

    ranking_keywords = ["人気", "ランキング", "ranking", "popular", "よく読まれ", "アクセス"]
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = heading.get_text(strip=True).lower()
        if not any(kw in text for kw in ranking_keywords):
            continue
        section = heading.find_parent(["section", "div", "article", "aside", "nav"])
        if section is None:
            continue
        candidates = _extract_links(section, seen_in_fetch)
        if candidates:
            print(f"  人気記事セクション「{heading.get_text(strip=True)}」を検出しました")
            return candidates[:20]

    # 3. フォールバック: トップページ全体
    print("  ランキングセクションが見つからなかったためトップページ全体を使用します")
    return _extract_links(soup, seen_in_fetch)[:20]


def fetch_description(url: str) -> str:
    """記事ページの meta description を取得する。なければ本文冒頭を返す。"""
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # og:description → description → 本文冒頭の順で試す
        for attr in [
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ]:
            tag = soup.find("meta", attrs=attr)
            if tag and tag.get("content", "").strip():
                return tag["content"].strip()

        # メタ説明がなければ本文最初の段落
        for sel in ["article", ".article-body", ".entry-content", "main"]:
            el = soup.select_one(sel)
            if el:
                para = el.find("p")
                if para:
                    return para.get_text(strip=True)[:200]
    except Exception:
        pass
    return ""


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
        body_text = f"*{i}. <{art['url']}|{art['title']}>*"
        if art.get("description"):
            body_text += f"\n{art['description']}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body_text}})

    slack.chat_postMessage(
        channel=SLACK_CHANNEL,
        blocks=blocks,
        text=f"DHBR 人気記事まとめ（{today}）",
        unfurl_links=False,
    )


def main() -> None:
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        print("SLACK_BOT_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    seen_urls = load_seen_urls()

    print("人気記事を取得中...")
    popular = fetch_popular_articles()
    if not popular:
        print("記事の取得に失敗しました", file=sys.stderr)
        sys.exit(1)

    print(f"取得: {len(popular)} 件")

    unseen = [a for a in popular if a["url"] not in seen_urls]
    print(f"未投稿: {len(unseen)} 件（投稿済み除外後）")

    if len(unseen) < SELECT_COUNT:
        print(
            f"未投稿の人気記事が {SELECT_COUNT} 件未満のためスキップします "
            f"（未投稿: {len(unseen)} 件）"
        )
        seen_urls.update(a["url"] for a in popular)
        save_seen_urls(seen_urls)
        return

    selected = unseen[:SELECT_COUNT]
    slack_client = WebClient(token=slack_token)

    results = []
    for art in selected:
        print(f"  説明文を取得中: {art['title'][:40]}...")
        desc = fetch_description(art["url"])
        results.append({**art, "description": desc})

    post_to_slack(slack_client, results)
    print(f"Slack に投稿しました（{len(results)} 件）")

    seen_urls.update(a["url"] for a in popular)
    save_seen_urls(seen_urls)
    print("既読リストを更新しました")


if __name__ == "__main__":
    main()
