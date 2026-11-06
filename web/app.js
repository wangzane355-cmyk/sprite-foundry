"use strict";

const el = (id) => document.getElementById(id);
const sources = {openai: "AI 生成", sample: "示例", import: "导入"};
const jobStates = {running: "生成中", done: "生成完成", failed: "任务暂停", interrupted: "任务中断"};
const styles = {
  neon: "精细但轮廓简洁的科幻装备，深蓝钢与暖黄铜，少量青色能量发光。四分之三视角，左上方主光，统一材质和对比度。",
  rts: "战术 RTS 游戏风格，正交等距视角，从东南方向看，左上方主光。灰蓝工业钢，低饱和橄榄绿与暖色识别标记。",
  pixel: "手绘复古像素美术，硬像素边缘，16 色有限色板，轮廓比纹理重要，禁止抗锯齿与渐变。",
};
let assets = [];
let selected = new Set();
let current = null;
let filter = "all";
let activeJob = false;
let generating = false;
let previewVersion = 0;
let previewTimer;
let previewUrl;
let noticeTimer;

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Sprite-Foundry": "1"},
    body: JSON.stringify(data),
  };
  const response = await fetch(path, options);
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(problem.error || `请求失败（${response.status}）`);
  }
  return response;
}

function notice(message, error = false) {
  const box = el("notice");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { box.hidden = true; }, error ? 8000 : 3800);
}

function visibleAssets() {
  return filter === "all" ? assets : assets.filter((asset) => selected.has(asset.id));
}

function labelFor(asset) {
  return asset.variant ? `${asset.name} · ${asset.variant}` : asset.name;
}

function qaFor(asset) {
  const {width, height, clear, edge} = asset.qa;
  const transparency = clear ? `${Math.round(clear * 100)}% 透明` : "无全透明像素";
  return `${width}×${height} · ${transparency}${edge ? " · 主体贴边" : ""}`;
}

function makeCard(asset) {
  const card = document.createElement("article");
  card.className = "card";
  card.dataset.id = asset.id;
  card.classList.toggle("current", current === asset.id);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "asset-image checker";
  button.setAttribute("aria-label", `预览 ${labelFor(asset)}`);
  button.setAttribute("aria-pressed", String(current === asset.id));
  const image = document.createElement("img");
  image.alt = "";
  image.loading = "lazy";
  image.src = `/api/thumb/${asset.id}`;
  button.append(image);
  button.addEventListener("click", () => focusAsset(asset.id));

  const body = document.createElement("div");
  body.className = "card-text";
  const label = document.createElement("label");
  label.className = "card-name";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = selected.has(asset.id);
  box.addEventListener("change", () => {
    if (box.checked) selected.add(asset.id);
    else selected.delete(asset.id);
    if (filter === "selected") renderAssets();
    else renderCounts();
  });
  const title = document.createElement("span");
  title.textContent = labelFor(asset);
  title.title = labelFor(asset);
  label.append(box, title);
  const meta = document.createElement("p");
  meta.textContent = `${sources[asset.source]} · ${qaFor(asset)}`;
  meta.classList.toggle("warning", !asset.qa.clear || asset.qa.edge);
  body.append(label, meta);
  card.append(button, body);
  return card;
}

function renderCounts() {
  el("asset-count").textContent = `${assets.length} 张`;
  el("selected-count").textContent = selected.size;
  el("export-button").disabled = !selected.size || selected.size > 48;
  el("export-button").textContent = selected.size > 48 ? "每次最多导出 48 张" :
    selected.size ? `↓ 导出 ${selected.size} 张 · Unity ZIP` : "↓ 导出 Unity ZIP";
}

function renderAssets() {
  const visible = visibleAssets();
  el("assets").replaceChildren(...visible.map(makeCard));
  el("empty").hidden = visible.length > 0;
  el("empty-title").textContent = filter === "selected" ? "还没有选中的素材" : "这里会显示素材候选";
  el("empty-text").textContent = filter === "selected" ? "勾选候选卡片，把它加入导出清单。" : "生成一组素材，或载入示例体验预览和导出。";
  renderCounts();
}

function focusAsset(id) {
  current = id;
  for (const card of el("assets").children) {
    const focused = card.dataset.id === id;
    card.classList.toggle("current", focused);
    card.firstElementChild.setAttribute("aria-pressed", String(focused));
  }
  queuePreview();
}

function outputSettings() {
  return {
    size: Number(el("size").value),
    margin: Number(el("margin").value),
    ppu: Number(el("ppu").value),
    pivot: el("pivot").value,
    filter: el("filter").value,
    atlas: el("atlas").checked,
  };
}

function queuePreview() {
  clearTimeout(previewTimer);
  const version = ++previewVersion;
  if (current) previewTimer = setTimeout(() => updatePreview(version), 110);
}

async function updatePreview(version) {
  const asset = assets.find((item) => item.id === current);
  if (!asset) return;
  const settings = outputSettings();
  el("preview-name").textContent = labelFor(asset);
  el("preview-name").title = labelFor(asset);
  el("preview-info").textContent = `${qaFor(asset)} → ${settings.size}×${settings.size}`;
  el("preview-image").hidden = true;
  el("preview-placeholder").hidden = false;
  el("preview-placeholder").textContent = "正在更新预览";
  try {
    const response = await api("/api/preview", {...settings, ids: [asset.id]});
    const blob = await response.blob();
    if (version !== previewVersion) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    el("preview-image").src = previewUrl;
    el("preview-image").hidden = false;
    el("preview-placeholder").hidden = true;
  } catch (error) {
    if (version === previewVersion) el("preview-placeholder").textContent = error.message;
  }
}

