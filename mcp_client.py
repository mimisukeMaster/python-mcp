import asyncio
import os
import json
import sys
import traceback
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from dotenv import load_dotenv

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from google.generativeai.protos import Part

# .envファイルから環境変数を読み込む
load_dotenv()

# Gemini APIクライアントを初期化
try:
    api_key = os.environ["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except KeyError:
    print("エラー: 環境変数 GOOGLE_API_KEY が設定されていません。")
    exit()

def clean_schema_for_gemini(schema_dict):
    """Geminiが受け付けない'title'と'default'フィールドを再帰的に削除する"""
    if isinstance(schema_dict, dict):
        # 'title'と'default'を削除
        schema_dict.pop('title', None)
        schema_dict.pop('default', None)
        
        # さらに下の階層にも適用
        for key, value in schema_dict.items():
            clean_schema_for_gemini(value)

    elif isinstance(schema_dict, list):
        for item in schema_dict:
            clean_schema_for_gemini(item)

    return schema_dict

async def main():

    # サーバ起動準備
    python_executable = os.environ["PYTHON_EXE"]
    server_script = os.environ["SERVER_SCRIPT"]
    
    # サーバ起動
    server_params = StdioServerParameters(command=python_executable, args=[server_script])
    
    # mcpクライアントを起動・管理
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:

            # サーバとの通信の初期化
            await session.initialize()
            print("MCPサーバーに接続しました。")

            mcp_tools = await session.list_tools()
            
            # MCPのツール定義をGemini APIが理解できる形式に変換
            gemini_tool_declarations = []
            for tool in mcp_tools.tools:
                # input_schemaを一度Pythonの辞書に変換
                params_schema = tool.inputSchema.copy()
                
                cleaned_schema = clean_schema_for_gemini(params_schema)

                
                # titleを削除したスキーマでFunctionDeclarationを作成
                gemini_tool_declarations.append(
                    FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters=cleaned_schema
                    )
                )
            gemini_tools = [Tool(function_declarations=gemini_tool_declarations)]
            
            # 通信の確認としてサーバの関数名を表示
            if gemini_tool_declarations:
                print(f"サーバの関数 '{', '.join([t.name for t in gemini_tool_declarations])}' を認識しました。")
            else:
                print("サーバーから利用可能なツールが見つかりませんでした。サーバー側のコードを確認してください。")
            print("----------------------------------------------------")

            print("自然言語でBlenderに指示を出してください。('exit'で終了）")

            system_instruction = (
                "You are an expert assistant for Blender. "
                "Your task is to understand the user's natural language request and break it down into a sequence of precise Blender operator calls. "
                "Use the provided 'execute_blender_operator' tool to execute these calls. "
                "Do not ask for confirmation. Execute the task directly. "
                "If a task is complex, chain multiple tool calls together until the task is complete."
            )
    
            # モデルの初期化
            model = genai.GenerativeModel(
                'gemini-1.5-flash',
                tools=gemini_tools,
                system_instruction=system_instruction
            )
            # チャットセッション開始
            chat = model.start_chat(enable_automatic_function_calling=False)
    
            # 対話ループ
            while True:
                user_input = input("> ")
                if user_input.lower() == 'exit':
                    break
                
                print("Geminiに問い合わせ中...")
                try:
                    # ユーザの最初の指示を送信
                    response = await chat.send_message_async(user_input)
                    
                    # Geminiがツール呼び出しを続ける限りループ
                    while True:
                    
                        # 応答からfunction_callを探す
                        candidate = response.candidates[0]
    
                        # function_callがなければループを抜ける
                        if not candidate.content.parts or not hasattr(candidate.content.parts[0], 'function_call') or not candidate.content.parts[0].function_call.name:                        
                            break    
                        
                        # 応答に含まれる全てのツール呼び出しを順番に実行
                        api_requests_for_next_turn = []
                        for part in candidate.content.parts:
                            if part.function_call and part.function_call.name:
                                tool_name = part.function_call.name
                                
                                # Geminiの引数形式(Struct)をPythonの辞書に変換
                                tool_input = {key: value for key, value in part.function_call.args.items()}
    
                                print(f"Geminiがツール '{tool_name}' の使用を決定しました。")
                                print(f"引数: {tool_input}")
                                
                                # MCPサーバにツール実行をリクエスト
                                result = await session.call_tool(tool_name, tool_input)
                                tool_result_text = result.content[0].text if result.content and hasattr(result.content[0], 'text') else str(result.content)
                                print(f"Blenderからの結果: {tool_result_text}")
    
                                # Geminiへの次のリクエスト（ツール実行結果）を準備
                                api_requests_for_next_turn.append(
                                    Part(function_response={
                                        "name": tool_name,
                                        "response": {"result": tool_result_text}
                                    })
                                )
    
                        # 実行結果をGeminiにフィードバックして、次の指示を仰ぐ
                        print("Geminiからの指示を待っています...")
                        response = await chat.send_message_async(api_requests_for_next_turn)
                    
                    # ツール呼び出しのループが終わったら、チャット履歴の最後のメッセージを表示
                    final_response_text = chat.history[-1].parts[0].text
                    print(f"Gemini（最終的な応答）: {final_response_text}")
    
                except Exception as e:
                    print(f"エラーが発生しました: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    print("Blenderを起動し、MCPアドオンが有効になっていることを確認してください...")
    asyncio.run(main())