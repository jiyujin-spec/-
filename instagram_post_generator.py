#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram 自動投稿生成スクリプト
- トレンドリサーチ → Gemini APIで投稿案生成 → LINE通知 → ファイル保存
"""

# ================================================================
# Step 0: 必要なライブラリを自動インストール
# ================================================================
import subprocess
import sys

REQUIRED_PACKAGES = [
    "google-generativeai",
    "requests",
    "duckduckgo-search",
]

def _auto_install():
    for pkg in REQUIRED_PACKAGES:
        mod = pkg.replace("-", "_").split("_")[0]
        try:
            __import__(mod)
        except ImportError:
            print(f"📦 {pkg} をインストール中...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", pkg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"✅ {pkg} インストール完了")

_auto_install()

# ================================================================
# インポート
# ================================================================
import json
import datetime
import time
import requests
import google.generativeai as genai
from pathlib import Path

# ================================================================
# 設定ファイルの読み込み
# ================================================================
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.py"

if not CONFIG_FILE.exists():
    print(f"❌ config.py が見つかりません: {CONFIG_FILE}")
    sys.exit(1)

import importlib.util
_spec = importlib.util.spec_from_file_location("config", CONFIG_FILE)
_cfg  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)

CONFIG = {
    "genre":            getattr(_cfg, "GENRE",            "カフェ・グルメ"),
    "target":           getattr(_cfg, "TARGET",           ""),
    "post_style":       getattr(_cfg, "POST_STYLE",       ""),
    "tone":             getattr(_cfg, "TONE",             ""),
    "gemini_api_key":   getattr(_cfg, "GEMINI_API_KEY",   ""),
    "line_notify_token":getattr(_cfg, "LINE_NOTIFY_TOKEN",""),
    "save_dir":         Path(getattr(_cfg, "SAVE_DIR", "~/Documents/insta-auto")).expanduser(),
}


# ================================================================
# ユーティリティ
# ================================================================
def _get_season(month: int) -> str:
    return {1:"冬", 2:"冬", 3:"春", 4:"春", 5:"春",
            6:"夏", 7:"夏", 8:"夏", 9:"秋", 10:"秋",
            11:"秋", 12:"冬"}[month]


# ================================================================
# Step 1: Instagram トレンドリサーチ（DuckDuckGo）
# ================================================================
def research_trends(genre: str) -> str:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "（トレンド情報取得ライブラリが利用できませんでした）"

    today  = datetime.date.today()
    ym     = today.strftime("%Y年%m月")
    season = _get_season(today.month)

    queries = [
        f"Instagram {genre} トレンド {ym}",
        f"インスタグラム {genre} {season} バズ 投稿",
        f"{genre} インスタ 人気 ハッシュタグ",
    ]

    lines = []
    for q in queries:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=5, region="jp-jp"):
                    body = r.get("body", "")[:200]
                    lines.append(f"・{r.get('title','')}: {body}")
            time.sleep(0.5)
        except Exception as e:
            lines.append(f"（検索失敗: {q} — {e}）")

    return "\n".join(lines[:15]) if lines else "（トレンド情報を取得できませんでした）"


# ================================================================
# Step 2–5: Gemini API で投稿案を生成
# ================================================================
def generate_post(trend_info: str, cfg: dict) -> dict:
    genai.configure(api_key=cfg["gemini_api_key"])
    model = genai.GenerativeModel("gemini-1.5-flash")

    today  = datetime.date.today()
    season = _get_season(today.month)

    prompt = f"""
あなたはInstagramマーケティングの専門家です。
以下の情報をもとに、最適なInstagram投稿案を作成してください。

【アカウント情報】
- ジャンル: {cfg['genre']}
- ターゲット層: {cfg['target']}
- 普段の投稿スタイル: {cfg['post_style']}
- 投稿トーン: {cfg['tone']}
- 今の季節: {season}
- 今日の日付: {today.strftime('%Y年%m月%d日')}

【最新トレンド情報（Web検索結果）】
{trend_info}

以下のキーを持つJSONを返してください（マークダウン不要、JSONのみ）:

{{
  "concept": "投稿コンセプト。アカウントの特徴とトレンドを融合した2〜3文の具体的なコンセプト。",
  "image_prompt_en": "画像生成AI(Midjourney/DALL-E/SD)向け英語プロンプト。構図・光・雰囲気・色調・スタイルを詳細に。",
  "image_prompt_ja": "同上の日本語版プロンプト。",
  "caption": "実際に投稿するキャプション本文。自然な改行あり。絵文字適度に使用。200〜300文字。",
  "hashtags": "#ハッシュタグ を半角スペース区切りで25〜30個。日本語と英語を混在。",
  "best_time": "おすすめ投稿時間帯と理由（50文字以内）。",
  "engagement_tips": ["エンゲージメントのポイント1", "ポイント2", "ポイント3"]
}}
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # コードブロックの除去
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


