(() => {
  "use strict";
  if (globalThis.screenTranslation) return;
  const selector = "script,style,noscript,textarea,input,select,[contenteditable],svg,math,code,pre";
  const documentID = Math.random().toString(36).slice(2);
  let configuration = 0, session = documentID + ":0";
  const ids = new WeakMap();
  let nextID = 0, entries = new Map();
  let region = { x: 0, y: 0, w: 1, h: 1 }, mode = "off";
  let revision = 0, dirty = true, raf = 0, layer, hidden = false, ocr = [];
  const cache = new Map(), measure = document.createElement("canvas").getContext("2d");
  const viewport = () => {
    const v = window.visualViewport;
    return { x: v?.offsetLeft || 0, y: v?.offsetTop || 0, w: v?.width || innerWidth, h: v?.height || innerHeight };
  };
  const area = (v = viewport()) => ({
    x: v.x + region.x * v.w, y: v.y + region.y * v.h, w: region.w * v.w, h: region.h * v.h
  });
  const intersects = (r, b) => r.right > b.x && r.left < b.x + b.w && r.bottom > b.y && r.top < b.y + b.h;
  const within = (r, b) => intersects(r, b) && r.left >= b.x - 1 && r.top >= b.y - 1 &&
    r.right <= b.x + b.w + 1 && r.bottom <= b.y + b.h + 1;
  const clean = s => s.trim().replace(/\s+/gu, " ");
  const key = (t, lang) => JSON.stringify([t, lang]);
  const insideLayer = n => Boolean(layer && (n === layer || layer.contains(n)));
  function root() {
    if (layer?.isConnected) return layer;
    layer = document.createElement("div");
    layer.setAttribute("aria-hidden", "true");
    layer.style.cssText = "all:initial!important;position:absolute!important;left:0!important;top:0!important;width:0!important;height:0!important;z-index:2147483647!important;pointer-events:none!important;";
    document.documentElement.append(layer);
    return layer;
  }
  function bounds(node) {
    const r = document.createRange();
    r.setStart(node, node.data.length - node.data.trimStart().length);
    r.setEnd(node, node.data.trimEnd().length);
    return [...r.getClientRects()].filter(b => b.width > 2 && b.height > 3);
  }
  function visible(node) {
    if (!node?.isConnected || insideLayer(node) || node.closest(selector)) return false;
    if (node.checkVisibility && !node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const s = getComputedStyle(node);
    return s.visibility === "visible" && s.display !== "none" && s.opacity !== "0";
  }
  function backdrop(node) {
    for (let n = node; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && c !== "transparent" && !c.startsWith("rgba(") && !/\/\s*(?:0(?:\.\d+)?|\d+%)\s*\)/u.test(c)) return c;
      if (/^rgba\([^)]*,\s*1\s*\)$/u.test(c)) return c;
    }
    return matchMedia("(prefers-color-scheme: dark)").matches ? "#171717" : "#fff";
  }
  function boxesForText(text, rects, style) {
    const requested = Math.max(8, style.size);
    for (let size = requested; size >= Math.max(7, requested * .65); size -= 1) {
      measure.font = `${style.weight} ${size}px ${style.family}`;
      let rest = text;
      const lines = [];
      for (const box of rects) {
        if (!rest) { lines.push(""); continue; }
        if (measure.measureText(rest).width <= box.width + .1) {
          lines.push(rest); rest = ""; continue;
        }
        const chars = Array.from(rest);
        let fit = 0, hi = chars.length;
        while (fit < hi) {
          const mid = Math.ceil((fit + hi) / 2);
          if (measure.measureText(chars.slice(0, mid).join("")).width <= box.width + .1) fit = mid;
          else hi = mid - 1;
        }
        let whitespace = fit;
        while (whitespace > 0 && !/\s/u.test(chars[whitespace - 1])) whitespace--;
        if (whitespace > fit * .65 && whitespace < fit) fit = whitespace;
        lines.push(chars.slice(0, fit).join("").trim());
        rest = chars.slice(fit).join("").trimStart();
      }
      if (!rest) return { lines, size };
    }
    return null;
  }
  function draw(box, text, style, size, at) {
    const s = document.createElement("span");
    s.style.cssText = "all:initial!important;position:absolute!important;display:block!important;white-space:nowrap!important;overflow:hidden!important;pointer-events:none!important;box-sizing:border-box!important;text-align:left!important;";
    const values = {
      left: `${box.left - at.left}px`, top: `${box.top - at.top}px`,
      width: `${box.width}px`, height: `${box.height}px`, color: style.color,
      background: style.background, "font-family": style.family, "font-size": `${size}px`,
      "font-weight": style.weight, "line-height": `${box.height}px`
    };
    for (const [name, value] of Object.entries(values)) s.style.setProperty(name, value, "important");
    s.textContent = text;
    layer.append(s);
  }
  function drawEntry(text, boxes, style, at) {
    const fit = boxesForText(text, boxes, style);
    if (!fit) return;
    boxes.forEach((b, i) => draw(b, fit.lines[i], style, fit.size, at));
  }
  function repaint() {
    raf = 0;
    if (mode === "off") { layer?.replaceChildren(); return; }
    root().replaceChildren();
    if (hidden) return;
    const a = area(), at = layer.getBoundingClientRect();
    if (mode === "ocr") {
      for (const item of ocr) {
        const b = { left: item.x, top: item.y, width: item.w, height: item.h,
          right: item.x + item.w, bottom: item.y + item.h };
        if (within(b, a)) drawEntry(item.text, [b], {
          size: item.h * .85, weight: "400", family: "sans-serif", color: item.color, background: item.background
        }, at);
      }
      return;
    }
    for (const { node, text, lang } of entries.values()) {
      const translation = cache.get(key(text, lang));
      if (!translation || clean(node.data) !== text || !visible(node.parentElement)) continue;
      const rects = bounds(node);
      if (!rects.length || !rects.every(b => within(b, a))) continue;
      const s = getComputedStyle(node.parentElement);
      drawEntry(translation, rects, {
        size: parseFloat(s.fontSize) || 14, family: s.fontFamily, weight: s.fontWeight,
        color: s.color, background: backdrop(node.parentElement)
      }, at);
    }
  }
  function invalidate() {
    dirty = true;
    revision++;
    if (mode === "ocr") {
      ocr = [];
      layer?.replaceChildren();
    }
    if (mode === "dom" && !raf) raf = requestAnimationFrame(repaint);
  }
  const observer = new MutationObserver(records => {
    if (records.some(r => !insideLayer(r.target) &&
      (r.type !== "childList" || [...r.addedNodes, ...r.removedNodes].some(n => !insideLayer(n))))) invalidate();
  });
  observer.observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ["lang", "class", "style", "hidden", "src", "open"]
  });
  window.addEventListener("scroll", invalidate, { capture: true, passive: true });
  window.addEventListener("resize", invalidate, { passive: true });
  window.addEventListener("load", invalidate, { capture: true });
  window.visualViewport?.addEventListener("resize", invalidate, { passive: true });
  window.visualViewport?.addEventListener("scroll", invalidate, { passive: true });
  if (document.body && typeof ResizeObserver === "function") new ResizeObserver(invalidate).observe(document.body);
  document.fonts?.addEventListener("loadingdone", invalidate);

  function scan() {
    if (mode !== "dom" || !document.body) return { session, changed: false, items: [] };
    if (!dirty) return { session, changed: false, items: [] };
    dirty = false;
    const a = area(), matches = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    // Bound traversal cost on long pages; sort eligible text by visual position below.
    for (let count = 0, n; count < 18000 && (n = walker.nextNode()); count++) {
      const text = clean(n.data), parent = n.parentElement;
      if (text.length < 2 || text.length > 700 || !/\p{L}/u.test(text) || !visible(parent)) continue;
      const rects = bounds(n);
      if (!rects.length || !rects.every(b => within(b, a))) continue;
      const lang = parent.closest("[lang]")?.getAttribute("lang") || "";
      if (!ids.has(n)) ids.set(n, String(++nextID));
      matches.push({ node: n, id: ids.get(n), text, lang, y: rects[0].top, x: rects[0].left });
    }
    matches.sort((a, b) => a.y - b.y || a.x - b.x);
    const top = matches.slice(0, 96);
    entries = new Map(top.map(e => [e.id, e]));
    repaint();
    return { session, changed: true, items: top.filter(e => !cache.has(key(e.text, e.lang)))
      .map(({ id, text, lang }) => ({ id, text, lang })) };
  }
  globalThis.screenTranslation = {
    configure(newMode, selection) {
      mode = newMode;
      region = selection;
      session = documentID + ":" + (++configuration);
      entries.clear(); cache.clear(); ocr = [];
      invalidate(); repaint();
      return session;
    },
    scan,
    accept(domSession, items) {
      if (mode !== "dom" || session !== domSession) return false;
      for (const e of items) {
        cache.set(key(e.original, e.lang), e.translation);
        if (cache.size > 1500) cache.delete(cache.keys().next().value);
      }
      repaint();
      return true;
    },
    retry() { dirty = true; },
    setHidden(value) { hidden = value; repaint(); },
    metrics() {
      const v = viewport(), a = area(v);
      return { session, revision, x: a.x, y: a.y, w: a.w, h: a.h,
        vx: v.x, vy: v.y, vw: v.w, vh: v.h,
        scrollX, scrollY };
    },
    applyOCR(stamp, items) {
      if (mode !== "ocr" || stamp.session !== session || stamp.revision !== revision ||
          stamp.scrollX !== scrollX || stamp.scrollY !== scrollY) return false;
      ocr = items; repaint(); return true;
    }
  };
})();
