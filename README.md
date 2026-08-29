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

### 起動経路

APOD は**米国東部時間の 0 時ちょうど**に更新されます（日本時間では夏時間 **13:00**、冬時間 **14:00**）。

**GitHub Actions の `schedule` はこのリポジトリでは信頼できません。** 2026-08-27 は 9 回、
8-28 は 36 回の予定がいずれも 1 度も発火せず、2 日続けて投稿が飛びました。同じ日、
薬剤ニュースも cron から 3〜7 時間ずれて実行されています。そのため DHBR と同じく
**cron-job.org からの `workflow_dispatch` をメイン経路**にしています。

| 経路 | 起動 | 役割 |
|---|---|---|
| `workflow_dispatch` | cron-job.org が 14:05 JST に起動 | **メイン**。更新後の最新版が届く |
| `workflow_call` | DHBR Daily Digest から（6:00 JST） | **取りこぼし用**。メインが失敗した日を翌朝拾う |
| `schedule` | `13,33,53 3-14 * * *`（12:13〜23:53 JST） | バックアップ。動けば儲けもの |

どの経路から起動されても、同じ APOD なら手順 2 のガードで即終了するため**投稿は 1 日 1 回**です。
空振りの回は NASA API を 1 回叩いて終了するだけで Claude API は呼ばないので、
**課金は実際に投稿する 1 回ぶんだけ**です。

`workflow_call` 経由（6:00 JST）はその時点の最新が米国日付で前日ぶんになります。
前日ぶんが投稿できていれば重複ガードで何もせず終了し、飛んでいた日だけ遅れて投稿されます。

#### cron-job.org の設定

DHBR 用のジョブを複製し、URL だけ差し替えてください。

- **URL**: `https://api.github.com/repos/bntprt/claude-routines/actions/workflows/apod-daily.yml/dispatches`
- **Method**: `POST`
- **Headers**:
  - `Authorization: Bearer <GitHub の Personal Access Token>`
  - `Accept: application/vnd.github+json`
  - `Content-Type: application/json`
- **Body**: `{"ref":"main"}`
- **実行時刻**: 毎日 **14:05 JST**

APOD の更新は夏時間 13:00 JST / 冬時間 14:00 JST と年 2 回ずれます。遅いほうに合わせた
14:05 固定にしておけば、**年間を通して必ず更新後に走る**ため、切り替えのたびに設定を
直す必要がありません。夏のあいだは更新から約 1 時間後に届くことになります。

> 夏場もできるだけ早く受け取りたい場合は、cron-job.org のスケジュール画面で
> **時刻に 13 と 14 の両方を選択**してください（1 つのジョブで 2 回発火します）。
> 夏は 13:05 の回が投稿し、冬は 13:05 が空振りして 14:05 の回が投稿します。
> 重複ガードがあるので、どちらの季節でも投稿は 1 日 1 回のままです。

PAT は `repo` スコープ（fine-grained なら対象リポジトリの **Actions: Read and write**）が必要です。

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| Secret 名 | 説明 |
|---|---|
| `NASA_API_KEY` | [api.nasa.gov](https://api.nasa.gov/) で発行した API キー（未設定なら `DEMO_KEY` で動きますがレート制限が厳しめです） |
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー。**未登録だと日本語要約が生成されず、英語原文がそのまま投稿されます**（DHBR / 薬剤ニュースと共通） |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`、DHBR / 薬剤ニュースと共通） |

**このリポジトリは public です。API キーをコード中に直接書かないでください。**

`ANTHROPIC_API_KEY` を使う（＝ Claude API に課金が発生する）のは、このルーティンだけです。
薬剤ニュースと DHBR のワークフローにはこの Secret を渡していません。

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
4. 各記事のリード文を約 200 字ぶん抜粋
   （**Claude API による要約はあえて使っていません**。両サイトとも有料会員限定記事が多く
   本文を取得できないため、要約しても品質が出ず課金に見合わないという判断です。
   ワークフローから `ANTHROPIC_API_KEY` を渡していないので、Secret を登録しても
   このルーティンは課金されません）
5. サイトごとにまとめて Slack `#薬剤ニュース` チャンネルへ投稿
6. 投稿済み URL（同話題スキップ分を含む）を `data/pharmacy_seen_articles.json` に保存して main へコミット

### スケジュール

**メイン経路は DHBR Daily Digest への相乗りです。** DHBR は cron-job.org から
`workflow_dispatch` で毎朝 6:00 JST に起動されるため、GitHub 側の都合に左右されません。
`dhbr-digest.yml` の `pharmacy-news` ジョブが `pharmacy-news.yml` を
`workflow_call` で呼び出し、DHBR の投稿に続けて薬剤ニュースを投稿します。
DHBR 側が失敗しても薬剤ニュースは実行されます（`if: always()`）。

保険として `pharmacy-news.yml` 自身の `schedule` も残しています。

| cron (UTC) | JST | 役割 |
|---|---|---|
| （DHBR 相乗り） | 6:00 | **メイン**（cron-job.org 起動） |
| `0 21 * * *` | 6:00 | 保険 |
| `30 21 * * *` | 6:30 | 保険 |
| `0 23 * * *` | 8:00 | 保険 |

二重投稿は起きません。`data/pharmacy_seen_articles.json` の `last_posted`（JST の日付）を見て、
**その日すでに投稿済みなら即終了**します。相乗り経路と `schedule` が同時刻に重なっても
`concurrency: pharmacy-news` で直列化されるため、main への push も競合しません。

> **なぜ相乗りにしたか**: 2026-08-27、GitHub Actions の `schedule` がリポジトリ全体で
> 11 時間以上まったく発火せず、6:00 / 6:30 / 8:00 の 3 枠すべてが不発になりました
> （同時刻に `workflow_dispatch` は正常動作）。`schedule` だけに依存しない経路が必要と判断しました。

> **注意**: `schedule` トリガーはデフォルトブランチ（main）のワークフローのみ有効です。
> このワークフローを main にマージすると稼働を開始します。

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください
（DHBR Daily Digest と共通）。

| Secret 名 | 説明 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

`ANTHROPIC_API_KEY` は使いません（上記のとおり要約を行わないため）。

Bot を `#薬剤ニュース` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → Pharmacy News Daily → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export SLACK_BOT_TOKEN=xoxb-...
python scripts/pharmacy_news.py
```

## DHBR Daily Digest

毎朝 6:00 JST に [Diamond Harvard Business Review](https://dhbr.diamond.jp/) の新着記事を
取得・要約して Slack の `#hbrまとめ` チャンネルへ投稿します。

### 動作概要

1. dhbr.diamond.jp から最新 10 件の記事を取得
2. `data/seen_articles.json` と照合して未投稿の記事に絞る
3. 上位 3 件のリード文を 200 字ぶん抜粋（Claude API は使いません）
4. Slack `#hbrまとめ` チャンネルへ投稿
5. 投稿済み URL を `data/seen_articles.json` に保存してコミット

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| Secret 名 | 説明 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

`ANTHROPIC_API_KEY` は使いません（`scripts/dhbr_digest.py` は Claude API を呼びません）。

#### Slack Bot に必要なスコープ

- `chat:write` — メッセージ投稿
- `channels:read` / `groups:read` — チャンネル情報読み取り（任意）

Bot を `#hbrまとめ` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → DHBR Daily Digest → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export SLACK_BOT_TOKEN=xoxb-...
python scripts/dhbr_digest.py
```
