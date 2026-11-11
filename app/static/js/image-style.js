(function () {
  const PREVIEW_URL = "/imagens/previsualizar";

  document.querySelectorAll(".image-studio").forEach(bindStudio);

  function bindStudio(dialog) {
    const preview = dialog.querySelector(".js-style-preview");
    const choices = [...dialog.querySelectorAll(".js-style-choice")];
    const hiddenFields = [
      ...dialog.querySelectorAll(".js-image-preset"),
      ...document.querySelectorAll(".js-photo-form .js-image-preset"),
      ...document.querySelectorAll('input[name="cover_preset"]'),
      ...document.querySelectorAll('input[name="icon_preset"]'),
    ];
    const saveBtn = dialog.querySelector(".js-style-save");
    if (!preview || !choices.length) return;

    let sourceFile = null;
    let previewUrl = null;
    let requestId = 0;

    function setPreset(value) {
      choices.forEach((btn) => {
        const on = btn.getAttribute("data-preset") === value;
        btn.classList.toggle("is-on", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
      const name = dialog.id === "cover-crop-dialog" ? "cover_preset"
        : dialog.id === "icon-crop-dialog" ? "icon_preset"
        : "preset";
      hiddenFields.forEach((field) => {
        if (field.name === name || field.classList.contains("js-image-preset")) {
          if (dialog.id === "cover-crop-dialog" && field.name === "preset") return;
          if (dialog.id === "icon-crop-dialog" && field.name === "preset") return;
          if (dialog.id === "photo-crop-dialog" && field.name !== "preset" && !field.classList.contains("js-image-preset")) return;
          field.value = value;
        }
      });
    }

    function revoke() {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
    }

    async function showPreview(preset) {
      if (!sourceFile) return;
      const current = ++requestId;
      if (preset === "original") {
        revoke();
        previewUrl = URL.createObjectURL(sourceFile);
        preview.src = previewUrl;
        return;
      }
      const data = new FormData();
      data.append("photo", sourceFile);
      data.append("preset", preset);
      try {
        const response = await fetch(PREVIEW_URL, { method: "POST", body: data });
        if (!response.ok || current !== requestId) return;
        const blob = await response.blob();
        if (current !== requestId) return;
        revoke();
        previewUrl = URL.createObjectURL(blob);
        preview.src = previewUrl;
      } catch (_) {
        /* keep last preview */
      }
    }

    dialog.addEventListener("wc:cropped", (event) => {
      sourceFile = event.detail && event.detail.file;
      setPreset("original");
      showPreview("original");
    });

    choices.forEach((btn) => {
      btn.addEventListener("click", () => {
        const preset = btn.getAttribute("data-preset") || "original";
        setPreset(preset);
        showPreview(preset);
      });
    });

    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        const form = document.querySelector(".js-photo-form");
        if (form && dialog.id === "photo-crop-dialog") {
          dialog.close();
          form.submit();
          return;
        }
        dialog.close();
      });
    }

    dialog.addEventListener("close", () => {
      sourceFile = null;
      revoke();
    });
  }

  document.querySelectorAll("form.avatar-style-form, .js-page-style").forEach(bindPageStyle);

  function bindPageStyle(form) {
    const hidden = form.querySelector(".js-image-preset");
    const choices = [...form.querySelectorAll(".js-style-choice")];
    const previewSel = form.getAttribute("data-preview") || "";
    const originalUrl = form.getAttribute("data-original-url") || "";
    let originalBlob = null;
    let previewUrl = null;
    let requestId = 0;

    function previewImg() {
      if (!previewSel) return null;
      return document.querySelector(previewSel);
    }

    function revoke() {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
    }

    async function ensureOriginal() {
      if (originalBlob) return originalBlob;
      if (!originalUrl) return null;
      const response = await fetch(originalUrl);
      if (!response.ok) return null;
      originalBlob = await response.blob();
      return originalBlob;
    }

    async function showPreview(preset) {
      const img = previewImg();
      if (!img || !originalUrl) return;
      const current = ++requestId;
      const blob = await ensureOriginal();
      if (!blob || current !== requestId) return;
      if (preset === "original") {
        revoke();
        previewUrl = URL.createObjectURL(blob);
        img.src = previewUrl;
        img.hidden = false;
        return;
      }
      const file = new File([blob], "preview.png", { type: blob.type || "image/png" });
      const data = new FormData();
      data.append("photo", file);
      data.append("preset", preset);
      try {
        const response = await fetch(PREVIEW_URL, { method: "POST", body: data });
        if (!response.ok || current !== requestId) return;
        const styled = await response.blob();
        if (current !== requestId) return;
        revoke();
        previewUrl = URL.createObjectURL(styled);
        img.src = previewUrl;
        img.hidden = false;
      } catch (_) {
        /* keep last preview */
      }
    }

    choices.forEach((btn) => {
      btn.addEventListener("click", () => {
        const preset = btn.getAttribute("data-preset") || "original";
        if (hidden) hidden.value = preset;
        choices.forEach((item) => {
          const on = item === btn;
          item.classList.toggle("is-on", on);
          item.setAttribute("aria-pressed", on ? "true" : "false");
        });
        showPreview(preset);
      });
    });
  }
})();
