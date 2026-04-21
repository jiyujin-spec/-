#!/bin/bash
# ================================================================
#  Instagram 自動投稿生成 - セットアップスクリプト
#  macOS LaunchAgent の登録と依存ライブラリのインストールを行います
# ================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_SCRIPT="$SCRIPT_DIR/instagram_post_generator.py"
SAVE_DIR="$HOME/Documents/insta-auto"
PLIST_LABEL="com.instauto.dailypost"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

# Python3 のパスを自動検出（Homebrew → pyenv → system の順）
PYTHON_PATH=""
for candidate in \
    "$(brew --prefix 2>/dev/null)/bin/python3" \
    "$HOME/.pyenv/shims/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"; do
    if [ -x "$candidate" ] 2>/dev/null; then
        PYTHON_PATH="$candidate"
        break
    fi
done

if [ -z "$PYTHON_PATH" ]; then
    PYTHON_PATH=$(which python3 2>/dev/null || true)
fi

if [ -z "$PYTHON_PATH" ]; then
    echo "❌ python3 が見つかりません。Homebrew などでインストールしてください。"
    exit 1
fi

echo "=============================================="
echo "  📱  Instagram 自動投稿生成  セットアップ"
echo "=============================================="
echo ""
echo "  Python  : $PYTHON_PATH  ($($PYTHON_PATH --version))"
echo "  スクリプト: $MAIN_SCRIPT"
echo "  保存先  : $SAVE_DIR"
echo ""

# ── OS チェック ───────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    echo "⚠️  このスクリプトは macOS 専用です。"
    echo "   LaunchAgent の設定をスキップし、ライブラリのインストールのみ行います。"
    SKIP_LAUNCHAGENT=true
else
    SKIP_LAUNCHAGENT=false
fi

# ── ライブラリをインストール ──────────────────────────────────
echo "📦 必要なライブラリをインストール中..."
"$PYTHON_PATH" -m pip install -q \
    "google-genai" \
    "requests" \
    "duckduckgo-search" \
    "Pillow"
echo "✅ ライブラリのインストール完了"

# ── 保存ディレクトリを作成 ────────────────────────────────────
mkdir -p "$SAVE_DIR"
echo "✅ 保存ディレクトリ作成: $SAVE_DIR"

# ── LaunchAgent の登録（macOS のみ） ──────────────────────────
if [ "$SKIP_LAUNCHAGENT" = "false" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"

    cat > "$PLIST_DEST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${MAIN_SCRIPT}</string>
    </array>

    <!-- 毎朝 9:00 に実行 -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>   <integer>9</integer>
        <key>Minute</key> <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${SAVE_DIR}/run.log</string>
    <key>StandardErrorPath</key>
    <string>${SAVE_DIR}/error.log</string>

    <!-- ログイン直後の自動実行はしない -->
    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>LANG</key>
        <string>ja_JP.UTF-8</string>
    </dict>
</dict>
</plist>
PLIST_EOF

    echo "✅ LaunchAgent plist 作成: $PLIST_DEST"

    # 既存のエージェントをアンロードしてから再登録
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    launchctl load   "$PLIST_DEST"
    echo "✅ LaunchAgent 登録完了（毎朝 9:00 に自動実行されます）"
fi

# ── 完了メッセージ ────────────────────────────────────────────
echo ""
echo "=============================================="
echo "🎉 セットアップ完了！"
echo "=============================================="
echo ""
echo "【次のステップ】"
echo ""
echo "  1. config.py を開いて以下を設定してください:"
echo "       GEMINI_API_KEY   → https://aistudio.google.com/app/apikey"
echo "       LINE_NOTIFY_TOKEN → https://notify-bot.line.me/my/"
echo ""
echo "  2. 動作確認:"
echo "       python3 \"$MAIN_SCRIPT\""
echo ""
if [ "$SKIP_LAUNCHAGENT" = "false" ]; then
    echo "  3. 即時テスト実行（LaunchAgent経由）:"
    echo "       launchctl start ${PLIST_LABEL}"
    echo ""
    echo "  4. LaunchAgent の停止:"
    echo "       launchctl unload \"$PLIST_DEST\""
    echo ""
    echo "  ログの確認:"
    echo "       tail -f \"$SAVE_DIR/run.log\""
    echo "       tail -f \"$SAVE_DIR/error.log\""
fi
echo ""
