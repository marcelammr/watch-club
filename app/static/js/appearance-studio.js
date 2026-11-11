(function () {
  const root = document.querySelector(".js-look-studio");
  if (!root) return;

  const themeField = root.querySelector(".js-look-theme");
  const paperField = root.querySelector(".js-look-paper");
  const preview = root.querySelector(".js-look-preview");
  const themeButtons = [...root.querySelectorAll("[data-theme-pick]")];
  const paperButtons = [...root.querySelectorAll("[data-paper-pick]")];

  function mark(buttons, attr, value) {
    buttons.forEach((btn) => {
      const on = btn.getAttribute(attr) === value;
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-checked", on ? "true" : "false");
    });
  }

  function paint() {
    if (!preview || !themeField || !paperField) return;
    const paperBtn = paperButtons.find((btn) => btn.getAttribute("data-paper-pick") === paperField.value);
    const kind = paperBtn?.getAttribute("data-paper-kind") || "css";
    const paperClass =
      paperBtn?.className.split(/\s+/).find((name) => name.startsWith("wc-paper-") && name !== "wc-paper-asset") ||
      "wc-paper-" + paperField.value;
    preview.className =
      "look-live js-look-preview wc-theme-" +
      themeField.value +
      " " +
      (kind === "image" ? "wc-paper-asset " : "") +
      paperClass;
    if (kind === "image" && paperBtn?.getAttribute("data-paper-src")) {
      preview.style.setProperty("--wc-wallpaper-src", "url('" + paperBtn.getAttribute("data-paper-src") + "')");
      preview.style.setProperty("--wc-wallpaper-size", paperBtn.getAttribute("data-paper-size") || "cover");
      preview.style.setProperty("--wc-wallpaper-repeat", paperBtn.getAttribute("data-paper-repeat") || "no-repeat");
      preview.style.setProperty("--wc-wallpaper-position", paperBtn.getAttribute("data-paper-position") || "center");
    } else {
      preview.style.removeProperty("--wc-wallpaper-src");
    }
  }

  themeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-theme-pick") || "watchclub";
      themeField.value = key;
      mark(themeButtons, "data-theme-pick", key);
      paint();
    });
  });

  paperButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-paper-pick") || "grid";
      paperField.value = key;
      mark(paperButtons, "data-paper-pick", key);
      paint();
    });
  });
})();