# ================================================================
# Step 6: LINE Notify 送信（1000文字制限に対応して分割送信）
# ================================================================
def send_line_notify(token: str, post: dict, save_path: Path) -> bool:
    today = datetime.date.today().strftime("%Y年%m月%d日")
    url   = "https://notify-api.line.me/api/notify"
    hdrs  = {"Authorization": f"Bearer {token}"}

    # 第1メッセージ：コンセプト・キャプション・投稿時間
    msg1 = (
        f"\n📸 Instagram投稿案 {today}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💡コンセプト\n{post['concept']}\n\n"
        f"✍️キャプション\n{post['caption']}\n\n"
        f"⏰おすすめ投稿時間\n{post['best_time']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📁保存先: {save_path.name}"
    )

    # 第2メッセージ：ハッシュタグ
    msg2 = (
        "\n#️⃣ ハッシュタグ\n"
        "━━━━━━━━━━━━━━━━\n"
        + post["hashtags"]
    )

    # 第3メッセージ：画像生成プロンプト
    msg3 = (
        "\n🎨 画像生成プロンプト\n"
        "━━━━━━━━━━━━━━━━\n"
        + post["image_prompt_ja"]
    )

    success = True
    for msg in [msg1, msg2, msg3]:
        r = requests.post(url, headers=hdrs, data={"message": msg[:1000]}, timeout=30)
        if r.status_code != 200:
            success = False
        time.sleep(0.3)

    return success


# ================================================================
# Step 7: ファイル保存（上書きなし・連番付き）
# ================================================================
def save_to_file(save_dir: Path, post: dict, trend_info: str) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    today    = datetime.date.today().strftime("%Y-%m-%d")
    base     = f"{today}_投稿案"
    filepath = save_dir / f"{base}.txt"

    n = 1
    while filepath.exists():
        filepath = save_dir / f"{base}_{n}.txt"
        n += 1

    tips = post.get("engagement_tips", [])
    if isinstance(tips, list):
        tips_str = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(tips))
    else:
        tips_str = str(tips)

    content = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instagram 投稿案
生成日時: {datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【投稿コンセプト】
{post['concept']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【キャプション】
{post['caption']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ハッシュタグ】
{post['hashtags']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【おすすめ投稿時間】
{post['best_time']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【エンゲージメントアップのポイント】
{tips_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【画像生成プロンプト（英語）】
{post['image_prompt_en']}

【画像生成プロンプト（日本語）】
{post['image_prompt_ja']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【参照したトレンド情報（抜粋）】
{trend_info[:800]}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ================================================================
# メイン処理
# ================================================================
def main():
    print("=" * 52)
    print("  📱  Instagram 投稿案 自動生成ツール")
    print("=" * 52)

    # APIキーのチェック
    if not CONFIG["gemini_api_key"] or CONFIG["gemini_api_key"] == "YOUR_GEMINI_API_KEY_HERE":
        print("\n❌ エラー: config.py の GEMINI_API_KEY を設定してください。")
        print("   取得先: https://aistudio.google.com/app/apikey")
        sys.exit(1)

    line_enabled = bool(
        CONFIG["line_notify_token"]
        and CONFIG["line_notify_token"] != "YOUR_LINE_NOTIFY_TOKEN_HERE"
    )
    if not line_enabled:
        print("\n⚠️  LINE Notify トークン未設定 → LINE通知はスキップします")

    # ── Step 1 ──────────────────────────────────────
    print(f"\n🔍 Step 1: {CONFIG['genre']} のトレンドをリサーチ中...")
    trend_info = research_trends(CONFIG["genre"])
    hit_count  = len([l for l in trend_info.splitlines() if l.startswith("・")])
    print(f"   → {hit_count} 件のトレンド情報を取得しました")

    # ── Step 2–5 ─────────────────────────────────────
    print("\n✨ Step 2–5: Gemini API で投稿案を生成中...")
    try:
        post = generate_post(trend_info, CONFIG)
    except json.JSONDecodeError as e:
        print(f"❌ JSONパースエラー: {e}\nGeminiの返答をそのまま表示します。")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Gemini API エラー: {e}")
        sys.exit(1)
    print("   → 生成完了")

    # ── Step 7: 保存 ──────────────────────────────────
    print(f"\n💾 Step 7: ファイルを保存中 → {CONFIG['save_dir']}")
    save_path = save_to_file(CONFIG["save_dir"], post, trend_info)
    print(f"   → 保存完了: {save_path.name}")

    # ── Step 6: LINE通知 ──────────────────────────────
    if line_enabled:
        print("\n📲 Step 6: LINE Notify で送信中...")
        ok = send_line_notify(CONFIG["line_notify_token"], post, save_path)
        print("   → 送信完了 ✅" if ok else "   → 送信失敗 ❌（トークンを確認してください）")

    # ── 結果プレビュー ─────────────────────────────────
    print("\n" + "=" * 52)
    print("📋 生成された投稿案（プレビュー）")
    print("=" * 52)
    print(f"💡 コンセプト:\n   {post['concept'][:120]}...")
    print(f"\n✍️  キャプション（冒頭）:\n   {post['caption'][:80]}...")
    print(f"\n⏰ おすすめ投稿時間:\n   {post['best_time']}")
    print(f"\n📁 保存先: {save_path}")
    print("\n🎉 完了！")


if __name__ == "__main__":
    main()
