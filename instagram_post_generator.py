#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram 自動投稿生成スクリプト
トレンドリサーチ → テキスト生成（Gemini） → 画像生成（Imagen 3）→ LINE通知 → ファイル保存
"""

# ================================================================
# Step 0: 必要なライブラリを自動インストール
# ================================================================
import subprocess
import sys

REQUIRED_PACKAGES = [
    "google-genai",
    "requests",
    "duckduckgo-search",
    "Pillow",
]

def _auto_install():
    for pkg in REQUIRED_PACKAGES:
        mod = {"google-genai": "google.genai", "Pillow": "PIL"}.get(pkg, pkg.replace("-", "_"))
        try:
            __import__(mod.split(".")[0])
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
from pathlib import Path
from google import genai
from google.genai import types

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
    "genre":             getattr(_cfg, "GENRE",             "カフェ・グルメ"),
    "target":            getattr(_cfg, "TARGET",            ""),
    "post_style":        getattr(_cfg, "POST_STYLE",        ""),
    "tone":              getattr(_cfg, "TONE",              ""),
    "gemini_api_key":    getattr(_cfg, "GEMINI_API_KEY",    ""),
    "line_notify_token": getattr(_cfg, "LINE_NOTIFY_TOKEN", ""),
    "save_dir":          Path(getattr(_cfg, "SAVE_DIR", "~/Documents/insta-auto")).expanduser(),
}


# ================================================================
# ユーティリティ
# ================================================================
def _get_season(month: int) -> str:
    return {1:"冬", 2:"冬", 3:"春", 4:"春", 5:"春",
            6:"夏", 7:"夏", 8:"夏", 9:"秋", 10:"秋",
            11:"秋", 12:"冬"}[month]

def _strip_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


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
# Step 2: Gemini でキャプション・ハッシュタグ・投稿案を生成
# ================================================================
def generate_post(trend_info: str, cfg: dict, client: genai.Client) -> dict:
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

以下のキーを持つJSONだけを返してください（コードブロック・説明文は不要）:

{{
  "concept": "アカウントの特徴とトレンドを融合した具体的なコンセプト（2〜3文）",
  "image_prompt_en": "Imagen 3向け英語プロンプト。構図・光・雰囲気・色調・スタイルを詳細に。Instagramらしい正方形の写真を意識して。",
  "image_prompt_ja": "同上の日本語版プロンプト。",
  "caption": "実際に投稿するキャプション本文。自然な改行あり。絵文字適度に使用。200〜300文字。",
  "hashtags": "#ハッシュタグ を半角スペース区切りで25〜30個。日本語と英語を混在。",
  "best_time": "おすすめ投稿時間帯と理由（50文字以内）。",
  "engagement_tips": ["エンゲージメントのポイント1", "ポイント2", "ポイント3"]
}}
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    return json.loads(_strip_json(response.text))


# ================================================================
# Step 3: Imagen 3 で画像を生成して保存
# ================================================================
def generate_image(image_prompt_en: str, save_dir: Path, client: genai.Client) -> Path | None:
    today    = datetime.date.today().strftime("%Y-%m-%d")
    base     = f"{today}_投稿画像"
    img_path = save_dir / f"{base}.jpg"

    # 上書き防止
    n = 1
    while img_path.exists():
        img_path = save_dir / f"{base}_{n}.jpg"
        n += 1

    try:
        response = client.models.generate_images(
            model="imagen-3.0-generate-001",
            prompt=image_prompt_en,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1",     # Instagram正方形
            ),
        )
        image_bytes = response.generated_images[0].image.image_bytes
        img_path.write_bytes(image_bytes)
        return img_path

    except Exception as e:
        print(f"   ⚠️  画像生成エラー: {e}")
        return None


# ================================================================
# Step 4: LINE Notify 送信（画像 + テキスト、1000文字制限対応）
# ================================================================
def send_line_notify(token: str, post: dict, save_path: Path, img_path: Path | None) -> bool:
    today = datetime.date.today().strftime("%Y年%m月%d日")
    url   = "https://notify-api.line.me/api/notify"
    hdrs  = {"Authorization": f"Bearer {token}"}

    # メッセージ1: コンセプト・キャプション・投稿時間（＋画像ファイル添付）
    msg1 = (
        f"\n📸 Instagram投稿案 {today}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💡コンセプト\n{post['concept']}\n\n"
        f"✍️キャプション\n{post['caption']}\n\n"
        f"⏰おすすめ投稿時間\n{post['best_time']}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📁{save_path.name}"
    )

    # メッセージ2: ハッシュタグ
    msg2 = (
        "\n#️⃣ ハッシュタグ\n"
        "━━━━━━━━━━━━━━━━\n"
        + post["hashtags"]
    )

    # メッセージ3: エンゲージメントのポイント
    tips = post.get("engagement_tips", [])
    tips_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(tips)) if isinstance(tips, list) else str(tips)
    msg3 = (
        "\n✨ エンゲージメントのポイント\n"
        "━━━━━━━━━━━━━━━━\n"
        + tips_str
    )

    success = True

    # 1通目：画像を添付して送信
    if img_path and img_path.exists():
        try:
            with open(img_path, "rb") as f:
                r = requests.post(
                    url,
                    headers=hdrs,
                    data={"message": msg1[:1000]},
                    files={"imageFile": ("image.jpg", f, "image/jpeg")},
                    timeout=60,
                )
            if r.status_code != 200:
                success = False
            time.sleep(0.3)
        except Exception as e:
            print(f"   ⚠️  LINE画像送信エラー: {e}")
            success = False
    else:
        r = requests.post(url, headers=hdrs, data={"message": msg1[:1000]}, timeout=30)
        if r.status_code != 200:
            success = False
        time.sleep(0.3)

    # 2通目・3通目：テキストのみ
    for msg in [msg2, msg3]:
        r = requests.post(url, headers=hdrs, data={"message": msg[:1000]}, timeout=30)
        if r.status_code != 200:
            success = False
        time.sleep(0.3)

    return success


# ================================================================
# Step 5: テキストファイルに保存（上書きなし・連番付き）
# ================================================================
def save_to_file(save_dir: Path, post: dict, trend_info: str, img_path: Path | None) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    today    = datetime.date.today().strftime("%Y-%m-%d")
    base     = f"{today}_投稿案"
    filepath = save_dir / f"{base}.txt"

    n = 1
    while filepath.exists():
        filepath = save_dir / f"{base}_{n}.txt"
        n += 1

    tips = post.get("engagement_tips", [])
    tips_str = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(tips)) if isinstance(tips, list) else str(tips)

    img_line = f"  生成画像: {img_path.name}" if img_path else "  生成画像: 生成失敗（エラーログを確認）"

    content = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instagram 投稿案
生成日時: {datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
{img_line}
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
【画像生成プロンプト（英語 / Imagen 3使用）】
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

    client = genai.Client(api_key=CONFIG["gemini_api_key"])
    CONFIG["save_dir"].mkdir(parents=True, exist_ok=True)

    # ── Step 1: トレンドリサーチ ──────────────────────
    print(f"\n🔍 Step 1: {CONFIG['genre']} のトレンドをリサーチ中...")
    trend_info = research_trends(CONFIG["genre"])
    hit_count  = len([l for l in trend_info.splitlines() if l.startswith("・")])
    print(f"   → {hit_count} 件のトレンド情報を取得しました")

    # ── Step 2: テキスト生成 ──────────────────────────
    print("\n✨ Step 2: Gemini でキャプション・ハッシュタグを生成中...")
    try:
        post = generate_post(trend_info, CONFIG, client)
    except json.JSONDecodeError as e:
        print(f"❌ JSONパースエラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Gemini API エラー: {e}")
        sys.exit(1)
    print("   → 生成完了")

    # ── Step 3: 画像生成 ──────────────────────────────
    print("\n🎨 Step 3: Imagen 3 で画像を生成中（〜30秒）...")
    img_path = generate_image(post["image_prompt_en"], CONFIG["save_dir"], client)
    if img_path:
        print(f"   → 画像保存完了: {img_path.name}")
    else:
        print("   → 画像生成をスキップしました（テキストのみで続行）")

    # ── Step 4: ファイル保存 ──────────────────────────
    print(f"\n💾 Step 4: ファイルを保存中...")
    save_path = save_to_file(CONFIG["save_dir"], post, trend_info, img_path)
    print(f"   → 保存完了: {save_path.name}")

    # ── Step 5: LINE通知 ──────────────────────────────
    if line_enabled:
        print("\n📲 Step 5: LINE Notify で送信中...")
        ok = send_line_notify(CONFIG["line_notify_token"], post, save_path, img_path)
        print("   → 送信完了 ✅" if ok else "   → 送信失敗 ❌（トークンを確認してください）")

    # ── プレビュー ────────────────────────────────────
    print("\n" + "=" * 52)
    print("📋 生成された投稿案（プレビュー）")
    print("=" * 52)
    print(f"💡 コンセプト:\n   {post['concept'][:120]}...")
    print(f"\n✍️  キャプション（冒頭）:\n   {post['caption'][:80]}...")
    print(f"\n⏰ おすすめ投稿時間:\n   {post['best_time']}")
    if img_path:
        print(f"\n🖼️  生成画像: {img_path}")
    print(f"\n📁 投稿案: {save_path}")
    print("\n🎉 完了！")


if __name__ == "__main__":
    main()
