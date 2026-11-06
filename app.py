"""Local Sprite Foundry application and HTTP interface."""

import argparse
import base64
import binascii
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid
import webbrowser

from PIL import Image

from pipeline import (
    KINDS, MAX_EXPORT_ASSETS, MAX_IMAGE_BYTES, bounded_int, decode_image,
    export_pack, inspect_image, make_prompt, png_bytes, prepare_sprite, short_text,
    sprite_settings,
)


ROOT = Path(__file__).resolve().parent
MODEL = os.environ.get("SPRITE_FOUNDRY_IMAGE_MODEL", "gpt-image-2.5-flare")
ORIGIN = "http://127.0.0.1"
DEFAULT_PORT = 18764
PORTABLE_PORT = 18767
IMAGE_API = "https://api.openai.com/v1/images/generations"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Library:
    def __init__(self, location):
        location.mkdir(parents=True, exist_ok=True)
        self.path = location / "library.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL,
                    metadata TEXT NOT NULL, original BLOB NOT NULL, thumb BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, updated TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(state) WHERE state = 'running';
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def asset_row(self, content, name, source, *, asset_id=None, **detail):
        image = decode_image(content)
        qa = inspect_image(image)
        if qa["alpha"] == "empty":
            raise ValueError("图片没有可见像素。")
        asset_id = asset_id or uuid.uuid4().hex
        record = {"id": asset_id, "name": name, "source": source, "qa": qa, **detail}
        thumb = image.copy()
        thumb.thumbnail((260, 260), Image.Resampling.LANCZOS)
        return asset_id, now(), json.dumps(record, ensure_ascii=False), content, png_bytes(thumb)

    def add_assets(self, rows):
        with self.connect() as connection:
            connection.executemany("INSERT OR IGNORE INTO assets VALUES (?, ?, ?, ?, ?)", rows)

    def listing(self):
        with self.connect() as connection:
            assets = connection.execute("SELECT metadata FROM assets ORDER BY created DESC").fetchall()
            jobs = connection.execute("SELECT detail FROM jobs ORDER BY updated DESC LIMIT 8").fetchall()
        return {"assets": [json.loads(row[0]) for row in assets], "jobs": [json.loads(row[0]) for row in jobs]}

    def get_asset(self, asset_id, thumbnail=False):
        column = "thumb" if thumbnail else "original"
        with self.connect() as connection:
            row = connection.execute(f"SELECT metadata, {column} FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise ValueError("找不到素材。")
        return json.loads(row[0]), row[1]

    def start_job(self, detail):
        with self.connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?)",
                    (detail["id"], detail["state"], now(), json.dumps(detail, ensure_ascii=False)),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("已有生成任务在执行。") from error

    def update_job(self, detail, rows=()):
        with self.connect() as connection:
            connection.executemany("INSERT INTO assets VALUES (?, ?, ?, ?, ?)", rows)
            connection.execute(
                "UPDATE jobs SET state = ?, updated = ?, detail = ? WHERE id = ?",
                (detail["state"], now(), json.dumps(detail, ensure_ascii=False), detail["id"]),
            )

    def recover_jobs(self):
        with self.connect() as connection:
            pending = connection.execute("SELECT detail FROM jobs WHERE state = 'running'").fetchall()
        for row in pending:
            detail = json.loads(row[0])
            detail.update(state="interrupted", message="工作台重启。已收到的候选仍可使用。")
            self.update_job(detail)


