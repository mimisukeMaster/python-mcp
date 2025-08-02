import sys
import logging
import os
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# 必要なライブラリをインポート
from tavily import TavilyClient
from huggingface_hub import InferenceClient
import requests
from moviepy import ImageClip, AudioFileClip
from PIL import Image

# 環境変数をロード
load_dotenv()

# ログ設定
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='[SERVER] %(message)s')

# サーバー初期化
mcp = FastMCP("video-generator-server")
OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Tool 1: Web検索 (Tavily) ---
@mcp.tool()
def search_web(query: str) -> str:
    """指定されたクエリでWebを検索し、AIに適した要約済みの検索結果を返す"""
    logging.info(f"Searching web with Tavily for: {query}")
    try:
        tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        response = tavily.search(query=query, search_depth="basic", max_results=5)
        formatted_results = "\n".join([f"- {obj['title']}: {obj['content']}" for obj in response['results']])
        return f"Web検索結果:\n{formatted_results}"
    except Exception as e:
        return f"TavilyでのWeb検索中にエラーが発生しました: {e}"

# --- Tool 2: 画像生成 (Hugging Face) ---
@mcp.tool()
def generate_image(prompt: str) -> str:
    """指定されたプロンプトで画像を生成し、PNG形式(.png)で保存後、そのファイルパスを返す"""
    logging.info(f"Generating image with Hugging Face for: {prompt}")
    try:
        client = InferenceClient(token=os.environ["HUGGINGFACE_API_KEY"])
        
        # text_to_imageはPillowのImageオブジェクトを返す
        image_object = client.text_to_image(
            prompt, 
            model="stabilityai/stable-diffusion-xl-base-1.0"
        )
        
        # PillowのImageオブジェクトをファイルに保存するには .save() メソッドを使う
        img_path = OUTPUT_DIR / f"{prompt[:30].replace(' ', '_')}.png"
        image_object.save(img_path)
        
        return str(img_path)
    except Exception as e:
        return f"Hugging Faceでの画像生成中にエラーが発生しました: {e}"

# --- Tool 3: 音声合成 (VOICEVOX su-shiki API) ---
@mcp.tool()
def synthesize_speech(text: str, speaker_id: int = 3, filename: str = "narration") -> str:
    """VOICEVOX Web APIを使用してテキストから音声を合成し、WAV形式(.wav)で保存後、そのファイルパスを返す"""
    logging.info(f"Synthesizing speech with VOICEVOX API for: {text[:30]}...")
    API_KEY = os.environ.get("VOICEVOX_API_KEY")
    if not API_KEY:
        return "エラー: 環境変数 VOICEVOX_API_KEY が設定されていません。"
    VOICEVOX_URL = "https://api.su-shiki.com/v2/voicevox/audio/"
    try:
        params = {"text": text, "speaker": speaker_id, "key": API_KEY}
        response = requests.post(VOICEVOX_URL, params=params, timeout=60)
        if response.status_code != 200:
            return f"エラー: VOICEVOX APIリクエスト失敗. Status: {response.status_code}, Body: {response.text}"
        audio_path = OUTPUT_DIR / Path(filename).with_suffix('.wav')
        with open(audio_path, "wb") as f:
            f.write(response.content)
        return str(audio_path)
    except Exception as e:
        return f"VOICEVOX APIでの音声合成中にエラーが発生しました: {e}"

# --- Tool 4: 動画組立 (MoviePy) ---
@mcp.tool()
def create_video(image_path: str, audio_path: str, output_filename: str = "final_video") -> str:
    """一枚の画像と一つの音声ファイルから動画を作成し、MP4形式(.mp4)で保存後、そのファイルパスを返す"""
    logging.info(f"Creating video from {image_path} and {audio_path}")
    try:
        with AudioFileClip(audio_path) as audio_clip:
            
            final_clip = (ImageClip(image_path)
                        .with_duration(audio_clip.duration)
                        .with_audio(audio_clip))
            
            video_path = OUTPUT_DIR / Path(output_filename).with_suffix('.mp4')
            final_clip.write_videofile(str(video_path), fps=24, codec="libx264", threads=4)
            
        return str(video_path)
    except Exception as e:
        import traceback
        logging.error(f"動画作成中にエラーが発生しました: {e}\n{traceback.format_exc()}")
        return f"動画作成中にエラーが発生しました: {e}"

# --- サーバー実行 ---
if __name__ == "__main__":
    mcp.run()