import asyncio
import os
from pathlib import Path
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from dotenv import load_dotenv

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from google.generativeai.protos import Part

load_dotenv()
try:
    api_key = os.environ["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except KeyError:
    print("エラー: .envファイルに GOOGLE_API_KEY がありません。")
    exit()

def clean_schema_for_gemini(schema_dict):
    """'title'と'default'フィールドを再帰的に削除する"""
    if isinstance(schema_dict, dict):
        schema_dict.pop('title', None)
        schema_dict.pop('default', None)
        for value in schema_dict.values():
            clean_schema_for_gemini(value)
    elif isinstance(schema_dict, list):
        for item in schema_dict:
            clean_schema_for_gemini(item)
    return schema_dict

async def main():
    try:
        python_executable = os.environ["PYTHON_EXE"]
        server_script_path_str = os.environ["SERVER_SCRIPT"]
    except KeyError as e:
        print(f"エラー: .envファイルに {e} が設定されていません。")
        exit()
    
    python_path = Path(python_executable)
    script_path = Path(server_script_path_str)

    if not python_path.exists():
        print(f"❌ エラー: 指定されたPython実行ファイルが見つかりません。パスを確認してください。")
        return
    if not script_path.exists():
        print(f"❌ エラー: 指定されたサーバー・スクリプトが見つかりません。パスを確認してください。")
        return
    
    server_params = StdioServerParameters(
        command=python_executable,
        args=[f"{script_path}"]
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("✅ MCPサーバーに接続しました。")

            mcp_tools = await session.list_tools()
            gemini_tool_declarations = []
            for tool in mcp_tools.tools:
                params_schema = tool.inputSchema.copy()
                cleaned_schema = clean_schema_for_gemini(params_schema)
                gemini_tool_declarations.append(
                    FunctionDeclaration(
                        name=tool.name, description=tool.description, parameters=cleaned_schema
                    )
                )
            gemini_tools = [Tool(function_declarations=gemini_tool_declarations)]
            
            if gemini_tool_declarations:
                print(f"✅ サーバーツール '{', '.join([t.name for t in gemini_tool_declarations])}' を認識しました。")
            
            print("----------------------------------------------------")

            system_instruction = (
                "あなたは短い解説動画を生成する専門家アシスタントです。"
                "以下の手順に厳密に従ってください:\n"
                "1. 'search_web'ツールを使い、ユーザーのトピックについて調査します。\n"
                "2. 検索結果に基づき、100文字程度の簡潔なナレーション原稿を作成します。\n"
                "3. 'synthesize_speech'ツールを使い、その原稿を音声に変換します。\n"
                "4. 原稿の内容に合った、魅力的で具体的な画像生成プロンプトを考案し、'generate_image'ツールを使います。\n"
                "5. 'create_video'ツールを使い、生成された画像と音声のパスを指定して、最終的な動画を組み立てます。\n"
                "これらのステップを順番に実行してください。確認を求めず、直接計画を実行してください。"
                "--- \n"
                "重要ルール: \n"
                "- 'synthesize_speech'ツールはWAV形式(.wav)のファイルを生成します。\n"
                "- 'generate_image'ツールはPNG形式(.png)のファイルを生成します。\n"
                "- 'create_video'ツールはMP4形式(.mp4)のファイルを生成します。"
            )
            model = genai.GenerativeModel('gemini-2.5-pro', tools=gemini_tools, system_instruction=system_instruction)
            chat = model.start_chat(enable_automatic_function_calling=False)
            
            print("動画にしたいトピックを教えてください。(例: 量子コンピュータの仕組み / exitで終了)")
            while True:
                user_input = input("> ")
                if user_input.lower() == 'exit':
                    break

                print("🧠 Geminiに動画作成プランを問い合わせ中...")
                try:
                    response = await chat.send_message_async(user_input)
                    
                    while True:
                        if not response.candidates or not response.candidates[0].content.parts or not hasattr(response.candidates[0].content.parts[0], 'function_call') or not response.candidates[0].content.parts[0].function_call.name:
                            break
                        
                        api_requests_for_next_turn = []
                        for part in response.candidates[0].content.parts:
                            if part.function_call and part.function_call.name:
                                tool_name = part.function_call.name
                                tool_input = {key: value for key, value in part.function_call.args.items()}
                                
                                print(f"🤖 Geminiがツール '{tool_name}' の使用を決定しました。")
                                
                                result = await session.call_tool(tool_name, tool_input)
                                tool_result_text = result.content[0].text if result.content and hasattr(result.content[0], 'text') else str(result.content)
                                print(f"✅ 実行結果: {tool_result_text}")

                                api_requests_for_next_turn.append(
                                    Part(function_response={"name": tool_name, "response": {"result": tool_result_text}})
                                )
                        
                        print("🧠 実行結果をGeminiに報告し、次の指示を待っています...")
                        response = await chat.send_message_async(api_requests_for_next_turn)
                    
                    final_response_text = chat.history[-1].parts[0].text
                    print(f"🎉 Gemini (タスク完了): {final_response_text}")

                except Exception as e:
                    print(f"エラーが発生しました: {e}")

if __name__ == "__main__":
    asyncio.run(main())