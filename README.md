# kibaco-sync

東京都立大学の e ラーニングシステム **kibaco**（Sakai）の

- **課題の締切** → Google カレンダーの専用カレンダー「kibaco課題」
- **授業資料（リソース）** → 指定したフォルダの `<年度>\<授業名>\`

を自動で同期する Windows 用アプリです。

> [!IMPORTANT]
> 大学公式のツールではありません。利用は自己責任で、kibaco の利用規約に従ってください。
> アクセスするのは自分のアカウントで見られる情報だけで、2 回目以降は新しい・更新された資料だけを取得します。

## 機能

- 設定画面から kibaco へのログイン・Google 連携・保存先・対象年度・更新頻度（30 分〜1 日）を設定
- Windows のタスクスケジューラで、ログオン時と一定間隔ごとに自動同期
- 資料は新規・更新分だけ取得。更新されたファイルは古い版を `名前 (旧yyyymmddHHMM).ext` として残してから上書き
- 課題は締切の 30 分前〜締切の予定として登録（1 日前と 3 時間前に通知）。締切前に kibaco から消えた課題は予定も削除
- kibaco のログインが切れると Windows の通知でお知らせ

提出済みかどうかは kibaco の API から取得できないため、カレンダーには反映されません。

## 必要なもの

- Windows 10/11（Microsoft Edge。標準で入っています）
- Python 3.12 以上（ビルドする場合）
- 東京都立大学の kibaco アカウント
- Google アカウント（カレンダー連携を使う場合）

## セットアップ

### 1. Google の OAuth クライアントを作る（カレンダー連携を使う場合）

1. [Google Cloud Console](https://console.cloud.google.com/) で新しいプロジェクトを作成
2. 「API とサービス」→「ライブラリ」で **Google Calendar API** を有効化
3. 「Google Auth Platform」（OAuth 同意画面）を設定：対象は **外部**
4. 「対象」で公開ステータスを **本番環境** にする
   （テストのままだと 7 日ごとに再認証が必要。未審査のアプリは利用者 100 人までという上限があります）
5. 「クライアント」→ 種類 **デスクトップ アプリ** で作成し、JSON をダウンロード
6. リポジトリ直下に `client_secret.json` という名前で置く

使う権限は `calendar.app.created`（このアプリが作ったカレンダーだけを操作できる）だけで、他の予定は読み書きしません。

### 2. ビルド

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

`dist\kibaco-sync.exe` ができます（`client_secret.json` が同梱されます）。
ビルドせずに `.\.venv\Scripts\python app.py` で直接動かすこともできます。

### 3. 使い方

1. `kibaco-sync.exe` を、消したり動かしたりしない場所に置く
   （例: `%LOCALAPPDATA%\Programs\kibaco-sync\`。自動同期はこの場所を覚えるため）
2. 起動して **kibaco にログイン** → 開いた Edge で大学のアカウントでログイン
3. **Google と連携** → ブラウザで Google アカウントを選んで許可
4. 保存先・対象年度・更新頻度を選んで **設定を保存**
5. **今すぐ同期** で 1 回目を実行（資料が多いと数 GB・数分かかります）

設定・ログイン情報・ログは `%LOCALAPPDATA%\kibaco-sync` に保存されます。
アンインストールするときは、自動同期をオフにして保存してから、exe とこのフォルダを削除してください。

## 構成

| ファイル | 役割 |
|---|---|
| `app.py` | 設定画面（tkinter）。`--sync` で画面なし同期、`--apply-settings` で自動同期タスクを設定どおりに再登録 |
| `sync.py` | 同期処理本体（資料ダウンロード・カレンダー呼び出し） |
| `kibaco.py` | Playwright（システムの Edge）で kibaco にログインし、Sakai の `/direct` API を呼ぶ |
| `gcal.py` | Google Calendar API |
| `scheduler.py` | タスクスケジューラ「kibaco同期」の登録・解除 |
| `paths.py` / `config.py` | 保存場所と設定の既定値 |

使っている kibaco の API: `/direct/session/current.json`、`/direct/site.json`、`/direct/assignment/my.json`、`/direct/content/site/<siteId>.json`

## 開発メモ

- ログインの入口は `https://kibaco.tmu.ac.jp/portal/login`。`kibaco-d.tmu.ac.jp` はダッシュボードという別のアプリで、そこでログインしても Sakai のセッションはできません。
- MSIX パッケージのアプリ（Claude デスクトップなど）から起動したプロセスが `%LOCALAPPDATA%` に新しいフォルダを作ると、書き込みがパッケージ専用の領域へ仮想化され、タスクスケジューラからは見えません。動作確認は Explorer から起動して行ってください。
- 起動時の診断ログは `%TEMP%\kibaco-sync-startup.log` に出ます。

## ライセンス

[MIT](LICENSE)
