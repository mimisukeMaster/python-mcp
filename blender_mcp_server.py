# mcp_blender_server.py (最終修正版)

bl_info = {
    "name": "MCP Command Server",
    "author": "You",
    "version": (3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MCP Tab",
    "description": "Receives and executes commands synchronously from an MCP server.",
    "category": "Development",
}

import bpy
import socketserver
import threading
import json
import queue
from bpy.app.handlers import persistent

# メインスレッドで実行するコマンドと、結果を返すためのキューを保持する
command_queue = queue.Queue()

def execute_commands_from_queue():
    """キューに溜まったコマンドをBlenderのメインスレッドで実行し、結果を返す"""
    while not command_queue.empty():
        # コマンドと、結果を返すためのレスポンスキューを取り出す
        command, response_queue = command_queue.get_nowait()
        response = {}
        try:
            operator_path = command.get("operator")
            params = command.get("params", {})
            
            if not operator_path:
                raise ValueError("'operator' key is missing.")

            op_module, op_name = operator_path.rsplit('.', 1)
            op_module_obj = getattr(bpy.ops, op_module)
            operator_func = getattr(op_module_obj, op_name)
            
            print(f"Executing: bpy.ops.{operator_path}(**{params})")
            result = operator_func('INVOKE_DEFAULT', True, **params)
            
            # 正常に終了した場合
            if 'FINISHED' in result:
                response = {"status": "OK", "message": f"Executed '{operator_path}' successfully."}
            else:
                response = {"status": "ERROR", "message": f"Operator '{operator_path}' did not finish."}
            
        except Exception as e:
            print(f"Error executing command: {e}")
            response = {"status": "ERROR", "message": str(e)}
        
        # ネットワークスレッドが待っているレスポンスキューに結果を入れる
        response_queue.put(response)
        
    return 0.1

class BlenderCommHandler(socketserver.BaseRequestHandler):
    """ネットワークからのリクエストを同期的に処理するハンドラ"""
    def handle(self):
        try:
            data = self.request.recv(4096).strip()
            command = json.loads(data.decode('utf-8'))
            
            # 応答を待つための専用キューを作成
            response_queue = queue.Queue()
            # メインスレッドに、コマンドとこの応答用キューを渡す
            command_queue.put((command, response_queue))
            
            # メインスレッドからの応答がキューに入るまで、ここで待機する（タイムアウト付き）
            response = response_queue.get(timeout=10.0)
            
            # 受け取った応答をクライアント（MCPサーバー）に送信
            self.request.sendall(json.dumps(response).encode('utf-8'))
            
        except queue.Empty:
            print("Error: Timed out waiting for Blender main thread response.")
            response = {"status": "ERROR", "message": "Blender process timed out."}
            self.request.sendall(json.dumps(response).encode('utf-8'))
        except Exception as e:
            print(f"Error in request handler: {e}")
            response = {"status": "ERROR", "message": str(e)}
            self.request.sendall(json.dumps(response).encode('utf-8'))

# --- 以下、UIとサーバー起動/停止のコード (変更なし) ---
class BlenderTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
server_thread = None
tcp_server = None
def start_server():
    global tcp_server, server_thread
    if server_thread and server_thread.is_alive(): return
    HOST, PORT = "localhost", 65432
    tcp_server = BlenderTCPServer((HOST, PORT), BlenderCommHandler)
    server_thread = threading.Thread(target=tcp_server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    print(f"MCP Blender Server started on {HOST}:{PORT}")
def stop_server():
    global tcp_server
    if tcp_server:
        print("Shutting down MCP Blender Server.")
        tcp_server.shutdown()
        tcp_server.server_close()
        tcp_server = None
class MCP_PT_Panel(bpy.types.Panel):
    bl_label, bl_idname, bl_space_type, bl_region_type, bl_category = "MCP Server", "MCP_PT_panel", 'VIEW_3D', 'UI', 'MCP'
    def draw(self, context):
        self.layout.operator("mcp.start_server" if not tcp_server else "mcp.stop_server", text="Start Server" if not tcp_server else "Stop Server")
class MCP_OT_StartServer(bpy.types.Operator):
    bl_idname, bl_label = "mcp.start_server", "Start MCP Server"
    def execute(self, context):
        start_server(); return {'FINISHED'}
class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname, bl_label = "mcp.stop_server", "Stop MCP Server"
    def execute(self, context):
        stop_server(); return {'FINISHED'}
@persistent
def load_handler(dummy):
    start_server()
classes = (MCP_PT_Panel, MCP_OT_StartServer, MCP_OT_StopServer)
def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.app.timers.register(execute_commands_from_queue, first_interval=1.0)
    bpy.app.handlers.load_post.append(load_handler)
    start_server()
def unregister():
    stop_server()
    bpy.app.handlers.load_post.remove(load_handler)
    bpy.app.timers.unregister(execute_commands_from_queue)
    for cls in reversed(classes): bpy.utils.unregister_class(cls)