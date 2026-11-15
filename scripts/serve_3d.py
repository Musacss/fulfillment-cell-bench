#!/usr/bin/env python3
"""Read-only local HTTP + CORS static bridge for Musa's 3D Warehouse Showcase."""

import argparse
from collections.abc import Sequence
import errno
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]

_MIME_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".ndjson": "application/x-ndjson; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _content_type_for(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _is_ascii_digits(s: str) -> bool:
    return bool(s) and s.isascii() and s.isdigit()


def _parse_bounded_ascii_int(s: str, cap: int = 10**20) -> int | None:
    if not _is_ascii_digits(s):
        return None
    norm = s.lstrip("0") or "0"
    return cap if len(norm) > 20 else int(norm, 10)


def _validate_url_segments(raw_target: str) -> tuple[int, list[str] | None, str]:
    if "\x00" in raw_target or "\\" in raw_target:
        return 403, None, "Invalid characters in request target"
    if raw_target.startswith("//"):
        return 403, None, "Ambiguous double-slash request target forbidden"
    try:
        split = urllib.parse.urlsplit(raw_target)
    except ValueError:
        return 400, None, "Malformed request URI"
    if split.scheme or split.netloc:
        return 400, None, "Relative request path required"
    decoded = urllib.parse.unquote(split.path)
    if "\x00" in decoded or "\\" in decoded or not decoded.startswith("/"):
        return 403, None, "Forbidden request path"
    segments = decoded.split("/")[1:]
    if any(seg in (".", "..") for seg in segments):
        return 403, None, "Path traversal forbidden"
    if not segments or any(seg == "" for seg in segments):
        return 403, None, "Directory listing is disabled; fetch /index.json"
    return 200, segments, ""


def _open_safe_file(root_dir: Path, raw_target: str) -> tuple[int, int | None, Path | None, str]:
    status, segments, err = _validate_url_segments(raw_target)
    if status != 200 or segments is None:
        return status, None, None, err

    current = root_dir
    for seg in segments:
        candidate = current / seg
        if candidate.is_symlink():
            return 403, None, None, "Symlinks are forbidden"
        current = candidate

    try:
        resolved = current.resolve(strict=False)
    except OSError:
        return 403, None, None, "Unresolvable path"
    if not resolved.is_relative_to(root_dir) or resolved == root_dir:
        return 403, None, None, "Path escapes serve root"

    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(resolved, flags)
    except IsADirectoryError:
        return 403, None, None, "Directory listing is disabled"
    except (FileNotFoundError, NotADirectoryError):
        return 404, None, None, "File not found"
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EACCES, errno.EPERM, errno.EISDIR):
            return 403, None, None, "Forbidden file"
        return 404, None, None, "File unavailable"

    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode):
            os.close(fd)
            return 403, None, None, "Not a regular file"
    except OSError:
        os.close(fd)
        return 403, None, None, "Unreadable file metadata"

    return 200, fd, resolved, ""


_MAX_DRAIN_BYTES = 2_097_152
_DRAIN_CHUNK_BYTES = 65_536


def _parse_byte_range(range_header: str, total_len: int) -> tuple[str, int, int]:
    spec_full = range_header.strip()
    if not spec_full.lower().startswith("bytes="):
        return ("none", 0, total_len - 1)
    spec = spec_full[6:].strip()
    if total_len <= 0 or "," in spec or "-" not in spec:
        return ("unsatisfiable", 0, 0)
    start_str, end_str = spec.split("-", 1)
    start_str = start_str.strip()
    end_str = end_str.strip()
    if start_str == "":
        suffix = _parse_bounded_ascii_int(end_str)
        if suffix is None or suffix <= 0:
            return ("unsatisfiable", 0, 0)
        start = max(0, total_len - suffix)
        end = total_len - 1
        return ("partial", start, end)
    start = _parse_bounded_ascii_int(start_str)
    if start is None or start >= total_len:
        return ("unsatisfiable", 0, 0)
    if end_str == "":
        return ("partial", start, total_len - 1)
    end = _parse_bounded_ascii_int(end_str)
    if end is None or start > end:
        return ("unsatisfiable", 0, 0)
    return ("partial", start, min(end, total_len - 1))


class PackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    root_dir: Path
    quiet: bool = False
    sync_once: bool = False

    def process_request(self, request: Any, client_address: Any) -> None:
        if self.sync_once:
            HTTPServer.process_request(self, request, client_address)
        else:
            super().process_request(request, client_address)


