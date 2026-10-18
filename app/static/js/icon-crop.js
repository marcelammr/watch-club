(function () {
  const STAGE = 280;
  const OUTPUT = 512;
  const MAX_READ = 12 * 1024 * 1024;
  const MAX_UPLOAD = 2 * 1024 * 1024;
  const MAX_EDGE = 1600;
  const ZOOM_MAX = 4;

  const input = document.querySelector(".js-icon-file");
  const previewImg = document.querySelector(".js-icon-preview-img");
  const fallback = document.querySelector(".js-icon-fallback");
  const dialog = document.getElementById("icon-crop-dialog");
  const canvas = dialog && dialog.querySelector(".js-icon-crop-canvas");
  const zoom = dialog && dialog.querySelector(".js-icon-crop-zoom");
  const errorEl = dialog && dialog.querySelector(".js-icon-crop-error");
  const cancelBtns = dialog ? dialog.querySelectorAll(".js-icon-crop-cancel") : [];
  const confirmBtn = dialog && dialog.querySelector(".js-icon-crop-confirm");
  if (!input || !previewImg || !dialog || !canvas || !zoom || !confirmBtn) return;

  const ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(STAGE * dpr);
  canvas.height = Math.round(STAGE * dpr);

  let bitmap = null;
  let objectUrl = null;
  let previewUrl = null;
  let sourceFile = null;
  let scale = 1;
  let minScale = 1;
  let x = 0;
  let y = 0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  let committedSrc = previewImg.getAttribute("src") || "";
  let committedHidden = previewImg.hidden;

  function showError(message) {
    if (!errorEl) return;
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function showPreview(src) {
    if (src) {
      previewImg.src = src;
      previewImg.hidden = false;
      if (fallback) fallback.hidden = true;
    } else {
      previewImg.removeAttribute("src");
      previewImg.hidden = true;
      if (fallback) fallback.hidden = false;
    }
  }

  function restorePreview() {
    if (committedSrc && !committedHidden) showPreview(committedSrc);
    else showPreview("");
  }

  function revokeUrl(which) {
    if (which === "source" && objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
    if (which === "preview" && previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
  }

  function resetState() {
    bitmap = null;
    sourceFile = null;
    scale = 1;
    minScale = 1;
    x = 0;
    y = 0;
    dragging = false;
    zoom.value = "1";
    showError("");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    revokeUrl("source");
  }

  function closeDialog(clearInput) {
    dialog.close();
    if (clearInput) {
      input.value = "";
      restorePreview();
    }
    resetState();
  }

  function stagePoint(event) {
    const rect = canvas.getBoundingClientRect();
    const px = rect.width ? ((event.clientX - rect.left) * STAGE) / rect.width : 0;
    const py = rect.height ? ((event.clientY - rect.top) * STAGE) / rect.height : 0;
    return { x: px, y: py };
  }

  function clamp() {
    if (!bitmap) return;
    const dw = bitmap.width * scale;
    const dh = bitmap.height * scale;
    x = Math.min(0, Math.max(STAGE - dw, x));
    y = Math.min(0, Math.max(STAGE - dh, y));
  }

  function drawPreview() {
    if (!bitmap) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, STAGE, STAGE);
    ctx.drawImage(bitmap, x, y, bitmap.width * scale, bitmap.height * scale);
  }

  function setCover() {
    minScale = Math.max(STAGE / bitmap.width, STAGE / bitmap.height);
    scale = minScale;
    x = (STAGE - bitmap.width * scale) / 2;
    y = (STAGE - bitmap.height * scale) / 2;
    zoom.min = "1";
    zoom.max = String(ZOOM_MAX);
    zoom.step = "0.01";
    zoom.value = "1";
    clamp();
    drawPreview();
  }

  function zoomTo(factor, cx, cy) {
    const next = Math.min(minScale * ZOOM_MAX, Math.max(minScale, minScale * factor));
    const px = (cx - x) / scale;
    const py = (cy - y) / scale;
    scale = next;
    x = cx - px * scale;
    y = cy - py * scale;
    zoom.value = String(scale / minScale);
    clamp();
    drawPreview();
  }

  async function limitBitmap(source) {
    const w = source.width;
    const h = source.height;
    const max = Math.max(w, h);
    if (max <= MAX_EDGE) return source;
    const ratio = MAX_EDGE / max;
    const cw = Math.max(1, Math.round(w * ratio));
    const ch = Math.max(1, Math.round(h * ratio));
    const off = document.createElement("canvas");
    off.width = cw;
    off.height = ch;
    off.getContext("2d").drawImage(source, 0, 0, cw, ch);
    if (source.close) source.close();
    return off;
  }

  async function loadFile(file) {
    if (window.createImageBitmap) {
      try {
        return await createImageBitmap(file, { imageOrientation: "from-image" });
      } catch (_) {}
    }
    objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.src = objectUrl;
    await image.decode();
    return image;
  }

  function hasTransparency(file) {
    const type = (file.type || "").toLowerCase();
    return type === "image/png" || type === "image/webp";
  }

  function encodeFrame(out, mime, quality) {
    return new Promise((resolve) => {
      if (quality == null) out.toBlob(resolve, mime);
      else out.toBlob(resolve, mime, quality);
    });
  }

  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const type = (file.type || "").toLowerCase();
    if (type === "image/gif" || (file.name || "").toLowerCase().endsWith(".gif")) {
      resetState();
      input.value = "";
      restorePreview();
      showError("O ícone não aceita GIF. Use JPG, PNG ou WebP.");
      dialog.showModal();
      return;
    }
    if (file.size > MAX_READ) {
      resetState();
      input.value = "";
      restorePreview();
      showError("A imagem é grande demais. Escolha um arquivo de até 12 MB.");
      dialog.showModal();
      return;
    }
    resetState();
    sourceFile = file;
    try {
      bitmap = await limitBitmap(await loadFile(file));
      if (!bitmap.width || !bitmap.height) throw new Error("empty");
      setCover();
      dialog.showModal();
    } catch (_) {
      resetState();
      input.value = "";
      restorePreview();
      showError("Não foi possível ler esta imagem.");
      dialog.showModal();
    }
  });

  canvas.addEventListener("pointerdown", (event) => {
    if (!bitmap) return;
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging || !bitmap) return;
    const rect = canvas.getBoundingClientRect();
    const kx = rect.width ? STAGE / rect.width : 1;
    const ky = rect.height ? STAGE / rect.height : 1;
    x += (event.clientX - lastX) * kx;
    y += (event.clientY - lastY) * ky;
    lastX = event.clientX;
    lastY = event.clientY;
    clamp();
    drawPreview();
  });
  function stopDrag(event) {
    dragging = false;
    if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  }
  canvas.addEventListener("pointerup", stopDrag);
  canvas.addEventListener("pointercancel", stopDrag);

  canvas.addEventListener("wheel", (event) => {
    if (!bitmap) return;
    event.preventDefault();
    const factor = Number(zoom.value) * (event.deltaY < 0 ? 1.08 : 1 / 1.08);
    const pt = stagePoint(event);
    zoomTo(factor, pt.x, pt.y);
  }, { passive: false });

  zoom.addEventListener("input", () => {
    if (!bitmap) return;
    zoomTo(Number(zoom.value), STAGE / 2, STAGE / 2);
  });

  cancelBtns.forEach((btn) => btn.addEventListener("click", () => closeDialog(true)));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialog(true);
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDialog(true);
  });

  confirmBtn.addEventListener("click", async () => {
    if (!bitmap) return;
    const out = document.createElement("canvas");
    out.width = OUTPUT;
    out.height = OUTPUT;
    const octx = out.getContext("2d");
    const k = OUTPUT / STAGE;
    octx.drawImage(bitmap, x * k, y * k, bitmap.width * scale * k, bitmap.height * scale * k);
    const png = sourceFile && hasTransparency(sourceFile);
    let mime = png ? "image/png" : "image/jpeg";
    let blob = await encodeFrame(out, mime, png ? undefined : 0.9);
    if (blob && blob.size > MAX_UPLOAD) {
      mime = "image/jpeg";
      blob = await encodeFrame(out, mime, 0.85);
    }
    if (!blob || blob.size > MAX_UPLOAD) {
      showError("O recorte ficou grande demais. Aproxime menos o zoom ou use JPEG.");
      return;
    }
    const name = mime === "image/png" ? "icon.png" : "icon.jpg";
    const cropped = new File([blob], name, { type: mime });
    const transfer = new DataTransfer();
    transfer.items.add(cropped);
    input.files = transfer.files;
    revokeUrl("preview");
    previewUrl = URL.createObjectURL(cropped);
    committedSrc = previewUrl;
    committedHidden = false;
    showPreview(previewUrl);
    revokeUrl("source");
    dialog.close();
    resetState();
  });

  window.addEventListener("club-icon-cleared", () => {
    committedSrc = "";
    committedHidden = true;
    input.value = "";
    showPreview("");
  });
})();
