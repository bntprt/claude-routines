# claude-routines

Claude Code で動かす自動化ルーティン集。

## 今日の天文学（APOD）

NASA の [APOD（Astronomy Picture of the Day）](https://apod.nasa.gov/apod/astropix.html) が更新され次第、
**高校生が理解できるレベル**の日本語にまとめて Slack の `#天文学` チャンネルへ投稿します。
GitHub Actions 上で動くため、**PC やデスクトップアプリが起動していなくても実行されます**。

### 動作概要

1. `https://api.nasa.gov/planetary/apod` から最新の APOD を取得（`thumbs=true` で動画のサムネイルも取得）
2. `data/apod_seen.json` と照合し、同じ日付の APOD を二重投稿しない
3. 解説文を Claude API（Haiku）で高校生向けの日本語に要約
   （タイトル訳 / 約 350 字の要約 / 「ここが面白い」1 行 / ことばのメモ 0〜4 個）
   `ANTHROPIC_API_KEY` 未設定時は英語原文をそのまま投稿します
4. 画像（動画ならサムネイル＋リンク）付きで Slack `#天文学` チャンネルへ投稿
5. 投稿した APOD の日付を `data/apod_seen.json` に保存して main へコミット

### スケジュール

APOD は**米国東部時間の 0 時ちょうど**に更新されます。日本時間では夏時間なら **13:00**、
冬時間なら **14:00** です。

`.github/workflows/apod-daily.yml` は cron `0 4-12 * * *`（UTC）＝ **13:00〜21:00 JST を 1 時間ごと**に
チェックし、新しい APOD を見つけた最初の回だけ投稿します。同じ APOD なら手順 2 のガードで
即終了するため、**投稿は 1 日 1 回**です。固定時刻ではなく毎時チェックにしているのは、
夏時間の切り替わりや公開の遅れに自動で追従させるためです。

スクリプトは日付を指定せず「その時点での最新 1 件」を取得します。そのため公開が極端に遅れて
翌日の窓まで持ち越した場合は、常に新しいほうの 1 件が投稿されます。

> **注意**: `schedule` トリガーはデフォルトブランチ（main）のワークフローのみ有効です。
> このワークフローを main にマージすると稼働を開始します。

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| Secret 名 | 説明 |
|---|---|
| `NASA_API_KEY` | [api.nasa.gov](https://api.nasa.gov/) で発行した API キー（未設定なら `DEMO_KEY` で動きますがレート制限が厳しめです） |
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー。**未登録だと日本語要約が生成されず、英語原文がそのまま投稿されます**（DHBR / 薬剤ニュースと共通） |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`、DHBR / 薬剤ニュースと共通） |

**このリポジトリは public です。API キーをコード中に直接書かないでください。**

Bot（`claude-hbr`）は `#天文学` チャンネルに参加済みです。

### 手動実行

GitHub の **Actions タブ → APOD Daily → Run workflow** から手動実行できます。

その日の APOD をすでに投稿済みだと重複ガードで何もせず終了します。動作確認などで
あえて再投稿したいときは、Run workflow のダイアログで
**「投稿済みの APOD でも再投稿する」にチェック**を入れてください。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export NASA_API_KEY=...
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/apod_daily.py

# 投稿済みでも再投稿する
FORCE_POST=true python scripts/apod_daily.py
```

## Pharmacy News Daily（日刊薬業・PHARMACY NEWSBREAK）

毎朝 6:00 JST に [日刊薬業（nk.jiho.jp）](https://nk.jiho.jp/) と
[PHARMACY NEWSBREAK（pnb.jiho.jp）](https://pnb.jiho.jp/) の新着記事を**各 3 件**取得し、
約 200 字に要約して Slack の `#薬剤ニュース` チャンネルへ投稿します。
GitHub Actions 上で動くため、**PC やデスクトップアプリが起動していなくても実行されます**。

### 動作概要

1. nk.jiho.jp / pnb.jiho.jp のトップページ・新着一覧から記事リンクを収集
2. `data/pharmacy_seen_articles.json` と照合して未投稿の記事に絞る（重複排除、14 日で失効）
3. 各サイトから 3 件ずつ選定。**両サイトが同じ話題を報じている場合は片方だけ採用**し、
   もう片方は次の記事に差し替える（タイトルの文字一致率で判定）
4. 各記事を Claude API（Haiku）で約 200 字に要約
   （`ANTHROPIC_API_KEY` 未設定時は記事リード文の抜粋で代替）
5. サイトごとにまとめて Slack `#薬剤ニュース` チャンネルへ投稿
6. 投稿済み URL（同話題スキップ分を含む）を `data/pharmacy_seen_articles.json` に保存して main へコミット

### スケジュール

`.github/workflows/pharmacy-news.yml` の `schedule`（cron: `0 21 * * *` UTC = 6:00 JST）で自動実行されます。
GitHub Actions の cron は数分〜十数分遅れることがあります。時刻の正確さが必要な場合は、
DHBR と同様に cron-job.org から `workflow_dispatch` を起動する方式も併用できます。

> **注意**: `schedule` トリガーはデフォルトブランチ（main）のワークフローのみ有効です。
> このワークフローを main にマージすると稼働を開始します。

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください
（DHBR Daily Digest と共通）。

| Secret 名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

Bot を `#薬剤ニュース` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → Pharmacy News Daily → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/pharmacy_news.py
```

## DHBR Daily Digest

毎朝 6:00 JST に [Diamond Harvard Business Review](https://dhbr.diamond.jp/) の新着記事を
取得・要約して Slack の `#hbrまとめ` チャンネルへ投稿します。

### 動作概要

1. dhbr.diamond.jp から最新 10 件の記事を取得
2. `data/seen_articles.json` と照合して未投稿の記事に絞る
3. 上位 3 件を Claude API（Haiku）で 200 字に要約
4. Slack `#hbrまとめ` チャンネルへ投稿
5. 投稿済み URL を `data/seen_articles.json` に保存してコミット

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| Secret 名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

#### Slack Bot に必要なスコープ

- `chat:write` — メッセージ投稿
- `channels:read` / `groups:read` — チャンネル情報読み取り（任意）

Bot を `#hbrまとめ` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → DHBR Daily Digest → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/dhbr_digest.py
```
