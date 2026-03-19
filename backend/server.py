import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from cloud_sync import CloudSyncManager
from file_analyzer import FileAnalyzer


class RequestHandler(BaseHTTPRequestHandler):
    analyzer = None
    cloud_sync_manager = None
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

    @classmethod
    def get_cloud_sync_manager(cls):
        if cls.cloud_sync_manager is not None:
            return cls.cloud_sync_manager, None

        try:
            cls.cloud_sync_manager = CloudSyncManager()
            return cls.cloud_sync_manager, None
        except Exception as exc:
            return None, str(exc)

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode("utf-8"))
        analyzer, analyzer_error = self.get_analyzer()
        cloud_sync_manager, cloud_sync_error = self.get_cloud_sync_manager()

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
            mode = data.get("mode")
            target_root_path = data.get("target_root_path")
            user_requests = data.get("user_requests")
            result = analyzer.analyze_folder(
                folder_path,
                mode=mode,
                target_root_path=target_root_path,
                user_requests=user_requests,
            )
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
            mode = data.get("mode")
            target_root_path = data.get("target_root_path")
            result = analyzer.execute_plan(
                folder_path,
                operations,
                write_readme=write_readme,
                mode=mode,
                target_root_path=target_root_path,
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

        if self.path == "/cloud/status":
            if cloud_sync_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": cloud_sync_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            result = cloud_sync_manager.get_status()
            self._set_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/cloud/upload":
            if cloud_sync_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": cloud_sync_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            folder_path = data.get("folder_path")
            remote_path = data.get("remote_path")
            try:
                result = cloud_sync_manager.upload_folder(folder_path, remote_path)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            self._set_headers(200 if result.get("success") else 400)
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/cloud/schedule":
            if cloud_sync_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": cloud_sync_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            folder_path = data.get("folder_path")
            remote_path = data.get("remote_path")
            cron_expression = data.get("cron_expression")
            daily_time = data.get("daily_time")
            timezone = data.get("timezone")
            try:
                result = cloud_sync_manager.create_schedule(
                    folder_path,
                    remote_path,
                    cron_expression,
                    daily_time=daily_time,
                    timezone=timezone,
                )
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            self._set_headers(200 if result.get("success") else 400)
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/cloud/schedule/remove":
            if cloud_sync_error:
                self._set_headers(500)
                self.wfile.write(
                    json.dumps(
                        {"success": False, "error": cloud_sync_error},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            job_id = data.get("job_id")
            try:
                result = cloud_sync_manager.remove_schedule(job_id)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            self._set_headers(200 if result.get("success") else 400)
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
