# Sprite Foundry · 游戏素材工坊

面向 2D 游戏图标、道具和静态精灵的 Windows 本地工作台。素材库保存在项目下的 `.data/library.sqlite3`。关闭工作台后可再次打开继续挑选和导出。

## 打开工作台

双击 `Launch.cmd`。首次安装依赖需要可用的 Python 3.11 或更高版本。浏览器入口是 `http://127.0.0.1:18764`。

1. 点「载入示例」直接预览和导出。也可以导入 PNG、JPEG 或 WebP。
2. 生成新素材时，选类型和共享风格，每行填写 `素材名 | 描述`。单批最多 8 个主题、12 张候选。
3. 在候选区勾选要交付的版本。用预览区的浅色和深色底检查轮廓，再设置尺寸、留白、锚点和 PPU。
4. 下载 ZIP。将 `Sprites/` 中的 PNG 和同名 `.meta` 一起解压到 Unity 工程的一个新子目录。重复导出同一素材时，在相同位置更新文件以保留引用。

生成按钮调用 OpenAI Images API，默认使用支持透明 PNG 的 GPT Image 2.5 Flare。可在本页填写 API 密钥，也可在启动环境设置 `OPENAI_API_KEY`。程序把密钥用于运行中的请求，素材库与导出包只保存素材和提示词等来源信息。可通过启动环境变量 `SPRITE_FOUNDRY_IMAGE_MODEL` 选择支持同一参数的模型。[OpenAI Images API](https://developers.openai.com/api/reference/resources/images/methods/generate)

内置示例包括一张 Codex ImageGen 生成的离子电池，以及六张现有 FootballRoguelite 工程的自制图标。导入与导出可在离线环境运行。普通实底照片会带着背景进入成品，工作台会标出缺少透明像素的图。导入这类图前可先在图像工具里去底。

## 导出格式

- `Sprites/` 含规范化 RGBA PNG 和 Unity 单精灵导入设置。最近邻对应 Point 采样，平滑对应 Bilinear，均关闭 Mipmap。
- `Atlas/atlas.png` 是可选的整张图集。清单中的切片矩形以图集左上为原点，单位是像素。Unity 会直接识别独立 Sprite。使用图集时由引擎侧按清单切片。
- `manifest.json` 记录每张图的源尺寸、透明度、素材来源、输出路径，以及图集坐标和导出设置。锚点的归一化坐标以左下为原点。

## 从 Codex 送入素材

仓库自带 [`$game-asset-foundry`](.agents/skills/game-asset-foundry/SKILL.md)。在项目目录打开 Codex 后，可以直接说「用 $game-asset-foundry 做一套 3 张等距科幻补给道具，导出成 Unity 的 128 像素精灵包」。

用 ImageGen 生成或编辑透明 PNG，再运行以下命令。工作台需保持运行。

```powershell
.venv\Scripts\python.exe -X utf8 cli.py import "D:\path\ion_battery.png" --credit "Codex ImageGen"
.venv\Scripts\python.exe -X utf8 cli.py list
.venv\Scripts\python.exe -X utf8 cli.py export <id> --out "D:\codex\artifacts\ion-battery.zip" --size 128 --margin 8
```

## 首版验证

Chrome 实测通过样本载入、透明底预览、调整尺寸、ZIP 下载和本地素材持久化。示例 ZIP 的七个图集矩形均与独立 PNG 像素一致。Unity 6000.1.5f1 在隔离工程中加载了全部七个 Sprite，并验证尺寸、Alpha、锚点、PPU、采样与 Mipmap。

当前账户的真实 OpenAI 生成请求返回 `429 credit_balance_exhausted`。生成任务的成功、部分失败保留和多候选处理使用真实 ImageGen 图片作为本地替身验证。具备额度的账户可继续验证工作台直接生成路径。
