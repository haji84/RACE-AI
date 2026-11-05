"""Loopback UI and lifecycle owner of the selected existing automation plane.

Only the server-owned service chooses inputs, source uses, clocks and storage.
The browser requests a sport/stage; exact native forecasts remain in the private
journal. This transport never grants source rights or authenticates a freeze.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
from urllib.parse import parse_qsl, urlsplit

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/forecast-audit-model.js": ("forecast-audit-model.js", "text/javascript; charset=utf-8"),
    "/product-data.js": ("product-data.js", "text/javascript; charset=utf-8"),
    "/existing-model-catalog.js": ("existing-model-catalog.js", "text/javascript; charset=utf-8"),
    "/ui-model.js": ("ui-model.js", "text/javascript; charset=utf-8"),
    "/data/example-synthetic-forecast-audit.json": (
        "data/example-synthetic-forecast-audit.json", "application/json; charset=utf-8"),
}
SPORTS = frozenset(("boat", "keirin", "autorace", "horse"))
STAGES = frozenset(("P0", "P1", "A_PRE_TRIAL", "B_POST_TRIAL"))
CAPABILITY = b'<meta name="race-ai-generation-api" content="/api/forecast">'
MAX_REQUEST = 1024
MAX_STATIC = 4 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024

ERRORS = {
    "LOCAL_REQUEST_REQUIRED": (403, "この端末の予想画面から操作してください。"),
    "INVALID_REQUEST": (400, "競技と予想時点を選び直してください。"),
    "REQUEST_TOO_LARGE": (413, "リクエストが上限を超えています。"),
    "JSON_REQUIRED": (415, "JSON形式で操作してください。"),
    "NOT_FOUND": (404, "この画面または取得経路はありません。"),
    "METHOD_NOT_ALLOWED": (405, "予想生成ボタンから操作してください。"),
    "SOURCE_PERMISSION_REQUIRED": (403, "取得元の解析・私有保存の利用条件を確認してください。"),
    "SOURCE_TIMEOUT": (504, "入力の取得が時間内に完了しませんでした。取得状態を確認してください。"),
    "GENERATION_INPUT_UNAVAILABLE": (422, "対象レース・予想時点・必要な実入力を確認してください。"),
    "PRIVATE_STORAGE_UNAVAILABLE": (503, "私有保存先または入力の取得経路を確認してください。"),
    "GENERATION_UNAVAILABLE": (503, "予想生成を完了できませんでした。入力と保存の状態を確認してください。"),
    "AUTOMATIC_MANAGED": (409, "自動巡回が予想を管理しています。保存された予想と稼働状態を確認してください。"),
}


def _asset_bytes(root, relative):
    """Read fixed assets through no-follow descriptors, never arbitrary paths."""
    if os.name != "posix" or not root.is_absolute() or ".." in root.parts:
        raise OSError("invalid static root")
    fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        components = list(root.parts[1:]) + relative.split("/")
        for component in components[:-1]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        source = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(source, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_STATIC:
                raise OSError("invalid static asset")
            body = stream.read(MAX_STATIC + 1)
            if len(body) > MAX_STATIC:
                raise OSError("oversized static asset")
            return body
    finally:
        os.close(fd)


class ForecastHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, service, *, port, web_root, automatic=None):
        self.service = service
        self.nonce = secrets.token_urlsafe(32)
        self.web_root = web_root
        self.automation = None
        self._lifecycle_lock = threading.Lock()
        self._automation_started = False
        self._automation_stopped = False
        self._serving = False
        self._closed = False
        super().__init__(("127.0.0.1", port), ForecastHandler)
        self.origin = "http://127.0.0.1:" + str(self.server_port)
        self.expected_host = "127.0.0.1:" + str(self.server_port)
        try:
            if automatic is None and getattr(service, "automatic_supported", False) is True:
                from .local_forecast_automation import ForecastAutomation
                automatic = ForecastAutomation(service)
            if automatic is not None and automatic is not False:
                if not all(callable(getattr(automatic, key, None)) for key in ("start", "stop", "status")):
                    raise ValueError("automatic lifecycle required")
                self.automation = automatic
                service.automation = automatic
        except BaseException:
            super().server_close()
            raise

    def _stop_automatic(self):
        with self._lifecycle_lock:
            stop = self.automation is not None and not self._automation_stopped
            self._automation_stopped = True
        if stop:
            self.automation.stop()

    def serve_forever(self, poll_interval=0.5):
        try:
            with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError("local server already closed")
                self._serving = True
                start = self.automation is not None and not self._automation_started
                self._automation_started = True
                # Serialize start with close/stop. Otherwise close could stop
                # an unstarted controller just before start spawns its worker.
                if start:
                    self.automation.start()
            return super().serve_forever(poll_interval=poll_interval)
        finally:
            with self._lifecycle_lock:
                self._serving = False
            self._stop_automatic()

    def shutdown(self):
        try:
            with self._lifecycle_lock:
                serving = self._serving
            if serving:
                super().shutdown()
        finally:
            self._stop_automatic()

    def server_close(self):
        with self._lifecycle_lock:
            self._closed = True
        try:
            self._stop_automatic()
        finally:
            super().server_close()


class ForecastHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "RACE-AI-local"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        # Race IDs, payloads, private paths and source errors never go to logs.
        pass

    def _reply(self, status, body, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, document):
        try:
            body = json.dumps(document, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_RESPONSE:
                raise ValueError("response bound")
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._error("GENERATION_UNAVAILABLE")
            return
        self._reply(status, body)

    def _error(self, code):
        status, message = ERRORS[code]
        # The finite fixed error table prevents source or exception text leaks.
        self._reply(status, json.dumps({"error": {"code": code, "message": message}},
            ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _local(self, *, mutation=False):
        try:
            local = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local = False
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if (not local or hosts != [self.server.expected_host] or
                len(origins) > 1 or origins and origins[0] != self.server.origin):
            self._error("LOCAL_REQUEST_REQUIRED")
            return False
        if mutation:
            nonces = self.headers.get_all("X-Race-AI-Nonce", [])
            try:
                allowed = (origins == [self.server.origin] and len(nonces) == 1 and
                           hmac.compare_digest(nonces[0].encode("ascii"), self.server.nonce.encode("ascii")))
            except UnicodeEncodeError:
                allowed = False
            if not allowed:
                self._error("LOCAL_REQUEST_REQUIRED")
                return False
        return True

    def _service_failure(self, error):
        if isinstance(error, PermissionError): code = "SOURCE_PERMISSION_REQUIRED"
        elif isinstance(error, TimeoutError): code = "SOURCE_TIMEOUT"
        elif isinstance(error, ValueError): code = "GENERATION_INPUT_UNAVAILABLE"
        elif isinstance(error, OSError): code = "PRIVATE_STORAGE_UNAVAILABLE"
        else: code = "GENERATION_UNAVAILABLE"
        self._error(code)

    def do_GET(self):
        if not self._local():
            return
        if self.path == "/api/forecast/status":
            try:
                value = self.server.service.status()
                if type(value) is not dict:
                    raise ValueError("invalid service status")
                if self.server.automation is not None:
                    value = {**value, "auto": self.server.automation.status()}
                self._json(200, {**value, "nonce": self.server.nonce})
            except Exception as error:
                self._service_failure(error)
            return
        if self.path.partition("?")[0] == "/api/forecast/latest":
            try:
                target = urlsplit(self.path)
                pairs = parse_qsl(target.query, keep_blank_values=True,
                                  strict_parsing=True, max_num_fields=2)
                query = dict(pairs)
                if (target.scheme or target.netloc or target.fragment or len(pairs) != 2 or
                        len(query) != 2 or set(query) != {"sport", "stage"} or
                        query["sport"] not in SPORTS or query["stage"] not in STAGES):
                    raise ValueError("display selection required")
            except (ValueError, TypeError):
                self._error("INVALID_REQUEST")
                return
            try:
                latest = self.server.service.latest(query["sport"], query["stage"])
                if type(latest) is not dict:
                    raise ValueError("invalid saved view")
                self._json(200, latest)
            except Exception as error:
                self._service_failure(error)
            return
        if self.path == "/api/forecast/generate":
            self._error("METHOD_NOT_ALLOWED")
            return
        if self.path == "/favicon.ico":
            self._reply(204, b"", "image/x-icon")
            return
        asset = ASSETS.get(self.path)
        if not asset:
            self._error("NOT_FOUND")
            return
        relative, content_type = asset
        try:
            body = _asset_bytes(self.server.web_root, relative)
            if relative == "index.html":
                if body.count(b"</head>") != 1:
                    raise OSError("index head missing")
                body = body.replace(b"</head>", CAPABILITY + b"\n</head>", 1)
            self._reply(200, body, content_type)
        except OSError:
            self._error("NOT_FOUND")

    def do_POST(self):
        if not self._local(mutation=True):
            return
        if self.path != "/api/forecast/generate":
            self._error("NOT_FOUND")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._error("JSON_REQUIRED")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get_all("Transfer-Encoding") or len(lengths) != 1 or
                not lengths[0].isascii() or not lengths[0].isdigit()):
            self._error("INVALID_REQUEST")
            return
        normalized = lengths[0].lstrip("0") or "0"
        if len(normalized) > len(str(MAX_REQUEST)) or int(normalized) > MAX_REQUEST:
            self._error("REQUEST_TOO_LARGE")
            return
        length = int(normalized)
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result
        try:
            if not length:
                raise ValueError("empty request")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
            if (type(value) is not dict or set(value) != {"sport", "stage"} or
                    type(value["sport"]) is not str or value["sport"] not in SPORTS or
                    type(value["stage"]) is not str or value["stage"] not in STAGES):
                raise ValueError("sport/stage request required")
        except (ValueError, UnicodeError, OSError):
            self._error("INVALID_REQUEST")
            return
        try:
            # A stopped bounded session remains automatic-owned. A browser
            # POST cannot bypass its stop condition or reset its frequency.
            if self.server.automation is not None:
                self._error("AUTOMATIC_MANAGED")
                return
            result = self.server.service.generate(value["sport"], value["stage"])
            if type(result) is not dict:
                raise ValueError("invalid service response")
            self._json(200, result)
        except Exception as error:
            self._service_failure(error)

    def _unsupported(self):
        if self._local():
            self._error("METHOD_NOT_ALLOWED")

    do_OPTIONS = do_PUT = do_DELETE = do_PATCH = do_HEAD = _unsupported


def make_server(service, *, port=0, web_root=None, automatic=None):
    """Bind loopback first; automation begins only when serving starts.

    ``automatic=False`` is the explicit legacy/testing escape hatch. It is
    deliberately not exposed as a browser request or CLI scheduling flag.
    """
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid local port")
    if not callable(getattr(service, "status", None)) or not callable(getattr(service, "generate", None)):
        raise ValueError("forecast service required")
    root = Path(web_root).absolute() if web_root is not None else Path(__file__).resolve().parents[1] / "web"
    return ForecastHTTPServer(service, port=port, web_root=root, automatic=automatic)


def main(argv=None):
    parser = argparse.ArgumentParser(description="RACE-AI: local forecast generation and private viewing")
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--automatic-mode", choices=("native", "github"), default="native")
    parser.add_argument("--supervisor-dir", type=Path)
    args = parser.parse_args(argv)
    if args.automatic_mode == "github" and args.supervisor_dir is None:
        parser.error("--supervisor-dir is required for --automatic-mode github")
    if args.automatic_mode == "native" and args.supervisor_dir is not None:
        parser.error("--supervisor-dir requires --automatic-mode github")
    try:
        from .local_forecast_service import LocalForecastService
        if args.automatic_mode == "github":
            from .github_continuous_supervisor import GitHubSupervisor
            from .workflow_live_projection import refresh_projection
            service = LocalForecastService(args.private_dir, workflow_projection_root=args.supervisor_dir)
            automatic = GitHubSupervisor(args.supervisor_dir, projection_refresh=refresh_projection)
            server = make_server(service, port=args.port, automatic=automatic)
        else:
            service = LocalForecastService(args.private_dir)
            server = make_server(service, port=args.port)
        with server as running:
            print("RACE-AI local forecast: " + running.origin, flush=True)
            try:
                running.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except (OSError, ValueError):
        print("LOCAL_FORECAST_START_FAILED: 私有保存先とローカルポートを確認してください。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
