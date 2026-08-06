#!/usr/bin/env python3
"""DHBR daily digest: fetch popular articles, skip seen ones, post to Slack."""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))

import requests
from bs4 import BeautifulSoup
from slack_sdk import WebClient

DATA_FILE = Path(__file__).parent.parent / "data" / "seen_articles.json"
SLACK_CHANNEL = "C0985BY63KM"  # #hbrまとめ
DHBR_BASE = "https://dhbr.diamond.jp"
SELECT_COUNT = 3
EXPIRE_DAYS = 7  # この日数を過ぎたら再投稿OK


def today_jst() -> str:
    return datetime.now(JST).date().isoformat()


def load_state() -> tuple[str, dict[str, str]]:
    """(最終投稿日, 有効期限内の既読データ) を返す。既読は {url: "YYYY-MM-DD"}。"""
    if not DATA_FILE.exists():
        return "", {}
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    # 旧フォーマット（urls リスト）の場合は空扱いにしてリセット
    if not isinstance(raw.get("articles"), dict):
        return "", {}

    cutoff = date.fromisoformat(today_jst()) - timedelta(days=EXPIRE_DAYS)
    articles = {
        url: seen_on
        for url, seen_on in raw["articles"].items()
        if date.fromisoformat(seen_on) >= cutoff
    }
    return raw.get("last_posted", ""), articles


def save_state(last_posted: str, articles: dict[str, str]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(
            {"last_posted": last_posted, "articles": articles},
            ensure_ascii=False,
            indent=2,
        ),
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
    """人気記事を複数ソースから集めて返す。ランキング7件程度しかないため必ずトップ全体も取得する。"""
    seen_in_fetch: set[str] = set()
    results: list[dict] = []

    # 1. 専用ランキングページ
    for path in ["/ranking", "/rankings", "/popular", "/hotarticles"]:
        soup = _get_soup(path)
        if soup is None:
            continue
        candidates = _extract_links(soup, seen_in_fetch)
        if candidates:
            print(f"  ランキングページ {path} から {len(candidates)} 件取得")
            results.extend(candidates)
            break

    # 2. トップページ: ランキングセクション + ページ全体の両方を取得
    soup = _get_soup("/")
    if soup is not None:
        # 2a. ランキングセクション（存在すれば先頭に追加）
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
                print(f"  ランキングセクション「{heading.get_text(strip=True)}」から {len(candidates)} 件取得")
                results.extend(candidates)
                break

        # 2b. トップページ全体（ランキングが少ない場合の補完として常に実行）
        all_links = _extract_links(soup, seen_in_fetch)
        if all_links:
            print(f"  トップページ全体から追加 {len(all_links)} 件取得")
            results.extend(all_links)
    else:
        print("トップページの取得に失敗しました", file=sys.stderr)

    # 3. 補完: 記事一覧ページ
    for path in ["/articles", "/articles/new", "/articles/latest", "/new", "/latest"]:
        if len(results) >= 40:
            break
        soup = _get_soup(path)
        if soup is None:
            continue
        candidates = _extract_links(soup, seen_in_fetch)
        if candidates:
            print(f"  補完ページ {path} から {len(candidates)} 件追加取得")
            results.extend(candidates)

    print(f"  合計取得: {len(results)} 件")
    return results[:40]


def fetch_description(url: str) -> str:
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for attr in [
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ]:
            tag = soup.find("meta", attrs=attr)
            if tag and tag.get("content", "").strip():
                return tag["content"].strip()

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
    today = datetime.now(JST).strftime("%Y年%m月%d日")
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

    last_posted, seen_data = load_state()
    today = today_jst()

    # 同じ日に複数回起動されても投稿は1回だけ（リトライ起動を安全にするためのガード）
    if last_posted == today:
        print(f"本日（{today}）は投稿済みのため終了します")
        return

    seen_urls = set(seen_data.keys())
    print(f"既読: {len(seen_urls)} 件（{EXPIRE_DAYS}日以内）")

    print("人気記事を取得中...")
    popular = fetch_popular_articles()
    if not popular:
        print("記事の取得に失敗しました", file=sys.stderr)
        sys.exit(1)

    print(f"取得: {len(popular)} 件")

    unseen = [a for a in popular if a["url"] not in seen_urls]
    print(f"未投稿: {len(unseen)} 件（既読除外後）")

    if len(unseen) < SELECT_COUNT:
        print(
            f"未投稿の人気記事が {SELECT_COUNT} 件未満のためスキップします "
            f"（未投稿: {len(unseen)} 件）"
        )
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

    # 投稿した3件を本日付で既読に追加（7日後に自動失効）
    for art in selected:
        seen_data[art["url"]] = today
    save_state(today, seen_data)
    print(f"既読リストを更新しました（計 {len(seen_data)} 件）")


if __name__ == "__main__":
    main()
