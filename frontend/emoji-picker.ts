type CatalogItem = { id: number; token: string; src: string; pack?: string };
type CatalogPack = { id: string; label: string; count: number };
type Catalog = { pack: string; count: number; items: CatalogItem[]; packs?: CatalogPack[] };

let catalogCache: Catalog | null = null;

function panelOf(wrap: HTMLElement) {
  const id = wrap.dataset.panelId;
  if (id) {
    const hosted = document.getElementById(id);
    if (hosted) return hosted;
  }
  return wrap.querySelector<HTMLElement>(".js-emoji-panel");
}

function toggleOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLButtonElement>(".js-emoji-toggle");
}

function hostOf(panel: HTMLElement) {
  return panel.querySelector<HTMLElement>(".js-emoji-grid-host");
}

function packsOf(panel: HTMLElement) {
  return panel.querySelector<HTMLElement>(".js-emoji-packs");
}

function dockPanel(wrap: HTMLElement, panel: HTMLElement) {
  if (!panel.id) panel.id = `emoji-panel-${Math.random().toString(36).slice(2, 9)}`;
  wrap.dataset.panelId = panel.id;
  toggleOf(wrap)?.setAttribute("aria-controls", panel.id);
  if (panel.parentElement !== document.body) {
    document.body.append(panel);
  }
}

export function closeEmojiPicker(wrap: HTMLElement) {
  wrap.classList.remove("is-open");
  toggleOf(wrap)?.setAttribute("aria-expanded", "false");
  const panel = panelOf(wrap);
  if (panel) panel.hidden = true;
}

export function closeAllEmojiPickers(except?: HTMLElement) {
  document.querySelectorAll<HTMLElement>(".js-emoji-picker.is-open").forEach((wrap) => {
    if (wrap !== except) closeEmojiPicker(wrap);
  });
}

async function loadCatalog(): Promise<Catalog> {
  if (catalogCache) return catalogCache;
  const embedded = document.getElementById("joi3-emoji-catalog");
  if (embedded?.textContent) {
    try {
      catalogCache = JSON.parse(embedded.textContent) as Catalog;
      return catalogCache;
    } catch {
      /* fetch fallback */
    }
  }
  const response = await fetch("/static/emojis/joi3/catalog.json", { credentials: "same-origin" });
  if (!response.ok) {
    catalogCache = { pack: "JOI3", count: 0, items: [] };
    return catalogCache;
  }
  catalogCache = (await response.json()) as Catalog;
  return catalogCache;
}

function placePanel(wrap: HTMLElement) {
  const panel = panelOf(wrap);
  const toggle = toggleOf(wrap);
  if (!panel || !toggle || panel.hidden) return;
  const btn = toggle.getBoundingClientRect();
  const width = Math.min(panel.offsetWidth || 296, window.innerWidth - 16);
  const height = Math.min(panel.offsetHeight || 320, window.innerHeight - 16);
  let left = btn.left;
  let top = btn.top - height - 8;
  if (top < 8) top = btn.bottom + 8;
  if (top + height > window.innerHeight - 8) top = Math.max(8, window.innerHeight - height - 8);
  if (left + width > window.innerWidth - 8) left = window.innerWidth - 8 - width;
  if (left < 8) left = 8;
  panel.style.width = `${width}px`;
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}

function itemsForPack(catalog: Catalog, packId: string | null) {
  if (!packId || packId === "all") return catalog.items || [];
  return (catalog.items || []).filter((item) => (item.pack || "joi3") === packId);
}

function renderPacks(panel: HTMLElement, wrap: HTMLElement, catalog: Catalog) {
  const nav = packsOf(panel);
  if (!nav) return;
  const packs = catalog.packs?.filter((pack) => pack.count > 0) || [];
  nav.replaceChildren();
  if (packs.length < 2) {
    nav.hidden = true;
    return;
  }
  nav.hidden = false;
  const current = panel.dataset.pack || packs[0].id;
  packs.forEach((pack) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "emoji-pack" + (pack.id === current ? " is-on" : "");
    button.setAttribute("aria-pressed", pack.id === current ? "true" : "false");
    button.dataset.pack = pack.id;
    button.textContent = pack.label;
    button.addEventListener("click", () => {
      panel.dataset.pack = pack.id;
      renderGrid(panel, wrap, catalog);
      renderPacks(panel, wrap, catalog);
      placePanel(wrap);
    });
    nav.append(button);
  });
}

