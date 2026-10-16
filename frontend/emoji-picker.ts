type PickerEmoji = { native?: string };

type MartModule = {
  Picker: new (props: Record<string, unknown>) => HTMLElement;
};

let martPromise: Promise<{ Picker: MartModule["Picker"]; data: unknown; i18n: unknown }> | null = null;

function loadMart() {
  if (!martPromise) {
    martPromise = Promise.all([
      import("emoji-mart") as Promise<MartModule>,
      import("@emoji-mart/data"),
      import("@emoji-mart/data/i18n/pt.json"),
    ]).then(([mart, data, i18n]) => ({
      Picker: mart.Picker,
      data: (data as { default?: unknown }).default ?? data,
      i18n: (i18n as { default?: unknown }).default ?? i18n,
    }));
  }
  return martPromise;
}

function panelOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLElement>(".js-emoji-panel");
}

function toggleOf(wrap: HTMLElement) {
  return wrap.querySelector<HTMLButtonElement>(".js-emoji-toggle");
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
  if (!panel.dataset.ready) {
    const { Picker, data, i18n } = await loadMart();
    const picker = new Picker({
      data,
      i18n,
      theme: "dark",
      locale: "pt",
      previewPosition: "none",
      skinTonePosition: "search",
      navPosition: "top",
      searchPosition: "sticky",
      maxFrequentRows: 2,
      onEmojiSelect: (emoji: PickerEmoji) => {
        wrap.dispatchEvent(
          new CustomEvent("emoji-select", {
            bubbles: true,
            detail: { emoji: emoji.native || "" },
          }),
        );
        if (wrap.dataset.emojiMode !== "tag") closeEmojiPicker(wrap);
      },
      onClickOutside: (event?: Event) => {
        const target = event?.target;
        if (target instanceof Node && wrap.contains(target)) return;
        closeEmojiPicker(wrap);
      },
    });
    panel.replaceChildren(picker);
    panel.dataset.ready = "1";
  }
  panel.hidden = false;
  wrap.classList.add("is-open");
  toggle.setAttribute("aria-expanded", "true");
}

export function emojiPickerIsOpen() {
  return Boolean(document.querySelector(".js-emoji-picker.is-open"));
}

export function mountEmojiPickers(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>(".js-emoji-picker").forEach((wrap) => {
    if (wrap.dataset.bound === "1") return;
    wrap.dataset.bound = "1";
    const toggle = toggleOf(wrap);
    if (!toggle) return;
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (wrap.classList.contains("is-open")) closeEmojiPicker(wrap);
      else void openEmojiPicker(wrap);
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
