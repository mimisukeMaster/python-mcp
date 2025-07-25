import sys
import logging
import socket
import json
from mcp.server.fastmcp import FastMCP

# ログ設定: デバッグ情報は標準エラー出力(stderr)へ出力します
# これにより、Claude for Desktopのログファイルに記録されます
logging.basicConfig(
    level=logging.INFO, 
    stream=sys.stderr, 
    format='[%(asctime)s][SERVER] %(message)s'
)

# FastMCPサーバーを初期化します
# "my-python-server" の部分は、config.jsonで設定したサーバー名と合わせると分かりやすいです
mcp = FastMCP("my-python-server")

@mcp.tool()
def greet(name: str) -> str:
    """
    指定された名前で挨拶を返します。
    
    Args:
        name: 挨拶する相手の名前
    """
    logging.info(f"greetツールが引数 '{name}' で実行されました。")
    return f"こんにちは、{name}さん！"


def send_to_blender(payload: dict) -> str:
    """BlenderのサーバーにJSON形式でコマンドを送信するヘルパー関数"""
    HOST, PORT = "localhost", 65432
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(json.dumps(payload).encode('utf-8'))
            response_data = s.recv(1024)
            response = json.loads(response_data.decode('utf-8'))
            return response.get("message", "Blenderから予期せぬ応答がありました。")
    except ConnectionRefusedError:
        return "Blenderへの接続に失敗しました。Blenderが起動しているか、MCPアドオンが有効になっているか確認してください。"
    except Exception as e:
        return f"Blenderとの通信中に予期せぬエラーが発生しました: {e}"

@mcp.tool()
def execute_blender_operator(operator: str, params_json: str = '{}') -> str:
    """
    Blenderの任意のオペレーター(bpy.ops)を、指定されたパラメータで実行します。
    
    Args:
        operator: 実行したいオペレーターのパス。例: 'mesh.primitive_cube_add', 'transform.rotate'
        params_json: オペレーターに渡す引数をJSON形式の文字列で指定します。例: '{"size": 2, "location": [1, 2, 3]}', '{"value": 1.5708, "orient_axis": "Z"}'
    """
    logging.info(f"Executing Blender operator: {operator} with params: {params_json}")
    try:
        # JSON文字列をPythonの辞書に変換
        params = json.loads(params_json)
    except json.JSONDecodeError:
        return "エラー: params_jsonの形式が正しくありません。有効なJSON文字列を指定してください。"
    
    # Blenderに送信するコマンドを作成
    command = {"operator": operator, "params": params}
    return send_to_blender(command)

if __name__ == "__main__":
    mcp.run()