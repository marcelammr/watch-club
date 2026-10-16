import { closeAllEmojiPickers } from "./emoji-picker";

type IroColor = { hexString: string };
type IroPicker = {
  color: IroColor;
  on: (event: string, callback: (color: IroColor) => void) => void;
};
type IroModule = {
  default?: IroNS;
  ColorPicker: new (el: HTMLElement, opts: Record<string, unknown>) => IroPicker;
  ui: { Box: unknown; Slider: unknown };
};
type IroNS = {
  ColorPicker: IroModule["ColorPicker"];
  ui: IroModule["ui"];
};

const HEX_RE = /^#[0-9A-F]{6}$/;
let iroPromise: Promise<IroNS> | null = null;

function loadIro() {
  if (!iroPromise) {
    iroPromise = import("@jaames/iro").then((mod) => {
      const loaded = (mod as IroModule).default ?? (mod as IroNS);
      return loaded;
    });
  }
  return iroPromise;
}

export function normalizeHex(value: string | null | undefined): string | null {
  const text = (value || "").trim().toUpperCase();
  return HEX_RE.test(text) ? text : null;
}

function panelOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLElement>(".js-color-panel");
}

function toggleOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLButtonElement>(".js-color-toggle");
}

function valueInputOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLInputElement>(".js-color-value");
}

function hexInputOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLInputElement>(".js-color-hex");
}

function mountOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLElement>(".js-color-iro");
}

export function closeColorPicker(wrap: HTMLElement) {
  wrap.classList.remove("is-open");
  toggleOf(wrap)?.setAttribute("aria-expanded", "false");
  const panel = panelOf(wrap);
  if (panel) panel.hidden = true;
}

export function closeAllColorPickers(except?: HTMLElement) {
  document.querySelectorAll<HTMLElement>(".js-color-picker.is-open").forEach((wrap) => {
    if (wrap !== except) closeColorPicker(wrap);
  });
}

function currentHex(wrap: HTMLElement) {
  return normalizeHex(valueInputOf(wrap)?.value) || "#B892FF";
}

function markPresets(wrap: HTMLElement, hex: string) {
  wrap.querySelectorAll<HTMLElement>(".js-color-preset").forEach((btn) => {
    btn.classList.toggle("is-on", normalizeHex(btn.dataset.hex) === hex);
  });
}

function paintPreview(wrap: HTMLElement, hex: string) {
  wrap.querySelectorAll<HTMLElement>(".js-color-preview").forEach((node) => {
    node.style.setProperty("--swatch", hex);
  });
}

function commitHex(wrap: HTMLElement, raw: string, syncIro = true) {
  const hex = normalizeHex(raw);
  if (!hex) return;
  const hidden = valueInputOf(wrap);
  const hexField = hexInputOf(wrap);
  if (hidden) hidden.value = hex;
  if (hexField && hexField.value.toUpperCase() !== hex) hexField.value = hex;
  paintPreview(wrap, hex);
  markPresets(wrap, hex);
  const picker = (wrap as HTMLElement & { _iro?: IroPicker })._iro;
  if (syncIro && picker && picker.color.hexString.toUpperCase() !== hex) {
    picker.color.hexString = hex;
  }
  wrap.dispatchEvent(
    new CustomEvent("color-change", {
      bubbles: true,
      detail: { hex },
    }),
  );
}

async function openColorPicker(wrap: HTMLElement) {
  const panel = panelOf(wrap);
  const toggle = toggleOf(wrap);
  const mount = mountOf(wrap);
  if (!panel || !toggle || !mount) return;
  closeAllColorPickers(wrap);
  closeAllEmojiPickers();
  if (!panel.dataset.ready) {
    const iro = await loadIro();
    const picker = new iro.ColorPicker(mount, {
      width: 220,
      color: currentHex(wrap),
      borderWidth: 1,
      borderColor: "rgba(247, 240, 255, 0.16)",
      layout: [
        { component: iro.ui.Box },
        { component: iro.ui.Slider, options: { sliderType: "hue" } },
      ],
    });
    picker.on("color:change", (color) => {
      commitHex(wrap, color.hexString, false);
    });
    (wrap as HTMLElement & { _iro?: IroPicker })._iro = picker;
    panel.dataset.ready = "1";
  } else {
    const picker = (wrap as HTMLElement & { _iro?: IroPicker })._iro;
    if (picker) picker.color.hexString = currentHex(wrap);
  }
  panel.hidden = false;
  wrap.classList.add("is-open");
  toggle.setAttribute("aria-expanded", "true");
}

export function colorPickerIsOpen() {
  return Boolean(document.querySelector(".js-color-picker.is-open"));
}

export function setColorPickerHex(wrap: HTMLElement, raw: string) {
  commitHex(wrap, raw);
}

export function mountColorPickers(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>(".js-color-picker").forEach((wrap) => {
    if (wrap.dataset.bound === "1") return;
    wrap.dataset.bound = "1";
    commitHex(wrap, currentHex(wrap), false);
    wrap.querySelectorAll<HTMLElement>(".js-color-preset").forEach((btn) => {
      btn.addEventListener("click", () => {
        commitHex(wrap, btn.dataset.hex || "");
      });
    });
    hexInputOf(wrap)?.addEventListener("input", (event) => {
      const field = event.target as HTMLInputElement;
      const hex = normalizeHex(field.value.startsWith("#") ? field.value : `#${field.value}`);
      if (hex) commitHex(wrap, hex);
    });
    hexInputOf(wrap)?.addEventListener("blur", (event) => {
      const field = event.target as HTMLInputElement;
      field.value = currentHex(wrap);
    });
    const toggle = toggleOf(wrap);
    if (!toggle) return;
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (wrap.classList.contains("is-open")) closeColorPicker(wrap);
      else void openColorPicker(wrap);
    });
  });
}

document.addEventListener(
  "pointerdown",
  (event) => {
    const target = event.target;
    if (!(target instanceof Node)) return;
    document.querySelectorAll<HTMLElement>(".js-color-picker.is-open").forEach((wrap) => {
      if (!wrap.contains(target)) closeColorPicker(wrap);
    });
  },
  true,
);

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key !== "Escape" || !colorPickerIsOpen()) return;
    closeAllColorPickers();
    event.preventDefault();
    event.stopPropagation();
  },
  true,
);