def generate_images(key, prompt, quality, count):
    payload = {
        "model": MODEL, "prompt": prompt, "quality": quality, "n": count,
        "background": "transparent", "size": "1024x1024", "output_format": "png",
    }
    request = Request(
        IMAGE_API, json.dumps(payload).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=240) as response:
            body = response.read(64 * 1024 * 1024 + 1)
            if len(body) > 64 * 1024 * 1024:
                raise ValueError("图像服务返回的数据太大，请减少候选数量。")
            data = json.loads(body)["data"]
            if len(data) != count:
                raise ValueError(f"图像服务返回 {len(data)} 张，预期 {count} 张。")
            return [base64.b64decode(item["b64_json"], validate=True) for item in data]
    except HTTPError as error:
        try:
            api_code = json.loads(error.read(8192)).get("error", {}).get("code")
        except (ValueError, AttributeError):
            api_code = None
        notes = {400: "检查提示词或模型参数", 401: "检查 API 密钥", 403: "检查模型权限", 429: "检查额度或频率限制"}
        safe_code = api_code if isinstance(api_code, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,64}", api_code) else ""
        suffix = f" · {safe_code}" if safe_code else ""
        raise ValueError(f"图像服务 HTTP {error.code}{suffix}。{notes.get(error.code, '可以稍后手动重试')}。") from error
    except (URLError, TimeoutError) as error:
        raise ValueError("连接图像服务失败或超时。请检查网络和 API 请求记录。") from error
    except (KeyError, TypeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValueError("图像服务返回了无法读取的数据。") from error


def generation_spec(values):
    kind = values.get("kind")
    quality = values.get("quality", "medium")
    if not isinstance(kind, str) or kind not in KINDS or quality not in ("low", "medium", "high"):
        raise ValueError("选择有效的素材类型与质量。")
    count = bounded_int(values, "variants", 1, 1, 3)
    style = short_text(values, "style", 1500)
    entries = values.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8 or len(entries) * count > 12:
        raise ValueError("每批 1–8 个主题，最多 12 张候选。")
    specs = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("每个主题需要名称和描述。")
        name = short_text(entry, "name", 80, required=True)
        subject = short_text(entry, "subject", 500, required=True)
        specs.append((name, make_prompt(subject, kind, style)))
    return quality, count, specs


def run_job(library, job, key, quality, count, specs):
    try:
        for name, prompt in specs:
            job["message"] = f"正在生成 {name}"
            library.update_job(job)
            contents = generate_images(key, prompt, quality, count)
            rows = [
                library.asset_row(
                    content, name, "openai", model=MODEL, prompt=prompt,
                    job=job["id"], variant=number,
                )
                for number, content in enumerate(contents, 1)
            ]
            job["completed"] += 1
            library.update_job(job, rows)
        job.update(state="done", message="生成完成。")
    except ValueError as error:
        job.update(state="failed", message=str(error))
    except Exception:
        job.update(state="failed", message="任务发生内部错误，已保存先前完成的素材。")
    library.update_job(job)


class Handler(BaseHTTPRequestHandler):
    server_version = "SpriteFoundry/1"

    def log_message(self, fmt, *args):
        if args[1:2] != ("200",):
            super().log_message(fmt, *args)

    @property
    def library(self):
        return self.server.library

    def reply(self, status, content, content_type, *, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, content, status=HTTPStatus.OK):
        self.reply(status, json.dumps(content, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def valid_host(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_json({"error": "请通过 127.0.0.1 打开工作台。"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        if path in STATIC:
            name, content_type = STATIC[path]
            self.reply(HTTPStatus.OK, (ROOT / "web" / name).read_bytes(), content_type)
        elif path == "/api/library":
            self.send_json({**self.library.listing(), "model": MODEL, "configured": bool(os.environ.get("OPENAI_API_KEY", "").strip())})
        elif match := re.fullmatch(r"/api/thumb/([0-9a-f]{32})", path):
            try:
                _, content = self.library.get_asset(match[1], thumbnail=True)
                self.reply(HTTPStatus.OK, content, "image/png")
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        else:
            self.send_json({"error": "找不到这个页面。"}, HTTPStatus.NOT_FOUND)

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求必须使用 JSON。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_IMAGE_BYTES * 4 // 3 + 4096:
                raise ValueError("请求为空或超过大小上限。")
            values = json.loads(self.rfile.read(length))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("请求格式无效。") from error
        if not isinstance(values, dict):
            raise ValueError("需要 JSON 对象。")
        return values

    def do_POST(self):
        if not self.valid_host():
            return
        origin = self.headers.get("Origin")
        if self.headers.get("X-Sprite-Foundry") != "1" or origin not in (None, f"{ORIGIN}:{self.server.server_port}"):
            self.send_json({"error": "请求来源无效。"}, HTTPStatus.FORBIDDEN)
            return
        try:
            self.post_action(urlsplit(self.path).path, self.read_json())
        except (BrokenPipeError, ConnectionResetError):
            return
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def post_action(self, path, values):
        if path == "/api/import":
            encoded = short_text(values, "content", MAX_IMAGE_BYTES * 4 // 3 + 4, required=True)
            name = short_text(values, "name", 80, required=True)
            try:
                content = base64.b64decode(encoded, validate=True)
            except binascii.Error as error:
                raise ValueError("图片编码无效。") from error
            credit = short_text(values, "credit", 200)
            prompt = short_text(values, "prompt", 4000)
            row = self.library.asset_row(content, name, "import", credit=credit or None, prompt=prompt or None)
            self.library.add_assets([row])
            self.send_json({"id": row[0]}, HTTPStatus.CREATED)
        elif path == "/api/samples":
            samples = sorted((ROOT / "samples").glob("*.png"))
            rows = [
                self.library.asset_row(
                    image.read_bytes(), image.stem, "sample",
                    asset_id=uuid.uuid5(uuid.NAMESPACE_URL, f"sprite-foundry:sample:{image.name}").hex,
                    credit="Codex ImageGen" if image.stem == "ion_battery" else "FootballRoguelite_Art / 项目自制素材",
                )
                for image in samples
            ]
            self.library.add_assets(rows)
            self.send_json({"ids": [row[0] for row in rows]})
        elif path == "/api/generate":
            quality, count, specs = generation_spec(values)
            key = short_text(values, "key", 512) or os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                raise ValueError("请在本次会话输入 API 密钥，或设置 OPENAI_API_KEY 后重启。")
            if not re.fullmatch(r"[!-~]{1,512}", key):
                raise ValueError("API 密钥格式无效。")
            job = {"id": uuid.uuid4().hex, "state": "running", "total": len(specs), "completed": 0, "message": "任务已提交。"}
            self.library.start_job(job)
            threading.Thread(target=run_job, args=(self.library, job, key, quality, count, specs), daemon=True).start()
            self.send_json({"id": job["id"]}, HTTPStatus.ACCEPTED)
        elif path == "/api/preview":
            _, content = self.library.get_asset(self.asset_ids(values, 1)[0])
            preview = prepare_sprite(decode_image(content), sprite_settings(values))
            self.reply(HTTPStatus.OK, png_bytes(preview), "image/png")
        elif path == "/api/export":
            ids = self.asset_ids(values, MAX_EXPORT_ASSETS)
            settings = sprite_settings(values)
            include_atlas = values.get("atlas", True)
            if type(include_atlas) is not bool:
                raise ValueError("图集选项无效。")

            def selected():
                for asset_id in ids:
                    record, content = self.library.get_asset(asset_id)
                    yield record, decode_image(content)

            pack = export_pack(selected(), settings, include_atlas, count=len(ids))
            self.reply(HTTPStatus.OK, pack, "application/zip", headers={
                "Content-Disposition": 'attachment; filename="sprite-foundry-pack.zip"',
            })
        else:
            self.send_json({"error": "找不到这个操作。"}, HTTPStatus.NOT_FOUND)

    @staticmethod
    def asset_ids(values, limit):
        ids = values.get("ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= limit:
            raise ValueError(f"请选中 1–{limit} 张素材。")
        if any(not isinstance(asset_id, str) or not re.fullmatch(r"[0-9a-f]{32}", asset_id) for asset_id in ids):
            raise ValueError("素材 ID 无效。")
        if len(set(ids)) != len(ids):
            raise ValueError("每张素材只能选择一次。")
        return ids


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    portable = getattr(sys, "frozen", False)
    data_root = Path(sys.executable).parent if portable else ROOT
    parser = argparse.ArgumentParser(description="Sprite Foundry 本地素材工作台")
    parser.add_argument("--port", type=int, default=PORTABLE_PORT if portable else DEFAULT_PORT)
    parser.add_argument("--data", type=Path, default=data_root / ".data")
    parser.add_argument("--open", action=argparse.BooleanOptionalAction, default=portable, help="打开默认浏览器")
    args = parser.parse_args()

    try:
        with LocalServer(("127.0.0.1", args.port), Handler) as server:
            server.library = Library(args.data)
            server.library.recover_jobs()
            url = f"{ORIGIN}:{server.server_port}"
            print(f"Sprite Foundry  {url}", flush=True)
            if portable:
                print("Keep this window open while using Sprite Foundry. Close it to stop the app.", flush=True)
            if args.open:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, sqlite3.Error) as error:
        if not portable:
            raise
        print(f"Could not start Sprite Foundry: {error}", file=sys.stderr)
        print(f"Check that {args.data} is writable and close any other copy using port {args.port}.", file=sys.stderr)
        if sys.stdin.isatty():
            try:
                input("Press Enter to close.")
            except (EOFError, KeyboardInterrupt):
                pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