class PackRequestHandler(BaseHTTPRequestHandler):
    server_version = "FulfillmentCell3DBridge/1.0"
    protocol_version = "HTTP/1.1"
    default_request_version = "HTTP/1.1"
    timeout = 5.0

    def log_message(self, fmt: str, *args: Any) -> None:
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    def finish(self) -> None:
        try:
            super().finish()
        except (TimeoutError, ConnectionError, OSError):
            pass

    def _send_common_headers(self) -> None:
        if getattr(self, "_common_headers_sent", False):
            return
        self._common_headers_sent = True
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header(
            "Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def end_headers(self) -> None:
        self._send_common_headers()
        super().end_headers()

    def _drain_unread_socket(
        self,
        *,
        deadline_sec: float = 0.15,
        recv_timeout: float = 0.02,
        stop_on_double_crlf: bool = True,
    ) -> None:
        drained = 0
        deadline = time.monotonic() + deadline_sec
        prev_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(0.0)
            try:
                buffered = bytes(self.rfile.peek(1)) if hasattr(self.rfile, "peek") else b""
            except (BlockingIOError, TimeoutError, OSError):
                buffered = b""
            seen = bytes(getattr(self, "raw_requestline", b"")) + buffered
            already_terminated = stop_on_double_crlf and (b"\r\n\r\n" in seen)
            tail = seen[-4:]
            if already_terminated:
                while drained < _MAX_DRAIN_BYTES:
                    chunk = self.connection.recv(min(_DRAIN_CHUNK_BYTES, _MAX_DRAIN_BYTES - drained))
                    if not chunk:
                        break
                    drained += len(chunk)
            else:
                while drained < _MAX_DRAIN_BYTES:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        break
                    self.connection.settimeout(min(recv_timeout, rem))
                    chunk = self.connection.recv(min(_DRAIN_CHUNK_BYTES, _MAX_DRAIN_BYTES - drained))
                    if not chunk:
                        break
                    drained += len(chunk)
                    if stop_on_double_crlf and b"\r\n\r\n" in (tail + chunk):
                        break
                    tail = (tail + chunk)[-4:]
        except (BlockingIOError, TimeoutError, OSError):
            pass
        finally:
            try:
                self.connection.settimeout(prev_timeout)
            except OSError:
                pass

    def parse_request(self) -> bool:
        if not super().parse_request():
            self.close_connection = True
            if not getattr(self, "_common_headers_sent", False):
                self.request_version = "HTTP/1.1"
                self._send_json_error(400, "Bad Request")
            return False
        if self.request_version == "HTTP/0.9" or len(self.requestline.split()) < 3:
            self.request_version = "HTTP/1.1"
            self.close_connection = True
            self._send_json_error(400, "HTTP/0.9 is not supported")
            return False
        return True

    def _send_json_error(
        self, status: int, message: str, *, extra_headers: dict[str, str] | None = None
    ) -> None:
        self._drain_request_body()
        self.close_connection = True
        body = (json.dumps({"error": message}) + "\n").encode("utf-8")
        try:
            self.send_response(status)
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if getattr(self, "command", "GET") != "HEAD":
                self.wfile.write(body)
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def _drain_request_body(self) -> None:
        if getattr(self, "_body_drained", False):
            return
        self._body_drained = True
        headers = getattr(self, "headers", None)
        if headers is None:
            return
        raw_len = headers.get("Content-Length")
        if not raw_len:
            if headers.get("Transfer-Encoding"):
                self.close_connection = True
            return
        length = _parse_bounded_ascii_int(raw_len.strip())
        if length is None:
            self.close_connection = True
            return
        if length <= 0:
            return
        if length > _MAX_DRAIN_BYTES:
            self.close_connection = True
            return
        remaining = length
        deadline = time.monotonic() + 0.5
        prev_timeout = self.connection.gettimeout()
        read_fn = self.rfile.read1 if hasattr(self.rfile, "read1") else self.rfile.read
        try:
            while remaining > 0:
                rem_time = deadline - time.monotonic()
                if rem_time <= 0:
                    self.close_connection = True
                    break
                self.connection.settimeout(rem_time)
                chunk = read_fn(min(remaining, _DRAIN_CHUNK_BYTES))
                if not chunk:
                    self.close_connection = True
                    break
                remaining -= len(chunk)
        except (TimeoutError, OSError):
            self.close_connection = True
        finally:
            try:
                self.connection.settimeout(prev_timeout)
            except OSError:
                pass
        if remaining > 0:
            self.close_connection = True

    def handle_one_request(self) -> None:
        self._common_headers_sent = False
        self._body_drained = False
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self._drain_unread_socket(
                    deadline_sec=0.15, recv_timeout=0.02, stop_on_double_crlf=True
                )
                self.requestline = ""
                self.request_version = "HTTP/1.1"
                self.command = ""
                self._body_drained = True
                self._send_json_error(414, "Request-URI Too Long")
                self.wfile.flush()
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            stripped_line = self.raw_requestline.strip()
            if not stripped_line or len(stripped_line.split()) < 3:
                self._drain_unread_socket(
                    deadline_sec=0.02, recv_timeout=0.01, stop_on_double_crlf=True
                )
                self.requestline = self.raw_requestline.rstrip(b"\r\n").decode("iso-8859-1")
                self.request_version = "HTTP/1.1"
                self.command = ""
                self.close_connection = True
                self._body_drained = True
                self._send_json_error(400, "Bad Request")
                self.wfile.flush()
                return
            if not self.parse_request():
                self.wfile.flush()
                return
            if self.command == "GET":
                self.do_GET()
            elif self.command == "HEAD":
                self.do_HEAD()
            elif self.command == "OPTIONS":
                self.do_OPTIONS()
            else:
                self._drain_request_body()
                self._send_json_error(
                    405,
                    "Method Not Allowed",
                    extra_headers={"Allow": "GET, HEAD, OPTIONS"},
                )
            self.wfile.flush()
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def _raw_request_target(self) -> str:
        words = self.requestline.split()
        if len(words) >= 2:
            return words[1]
        return self.path

    def do_OPTIONS(self) -> None:
        target = self._raw_request_target()
        if target != "*":
            if "\x00" in target or "\\" in target or target.startswith("//"):
                self._send_json_error(403, "Invalid characters in request target")
                return
            try:
                split = urllib.parse.urlsplit(target)
            except ValueError:
                self._send_json_error(400, "Malformed request URI")
                return
            if split.scheme or split.netloc or not split.path.startswith("/"):
                self._send_json_error(400, "Relative request path required")
                return
            decoded = urllib.parse.unquote(split.path)
            if not decoded.startswith("/"):
                self._send_json_error(400, "Relative request path required")
                return
            if "\x00" in decoded or "\\" in decoded or ".." in decoded.split("/"):
                self._send_json_error(403, "Path traversal forbidden")
                return
        self.close_connection = True
        try:
            self.send_response(204)
            self.send_header("Connection", "close")
            self.send_header("Allow", "GET, HEAD, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def _serve_file(self, *, send_body: bool) -> None:
        root_dir: Path = self.server.root_dir  # type: ignore[attr-defined]
        status, fd, resolved, err = _open_safe_file(root_dir, self._raw_request_target())
        if status != 200 or fd is None or resolved is None:
            self._send_json_error(status, err)
            return

        try:
            with os.fdopen(fd, "rb") as handle:
                data = handle.read()
        except OSError:
            self._send_json_error(404, "Unable to read file")
            return

        total_len = len(data)
        content_type = _content_type_for(resolved)
        range_hdr = self.headers.get("Range")

        try:
            if range_hdr is not None:
                mode, start, end = _parse_byte_range(range_hdr, total_len)
                if mode == "unsatisfiable":
                    self.close_connection = True
                    self.send_response(416)
                    self.send_header("Connection", "close")
                    self.send_header("Content-Range", f"bytes */{total_len}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if mode == "partial":
                    chunk = data[start : end + 1]
                    self.close_connection = True
                    self.send_response(206)
                    self.send_header("Connection", "close")
                    self.send_header("Content-Type", content_type)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_len}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    if send_body:
                        self.wfile.write(chunk)
                    return

            self.close_connection = True
            self.send_response(200)
            self.send_header("Connection", "close")
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total_len))
            self.end_headers()
            if send_body:
                self.wfile.write(data)
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def do_GET(self) -> None:
        self._serve_file(send_body=True)

    def do_HEAD(self) -> None:
        self._serve_file(send_body=False)


