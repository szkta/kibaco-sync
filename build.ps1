# kibaco-sync.exe をビルドする（dist\kibaco-sync.exe ができる）
# 事前に client_secret.json（デスクトップアプリ用 OAuth クライアント）をこのフォルダに置くこと
Set-Location $PSScriptRoot
.\.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name kibaco-sync `
    --add-data "client_secret.json;." `
    --collect-all playwright --collect-data googleapiclient `
    --hidden-import google_auth_oauthlib.flow app.py
