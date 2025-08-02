# minimal_server.py

import sys
import logging
from mcp.server.fastmcp import FastMCP

# ログ設定
logging.basicConfig(
    level=logging.INFO, 
    stream=sys.stderr, 
    format='[MINIMAL-SERVER] %(message)s'
)

# FastMCPサーバーを初期化
mcp = FastMCP("minimal-python-server")

@mcp.tool()
def test_tool(message: str) -> str:
    """
    接続テスト用のシンプルなツールです。
    """
    logging.info(f"test_toolが引数 '{message}' で実行されました。")
    return f"サーバーからの応答: {message}"

if __name__ == "__main__":
    logging.info("--- Minimal server process started, entering mcp.run() ---")
    mcp.run()
    logging.info("--- Minimal server process finished ---")