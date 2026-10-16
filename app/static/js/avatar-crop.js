(function () {
  const STAGE = 280;
  const OUTPUT = 512;
  const MAX_BYTES = 12 * 1024 * 1024;
  const MAX_EDGE = 1600;
  const ZOOM_MAX = 4;

  const form = document.querySelector(".js-photo-form");
  const input = document.querySelector(".js-photo-input");
  const openBtn = document.querySelector(".js-photo-open");
  const dialog = document.getElementById("photo-crop-dialog");
  const canvas = dialog && dialog.querySelector(".js-crop-canvas");
  const zoom = dialog && dialog.querySelector(".js-crop-zoom");
  const errorEl = dialog && dialog.querySelector(".js-crop-error");
  const cancelBtns = dialog ? dialog.querySelectorAll(".js-crop-cancel") : [];
  const confirmBtn = dialog && dialog.querySelector(".js-crop-confirm");
  if (!form || !input || !openBtn || !dialog || !canvas || !zoom || !confirmBtn) return;

  const ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(STAGE * dpr);
  canvas.height = Math.round(STAGE * dpr);

  let bitmap = null;
  let objectUrl = null;
  let scale = 1;
  let minScale = 1;
  let x = 0;
  let y = 0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  function showError(message) {
    if (!errorEl) return;
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function revokeUrl() {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }

  function resetState() {
    bitmap = null;
    scale = 1;
    minScale = 1;
    x = 0;
    y = 0;
    dragging = false;
    zoom.value = "1";
    showError("");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    revokeUrl();
  }

  function closeDialog() {
    dialog.close();
    input.value = "";
    resetState();
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
    return type === "image/png" || type === "image/webp" || type === "image/gif";
  }

  openBtn.addEventListener("click", () => input.click());

  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > MAX_BYTES) {
      resetState();
      input.value = "";
      showError("A imagem é grande demais. Escolha uma foto de até 12 MB.");
      dialog.showModal();
      return;
    }
    resetState();
    try {
      bitmap = await limitBitmap(await loadFile(file));
      if (!bitmap.width || !bitmap.height) throw new Error("empty");
      setCover();
      dialog.showModal();
    } catch (_) {
      resetState();
      input.value = "";
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
    x += event.clientX - lastX;
    y += event.clientY - lastY;
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
    const rect = canvas.getBoundingClientRect();
    zoomTo(factor, event.clientX - rect.left, event.clientY - rect.top);
  }, { passive: false });

  zoom.addEventListener("input", () => {
    if (!bitmap) return;
    zoomTo(Number(zoom.value), STAGE / 2, STAGE / 2);
  });

  cancelBtns.forEach((btn) => btn.addEventListener("click", () => closeDialog()));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialog();
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDialog();
  });

  confirmBtn.addEventListener("click", async () => {
    if (!bitmap) return;
    const out = document.createElement("canvas");
    out.width = OUTPUT;
    out.height = OUTPUT;
    const octx = out.getContext("2d");
    const k = OUTPUT / STAGE;
    octx.drawImage(bitmap, x * k, y * k, bitmap.width * scale * k, bitmap.height * scale * k);
    const file = input.files && input.files[0];
    const png = file && hasTransparency(file);
    const mime = png ? "image/png" : "image/jpeg";
    const blob = await new Promise((resolve) => out.toBlob(resolve, mime, png ? undefined : 0.9));
    if (!blob) return;
    const cropped = new File([blob], png ? "avatar.png" : "avatar.jpg", { type: mime });
    const transfer = new DataTransfer();
    transfer.items.add(cropped);
    input.files = transfer.files;
    revokeUrl();
    dialog.close();
    form.submit();
  });
})();
