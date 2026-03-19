import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from file_analyzer import FileAnalyzer


class RequestHandler(BaseHTTPRequestHandler):
    analyzer = None
    current_backup = None

    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    @classmethod
    def get_analyzer(cls):
        if cls.analyzer is not None:
            return cls.analyzer, None

        try:
            cls.analyzer = FileAnalyzer()
            return cls.analyzer, None
        except Exception as exc:
            return None, str(exc)

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode("utf-8"))
        analyzer, analyzer_error = self.get_analyzer()

        if self.path == "/analyze":
            if analyzer_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": analyzer_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            folder_path = data.get("folder_path")
            result = analyzer.analyze_folder(folder_path)
            self._set_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/execute":
            if analyzer_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": analyzer_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            folder_path = data.get("folder_path")
            operations = data.get("operations")
            write_readme = bool(data.get("write_readme"))
            result = analyzer.execute_plan(
                folder_path,
                operations,
                write_readme=write_readme,
            )
            if result.get("success"):
                previous_backup = RequestHandler.current_backup or []
                current_backup = result.get("backup_info") or []
                RequestHandler.current_backup = previous_backup + current_backup

            self._set_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/rollback":
            if analyzer_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": analyzer_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            if RequestHandler.current_backup:
                result = analyzer.rollback(RequestHandler.current_backup)
                if result.get("success"):
                    RequestHandler.current_backup = None
            else:
                result = {"success": False, "error": "没有可回退的操作"}

            self._set_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(
            json.dumps(
                {"success": False, "error": f"Unknown path: {self.path}"},
                ensure_ascii=False,
            ).encode("utf-8")
        )

    def log_message(self, format, *args):
        print(f"[Server] {format % args}")


def run_server(port=8765):
    server_address = ("", port)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"Python backend server is running on port {port}...")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
