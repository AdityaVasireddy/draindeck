// Minimal, self-contained DOM shim shared by RED tests that need real
// dialog/page click-and-close behavior (project convention -- see
// test_dashboard_run_readiness_ui.mjs / test_proxy_cost_render.mjs for the
// lighter single-file precedent -- no dependency install; runs under plain
// `node`). Supports exactly what dom.js / dialog.js / the pages under test
// touch: element creation/attributes, a small CSS-subset query engine
// (#id, .class, tag, [attr], [attr="value"], the one ":not([tabindex="-1"])"
// suffix dialog.js uses, and two-level descendant selectors like
// ".run-control-table tbody"), event listeners, and a document with a body.

class FakeNode {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.nodeType = 1;
    this.childNodes = [];
    this.parentNode = null;
    this._attrs = {};
    this._listeners = {};
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.offsetParent = {}; // truthy: "visible" by default
    this._text = "";
  }

  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  hasAttribute(k) { return k in this._attrs; }

  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    this.childNodes.push(c);
    c.parentNode = this;
    return c;
  }

  append(...nodes) {
    for (const n of nodes) this.appendChild(typeof n === "string" ? new FakeText(n) : n);
  }

  removeChild(c) {
    const idx = this.childNodes.indexOf(c);
    if (idx >= 0) this.childNodes.splice(idx, 1);
    c.parentNode = null;
    return c;
  }

  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }

  insertBefore(newNode, refNode) {
    if (newNode.parentNode) newNode.parentNode.removeChild(newNode);
    if (refNode) {
      const idx = this.childNodes.indexOf(refNode);
      if (idx === -1) throw new Error("insertBefore: refNode is not a child");
      this.childNodes.splice(idx, 0, newNode);
    } else {
      this.childNodes.push(newNode);
    }
    newNode.parentNode = this;
    return newNode;
  }

  get firstChild() { return this.childNodes[0] || null; }

  get nextSibling() {
    if (!this.parentNode) return null;
    const idx = this.parentNode.childNodes.indexOf(this);
    return this.parentNode.childNodes[idx + 1] || null;
  }

  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }

  set textContent(v) {
    this.childNodes = [];
    this._text = String(v);
  }

  get textContent() {
    if (this.nodeType === 3) return this._text;
    return this._text + this.childNodes.map((c) => c.textContent).join("");
  }

  addEventListener(type, handler) {
    (this._listeners[type] = this._listeners[type] || []).push(handler);
  }

  removeEventListener(type, handler) {
    const arr = this._listeners[type];
    if (!arr) return;
    const idx = arr.indexOf(handler);
    if (idx >= 0) arr.splice(idx, 1);
  }

  dispatch(type, event) {
    for (const h of (this._listeners[type] || [])) h(event || { type });
  }

  click() { this.dispatch("click", { type: "click" }); }

  focus() { globalThis.document.activeElement = this; }

  contains(node) {
    let n = node;
    while (n) {
      if (n === this) return true;
      n = n.parentNode;
    }
    return false;
  }

  closest(selector) {
    let n = this;
    while (n) {
      if (n.nodeType === 1 && _matchSimple(n, selector)) return n;
      n = n.parentNode;
    }
    return null;
  }

  querySelector(selector) { return _queryAll(this, selector)[0] || null; }
  querySelectorAll(selector) { return _queryAll(this, selector); }
}

class FakeText extends FakeNode {
  constructor(v) {
    super("#text");
    this.nodeType = 3;
    this._text = String(v);
  }
}

function _matchSimple(node, rawSel) {
  let sel = rawSel.trim();
  let notSel = null;
  const notIdx = sel.indexOf(":not(");
  if (notIdx >= 0 && sel.endsWith(")")) {
    notSel = sel.slice(notIdx + 5, sel.length - 1);
    sel = sel.slice(0, notIdx);
  }
  let ok;
  if (sel === "") {
    ok = false;
  } else if (sel.startsWith("#")) {
    ok = node.getAttribute("id") === sel.slice(1);
  } else if (sel.startsWith(".")) {
    ok = (node.className || "").split(/\s+/).filter(Boolean).includes(sel.slice(1));
  } else if (sel.startsWith("[")) {
    const inner = sel.slice(1, -1);
    const eq = inner.indexOf("=");
    if (eq === -1) {
      ok = node.getAttribute(inner) !== null;
    } else {
      const attr = inner.slice(0, eq);
      const val = inner.slice(eq + 1).replace(/^"(.*)"$/, "$1");
      ok = node.getAttribute(attr) === val;
    }
  } else {
    ok = node.tagName === sel.toUpperCase();
  }
  if (!ok) return false;
  if (notSel && _matchSimple(node, notSel)) return false;
  return true;
}

function _queryAll(root, selectorGroup) {
  const groups = selectorGroup.split(",").map((s) => s.trim());
  function matchesGroup(node, group) {
    const steps = group.split(/\s+/).filter(Boolean);
    if (steps.length === 0) return false;
    if (!_matchSimple(node, steps[steps.length - 1])) return false;
    let stepIdx = steps.length - 2;
    let anc = node.parentNode;
    while (anc && stepIdx >= 0) {
      if (_matchSimple(anc, steps[stepIdx])) stepIdx -= 1;
      anc = anc.parentNode;
    }
    return stepIdx < 0;
  }
  const results = [];
  function walk(node) {
    for (const child of node.childNodes) {
      if (child.nodeType === 1) {
        if (groups.some((g) => matchesGroup(child, g))) results.push(child);
        walk(child);
      }
    }
  }
  walk(root);
  return results;
}

/** Installs `globalThis.document`. Call once at the top of a test file,
    before importing any module under test. */
export function installDomShim() {
  const doc = {
    _listeners: {},
    body: new FakeNode("body"),
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (v) => new FakeText(v),
    addEventListener(type, handler) {
      (this._listeners[type] = this._listeners[type] || []).push(handler);
    },
    removeEventListener(type, handler) {
      const arr = this._listeners[type];
      if (!arr) return;
      const idx = arr.indexOf(handler);
      if (idx >= 0) arr.splice(idx, 1);
    },
  };
  doc.activeElement = doc.body;
  globalThis.document = doc;
  return doc;
}

export { FakeNode, FakeText };