def create_server(
    directory: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    quiet: bool = False,
) -> PackHTTPServer:
    """Create a bound read-only CORS HTTP server rooted strictly at directory."""
    raw_dir = Path(directory)
    if raw_dir.is_symlink():
        raise ValueError(f"Refusing symlinked serve directory: {raw_dir}")
    if not raw_dir.exists() or not raw_dir.is_dir():
        raise FileNotFoundError(f"Serve directory does not exist or is not a directory: {raw_dir}")
    if type(port) is not int or not (0 <= port <= 65535):
        raise ValueError(f"Port must be an integer in 0..65535, got {port!r}")
    resolved_root = raw_dir.resolve(strict=True)
    server = PackHTTPServer((host, port), PackRequestHandler)
    server.root_dir = resolved_root
    server.quiet = quiet
    return server


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        type=Path,
        default=ROOT / "artifacts" / "3d-pack",
        help="Exported 3D pack directory to serve read-only",
    )
    ap.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1)",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port (default: 8765; use 0 for ephemeral OS port)",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="Handle a single HTTP request synchronously and exit 0",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        server = create_server(args.dir, host=args.host, port=args.port, quiet=False)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
        return 2

    server.sync_once = bool(args.once)
    bound_host, bound_port = server.server_address[:2]
    print(
        f"Serving 3D pack from {server.root_dir} at http://{bound_host}:{bound_port}/",
        flush=True,
    )
    try:
        if args.once:
            server.handle_request()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
