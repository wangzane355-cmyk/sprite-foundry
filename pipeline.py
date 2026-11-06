"""Image validation, game-size processing and Unity export."""

import io
import json
import math
import re
import unicodedata
import uuid
import zipfile

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_EXPORT_ASSETS = 48
FORMATS = ("PNG", "JPEG", "WEBP")
KINDS = {
    "icon": "A single inventory icon, recognizable at 32 pixels. Bold silhouette and restrained details.",
    "prop": "A single environment prop with the requested camera angle and a clearly defined base.",
    "sprite": "A single game sprite in a neutral readable pose, with consistent camera and ground contact.",
}


def bounded_int(values, key, default, low, high):
    value = values.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} 必须是 {low}–{high} 之间的整数。")
    return value


def short_text(values, key, limit, *, required=False):
    value = values.get(key, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{key} 需要有效文字，最多 {limit} 字。")
    return value.strip()


def make_prompt(subject, kind, style):
    return (
        f"Create a production-ready 2D game asset. {KINDS[kind]}\n"
        f"Subject: {subject}\n"
        f"Shared art direction: {style or 'Stylized game art, clean shapes and clear material separation.'}\n"
        "Keep the entire object in frame with comfortable transparent margins. Use true alpha, "
        "with one isolated subject, no scene, floor plane, drop shadow, text, watermark or border."
    )


def decode_image(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片上限为 12 MB。")
    try:
        with Image.open(io.BytesIO(data), formats=FORMATS) as image:
            if max(image.size) > 4096:
                raise ValueError("单边尺寸上限为 4096 像素。")
            if getattr(image, "is_animated", False):
                raise ValueError("请导入静态图片。")
            return ImageOps.exif_transpose(image).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("无法读取图片，请使用 PNG、JPEG 或 WebP。") from error


def png_bytes(image):
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


def inspect_image(image):
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    visible = alpha.point([0] * 16 + [255] * 240).getbbox()
    return {
        "width": image.width,
        "height": image.height,
        "clear": round(histogram[0] / (image.width * image.height), 4),
        "bounds": visible,
        "alpha": "empty" if visible is None else "solid" if histogram[255] == image.width * image.height else "mixed",
        "edge": visible is not None and (
            visible[0] == 0 or visible[1] == 0 or visible[2] == image.width or visible[3] == image.height
        ),
    }


def sprite_settings(values):
    size = bounded_int(values, "size", 128, 32, 512)
    margin = bounded_int(values, "margin", 8, 0, min(64, (size - 2) // 2))
    ppu = bounded_int(values, "ppu", size, 1, 4096)
    pivot = values.get("pivot", "center")
    filtering = values.get("filter", "smooth")
    if pivot not in ("center", "bottom") or filtering not in ("smooth", "pixel"):
        raise ValueError("无效的锚点或采样模式。")
    return {"size": size, "margin": margin, "ppu": ppu, "pivot": pivot, "filter": filtering}


def prepare_sprite(image, settings):
    # Trim only pixels with zero alpha so glows and soft edges survive resizing.
    bounds = image.getchannel("A").getbbox()
    if bounds is None or inspect_image(image)["alpha"] == "empty":
        raise ValueError("图片没有可见像素。")
    size, margin = settings["size"], settings["margin"]
    sampler = Image.Resampling.NEAREST if settings["filter"] == "pixel" else Image.Resampling.LANCZOS
    cropped = image.crop(bounds)
    scale = (size - margin * 2) / max(cropped.size)
    dimensions = tuple(max(1, round(length * scale)) for length in cropped.size)
    subject = cropped.resize(dimensions, sampler)
    x = (size - subject.width) // 2
    y = size - margin - subject.height if settings["pivot"] == "bottom" else (size - subject.height) // 2
    sprite = Image.new("RGBA", (size, size))
    sprite.paste(subject, (x, y))
    return sprite


def slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:52]
    if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", value):
        value = f"sprite_{value}"
    return value or "sprite"


def sprite_meta(asset_id, settings):
    guid = uuid.uuid5(uuid.NAMESPACE_URL, f"sprite-foundry:{asset_id}").hex
    pivot_y = 0.5 if settings["pivot"] == "center" else settings["margin"] / settings["size"]
    filter_mode = 0 if settings["filter"] == "pixel" else 1
    return f"""fileFormatVersion: 2
guid: {guid}
TextureImporter:
  serializedVersion: 13
  mipmaps:
    enableMipMap: 0
    sRGBTexture: 1
  textureSettings:
    serializedVersion: 2
    filterMode: {filter_mode}
    aniso: 1
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  spriteMode: 1
  spriteMeshType: 0
  alignment: 9
  spritePivot: {{x: 0.5, y: {pivot_y:.8f}}}
  spritePixelsToUnits: {settings["ppu"]}
  spriteGenerateFallbackPhysicsShape: 0
  alphaUsage: 1
  alphaIsTransparency: 1
  textureType: 8
  textureShape: 1
  platformSettings:
  - serializedVersion: 4
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 512
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    overridden: 0
  spriteSheet:
    serializedVersion: 2
    sprites: []
    spriteID: 5e97eb03825dee720800000000000000
    internalID: 0
"""


def atlas_grid(sprites, size):
    # Two blank pixels on each side of each cell.
    stride = size + 4
    columns = min(math.ceil(math.sqrt(len(sprites))), 4096 // stride)
    rows = math.ceil(len(sprites) / columns)
    width, height = columns * stride, rows * stride
    if height > 4096:
        raise ValueError("图集超过 4096 像素，请减少素材数量。")
    atlas = Image.new("RGBA", (width, height))
    frames = []
    for index, image in enumerate(sprites):
        x, y = index % columns * stride + 2, index // columns * stride + 2
        atlas.paste(image, (x, y))
        frames.append({"x": x, "y": y, "width": size, "height": size})
    return atlas, frames


def export_pack(assets, settings, include_atlas, *, count):
    if not 1 <= count <= MAX_EXPORT_ASSETS:
        raise ValueError(f"请选中 1–{MAX_EXPORT_ASSETS} 张素材。")
    size = settings["size"]
    manifest = {
        "version": 1, "settings": settings,
        "pivotNormalizedBottomLeft": [0.5, 0.5 if settings["pivot"] == "center" else settings["margin"] / size],
        "sprites": [],
    }
    result = io.BytesIO()
    sprites = []
    taken = set()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as bundle:
        for asset, image in assets:
            name = slug(asset["name"])
            filename = name
            suffix = 2
            while filename in taken:
                filename = f"{name}_{suffix}"
                suffix += 1
            taken.add(filename)
            path = f"Sprites/{filename}.png"
            sprite = prepare_sprite(image, settings)
            bundle.writestr(path, png_bytes(sprite))
            bundle.writestr(path + ".meta", sprite_meta(asset["id"], settings))
            manifest["sprites"].append({
                "id": asset["id"], "name": asset["name"], "path": path,
                "source": asset["source"], "model": asset.get("model"), "credit": asset.get("credit"),
                "prompt": asset.get("prompt"), "original": asset["qa"],
            })
            if include_atlas:
                sprites.append(sprite)
        if include_atlas:
            atlas, frames = atlas_grid(sprites, size)
            bundle.writestr("Atlas/atlas.png", png_bytes(atlas))
            manifest["atlas"] = {"path": "Atlas/atlas.png", "origin": "top-left", "width": atlas.width, "height": atlas.height}
            for record, frame in zip(manifest["sprites"], frames):
                record["frame"] = frame
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return result.getvalue()
