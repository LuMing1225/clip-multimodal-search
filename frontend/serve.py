# -*- coding: utf-8 -*-
"""
CLIP 电商多模态检索系统 - 前端静态文件服务
用法: python serve.py  (默认 8525 端口)
"""
import http.server
import socketserver
import os
import sys

PORT = 8525
# 本脚本所在目录即为 frontend 根目录
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """带 UTF-8 编码与 MIME 修正的静态文件处理器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def end_headers(self):
        # 禁止缓存，便于演示时即时看到改动
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def guess_type(self, path):
        mimetype = super().guess_type(path)
        # 强制常见前端资源的 MIME，避免 Windows 注册表异常导致 js/css 解析失败
        if path.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        if path.endswith(".json"):
            return "application/json; charset=utf-8"
        if path.endswith(".svg"):
            return "image/svg+xml"
        return mimetype

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        sys.stdout.write("[serve] %s - %s\n" % (self.address_string(), fmt % args))


def main():
    # 允许端口复用，避免 Ctrl+C 后端口占用
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), SPAHandler) as httpd:
        print("=" * 56)
        print(" CLIP 电商多模态检索系统 - 前端服务已启动")
        print(" 访问地址:  http://localhost:%d" % PORT)
        print(" 资源目录:  %s" % ROOT_DIR)
        print(" 后端API:   http://localhost:8565")
        print(" 按 Ctrl+C 停止服务")
        print("=" * 56)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] 服务已停止。")


if __name__ == "__main__":
    main()