function renderGrid(panel: HTMLElement, wrap: HTMLElement, catalog: Catalog) {
  const host = hostOf(panel);
  if (!host) return;
  host.replaceChildren();
  const packs = catalog.packs?.filter((pack) => pack.count > 0) || [];
  if (!panel.dataset.pack) panel.dataset.pack = packs[0]?.id || "joi3";
  const items = itemsForPack(catalog, panel.dataset.pack);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "emoji-empty muted";
    empty.textContent = "Pacote de emojis pixel indisponível.";
    host.append(empty);
    panel.dataset.ready = "1";
    return;
  }
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "emoji-cell";
    button.setAttribute("role", "option");
    button.setAttribute("aria-label", item.token);
    button.title = item.token;
    const img = document.createElement("img");
    img.src = item.src;
    img.alt = "";
    img.width = 28;
    img.height = 28;
    img.loading = "lazy";
    img.decoding = "async";
    img.draggable = false;
    button.append(img);
    button.addEventListener("click", () => {
      wrap.dispatchEvent(
        new CustomEvent("emoji-select", {
          bubbles: true,
          detail: { emoji: item.token },
        }),
      );
      if (wrap.dataset.emojiMode !== "tag") closeEmojiPicker(wrap);
    });
    host.append(button);
  });
  panel.dataset.ready = "1";
}

async function openEmojiPicker(wrap: HTMLElement) {
  const panel = panelOf(wrap);
  const toggle = toggleOf(wrap);
  if (!panel || !toggle) return;
  closeAllEmojiPickers(wrap);
  document.querySelectorAll<HTMLElement>(".js-color-picker.is-open").forEach((node) => {
    node.classList.remove("is-open");
    const colorPanel = node.querySelector<HTMLElement>(".js-color-panel");
    if (colorPanel) colorPanel.hidden = true;
    node.querySelector(".js-color-toggle")?.setAttribute("aria-expanded", "false");
  });
  dockPanel(wrap, panel);
  if (!panel.dataset.ready) {
    const catalog = await loadCatalog();
    renderPacks(panel, wrap, catalog);
    renderGrid(panel, wrap, catalog);
  }
  panel.hidden = false;
  wrap.classList.add("is-open");
  toggle.setAttribute("aria-expanded", "true");
  placePanel(wrap);
  hostOf(panel)?.querySelector<HTMLButtonElement>(".emoji-cell")?.focus();
}

export function emojiPickerIsOpen() {
  return Boolean(document.querySelector(".js-emoji-picker.is-open"));
}

export function mountEmojiPickers(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>(".js-emoji-picker").forEach((wrap) => {
    if (wrap.dataset.bound === "1") return;
    wrap.dataset.bound = "1";
    const toggle = toggleOf(wrap);
    const panel = panelOf(wrap);
    if (!toggle || !panel) return;
    dockPanel(wrap, panel);
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (wrap.classList.contains("is-open")) closeEmojiPicker(wrap);
      else void openEmojiPicker(wrap);
    });
    panel.querySelector(".js-emoji-close")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeEmojiPicker(wrap);
      toggle.focus();
    });
  });
}

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key !== "Escape" || !emojiPickerIsOpen()) return;
    closeAllEmojiPickers();
    event.preventDefault();
    event.stopPropagation();
  },
  true,
);

document.addEventListener(
  "pointerdown",
  (event) => {
    const target = event.target;
    if (!(target instanceof Node)) return;
    document.querySelectorAll<HTMLElement>(".js-emoji-picker.is-open").forEach((wrap) => {
      const panel = panelOf(wrap);
      if (wrap.contains(target) || panel?.contains(target)) return;
      closeEmojiPicker(wrap);
    });
  },
  true,
);

window.addEventListener("resize", () => {
  document.querySelectorAll<HTMLElement>(".js-emoji-picker.is-open").forEach(placePanel);
});
