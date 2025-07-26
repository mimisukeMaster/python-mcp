import asyncio
import os
import json
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from dotenv import load_dotenv

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

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
            
            # 連携テストとして最初のgreet関数が読めてるか確認
            print(f"Blender連携ツール '{gemini_tool_declarations[0].name}' を認識しました。")
            print("----------------------------------------------------")

            print("自然言語でBlenderに指示を出してください。('exit'で終了）")
            
            # 対話ループ
            while True:
                user_input = input("> ")
                if user_input.lower() == 'exit':
                    break

                print("Geminiに問い合わせ中...")
                try:
                    # Gemini APIを呼び出す
                    model = genai.GenerativeModel(
                        'gemini-2.5-pro', 
                        tools=gemini_tools
                    )
                    response = await model.generate_content_async(user_input)
                    
                    # Geminiの応答からツール呼び出し(function_call)を探す
                    function_call = response.candidates[0].content.parts[0].function_call
                    
                    if function_call.name:
                        tool_name = function_call.name

                        # Geminiの引数形式(Struct)をPythonの辞書に変換
                        tool_input = {key: value for key, value in function_call.args.items()}
                        
                        print(f"Geminiがツール '{tool_name}' の使用を決定しました。")
                        print(f"引数: {tool_input}")
                        
                        # MCPサーバーにツール実行をリクエスト
                        result = await session.call_tool(tool_name, tool_input)
                        
                        if result.content and hasattr(result.content[0], 'text'):
                            tool_result_text = result.content[0].text
                            print(f"Blenderからの結果: {tool_result_text}")
                        else:
                            print(f"Blenderから予期せぬ結果: {result.content}")
                    else:
                        print(f"Geminiの応答: {response.text}")

                except Exception as e:
                    print(f"エラーが発生しました: {e}")

if __name__ == "__main__":
    print("Blenderを起動し、MCPアドオンが有効になっていることを確認してください...")
    asyncio.run(main())