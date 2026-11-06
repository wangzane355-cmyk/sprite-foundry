"""Scriptable import and export for the running Sprite Foundry workbench."""

import argparse
import base64
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import DEFAULT_PORT, MAX_IMAGE_BYTES


def call(port, path, body=None):
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Sprite-Foundry": "1"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            if not response.headers.get("Server", "").startswith("SpriteFoundry/"):
                raise ValueError("该端口由其他服务使用。")
            return response.read()
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error", f"HTTP {error.code}")
        except (ValueError, AttributeError):
            detail = f"HTTP {error.code}"
        raise ValueError(detail) from error
    except URLError as error:
        raise ValueError(f"工作台未连接，请启动 app.py --port {port}。") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出素材和生成任务")
    add = commands.add_parser("import", help="导入原始图片并返回 ID")
    add.add_argument("files", type=Path, nargs="+")
    add.add_argument("--credit", default="")
    add.add_argument("--prompt", default="")
    export = commands.add_parser("export", help="将指定素材写成 Unity ZIP")
    export.add_argument("ids", nargs="+")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--size", type=int, default=128)
    export.add_argument("--margin", type=int, default=8)
    export.add_argument("--ppu", type=int)
    export.add_argument("--pivot", choices=("center", "bottom"), default="center")
    export.add_argument("--filter", choices=("smooth", "pixel"), default="smooth")
    export.add_argument("--no-atlas", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "list":
            print(call(args.port, "/api/library").decode())
        elif args.command == "import":
            for image in args.files:
                with image.open("rb") as file:
                    content = file.read(MAX_IMAGE_BYTES + 1)
                if len(content) > MAX_IMAGE_BYTES:
                    raise ValueError(f"{image.name} 超过 12 MB。")
                response = call(args.port, "/api/import", {
                    "name": image.stem[:80], "content": base64.b64encode(content).decode(),
                    "credit": args.credit, "prompt": args.prompt,
                })
                print(response.decode(), flush=True)
        else:
            if args.out.exists():
                raise FileExistsError(f"目标已存在 {args.out}。请选择新的输出名。")
            content = call(args.port, "/api/export", {
                "ids": args.ids, "size": args.size, "margin": args.margin,
                "ppu": args.ppu if args.ppu is not None else args.size, "pivot": args.pivot,
                "filter": args.filter, "atlas": not args.no_atlas,
            })
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("xb") as output:
                output.write(content)
            print(args.out.resolve())
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
