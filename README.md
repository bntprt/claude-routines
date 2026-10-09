# claude-routines

Claude Code で動かす自動化ルーティン集。

## 今日の天文学（APOD）

NASA の [APOD（Astronomy Picture of the Day）](https://science.nasa.gov/apod/) が更新され次第、
**高校生が理解できるレベル**の日本語にまとめて Slack の `#天文学` チャンネルへ投稿します。
GitHub Actions 上で動くため、**PC やデスクトップアプリが起動していなくても実行されます**。

### 動作概要

1. `https://science.nasa.gov/wp-json/wp/v2/apod-basic?per_page=1` から最新の APOD を取得
   （API キー不要。一時的な 5xx・タイムアウトは最大 3 回まで再試行）

   > 2026-09 に APOD は apod.nasa.gov から science.nasa.gov へ移転しました。旧 API
   > `api.nasa.gov/planetary/apod` は 9/30 から 500 やタイムアウトを返すようになり、
   > 応答があっても画像が NASA ロゴ・タイトルが「NASA Science」のダミーです（12/1 アーカイブ予定）。
2. `data/apod_seen.json` と照合し、同じ日付の APOD を二重投稿しない
3. 解説文を Claude API（Haiku）で高校生向けの日本語に要約
   （タイトル訳 / 約 350 字の要約 / 「ここが面白い」1 行 / ことばのメモ 0〜4 個）
   `ANTHROPIC_API_KEY` 未設定時は英語原文をそのまま投稿します
4. 画像（動画ならサムネイル＋リンク）付きで Slack `#天文学` チャンネルへ投稿
5. 投稿した APOD の日付を `data/apod_seen.json` に保存して main へコミット

### 起動経路

APOD は**米国東部時間の 0 時ちょうど**に更新されます（日本時間では夏時間 **13:00**、冬時間 **14:00**）。

**GitHub Actions の `schedule` はこのリポジトリでは信頼できません。** 2026-08-27 は 9 回、
8-28 は 36 回の予定がいずれも 1 度も発火せず、2 日続けて投稿が飛びました。そのため DHBR と同じく
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
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー。**未登録だと日本語要約が生成されず、英語原文がそのまま投稿されます**（DHBR と共通） |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`、DHBR と共通） |

**このリポジトリは public です。API キーをコード中に直接書かないでください。**

`ANTHROPIC_API_KEY` を使う（＝ Claude API に課金が発生する）のは、このルーティンだけです。
DHBR のワークフローにはこの Secret を渡していません。

Bot（`claude-hbr`）は `#天文学` チャンネルに参加済みです。

### 手動実行

GitHub の **Actions タブ → APOD Daily → Run workflow** から手動実行できます。

その日の APOD をすでに投稿済みだと重複ガードで何もせず終了します。動作確認などで
あえて再投稿したいときは、Run workflow のダイアログで
**「投稿済みの APOD でも再投稿する」にチェック**を入れてください。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/apod_daily.py

# 投稿済みでも再投稿する
FORCE_POST=true python scripts/apod_daily.py

# 取得と整形だけ確認する（要約・投稿・状態保存はしない。Slack トークン不要）
DRY_RUN=1 python scripts/apod_daily.py
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
