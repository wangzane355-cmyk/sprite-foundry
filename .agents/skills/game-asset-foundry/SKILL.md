---
name: game-asset-foundry
description: Generate, review, and package static 2D game art such as inventory icons, props, and character sprites. Use when a game asset needs transparent raster output, consistent art direction across a set, or Unity-ready sprite files and atlas coordinates.
---

# Game Asset Foundry

Deliver a usable sprite or set. Read the target project's sprite conventions before choosing canvas size, camera angle, pixel density, or pivot. Preserve existing names, import settings, and asset references when updating sprites in place.

## Brief and generation

- Separate the shared style specification from the description of each subject. Lock viewpoint, silhouette density, palette roles, key light, and scale across a set. Use the user's reference art to derive those constraints. Record which images are references, editable originals, and approved outputs.
- Distinct assets get distinct prompts. Generate one representative asset first if the art direction is new, then reuse the accepted style for the batch. Use variants when a decision is still open. Keep every selected object fully in frame with true alpha, including inside openings.
- Inventory art should read at the smallest UI size. For world props or characters, match camera and contact point. For pixel art, specify a working grid and palette and inspect pixels at final size. Nearest-neighbor resizing alone does not establish pixel-art quality.
- Use the built-in ImageGen capability when available. For edits, state what may change and what must survive. Preserve originals and the generated alpha. If the user chooses the workbench's OpenAI provider, submit the agreed batch there and surface service failures without automatically retrying a billable request.

## Review and packaging

1. Inspect candidates on light and dark backgrounds at output size. Check silhouette, cut-off edges, opaque backdrops, stray pixels, color consistency, and the actual pivot or ground contact. Keep intentional soft edges such as glow. Never treat a checkerboard pattern as transparency.
2. Use Sprite Foundry for consistent crop, fit, margin, anchor, and atlas layout. Find the app at the root of this repository and read `README.md` for supported formats and commands.
3. For an agent-run batch, start the app if needed, then use `cli.py import` with credit and prompt metadata. Select approved asset IDs via `cli.py list`. Use `cli.py export` to write a new ZIP in the requested location or the workspace's usual deliverables directory. For Unity, keep the generated `.meta` beside each PNG. Check for duplicate GUIDs before copying the same export to a second path in one project.
4. Verify the final RGBA files, target dimensions, expected PPU, and pivot. If exporting an atlas, verify that its manifest maps every sprite to its exact rectangle. The atlas uses top-left pixel coordinates. Unity pivots use normalized bottom-left coordinates. The app's Unity import settings apply to the standalone sprites. The raw atlas requires slicing.

Leave a concise record of what was generated, which outputs passed visual checks, where the files live, and which engine import checks actually ran.