function updateJob(job) {
  activeJob = job?.state === "running";
  el("generate-button").disabled = activeJob || generating;
  el("generate-button").textContent = activeJob ? "正在生成…" : "✦ 生成候选";
  el("job").hidden = !job;
  if (!job) return;
  el("job-state").textContent = `${jobStates[job.state]} · ${job.completed}/${job.total} 个主题`;
  el("progress").max = job.total;
  el("progress").value = job.completed;
  el("job-message").textContent = job.message;
}

async function refresh() {
  const response = await api("/api/library");
  const library = await response.json();
  el("connection").textContent = library.configured ? "本地 · API 已配置" : "本地模式";
  el("model").textContent = `${library.model} · ${library.configured ? "已读取运行环境的密钥" : "需提供密钥才能生成"}`;
  if (!current && library.assets.length) {
    current = library.assets[0].id;
    queuePreview();
  }
  const changed = assets.length !== library.assets.length || assets[0]?.id !== library.assets[0]?.id;
  assets = library.assets;
  if (changed) renderAssets();
  updateJob(library.jobs[0]);
}

async function poll() {
  try {
    await refresh();
  } catch {
    el("connection").textContent = "连接中断";
  } finally {
    setTimeout(poll, activeJob ? 1200 : 3000);
  }
}

function getEntries() {
  return el("entries").value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const separator = line.indexOf("|");
    if (separator < 0 || !line.slice(0, separator).trim() || !line.slice(separator + 1).trim()) {
      throw new Error("每行请按「素材名 | 描述」填写。");
    }
    return {name: line.slice(0, separator).trim(), subject: line.slice(separator + 1).trim()};
  });
}

el("preset").addEventListener("change", (event) => {
  if (event.target.value) el("style").value = styles[event.target.value];
});

el("generate").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (activeJob || generating) return;
  generating = true;
  el("generate-button").disabled = true;
  try {
    const entries = getEntries();
    const variants = Number(el("variants").value);
    await api("/api/generate", {
      entries, variants, kind: el("kind").value, quality: el("quality").value,
      style: el("style").value, key: el("key").value,
    });
    activeJob = true;
    await refresh();
  } catch (error) {
    notice(error.message, true);
  } finally {
    generating = false;
    el("generate-button").disabled = activeJob;
  }
});

el("load-samples").addEventListener("click", async () => {
  el("load-samples").disabled = true;
  try {
    const {ids} = await (await api("/api/samples", {})).json();
    await refresh();
    for (const id of ids) selected.add(id);
    renderAssets();
    focusAsset(ids[0]);
    notice(`已载入并选中 ${ids.length} 张示例。`);
  } catch (error) {
    notice(error.message, true);
  } finally {
    el("load-samples").disabled = false;
  }
});

function fileContent(file) {
  if (file.size > 12 * 1024 * 1024) throw new Error("图片超过 12 MB。");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]);
    reader.onerror = () => reject(new Error("无法读取本地文件。"));
    reader.readAsDataURL(file);
  });
}

el("files").addEventListener("change", async (event) => {
  const input = event.target;
  const files = Array.from(input.files);
  input.disabled = true;
  const imported = [];
  const errors = [];
  try {
    for (const file of files) {
      try {
        const name = file.name.replace(/\.[^.]+$/, "").slice(0, 80) || "sprite";
        const response = await api("/api/import", {name, content: await fileContent(file)});
        imported.push((await response.json()).id);
      } catch (error) {
        errors.push(`${file.name} · ${error.message}`);
      }
    }
    await refresh();
    if (imported.length) focusAsset(imported[0]);
    if (files.length) notice(`已导入 ${imported.length}/${files.length} 张。${errors[0] || ""}`, errors.length > 0);
  } catch (error) {
    notice(error.message, true);
  } finally {
    input.value = "";
    input.disabled = false;
  }
});

for (const button of document.querySelectorAll("[data-filter]")) {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    for (const item of document.querySelectorAll("[data-filter]")) {
      const on = item.dataset.filter === filter;
      item.classList.toggle("active", on);
      item.setAttribute("aria-pressed", String(on));
    }
    renderAssets();
  });
}

el("select-visible").addEventListener("click", () => {
  for (const asset of visibleAssets()) selected.add(asset.id);
  renderAssets();
});
el("clear-selection").addEventListener("click", () => {
  selected.clear();
  renderAssets();
});
el("toggle-bg").addEventListener("click", (event) => {
  const light = el("preview-area").classList.toggle("light");
  event.target.textContent = light ? "深色底" : "浅色底";
  event.target.setAttribute("aria-pressed", String(light));
});
el("export").addEventListener("input", queuePreview);
let previousSize = el("size").value;
el("size").addEventListener("change", () => {
  const size = Number(el("size").value);
  const margin = el("margin");
  margin.max = Math.min(64, Math.floor((size - 2) / 2));
  margin.value = Math.min(Number(margin.max), Number(margin.value));
  if (el("ppu").value === previousSize) el("ppu").value = String(size);
  previousSize = String(size);
});
el("export").addEventListener("submit", async (event) => {
  event.preventDefault();
  el("export-button").disabled = true;
  try {
    const response = await api("/api/export", {...outputSettings(), ids: Array.from(selected)});
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "sprite-foundry-pack.zip";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    notice("已导出素材包。");
  } catch (error) {
    notice(error.message, true);
  } finally {
    renderCounts();
  }
});

poll();
