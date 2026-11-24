"""Layout audit: measure text overflow on every desk screen, with pictures.

The tool boots an isolated copy of the desk (temporary data folder,
file-backed keychain, loopback mock model, no real keychain and no real
``~/.agent-desk``), drives it with Playwright, and records what the
browser actually lays out. Findings are plain JSON; screenshots are the
evidence. The probe is deterministic: the same viewports, themes, routes
and visit order every time, so a later run can be compared with this one.

Usage (from anywhere, with an ephemeral Playwright environment):

    uv run --no-project --with playwright --with keyring --with cryptography \
        python "<worktree>/tools/layout_audit.py"

Useful filters:

    --conditions fresh,full   --widths 1024,1280   --themes unkey
    --routes settings,marketplace   --no-stress   --out DIR
    --only-condition fresh   --fail-on high

The tool refuses to run on a real desk: every ``AGENTDESK_*`` variable is
pinned before ``agentdesk`` is imported, and ``AGENTDESK_DATA`` always
points at a fresh temporary folder.

Coverage is part of the result. After writing the outputs, a run where any
planned combination is not ``measured`` (an auth failure, a wrong-page
redirect, a theme that did not apply, an error, a child that died) prints
``COVERAGE INCOMPLETE`` with the count and reasons and exits 3, whatever
``--fail-on`` says. Overlay states that were explicitly found unreachable
are status ``skipped``, are listed in the summary, and do not fail the
run. Pass ``--allow-partial`` to keep the exit code from coverage alone.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "build" / "layout-audit"
FIXED_TIME = "2026-11-24T12:00:00Z"
FIXED_EPOCH = 1795521600.0
LONG_VALUES_FIXTURE = ROOT / "tools" / "layout_fixtures" / "long-values.api.json"
PENDING_SELECTOR = 'button,[role="button"],input[type="submit"],input[type="button"]'
PENDING_ENUM_JS = r"""
(arg) => {
  function visible(el) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') < 0.01) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  }
  function path(el) {
    const parts = [el.tagName.toLowerCase()];
    const cls = Array.from(el.classList || []).slice(0, 3);
    if (cls.length) parts[0] += '.' + cls.join('.');
    return parts.join('.');
  }
  const ordinals = {};
  return Array.from(document.querySelectorAll(arg.selector)).filter(visible).map(function(el, index) {
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 160);
    const key = path(el) + '|' + text;
    const ordinal = ordinals[key] || 0;
    ordinals[key] = ordinal + 1;
    return {index:index, ordinal:ordinal, tag:el.tagName.toLowerCase(), classes:String(el.className || ''),
            path:path(el), text:text,
            disabled:!!el.disabled, ariaBusy:el.getAttribute('aria-busy') || '',
            type:el.getAttribute('type') || ''};
  });
}
"""
PENDING_STATE_JS = r"""
(arg) => {
  function visible(el) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') < 0.01) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  }
  function path(el) {
    const parts = [el.tagName.toLowerCase()];
    const cls = Array.from(el.classList || []).slice(0, 3);
    if (cls.length) parts[0] += '.' + cls.join('.');
    return parts.join('.');
  }
  const found = [];
  for (const candidate of document.querySelectorAll(arg.selector)) {
    if (!visible(candidate)) continue;
    const text = (candidate.innerText || candidate.value || candidate.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 160);
    if (path(candidate) === arg.path && text === arg.text) found.push(candidate);
  }
  const el = found[arg.ordinal] || found[0] || null;
  const info = el ? {tag:el.tagName.toLowerCase(), classes:String(el.className || ''),
                     path:path(el), text:(el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 160),
                     disabled:!!el.disabled, ariaBusy:el.getAttribute('aria-busy') || ''} : null;
  const indicators = [];
  const seen = new Set();
  for (const selector of ['[aria-busy="true"]','[role="progressbar"]',
                          '[class*="skel"],[class*="skeleton"],[class*="busy"]']) {
    for (const node of document.querySelectorAll(selector)) {
      if (!visible(node) || seen.has(node)) continue;
      seen.add(node);
      indicators.push({path:path(node), text:(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)});
    }
  }
  const permanentWire = new Set(['wire','wire-chart','wire-copy','wire-rows','wire-lines',
                                 'wire-wide','moves-wire','setup-open-wire','wire-state']);
  for (const node of document.querySelectorAll('[class*="wire"]')) {
    const classes = String(node.className || '').split(/\s+/);
    const dynamic = classes.some(function(name) {
      return name.indexOf('wire') >= 0 && !permanentWire.has(name);
    });
    if (!dynamic || !visible(node) || seen.has(node)) continue;
    seen.add(node);
    indicators.push({path:path(node), text:(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)});
  }
  return {control:info,
          labelChanged: !!(info && arg.before && info.text !== arg.before),
          ariaBusy: !!(info && info.ariaBusy === 'true'),
          indicators:indicators.slice(0, 8),
          url:location.pathname + location.search};
}
"""

VIEWPORT_HEIGHT = 800
BASE_WIDTHS = (1024, 1280)
THEME_WIDTHS = (1024, 1280)
EXTREME_WIDTHS = (800, 1920)
BASE_CONDITIONS = ("fresh", "data", "plugins", "full", "long-values", "busy")
ALL_CONDITIONS = ("fresh", "data", "plugins", "full", "long-values", "busy",
                  "legacy-dashboard")
THEMES = ("unkey", "coforge", "momentuum")
STRESS_CONDITIONS = ("fresh", "full")
STRESS_WIDTHS = (1024, 1280)

# Every environment variable the product reads, from a grep of src/agentdesk.
# They are all pinned before agentdesk is imported; an empty value is a real
# value and beats ~/.agent-desk/config.env under load_env_file's setdefault.
PINNED_EMPTY = (
    "AGENTDESK_LLM_BASE",
    "AGENTDESK_LLM_KEY",
    "AGENTDESK_LLM_MODEL",
    "AGENTDESK_CALENDAR_FILE",
    "AGENTDESK_MAIL_FOLDER",
    "AGENTDESK_REGISTRY",
    "AGENTDESK_MARKETPLACE_ADMIN",
    "AGENTDESK_TEMPLATES",
)

PLAYWRIGHT_HELP = (
    "layout_audit needs Playwright: run "
    "`uv run --no-project --with playwright --with keyring --with cryptography "
    "python tools/layout_audit.py`"
)

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the documented environment has it
    sync_playwright = None
    PlaywrightTimeoutError = Exception

# The browser probe. One string, run through page.evaluate, returning plain
# JSON. It is deliberately dependency free: no npm, no helper library.
PROBE_JS = r"""
(() => {
  const STRESS = !!window.__AGENTDESK_LAYOUT_STRESS__;
  const VW = window.innerWidth;
  const VH = window.innerHeight;
  const OUT = [];
  const SKIP_TEXT_TAGS = {SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1, TEXTAREA:1};
  const GENERIC_HIGH_CLASS = /(^|[\s_-])(btn|button|badge|chip|card|cell|widget|tab|pill|status)([\s_-]|$)/;

  function r2(n) { return Math.round(n * 100) / 100; }
  function tagOf(el) { return el && el.tagName ? el.tagName.toLowerCase() : ''; }
  function classList(el) { return el ? Array.from(el.classList || []) : []; }
  function classString(el) { return classList(el).sort().join(' '); }
  function inSvg(el) { return !!(el && el.closest && el.closest('svg')); }
  function inClosedDetails(el) {
    let a = el;
    let hops = 0;
    while (a && a !== document.body && hops < 40) {
      if (a.tagName === 'DETAILS' && !a.open) {
        const summary = a.querySelector(':scope > summary');
        if (!(summary && (summary === el || summary.contains(el)))) return true;
      }
      a = a.parentElement;
      hops++;
    }
    return false;
  }
  function inBlockedTag(el) {
    if (!el || el.nodeType !== 1) return true;
    if (SKIP_TEXT_TAGS[el.tagName]) return true;
    if (el.tagName !== 'SVG' && inSvg(el)) return true;
    return false;
  }
  function styleOf(el) {
    try { return getComputedStyle(el); } catch (e) { return null; }
  }
  function rectOf(el) {
    const r = el.getBoundingClientRect();
    return {x:r.x, y:r.y, w:r.width, h:r.height, left:r.left, top:r.top,
            right:r.right, bottom:r.bottom, width:r.width, height:r.height};
  }
  function isSrOnly(el) {
    const c = (el.getAttribute('class') || '');
    if (/(^|\s)(sr-only|mkt-sr-only|visually-hidden|screen-reader|sr_only)(\s|$)/.test(c)) return true;
    const s = styleOf(el);
    if (!s) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 2 && r.height <= 2 && (s.position === 'absolute' || s.position === 'fixed')) {
      if ((s.clip && s.clip !== 'auto') || (s.clipPath && s.clipPath !== 'none')) return true;
    }
    return false;
  }
  function textVisible(el) {
    if (!el || el.nodeType !== 1 || !el.isConnected) return false;
    if (inBlockedTag(el)) return false;
    if (inClosedDetails(el)) return false;
    const s = styleOf(el);
    if (!s) return false;
    if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') return false;
    if (!(parseFloat(s.opacity || '1') > 0.01)) return false;
    let a = el.parentElement;
    let hops = 0;
    while (a && hops < 10) {
      const as = styleOf(a);
      if (as) {
        if (as.visibility === 'hidden' || as.visibility === 'collapse' || as.display === 'none') return false;
        if (!(parseFloat(as.opacity || '1') > 0.01)) return false;
      }
      a = a.parentElement;
      hops++;
    }
    if (isSrOnly(el)) return false;
    return true;
  }
  function visible(el) {
    if (!textVisible(el)) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 0.5 || r.height < 0.5) return false;
    return true;
  }
  function nodePath(el) {
    let out = tagOf(el);
    const parts = classList(el).slice(0, 3);
    if (parts.length) out += '.' + parts.join('.');
    return out;
  }
  function pathOf(el, ancestors) {
    const max = (ancestors === undefined) ? 4 : ancestors;
    const parts = [];
    let a = el;
    let n = 0;
    while (a && a.nodeType === 1 && n <= max) {
      parts.unshift(nodePath(a));
      a = a.parentElement;
      n++;
    }
    return parts.join(' > ');
  }
  function textOf(el, limit) {
    const parts = [];
    for (let n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && n.nodeValue) parts.push(n.nodeValue);
    }
    let text = parts.join(' ').replace(/\s+/g, ' ').trim();
    if (!text) text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    return text.slice(0, limit || 80);
  }
  function unionRects(rects) {
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const r of rects) {
      left = Math.min(left, r.left); top = Math.min(top, r.top);
      right = Math.max(right, r.right); bottom = Math.max(bottom, r.bottom);
    }
    return {x:left, y:top, w:right-left, h:bottom-top, left:left, top:top,
            right:right, bottom:bottom, width:right-left, height:bottom-top};
  }
  function textRects(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    const out = [];
    const list = range.getClientRects();
    for (let i = 0; i < list.length; i++) {
      const r = list[i];
      if (r.width > 0.5 && r.height > 0.5) {
        out.push({x:r.x, y:r.y, w:r.width, h:r.height, left:r.left, top:r.top,
                  right:r.right, bottom:r.bottom, width:r.width, height:r.height});
      }
    }
    return out;
  }
  function paddingBox(el) {
    const s = styleOf(el);
    const r = el.getBoundingClientRect();
    const bl = parseFloat(s.borderLeftWidth) || 0;
    const br = parseFloat(s.borderRightWidth) || 0;
    const bt = parseFloat(s.borderTopWidth) || 0;
    const bb = parseFloat(s.borderBottomWidth) || 0;
    return {left:r.left + bl, top:r.top + bt, right:r.right - br,
            bottom:r.bottom - bb, width:r.width - bl - br, height:r.height - bt - bb};
  }
  function contentWidth(el) {
    const s = styleOf(el);
    const r = el.getBoundingClientRect();
    const bl = parseFloat(s.borderLeftWidth) || 0;
    const br = parseFloat(s.borderRightWidth) || 0;
    const pl = parseFloat(s.paddingLeft) || 0;
    const pr = parseFloat(s.paddingRight) || 0;
    return r.width - bl - br - pl - pr;
  }
  function fitterScroller(el, includeSelf) {
    let a = includeSelf ? el : el.parentElement;
    let hops = 0;
    while (a && a !== document.documentElement && hops < 40) {
      const s = styleOf(a);
      if (s) {
        const ox = s.overflowX;
        if (ox === 'auto' || ox === 'scroll' || a.tagName === 'PRE' || a.tagName === 'TEXTAREA') {
          const r = a.getBoundingClientRect();
          if (r.left >= -1 && r.right <= VW + 1) return a;
        }
      }
      a = a.parentElement;
      hops++;
    }
    return null;
  }
  function parked(r) { return r.right <= -VW || r.left >= 2 * VW; }
  function dialogOf(el) { return el.closest ? el.closest('[role="dialog"]') : null; }
  function popoverOf(el) {
    return el.closest ? el.closest('[role="menu"],[role="listbox"],.w-menu,.mkt-menu,.popover') : null;
  }
  function sameLayer(a, b) {
    const da = dialogOf(a);
    const db = dialogOf(b);
    if ((da === null) !== (db === null)) return false;
    if (da !== null && da !== db) return false;
    const pa = popoverOf(a);
    const pb = popoverOf(b);
    if ((pa === null) !== (pb === null)) return false;
    if (pa !== null && pa !== pb) return false;
    return true;
  }
  function clampRects(el, rects) {
    const out = [];
    for (const rect of rects) {
      let left = rect.left, top = rect.top, right = rect.right, bottom = rect.bottom;
      let dropped = false;
      let a = el;
      let hops = 0;
      while (a && a !== document.documentElement && hops < 60) {
        const s = styleOf(a);
        if (s) {
          const clipsX = (s.overflowX === 'hidden' || s.overflowX === 'clip' ||
                          s.overflowX === 'auto' || s.overflowX === 'scroll');
          const clipsY = (s.overflowY === 'hidden' || s.overflowY === 'clip' ||
                          s.overflowY === 'auto' || s.overflowY === 'scroll');
          if (clipsX || clipsY) {
            const pb = paddingBox(a);
            if (clipsX) { left = Math.max(left, pb.left); right = Math.min(right, pb.right); }
            if (clipsY) { top = Math.max(top, pb.top); bottom = Math.min(bottom, pb.bottom); }
            if (right - left <= 0.5 || bottom - top <= 0.5) { dropped = true; break; }
          }
        }
        a = a.parentElement;
        hops++;
      }
      if (!dropped) {
        out.push({x:left, y:top, w:right-left, h:bottom-top, left:left, top:top,
                  right:right, bottom:bottom, width:right-left, height:bottom-top});
      }
    }
    return out;
  }
  function coveredByThird(a, b, box) {
    const x = (box.left + box.right) / 2;
    const y = (box.top + box.bottom) / 2;
    const top = document.elementFromPoint(x, y);
    if (!top) return false;
    if (a === top || a.contains(top) || top.contains(a)) return false;
    if (b === top || b.contains(top) || top.contains(b)) return false;
    return true;
  }
  function add(kind, severity, el, text, metrics, extra) {
    if (!el || el.nodeType !== 1) return;
    const b = rectOf(el);
    const f = {
      kind: kind,
      severity: severity,
      stress: STRESS,
      selector: pathOf(el),
      container: pathOf(el),
      classes: classString(el),
      text: text || '',
      metrics: metrics || {},
      rect: {x:r2(b.x), y:r2(b.y), w:r2(b.w), h:r2(b.h)}
    };
    if (extra) {
      for (const key in extra) { f[key] = extra[key]; }
    }
    OUT.push(f);
  }
  function textNodeList() {
    const root = document.body || document.documentElement;
    const out = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const p = node.parentElement;
        if (!p || inBlockedTag(p) || !textVisible(p)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (walker.nextNode()) out.push(walker.currentNode);
    return out;
  }
  function stressSkip(value) {
    const core = String(value || '').trim();
    if (!core || core.length <= 3) return true;
    if (/^\d+(?:[.,]\d+)*(?:\s*(?:%|px|k|m|b|usd|eur|hours?|days?))?$/i.test(core)) return true;
    if (/^\d{1,2}[:.]\d{2}(?:[:.]\d{2})?$/.test(core)) return true;
    if (/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?/.test(core)) return true;
    if (/^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$/.test(core)) return true;
    if (/^[0-9a-fA-F]{12,}$/.test(core)) return true;
    if (/^[A-Za-z0-9+/=_-]{16,}$/.test(core)) return true;
    return false;
  }
  function stressValue(value) {
    const raw = String(value == null ? '' : value);
    const lead = (raw.match(/^\s*/) || [''])[0];
    const trail = (raw.match(/\s*$/) || [''])[0];
    const core = raw.trim();
    if (!core || stressSkip(core)) return raw;
    return lead + [core, core, core].join(' ') + trail;
  }
  function tripleText() {
    const nodes = textNodeList();
    for (const node of nodes) {
      const p = node.parentElement;
      if (!p || p.tagName === 'OPTION' || p.tagName === 'TEXTAREA') continue;
      node.nodeValue = stressValue(node.nodeValue);
    }
    for (const el of document.querySelectorAll('option,textarea')) {
      if (!textVisible(el)) continue;
      if (el.tagName === 'TEXTAREA') {
        el.textContent = stressValue(el.textContent || '');
      } else {
        el.textContent = stressValue(el.textContent || '');
      }
    }
    for (const el of document.querySelectorAll('[placeholder],[title],[aria-label],[alt]')) {
      if (!textVisible(el)) continue;
      for (const name of ['placeholder', 'title', 'aria-label', 'alt']) {
        const value = el.getAttribute(name);
        if (value == null) continue;
        const next = stressValue(value);
        if (next !== value) el.setAttribute(name, next);
      }
    }
    window.__AGENTDESK_LAYOUT_TRIPLED__ = true;
  }

  const sc = document.scrollingElement || document.documentElement;
  const docWidth = Math.max(sc.scrollWidth, document.body ? document.body.scrollWidth : 0, VW);
  const docHeight = Math.max(sc.scrollHeight, document.body ? document.body.scrollHeight : 0, VH);

  function detectOffscreen() {
    const over = sc.scrollWidth - sc.clientWidth;
    let best = null;
    let bestDepth = -1;
    let bestArea = Infinity;
    const all = document.querySelectorAll('body *');
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (parked(r)) continue;
      if (fitterScroller(el, false)) continue;
      if (!(r.right > VW + 1 || r.left < -1)) continue;
      const s = styleOf(el);
      if (!s) continue;
      const inPopover = !!el.closest('[role="menu"],[role="dialog"],.w-menu,.mkt-sheet,.setup-sheet');
      if ((s.position === 'fixed' || s.position === 'absolute') && over <= 1 &&
          !inPopover) continue;
      let depth = 0;
      let a = el;
      while (a) { depth++; a = a.parentElement; }
      const area = r.width * r.height;
      if (depth > bestDepth || (depth === bestDepth && area < bestArea)) {
        best = el; bestDepth = depth; bestArea = area;
      }
    }
    if (over > 1 || best) {
      const el = best || document.body || document.documentElement;
      const r = best ? rectOf(best) : rectOf(document.documentElement);
      add('offscreen-content', 'high', el, textOf(el), {
        viewportWidth: VW,
        scrollWidth: sc.scrollWidth,
        clientWidth: sc.clientWidth,
        overBy: r2(Math.max(0, over)),
        culpritLeft: r2(r.left),
        culpritRight: r2(r.right),
        culpritWidth: r2(r.width),
        docWidth: r2(docWidth)
      });
    }
  }

  function spillSeverity(el) {
    const t = el.tagName;
    if (t === 'BUTTON' || t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' ||
        t === 'TD' || t === 'TH') return 'high';
    if (el.getAttribute && el.getAttribute('role') === 'button') return 'high';
    const c = classString(el);
    if (t === 'A' && /(^|\s)(btn|button)(\s|$)/.test(c)) return 'high';
    if (/(^|\s)(chip|badge|pill|tab|status)(\s|$)/.test(c)) return 'high';
    return 'medium';
  }

  function detectSpill() {
    const all = document.querySelectorAll('body *');
    const raw = [];
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (!visible(el)) continue;
      const s = styleOf(el);
      if (!s) continue;
      if (s.position === 'absolute' || s.position === 'fixed') continue;
      if (fitterScroller(el, false)) continue;
      const p = el.parentElement;
      if (p && p !== document.body && p !== document.documentElement) {
        const ps = styleOf(p);
        const pr = p.getBoundingClientRect();
        if (ps && pr.width > 1 && pr.height > 1 && ps.display !== 'contents') {
          const pLeft = pr.left + (parseFloat(ps.borderLeftWidth) || 0) + (parseFloat(ps.paddingLeft) || 0);
          const pRight = pr.right - (parseFloat(ps.borderRightWidth) || 0) - (parseFloat(ps.paddingRight) || 0);
          const r = el.getBoundingClientRect();
          const overRight = r.right - pRight;
          const overLeft = pLeft - r.left;
          const over = Math.max(overRight, overLeft);
          if (over > 1) {
            raw.push({container:p, offender:el, over:over, right:overRight,
                      left:overLeft, mode:'child'});
          }
        }
      }
      const selfScroll = (s.overflowX === 'auto' || s.overflowX === 'scroll' ||
                          el.tagName === 'PRE' || el.tagName === 'TEXTAREA');
      if (!selfScroll && s.overflowX === 'visible' && el.clientWidth > 0 &&
          el.scrollWidth > el.clientWidth + 1) {
        raw.push({container:el, offender:el, over:el.scrollWidth - el.clientWidth,
                  right:el.scrollWidth - el.clientWidth, left:0, mode:'scroll'});
      }
    }
    const kept = [];
    for (const c of raw) {
      let existing = null;
      for (const item of kept) {
        if (item.container === c.container && item.offender === c.offender) {
          existing = item;
          break;
        }
      }
      if (existing === null) {
        kept.push(c);
      } else if (c.over > existing.over) {
        existing.over = c.over;
        existing.right = c.right;
        existing.left = c.left;
        existing.mode = c.mode;
      }
    }
    for (const c of kept) {
      let hasDeeper = false;
      for (const other of kept) {
        if (other !== c && c.container.contains(other.container) &&
            c.offender.contains(other.offender)) {
          hasDeeper = true;
          break;
        }
      }
      if (hasDeeper) continue;
      add('content-spill', spillSeverity(c.container), c.container, textOf(c.container), {
        overRight: r2(c.right), overLeft: r2(c.left), over: r2(c.over),
        mode: c.mode,
        containerWidth: r2(c.container.getBoundingClientRect().width),
        offenderWidth: r2(c.offender.getBoundingClientRect().width)
      }, {
        container: pathOf(c.container),
        classes: classString(c.container),
        offender: pathOf(c.offender),
        offenderText: textOf(c.offender)
      });
    }
  }

  function detectTextClip(nodes) {
    const seen = new Set();
    for (const node of nodes) {
      const p = node.parentElement;
      if (!p) continue;
      const rects = textRects(node);
      if (!rects.length) continue;
      let clip = null;
      let axis = '';
      let stats = null;
      let a = p;
      let hops = 0;
      while (a && a !== document.documentElement && hops < 40) {
        const s = styleOf(a);
        if (s) {
          const ox = s.overflowX;
          const oy = s.overflowY;
          const pb = paddingBox(a);
          let outR = 0, outL = 0, outB = 0, outT = 0;
          for (const r of rects) {
            outR = Math.max(outR, r.right - pb.right);
            outL = Math.max(outL, pb.left - r.left);
            outB = Math.max(outB, r.bottom - pb.bottom);
            outT = Math.max(outT, pb.top - r.top);
          }
          let hit = '';
          if ((ox === 'hidden' || ox === 'clip' || ox === 'auto' || ox === 'scroll') &&
              (outR > 1 || outL > 1)) hit = 'x';
          else if ((oy === 'hidden' || oy === 'clip') &&
                   (outB > 1 || outT > 1)) hit = 'y';
          if (hit) {
            clip = a;
            axis = hit;
            stats = {outR:r2(outR), outL:r2(outL), outB:r2(outB), outT:r2(outT),
                     clipRight:r2(pb.right), clipLeft:r2(pb.left)};
            break;
          }
        }
        a = a.parentElement;
        hops++;
      }
      if (!clip) continue;
      if (fitterScroller(clip, true)) continue;
      let affordance = false;
      let b = p;
      let steps = 0;
      while (b && steps < 40) {
        const s = styleOf(b);
        if (s) {
          if ((s.textOverflow || '').indexOf('ellipsis') >= 0 &&
              (s.overflowX === 'hidden' || s.overflowX === 'clip') &&
              s.whiteSpace === 'nowrap') affordance = true;
          if (s.webkitLineClamp && s.webkitLineClamp !== 'none') affordance = true;
          if (s.lineClamp && s.lineClamp !== 'none') affordance = true;
        }
        if (b === clip) break;
        b = b.parentElement;
        steps++;
      }
      if (affordance) continue;
      const key = pathOf(p) + '|' + (node.nodeValue || '').trim().slice(0, 60);
      if (seen.has(key)) continue;
      seen.add(key);
      const union = unionRects(rects);
      add('text-clip', 'medium', p, (node.nodeValue || '').replace(/\s+/g, ' ').trim(), {
        axis: axis,
        overRight: stats.outR,
        overLeft: stats.outL,
        overBottom: stats.outB,
        overTop: stats.outT,
        clipRight: stats.clipRight,
        clipLeft: stats.clipLeft,
        lines: rects.length
      }, {
        container: pathOf(clip),
        classes: classString(clip),
        clippedBy: pathOf(clip),
        rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
      });
    }
  }

  function detectEllipsis() {
    const all = document.querySelectorAll('body *');
    const seen = new Set();
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (!visible(el)) continue;
      const s = styleOf(el);
      if (!s) continue;
      const ell = (s.textOverflow || '').indexOf('ellipsis') >= 0 &&
                  (s.overflowX === 'hidden' || s.overflowX === 'clip');
      const clampValue = parseFloat(s.webkitLineClamp) || parseFloat(s.lineClamp) || 0;
      if (!ell && !(clampValue > 0)) continue;
      const over = ell ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
      if (!(over > 1)) continue;
      const text = textOf(el, 400);
      if (!text) continue;
      const reachable = el.hasAttribute('title') || el.hasAttribute('aria-label') ||
                        !!el.closest('[title]') || !!el.closest('summary');
      if (reachable) continue;
      const key = pathOf(el) + '|' + text.slice(0, 60);
      if (seen.has(key)) continue;
      seen.add(key);
      add('ellipsis-no-affordance', 'low', el, text, {
        over: r2(over),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        lineClamp: r2(clampValue),
        ellipsis: ell ? 1 : 0
      });
    }
  }

  function buildTextItems(nodes) {
    const items = [];
    for (const node of nodes) {
      const el = node.parentElement;
      if (!el) continue;
      const rects = clampRects(el, textRects(node));
      if (!rects.length) continue;
      items.push({el:el, node:node, rects:rects, union:unionRects(rects),
                  text:(node.nodeValue || '').replace(/\s+/g, ' ').trim()});
    }
    return items;
  }

  function detectOverlap(items) {
    const hits = [];
    for (let i = 0; i < items.length; i++) {
      const a = items[i];
      for (let j = i + 1; j < items.length; j++) {
        const b = items[j];
        if (a.el === b.el) continue;
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
        if (a.union.right <= b.union.left || b.union.right <= a.union.left ||
            a.union.bottom <= b.union.top || b.union.bottom <= a.union.top) continue;
        let ix = 0, iy = 0, box = null;
        for (const ra of a.rects) {
          for (const rb of b.rects) {
            const left = Math.max(ra.left, rb.left);
            const top = Math.max(ra.top, rb.top);
            const right = Math.min(ra.right, rb.right);
            const bottom = Math.min(ra.bottom, rb.bottom);
            const w = right - left;
            const h = bottom - top;
            if (w > 2 && h > 4 && w * h > ix * iy) {
              ix = w; iy = h;
              box = {left:left, top:top, right:right, bottom:bottom};
            }
          }
        }
        if (ix > 2 && iy > 4 && sameLayer(a.el, b.el) &&
            !coveredByThird(a.el, b.el, box)) {
          hits.push({a:a, b:b, ix:ix, iy:iy});
        }
      }
    }
    const byPair = new Map();
    for (const hit of hits) {
      const key = [pathOf(hit.a.el), pathOf(hit.b.el)].sort().join('|');
      const prev = byPair.get(key);
      if (!prev || hit.ix * hit.iy > prev.ix * prev.iy) byPair.set(key, hit);
    }
    for (const hit of byPair.values()) {
      const areaA = hit.a.union.width * hit.a.union.height;
      const areaB = hit.b.union.width * hit.b.union.height;
      const primary = areaA <= areaB ? hit.a : hit.b;
      const other = primary === hit.a ? hit.b : hit.a;
      const both = unionRects([primary.union, other.union]);
      const severity = (hit.ix >= 8 && hit.iy >= 8) ? 'high' : 'medium';
      add('text-overlap', severity, primary.el, primary.text, {
        overlapWidth: r2(hit.ix), overlapHeight: r2(hit.iy),
        otherSelector: pathOf(other.el), otherText: other.text.slice(0, 80)
      }, {
        otherClasses: classString(other.el),
        rect: {x:r2(both.x), y:r2(both.y), w:r2(both.w), h:r2(both.h)}
      });
    }
  }

  function detectControls(items) {
    const list = document.querySelectorAll(
      'button,input,select,textarea,svg,img,a.btn,a.icon-btn,a.mkt-icon-btn,[role="button"],[role="link"]');
    const controls = [];
    for (let i = 0; i < list.length; i++) {
      const el = list[i];
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      controls.push({el:el, rect:rectOf(el)});
    }
    const seen = new Set();
    for (const item of items) {
      for (const control of controls) {
        if (item.el === control.el || item.el.contains(control.el) ||
            control.el.contains(item.el)) continue;
        let ix = 0, iy = 0, box = null;
        for (const ra of item.rects) {
          const left = Math.max(ra.left, control.rect.left);
          const top = Math.max(ra.top, control.rect.top);
          const right = Math.min(ra.right, control.rect.right);
          const bottom = Math.min(ra.bottom, control.rect.bottom);
          const w = right - left;
          const h = bottom - top;
          if (w > 2 && h > 4 && w * h > ix * iy) {
            ix = w; iy = h;
            box = {left:left, top:top, right:right, bottom:bottom};
          }
        }
        if (!(ix > 2 && iy > 4)) continue;
        if (!sameLayer(item.el, control.el) ||
            coveredByThird(item.el, control.el, box)) continue;
        const key = pathOf(item.el) + '|' + pathOf(control.el);
        if (seen.has(key)) continue;
        seen.add(key);
        const union = unionRects(item.rects.concat([control.rect]));
        add('control-collision', 'medium', item.el, item.text, {
          overlapWidth: r2(ix), overlapHeight: r2(iy),
          controlTag: tagOf(control.el), controlSelector: pathOf(control.el)
        }, {
          controlClasses: classString(control.el),
          rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
        });
      }
    }
    const controlSeen = new Set();
    for (let i = 0; i < controls.length; i++) {
      for (let j = i + 1; j < controls.length; j++) {
        const a = controls[i];
        const b = controls[j];
        if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
        const left = Math.max(a.rect.left, b.rect.left);
        const top = Math.max(a.rect.top, b.rect.top);
        const right = Math.min(a.rect.right, b.rect.right);
        const bottom = Math.min(a.rect.bottom, b.rect.bottom);
        const ix = right - left;
        const iy = bottom - top;
        if (!(ix > 2 && iy > 4)) continue;
        const box = {left:left, top:top, right:right, bottom:bottom};
        if (!sameLayer(a.el, b.el) || coveredByThird(a.el, b.el, box)) continue;
        const areaA = a.rect.width * a.rect.height;
        const areaB = b.rect.width * b.rect.height;
        const primary = areaA <= areaB ? a : b;
        const other = primary === a ? b : a;
        const key = pathOf(primary.el) + '|' + pathOf(other.el);
        if (controlSeen.has(key)) continue;
        controlSeen.add(key);
        const union = unionRects([primary.rect, other.rect]);
        const severity = (ix >= 8 && iy >= 8) ? 'high' : 'medium';
        add('control-overlap', severity, primary.el, textOf(primary.el), {
          overlapWidth: r2(ix), overlapHeight: r2(iy),
          controlTag: tagOf(primary.el), controlSelector: pathOf(other.el)
        }, {
          controlClasses: classString(primary.el),
          otherSelector: pathOf(other.el),
          otherClasses: classString(other.el),
          rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
        });
      }
    }
  }

  function blockOf(node) {
    let a = node.parentElement;
    let hops = 0;
    while (a && a !== document.body && hops < 40) {
      const s = styleOf(a);
      if (s) {
        if (s.whiteSpace === 'normal' && s.display !== 'inline' &&
            s.display !== 'contents' && s.display !== 'none') return a;
      }
      a = a.parentElement;
      hops++;
    }
    return null;
  }

  function detectSqueezed(nodes) {
    const squeezed = new Set();
    const byBlock = new Map();
    for (const node of nodes) {
      const block = blockOf(node);
      if (!block) continue;
      let list = byBlock.get(block);
      if (!list) { list = []; byBlock.set(block, list); }
      list.push(node);
    }
    for (const entry of byBlock.entries()) {
      const el = entry[0];
      const textNodes = entry[1];
      if (!textVisible(el)) continue;
      const s = styleOf(el);
      if (!s) continue;
      const cw = contentWidth(el);
      if (!(cw >= 0 && cw < 96)) continue;
      const tops = new Set();
      const allRects = [];
      let chars = 0;
      for (const node of textNodes) {
        chars += node.nodeValue.trim().length;
        for (const r of clampRects(el, textRects(node))) {
          tops.add(Math.round(r.top));
          allRects.push(r);
        }
      }
      if (chars < 6 || tops.size < 3 || !allRects.length) continue;
      const union = unionRects(allRects);
      const severity = cw < 40 ? 'high' : 'medium';
      squeezed.add(el);
      add('squeezed-text', severity, el, textOf(el), {
        width: r2(cw), lines: tops.size, chars: chars,
        fontSize: r2(parseFloat(s.fontSize) || 0)
      }, {
        rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
      });
    }
    return squeezed;
  }

  function wrappingBlockOf(node) {
    let a = node.parentElement;
    let hops = 0;
    while (a && a !== document.body && hops < 40) {
      const s = styleOf(a);
      if (s) {
        const ws = s.whiteSpace;
        if ((ws === 'normal' || ws === 'pre-wrap' || ws === 'break-spaces') &&
            s.display.indexOf('inline') !== 0 && s.display !== 'contents' &&
            s.display !== 'none' && s.display !== 'table-row') return a;
      }
      a = a.parentElement;
      hops++;
    }
    return null;
  }

  function brokenWordSeverity(el, s) {
    const c = classString(el);
    if (el.tagName === 'CODE' || el.tagName === 'PRE' || el.tagName === 'BUTTON') return 'high';
    if (/(^|\s)(value|figure|ml-figure|stamp|digest-src|digest-time)(\s|$)/.test(c)) return 'high';
    if (el.matches && el.matches('.hero-stats dd, .stage-axis small, td.num, th.num')) return 'high';
    if ((s.fontFamily || '').toLowerCase().indexOf('mono') >= 0) return 'high';
    return 'medium';
  }

  function detectBrokenWords(nodes, squeezedBlocks) {
    const byBlock = new Map();
    for (const node of nodes) {
      const block = wrappingBlockOf(node);
      if (!block) continue;
      let list = byBlock.get(block);
      if (!list) { list = []; byBlock.set(block, list); }
      list.push(node);
    }
    const seen = new Set();
    for (const entry of byBlock.entries()) {
      const el = entry[0];
      const textNodes = entry[1];
      if (!textVisible(el)) continue;
      if (squeezedBlocks && squeezedBlocks.has(el)) continue;
      const s = styleOf(el);
      if (!s) continue;
      const cw = contentWidth(el);
      for (const node of textNodes) {
        const text = node.nodeValue || '';
        const re = /\S+/g;
        let match;
        while ((match = re.exec(text))) {
          const word = match[0];
          const core = word.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '');
          if (core.length < 2) continue;
          if (/[-\/_.:]/.test(core)) continue;
          if (/^[0-9a-fA-F]{12,}$/.test(core)) continue;
          if (/^(?=.*[0-9])(?=.*[A-Za-z])[A-Za-z0-9+/=_-]{16,}$/.test(core)) continue;
          const range = document.createRange();
          range.setStart(node, match.index);
          range.setEnd(node, match.index + word.length);
          const raw = [];
          const list = range.getClientRects();
          for (let i = 0; i < list.length; i++) {
            const r = list[i];
            if (r.width > 0.5 && r.height > 0.5) {
              raw.push({x:r.x, y:r.y, w:r.width, h:r.height, left:r.left, top:r.top,
                        right:r.right, bottom:r.bottom, width:r.width, height:r.height});
            }
          }
          const rects = clampRects(el, raw);
          if (!rects.length) continue;
          const tops = new Set();
          for (const r of rects) tops.add(Math.round(r.top));
          if (tops.size < 2) continue;
          const key = pathOf(el) + '|' + word + '|' + Array.from(tops).join(',');
          if (seen.has(key)) continue;
          seen.add(key);
          const lineTops = Array.from(tops).sort(function(a, b) { return a - b; });
          const union = unionRects(rects);
          add('broken-word', brokenWordSeverity(el, s), el, word, {
            word: word,
            wordLength: word.length,
            lineCount: tops.size,
            lineTops: lineTops.slice(0, 8),
            width: r2(cw),
            fontSize: r2(parseFloat(s.fontSize) || 0)
          }, {
            word: word,
            rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
          });
        }
      }
    }
  }

  function detectTiny(nodes) {
    const elements = new Set();
    for (const node of nodes) {
      if (node.parentElement) elements.add(node.parentElement);
    }
    for (const el of elements) {
      if (!visible(el)) continue;
      const s = styleOf(el);
      if (!s) continue;
      const fs = parseFloat(s.fontSize);
      if (!(fs > 0 && fs < 11)) continue;
      const text = textOf(el);
      if (!text) continue;
      add('tiny-type', 'low', el, text, {fontSize: r2(fs)});
    }
  }

  if (STRESS) tripleText();
  detectOffscreen();
  const nodes = textNodeList();
  detectSpill();
  detectTextClip(nodes);
  detectEllipsis();
  const items = buildTextItems(nodes);
  detectOverlap(items);
  detectControls(items);
  const squeezedBlocks = detectSqueezed(nodes);
  detectBrokenWords(nodes, squeezedBlocks);
  detectTiny(nodes);

  return {
    findings: OUT,
    stress: STRESS,
    viewportWidth: VW,
    viewportHeight: VH,
    scrollX: window.scrollX,
    scrollY: window.scrollY,
    docWidth: docWidth,
    docHeight: docHeight
  };
})()
"""


SELFTEST_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
body { margin: 0; font: 14px Arial, sans-serif; background: #fff; color: #111; }
.selftest-squeezed { width: 30px; white-space: normal; }
.selftest-clip { width: 80px; overflow: hidden; white-space: nowrap; }
.selftest-ellipsis { width: 80px; overflow: hidden; white-space: nowrap;
  text-overflow: ellipsis; }
.selftest-ellipsis-title { width: 80px; overflow: hidden; white-space: nowrap;
  text-overflow: ellipsis; }
.selftest-overlap-a { position: absolute; left: 200px; top: 300px; }
.selftest-overlap-b { position: absolute; left: 210px; top: 302px; }
.selftest-control { position: absolute; left: 400px; top: 300px; width: 90px;
  height: 32px; }
.selftest-over-text { position: absolute; left: 410px; top: 304px; }
.selftest-card { width: 200px; border: 1px solid #111; padding: 10px; }
.selftest-spill { width: 300px; height: 20px; background: #eee; }
.selftest-broken { width: 150px; white-space: normal; overflow-wrap: anywhere;
  font-family: monospace; }
.selftest-tiny { font-size: 9px; }
.selftest-clean-scroller { width: 200px; overflow-x: auto; white-space: nowrap; }
.selftest-clean-scroller div { width: 500px; }
.selftest-clean-pill { display: inline-block; padding: 2px 8px;
  border-radius: 8px; background: #eee; white-space: nowrap; }
.selftest-cc-a { position: absolute; left: 650px; top: 300px; width: 80px;
  height: 30px; }
.selftest-cc-b { position: absolute; left: 700px; top: 305px; width: 80px;
  height: 30px; }
</style></head><body>
<div class="selftest-squeezed">Alpha Beta Gamma Delta</div>
<div class="selftest-clip">This line is clipped with no ellipsis at all</div>
<div class="selftest-ellipsis">This line is ellipsized with no title</div>
<div class="selftest-ellipsis-title" title="the full value">This line is ellipsized with a title</div>
<div class="selftest-overlap-a">Overlapping alpha text</div>
<div class="selftest-overlap-b">Overlapping beta text</div>
<button class="selftest-control">Action</button>
<div class="selftest-over-text">Text over the control</div>
<div class="selftest-card"><div class="selftest-spill">Spilling child content</div></div>
<div class="selftest-broken selftest-stamp">Supercalifragilisticexpialidocious</div>
<div class="selftest-tiny">Tiny type text</div>
<div class="selftest-clean-scroller"><div>long scrollable content that is deliberately scrollable</div></div>
<span class="selftest-clean-pill">Clean pill</span>
<button class="selftest-cc-a">First</button>
<button class="selftest-cc-b">Second</button>
</body></html>
"""

SELFTEST_OFFSCREEN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
body { margin: 0; font: 14px Arial, sans-serif; background: #fff; color: #111; }
.selftest-popover { position: absolute; left: calc(100vw - 30px); top: 100px;
  width: 200px; height: 40px; background: #eee; }
</style></head><body>
<div class="selftest-popover w-menu">Open popover past the viewport edge</div>
</body></html>
"""


class _SelftestHandler:
    """Serve the two static selftest pages on loopback only."""

    html = {"/": SELFTEST_HTML, "/offscreen": SELFTEST_OFFSCREEN_HTML}


def _selftest_server():
    """Start the static selftest pages and return the server and base URL."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        """Answer the two fixture addresses and nothing else."""

        def do_GET(self):  # noqa: N802 - the stdlib's spelling
            """Serve one fixture page, or a 404."""
            body = _SelftestHandler.html.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # noqa: A003 - the stdlib's hook
            """Stay quiet; the selftest prints its own verdict."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _selftest_hits(findings: list[dict], token: str) -> list[dict]:
    """Findings whose recorded paths mention one fixture class."""
    return [finding for finding in findings
            if any(token in str(finding.get(key, "")) for key in
                   ("selector", "container", "otherSelector", "offender",
                    "metrics"))]


def _selftest() -> int:
    """Run the planted-defect fixture and report every detector match."""
    server, thread, base = _selftest_server()
    failures: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1024, "height": 800},
                                          device_scale_factor=1,
                                          reduced_motion="reduce")
            page = context.new_page()
            page.goto(base + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(200)
            page.evaluate("() => { window.__AGENTDESK_LAYOUT_STRESS__ = false; }")
            findings = page.evaluate(PROBE_JS).get("findings", [])
            expectations = (
                ("squeezed-text", "selftest-squeezed", 1),
                ("text-clip", "selftest-clip", 1),
                ("ellipsis-no-affordance", "selftest-ellipsis", 1),
                ("ellipsis-no-affordance", "selftest-ellipsis-title", 0),
                ("text-overlap", "selftest-overlap-a", 1),
                ("control-collision", "selftest-over-text", 1),
                ("content-spill", "selftest-card", 1),
                ("broken-word", "selftest-broken", 1),
                ("tiny-type", "selftest-tiny", 1),
                ("content-spill", "selftest-clean-scroller", 0),
                ("text-clip", "selftest-clean-scroller", 0),
                ("text-overlap", "selftest-clean-pill", 0),
                ("squeezed-text", "selftest-clean-pill", 0),
            )
            for kind, token, expected in expectations:
                hits = [finding for finding in _selftest_hits(findings, token)
                        if finding.get("kind") == kind]
                if len(hits) != expected:
                    failures.append(f"{token} {kind}: expected {expected}, "
                                    f"found {len(hits)}")
            control_hits = _selftest_hits(findings, "selftest-cc-a")
            control_hits = [finding for finding in control_hits
                            if finding.get("kind") == "control-overlap"]
            if len(control_hits) != 1:
                failures.append(f"selftest-cc-a control-overlap: expected 1, "
                                f"found {len(control_hits)}")
            page.goto(base + "/offscreen", wait_until="domcontentloaded")
            page.wait_for_timeout(200)
            offscreen = page.evaluate(PROBE_JS).get("findings", [])
            popover_hits = [finding for finding in _selftest_hits(offscreen, "w-menu")
                            if finding.get("kind") == "offscreen-content"]
            if len(popover_hits) != 1:
                failures.append(f"w-menu offscreen-content: expected 1, "
                                f"found {len(popover_hits)}")
            browser.close()
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        try:
            thread.join(timeout=3)
        except Exception:
            pass
    if failures:
        print("SELFTEST FAIL")
        for failure in failures:
            print("  " + failure)
        return 1
    print("SELFTEST PASS 14 detector expectations")
    return 0

class AuditError(Exception):
    """One step of the audit could not run at all."""


def _now_stamp() -> str:
    """A filesystem-safe local timestamp naming one run folder."""
    return time.strftime("%Y%m%d-%H%M%S")


def _slug(text: str) -> str:
    """A filesystem-safe slug from a route or state name."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("_")
    return slug or "root"


def _severity_rank(severity: str) -> int:
    """Numeric rank for sorting, where high is 0 and unknown sorts last."""
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def _read_json(path: Path, default):
    """Read JSON, or return the default when the file is absent or broken."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    """Write one JSON document with a stable, readable shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _parse_list(value: str) -> list[str]:
    """Split a comma-separated CLI value into non-empty stripped tokens."""
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _registry_entries() -> list[dict]:
    """The plugin entries in registry/index.json, in the registry's order."""
    document = _read_json(ROOT / "registry" / "index.json", {})
    entries = document.get("plugins") if isinstance(document, dict) else None
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")] \
        if isinstance(entries, list) else []


def _plugin_ids() -> list[str]:
    """The registry plugin ids, in index order."""
    return [str(entry["id"]) for entry in _registry_entries()]


def _categories() -> list[str]:
    """The registry categories, in first-seen index order."""
    seen: list[str] = []
    for entry in _registry_entries():
        category = str(entry.get("category") or "").strip()
        if category and category not in seen:
            seen.append(category)
    return seen


def _publishers() -> list[str]:
    """The registry publishers, in first-seen index order."""
    seen: list[str] = []
    for entry in _registry_entries():
        publisher = str(entry.get("publisher") or "").strip()
        if publisher and publisher not in seen:
            seen.append(publisher)
    return seen


def build_views() -> list[dict]:
    """Every SPA route and server-rendered state the audit visits.

    The order is fixed so two runs visit the same screens in the same
    order. A view carries the address, the surface kind, a stable state
    name for file names and reports, and flags for the error page and the
    settings section it must prove visible before measuring.
    """
    views: list[dict] = [
        {"path": "/", "kind": "spa", "state": "dashboard"},
        {"path": "/marketplace", "kind": "spa", "state": "marketplace"},
        {"path": "/marketplace/search?q=watch", "kind": "spa", "state": "marketplace-search"},
    ]
    for category in _categories():
        views.append({"path": f"/marketplace/category/{category}", "kind": "spa",
                      "state": f"marketplace-category-{category}"})
    for plugin_id in _plugin_ids():
        views.append({"path": f"/marketplace/plugin/{plugin_id}", "kind": "spa",
                      "state": f"marketplace-plugin-{plugin_id}"})
    views.extend([
        {"path": "/marketplace/plugin/excel-report/manage", "kind": "spa",
         "state": "marketplace-manage-excel-report"},
        {"path": "/marketplace/pack/none", "kind": "spa", "state": "marketplace-pack-none"},
        {"path": "/marketplace/installed", "kind": "spa", "state": "marketplace-installed"},
        {"path": "/marketplace/publishers", "kind": "spa", "state": "marketplace-publishers"},
    ])
    for publisher in _publishers():
        views.append({"path": f"/marketplace/publisher/{publisher}", "kind": "spa",
                      "state": f"marketplace-publisher-{publisher}"})
    views.extend([
        {"path": "/marketplace/studio", "kind": "spa", "state": "marketplace-studio"},
        {"path": "/marketplace/admin", "kind": "spa", "state": "marketplace-admin"},
        {"path": "/marketplace/trust", "kind": "spa", "state": "marketplace-trust"},
        {"path": "/marketplace/nope", "kind": "spa", "state": "marketplace-notfound",
         "expected_error": True},
        {"path": "/inbox", "kind": "server", "state": "inbox"},
        {"path": "/assistant", "kind": "server", "state": "assistant"},
        {"path": "/agents", "kind": "server", "state": "agents"},
        {"path": "/memory", "kind": "server", "state": "memory"},
        {"path": "/memory/graph", "kind": "server", "state": "memory-graph"},
        {"path": "/memory/sweep", "kind": "server", "state": "memory-sweep"},
        {"path": "/memory/encrypt", "kind": "server", "state": "memory-encrypt"},
        {"path": "/mail", "kind": "server", "state": "mail"},
        {"path": "/capabilities", "kind": "server", "state": "capabilities"},
        {"path": "/peers", "kind": "server", "state": "peers"},
        {"path": "/settings", "kind": "server", "state": "settings"},
    ])
    for section in ("ai", "tools", "memory", "preferences", "advanced"):
        views.append({"path": f"/settings#{section}", "kind": "server",
                      "state": f"settings#{section}", "settings_section": section})
    views.extend([
        {"path": "/settings/activity", "kind": "server", "state": "settings-activity"},
        {"path": "/walkthrough/calendar", "kind": "server", "state": "walkthrough-calendar",
         "calendar_fixture": True},
        {"path": "/what-this-touches", "kind": "server", "state": "what-this-touches"},
        {"path": "/wizard", "kind": "server", "state": "wizard"},
        {"path": "/auth/not-a-real-token", "kind": "server", "state": "error-page",
         "expected_error": True},
    ])
    return views


def build_overlays() -> list[dict]:
    """The overlay states, each opened by a real control and measured alone.

    `conditions` and `widths` keep an overlay out of conditions where its
    trigger cannot exist (for example, a consent sheet needs an installed
    plugin that is not there). A missing control is reported as skipped.
    """
    return [
        {"key": "overlay-widget-menu", "route": "/", "opener": "widget-menu",
         "conditions": ("fresh", "data", "plugins", "full"), "widths": (1024, 1280),
         "state": "overlay-widget-menu"},
        {"key": "overlay-tracker-setup", "route": "/", "opener": "tracker-setup",
         "conditions": ("plugins", "full"), "widths": (1024, 1280),
         "state": "overlay-tracker-setup"},
        {"key": "overlay-customize", "route": "/", "opener": "customize",
         "conditions": ("fresh", "data", "plugins", "full"), "widths": (1024, 1280),
         "state": "overlay-customize"},
        {"key": "overlay-consent", "route": "/marketplace/plugin/excel-report",
         "opener": "consent", "conditions": ("data",), "widths": (1024, 1280),
         "state": "overlay-consent"},
        {"key": "overlay-instance-setup", "route": "/marketplace/plugin/excel-report/manage",
         "opener": "instance-setup", "conditions": ("plugins", "full"),
         "widths": (1024, 1280), "state": "overlay-instance-setup"},
        {"key": "overlay-purge", "route": "/marketplace/installed", "opener": "purge",
         "conditions": ("plugins", "full"), "widths": (1024, 1280),
         "state": "overlay-purge"},
        {"key": "overlay-describe", "route": "/marketplace", "opener": "describe",
         "conditions": ("data", "full"), "widths": (1024, 1280),
         "state": "overlay-describe"},
    ]


def _route_matches(view: dict, filters: list[str]) -> bool:
    """True when a view passes the --routes substring filter, if any."""
    if not filters:
        return True
    route = view.get("path") or view.get("route") or ""
    haystack = f"{route} {view.get('state', '')}".lower()
    return any(token.lower() in haystack for token in filters)


def build_combos(args) -> list[dict]:
    """The full matrix for the selected conditions, widths, themes and routes.

    The three bands are kept explicit: the base matrix (all conditions),
    themes (fresh and full only), extremes (fresh and full only), plus the
    overlay states and the legacy dashboard. A combo says which view to
    visit and whether the text-tripling stress pass runs after the normal
    measurement. Unsupported values and filters that match nothing are hard
    errors: an empty plan must never look like a complete run.
    """
    conditions = _parse_list(args.conditions)
    for condition in conditions:
        if condition not in ALL_CONDITIONS:
            raise AuditError(f"unsupported condition {condition!r}; "
                             f"choose from {', '.join(ALL_CONDITIONS)}")
    try:
        widths = [int(value) for value in _parse_list(args.widths)]
    except ValueError as exc:
        raise AuditError(f"--widths must be integers: {args.widths!r}") from exc
    for width in widths:
        if width not in (800, 1024, 1280, 1920):
            raise AuditError(f"unsupported width {width}; choose from 800, 1024, 1280, 1920")
    themes = _parse_list(args.themes)
    for theme in themes:
        if theme not in THEMES:
            raise AuditError(f"unsupported theme {theme!r}; choose from {', '.join(THEMES)}")
    filters = _parse_list(args.routes)
    views = [view for view in build_views() if _route_matches(view, filters)]
    overlay_filters = filters
    if filters and not views and not any(
            _route_matches(overlay, overlay_filters) for overlay in build_overlays()):
        raise AuditError(f"no route or overlay matches --routes {args.routes!r}")
    combos: list[dict] = []

    def add(condition: str, width: int, theme: str, view: dict, stress: bool) -> None:
        """Append one combination unless an identical one is already there."""
        key = (condition, width, theme, view["path"], view.get("state"), stress)
        seen = {(c["condition"], c["width"], c["theme"], c["view"]["path"],
                 c["view"].get("state"), c["stress"]) for c in combos}
        if key not in seen:
            combos.append({"condition": condition, "width": width, "theme": theme,
                           "view": view, "stress": stress, "kind": view["kind"]})

    if args.only_condition:
        conditions = [args.only_condition]
    for condition in conditions:
        if condition == "legacy-dashboard":
            if "unkey" in themes and 1024 in widths:
                add(condition, 1024, "unkey", {"path": "/", "kind": "server",
                                               "state": "legacy-dashboard"}, False)
            if "unkey" in themes and 1280 in widths:
                add(condition, 1280, "unkey", {"path": "/", "kind": "server",
                                               "state": "legacy-dashboard"}, False)
            continue
        if args.only_condition or condition in BASE_CONDITIONS:
            for width in BASE_WIDTHS:
                if width not in widths or "unkey" not in themes:
                    continue
                for view in views:
                    stress = (not args.no_stress and condition in STRESS_CONDITIONS
                              and width in STRESS_WIDTHS)
                    add(condition, width, "unkey", view, stress)
        if condition in ("fresh", "full"):
            for theme in ("coforge", "momentuum"):
                if theme not in themes:
                    continue
                for width in THEME_WIDTHS:
                    if width not in widths:
                        continue
                    for view in views:
                        add(condition, width, theme, view, False)
            for width in EXTREME_WIDTHS:
                if "unkey" not in themes or width not in widths:
                    continue
                for view in views:
                    add(condition, width, "unkey", view, False)
    for overlay in build_overlays():
        condition = args.only_condition or (conditions[0] if conditions else "")
        if overlay["conditions"] and condition not in overlay["conditions"]:
            continue
        if not _route_matches(overlay, overlay_filters):
            continue
        if "unkey" not in themes:
            continue
        for width in overlay["widths"]:
            if width not in widths:
                continue
            add(condition, width, "unkey",
                {"path": overlay["route"], "kind": "overlay",
                 "state": overlay["state"], "opener": overlay["opener"],
                 "overlay_key": overlay["key"]}, False)
    if not combos:
        raise AuditError(
            "the selected filters produce no combinations: check --conditions, "
            "--widths, --themes and --routes")
    return combos


def _combo_key(combo: dict) -> tuple:
    """The identity of one planned combination, independent of its outcome."""
    view = combo["view"]
    return (combo["condition"], combo["width"], combo["theme"],
            view.get("path", ""), view.get("state", ""), combo["stress"])


def _entry_key(entry: dict) -> tuple:
    """The identity of one matrix row, shaped like a combo key."""
    return (entry.get("condition"), entry.get("width"), entry.get("theme"),
            entry.get("route", ""), entry.get("state", ""), entry.get("stress"))


def _planned_combos(args, conditions: list[str]) -> list[dict]:
    """Every combination the selected conditions should have measured.

    The plan is rebuilt with one condition at a time, the same way each
    child builds its own, so a child that died before writing its matrix
    still shows up as missing rather than silently shrinking the run.
    """
    planned: list[dict] = []
    for condition in conditions:
        child_args = argparse.Namespace(**vars(args))
        child_args.only_condition = condition
        child_args.conditions = condition
        planned.extend(build_combos(child_args))
    return planned


def _free_udp_port() -> int:
    """A loopback UDP port that is free right now (probed, not reserved)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _load_mock_module():
    """The loopback mock endpoint module, by path (tools is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "agentdesk_layout_mock", ROOT / "tools" / "mock_endpoint.py")
    if spec is None or spec.loader is None:
        raise AuditError("tools/mock_endpoint.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FileKeychain:
    """The keyring module's three methods over a JSON file.

    Copied from tools/demo_readiness.py (around lines 151-184) so the audit
    never touches the real OS keychain. A second boot can read the same file
    back.
    """

    def __init__(self, path: Path) -> None:
        """Load whatever an earlier boot stored, or start empty."""
        self.path = Path(path)
        try:
            self.secrets: dict[str, str] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.secrets = {}

    def _save(self) -> None:
        """Persist the dict to the JSON file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.secrets), encoding="utf-8")

    def get_password(self, service: str, username: str):
        """The stored secret for the pair, or None when there is none."""
        return self.secrets.get(f"{service}|{username}")

    def set_password(self, service: str, username: str, secret: str) -> None:
        """Store the secret under the pair, replacing any earlier one."""
        self.secrets[f"{service}|{username}"] = secret
        self._save()

    def delete_password(self, service: str, username: str) -> None:
        """Remove the pair's secret; a missing one is a plain no-op."""
        self.secrets.pop(f"{service}|{username}", None)
        self._save()


def _pin_environment(data_dir: Path, condition: str, mock_port: int | None) -> None:
    """Set every AGENTDESK_* variable this process reads.

    Must run before any agentdesk import. Empty values are real values and
    beat ~/.agent-desk/config.env under load_env_file's setdefault rules;
    AGENTDESK_DATA is the one variable that must stay non-empty.
    """
    for name in PINNED_EMPTY:
        os.environ[name] = ""
    templates_dir = data_dir.parent / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AGENTDESK_DATA"] = str(data_dir)
    os.environ["AGENTDESK_TEMPLATES"] = str(templates_dir)
    os.environ["AGENTDESK_CALENDAR_FILE"] = ""
    if condition in ("data", "full", "long-values", "busy") and mock_port:
        os.environ["AGENTDESK_LLM_BASE"] = f"http://127.0.0.1:{mock_port}/v1"
        os.environ["AGENTDESK_LLM_KEY"] = "sk-local"
        os.environ["AGENTDESK_LLM_MODEL"] = "mock-chat"
    if condition in ("full", "long-values", "busy"):
        os.environ["AGENTDESK_MARKETPLACE_ADMIN"] = "1"


def _start_mock(delay_ms: int = 0):
    """Start the loopback mock chat endpoint on an ephemeral port."""
    from http.server import ThreadingHTTPServer

    module = _load_mock_module()
    module.DELAY_MS = max(0, int(delay_ms))
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.MockEndpointHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _pin_store_clocks(server) -> None:
    """Give every store that exposes a clock the same fixed instant.

    The sample seed builds its calendar and mail fixtures from the inbox
    store's clock, and the mail and memory pages age their rows from theirs.
    Pinning the attribute is the seam those stores already expose; the
    browser gets the same instant through Playwright's clock.
    """
    clock = lambda: FIXED_EPOCH
    for name in ("inbox", "mail_store", "settings", "activity_log", "memory",
                 "agents", "ledger", "keys"):
        store = getattr(server, name, None)
        if store is not None and hasattr(store, "clock"):
            try:
                store.clock = clock
            except Exception:
                pass


def _boot_desk(condition: str, tmp_root: Path) -> dict:
    """Boot the real app over a fresh data folder and a file-backed keychain.

    Mirrors tools/demo_readiness.Desk: ephemeral port, announce on a free
    UDP port, one daemon request thread, no real keychain and no real data
    folder. Background writers are deliberately not started: the agent
    loop, the excel, calendar and mail timers, plugin widget polls and the
    minute refresh tick can change page content while a run measures it.
    agent_loop_minutes is set to 0 as a second guard in case anything starts
    the loop later. A failure after the server bound stops it before the
    exception leaves this function.
    """
    data_dir = tmp_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    keychain = tmp_root / "keychain.json"
    from agentdesk.keys.secrets import KeychainSecrets
    from agentdesk.server import app as server_app

    server = None
    thread = None
    try:
        server = server_app.create_server(
            port=0, announce_port=_free_udp_port(),
            keychain=KeychainSecrets(backend=FileKeychain(keychain)))
        if getattr(server, "settings", None) is not None:
            server.settings.set("agent_loop_minutes", 0)
        _pin_store_clocks(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        if condition == "legacy-dashboard":
            server_app.SPA_DIR = tmp_root / "missing-spa-build"
        return {"server": server, "thread": thread,
                "base": f"http://127.0.0.1:{server.port}",
                "token": server.sessions.bootstrap_token()}
    except BaseException:
        if server is not None:
            try:
                if thread is not None and thread.is_alive():
                    server.shutdown()
                server.server_close()
                _close_stores(server)
            except Exception:
                pass
        raise


def _close_stores(server) -> None:
    """Close every SQLite connection the server holds, directly or on a store.

    A closed connection is harmless to close again; anything that is not a
    connection is left alone.
    """
    for value in list(vars(server).values()):
        holders = (value, getattr(value, "conn", None))
        for holder in holders:
            if isinstance(holder, sqlite3.Connection):
                try:
                    holder.close()
                except sqlite3.Error:
                    pass


def _stop_desk(desk: dict) -> list[str]:
    """Stop the server, its watchers, its stores and its thread.

    Returns the failures instead of hiding them. Every step is attempted
    even when an earlier one fails, because a store left open blocks the
    temporary folder removal on Windows.
    """
    server = desk["server"]
    errors: list[str] = []
    for name in ("excel", "calendar", "mail", "plugins"):
        watcher = getattr(server, name, None)
        stop = getattr(watcher, "stop_polling", None) if watcher is not None else None
        if callable(stop):
            try:
                stop()
            except Exception as exc:  # noqa: BLE001 - report, keep stopping
                errors.append(f"{name}.stop_polling: {type(exc).__name__}: {exc}")
    try:
        server.shutdown()
    except Exception as exc:  # noqa: BLE001 - report, keep stopping
        errors.append(f"server.shutdown: {type(exc).__name__}: {exc}")
    try:
        server.server_close()
    except Exception as exc:  # noqa: BLE001 - report, keep stopping
        errors.append(f"server.server_close: {type(exc).__name__}: {exc}")
    try:
        desk["thread"].join(timeout=5)
        if desk["thread"].is_alive():
            errors.append("server thread still alive after 5s")
    except Exception as exc:  # noqa: BLE001 - report, keep stopping
        errors.append(f"thread.join: {type(exc).__name__}: {exc}")
    try:
        _close_stores(server)
    except Exception as exc:  # noqa: BLE001 - report, keep stopping
        errors.append(f"close stores: {type(exc).__name__}: {exc}")
    return errors


def _post_json(context, url: str, payload: dict):
    """POST a JSON document through the browser context's request client."""
    return context.request.post(
        url, data=json.dumps(payload),
        headers={"Content-Type": "application/json"})


def _load_api_fixture(path: Path) -> dict:
    """Read an API fixture map, rejecting anything that is not an object.

    A top-level path key maps to the JSON body to fulfil for a matching GET;
    a null body means "do not intercept this endpoint".
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"API fixture {path} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise AuditError(f"API fixture {path} must be a JSON object of path to body")
    return document


def _apply_slow_routes(context, delay_ms: int) -> None:
    """Delay document and /api requests so first-load states can be seen."""
    if delay_ms <= 0:
        return

    def handler(route):
        """Sleep before letting a document or API request through."""
        request = route.request
        api = urllib.parse.urlsplit(request.url).path.startswith("/api/")
        if request.resource_type == "document" or api:
            time.sleep(delay_ms / 1000.0)
        route.continue_()

    context.route("**/*", handler)


def _api_fixture_path(args, condition: str) -> Path | None:
    """The fixture to apply for one condition, defaulted for long-values."""
    value = getattr(args, "api_fixture", "")
    if value:
        return Path(value)
    if condition == "long-values":
        return LONG_VALUES_FIXTURE
    return None


def _apply_api_fixture(context, path: Path) -> None:
    """Fulfil matching GET /api requests from the fixture map.

    The match is by URL path only, so a search query still receives the
    same long catalog. A null body falls through to the real server.
    """
    fixture = _load_api_fixture(path)

    def handler(route, request):
        """Answer one intercepted request, or let it reach the desk."""
        if request.method != "GET":
            route.fallback()
            return
        key = urllib.parse.urlsplit(request.url).path
        if key not in fixture:
            route.fallback()
            return
        body = fixture[key]
        if body is None:
            route.fallback()
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    context.route("**/api/**", handler)


def _api_record_path(record_dir: Path, condition: str, view: dict,
                     api_path: str) -> Path:
    """The file one recorded API response is written to."""
    route = view.get("path", "/").split("#")[0].lstrip("/") or "root"
    state = view.get("state", "state")
    return (record_dir / condition / f"{_slug(route)}__{_slug(state)}"
            / f"{_slug(api_path.lstrip('/'))}.json")


def _api_recorder(record_dir: Path | None, condition: str, view: dict):
    """A response listener that saves GET /api JSON bodies, or None."""
    if record_dir is None:
        return None

    def handler(response):
        """Write one JSON API body; a read failure is skipped, not raised."""
        try:
            if response.request.method != "GET":
                return
            api_path = urllib.parse.urlsplit(response.url).path
            if not api_path.startswith("/api/"):
                return
            body = response.body()
            if not body:
                return
            data = json.loads(body)
        except Exception:  # noqa: BLE001 - recording must never fail a page
            return
        _write_json(_api_record_path(record_dir, condition, view, api_path), data)

    return handler


def _seed(context, base: str, condition: str, tmp_root: Path) -> list[str]:
    """Seed one condition through the app's own routes, as a browser would.

    Sample data, registry installs and the opened sample tracker all use
    the routes the pages use. A refusal raises AuditError with the route
    and status, so a half-seeded desk is never measured as if it were the
    intended condition.
    """
    notes: list[str] = []
    if condition in ("data", "full", "long-values", "busy"):
        response = _post_json(context, f"{base}/settings/toggle", {"key": "sample_data"})
        if response.status != 200:
            raise AuditError(f"sample data toggle answered {response.status}")
        notes.append("sample data on")
    if condition in ("plugins", "full", "long-values", "busy"):
        for plugin_id in _plugin_ids():
            response = _post_json(context, f"{base}/api/registry/install", {"id": plugin_id})
            if response.status != 200:
                raise AuditError(
                    f"installing {plugin_id} answered {response.status}: {response.text()[:200]}")
        notes.append(f"{len(_plugin_ids())} plugin(s) installed")
    if condition in ("full", "long-values", "busy"):
        from agentdesk.server import demo_data

        sample = demo_data.sample_workbook_path()
        if not sample.is_file():
            raise AuditError(f"the sample workbook is not at {sample}")
        instance = "pipeline"
        response = _post_json(context, f"{base}/api/plugins/excel-report/instances",
                              {"name": "Pipeline"})
        if response.status != 200:
            raise AuditError(f"naming the tracker instance answered {response.status}")
        upload_url = (f"{base}/api/plugins/excel-report/instances/{instance}/upload/"
                      f"{urllib.parse.quote(sample.name)}")
        response = context.request.post(
            upload_url, data=sample.read_bytes(),
            headers={"Content-Type": "application/octet-stream"})
        if response.status != 200:
            raise AuditError(f"tracker upload answered {response.status}: {response.text()[:200]}")
        response = _post_json(
            context, f"{base}/api/plugins/excel-report/instances/{instance}/confirm",
            {"tracking": {"labelColumn": "Deal", "valueColumn": "Amount",
                          "aggregate": "sum"}})
        if response.status != 200:
            raise AuditError(f"tracker confirm answered {response.status}: {response.text()[:200]}")
        notes.append("sample tracker open")
    return notes


def _seed_busy(context, base: str, tmp_root: Path, server, mock_port: int | None,
               notes: list[str]) -> list[str]:
    """Seed the populated states on top of the full condition.

    A saved connection fills the Settings table, the assistant turn fills
    the thread, one agent run fills the history, the gates fill the
    capability cache, three long facts fill the memory pages, and mail is
    switched on over the sample .eml folder. The file-backed fake keychain
    holds the connection key; the real keychain is never touched. A failed
    step is reported in the returned notes instead of hiding the page state
    behind an exception.
    """
    if mock_port is None:
        notes.append("busy: no mock endpoint, connection and AI turns were skipped")
        return notes
    mock_base = f"http://127.0.0.1:{mock_port}/v1"
    label = "Regional Enterprise Sales Operation Team"
    model = "regional-forecast-model-enterprise-2026x"
    connection = {
        "provider": "custom",
        "label": label,
        "baseUrl": mock_base,
        "apiKey": "sk-local",
        "model": model,
    }
    try:
        response = context.request.post(
            base + "/api/connections", form=connection, max_redirects=0, timeout=60000)
        if response.status not in (200, 201, 303):
            notes.append(f"busy: connection save answered {response.status}")
        else:
            notes.append("busy: model connection saved")
    except Exception as exc:  # noqa: BLE001 - report the page state that follows
        notes.append(f"busy: connection save failed: {type(exc).__name__}: {exc}")

    question = ("Prepare the regional pipeline review: summarize the consolidated "
                "forecast, the three largest open commitments, and the decisions "
                "that need an owner before Friday.")
    try:
        response = context.request.post(
            base + "/assistant/ask", form={"question": question[:300]},
            max_redirects=0, timeout=120000)
        if response.status not in (200, 303):
            notes.append(f"busy: assistant turn answered {response.status}")
        else:
            notes.append("busy: assistant turn saved")
    except Exception as exc:  # noqa: BLE001 - report the page state that follows
        notes.append(f"busy: assistant turn failed: {type(exc).__name__}: {exc}")

    brief = ("Prepare a concise briefing for the regional sales leadership review that "
             "covers the consolidated pipeline, the three largest open commitments, the "
             "workbook movement since the last reading, and the decisions the desk should "
             "surface before Friday so every owner leaves with a named next step and a date.")
    try:
        response = context.request.post(
            base + "/agents/run",
            data=json.dumps({"agent": "worksheet-brief", "brief": brief[:300]}),
            headers={"Content-Type": "application/json"}, timeout=120000)
        if response.status not in (200, 201):
            notes.append(f"busy: agent run answered {response.status}: {response.text()[:120]}")
        else:
            notes.append("busy: agent run recorded")
    except Exception as exc:  # noqa: BLE001 - report the page state that follows
        notes.append(f"busy: agent run failed: {type(exc).__name__}: {exc}")

    try:
        from agentdesk.capabilities import GATES

        cached = 0
        for key, _number, _title in GATES:
            try:
                response = context.request.post(
                    base + f"/capabilities/{key}/retest",
                    headers={"Content-Type": "application/json"}, timeout=120000)
                if response.status in (200, 201):
                    cached += 1
                else:
                    notes.append(f"busy: gate {key} answered {response.status}")
            except Exception as exc:  # noqa: BLE001 - one gate cannot stop the rest
                notes.append(f"busy: gate {key} failed: {type(exc).__name__}: {exc}")
        notes.append(f"busy: {cached} capability gate(s) cached")
    except Exception as exc:  # noqa: BLE001 - report the page state that follows
        notes.append(f"busy: capability gates failed: {type(exc).__name__}: {exc}")

    facts = [
        ("The northern region renewal for Halvorsen Freight is expected to close before "
         "the end of the quarter, and the commercial team agreed to confirm the final "
         "contract value with the customer success team."),
        (r"C:\Users\a.manager\OneDrive - Northwind Holdings\Quarterly Forecasts"
         r"\FY2026 Consolidated Pipeline and Commitments.xlsx"),
        ("ENT" + "9" * 77),
    ]
    added = 0
    for text in facts:
        try:
            response = context.request.post(
                base + "/memory/add",
                data=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"}, timeout=60000)
            if response.status in (200, 201):
                added += 1
            else:
                notes.append(f"busy: memory add answered {response.status}")
        except Exception as exc:  # noqa: BLE001 - report the page state that follows
            notes.append(f"busy: memory add failed: {type(exc).__name__}: {exc}")
    notes.append(f"busy: {added} memory fact(s) added")

    try:
        response = _post_json(context, base + "/settings/toggle", {"key": "mail_enabled"})
        if response.status != 200:
            notes.append(f"busy: mail toggle answered {response.status}")
        else:
            mail_dir = tmp_root / "data" / "sample" / "sample-mail"
            response = _post_json(context, base + "/settings/mail/folder",
                                  {"folder": str(mail_dir)})
            if response.status != 200:
                notes.append(f"busy: mail folder answered {response.status}")
            else:
                notes.append("busy: mail watching the sample folder")
    except Exception as exc:  # noqa: BLE001 - report the page state that follows
        notes.append(f"busy: mail seed failed: {type(exc).__name__}: {exc}")

    for name in ("mail", "excel", "calendar"):
        watcher = getattr(server, name, None)
        stop = getattr(watcher, "stop_polling", None) if watcher is not None else None
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
    try:
        runner = getattr(getattr(server, "plugins", None), "runner", None)
        for watch in (getattr(runner, "_watches", {}) or {}).values():
            stop = getattr(watch, "stop_polling", None)
            if callable(stop):
                stop()
    except Exception:
        pass
    return notes

def _write_calendar_fixture(tmp_root: Path) -> Path:
    """Write a tiny valid calendar file for the walkthrough page hint."""
    path = tmp_root / "calendar_sync.json"
    path.write_text(json.dumps({
        "generatedAt": "2026-11-24T08:00:00",
        "events": [{"id": "evt-1", "subject": "Layout audit event",
                    "start": "2026-11-24T14:00:00", "end": "2026-11-24T15:00:00"}],
    }), encoding="utf-8")
    return path


def _wait_for_view(page, view: dict) -> None:
    """Wait until the page's own content is on screen, not a loading skeleton.

    SPA pages are ready when their main landmark exists and no polite
    loading line or aria-busy region is still showing. A settings section
    is ready when the section script has run and exactly one group is
    visible. Server pages are ready when the body has parsed; fonts are
    awaited separately for every page.
    """
    page.wait_for_function(
        "() => document.body && document.body.childElementCount > 0", timeout=15000)
    if view.get("kind") == "spa" and view.get("path") == "/":
        page.wait_for_function(
            "() => { const m = document.querySelector('#dashboard-main');"
            " const c = document.querySelector('.center-card');"
            " if (!m && !c) return false;"
            " if (c && c.getAttribute('aria-busy') === 'true') return false;"
            " return true; }", timeout=20000)
    elif view.get("kind") == "spa":
        page.wait_for_function(
            "() => { const m = document.querySelector('main.mkt-main');"
            " if (!m) return false;"
            " if (m.querySelector('[aria-busy=\"true\"]')) return false;"
            " const statuses = Array.prototype.slice.call(m.querySelectorAll('[role=\"status\"]'));"
            " for (const el of statuses) { if (/^Loading/.test((el.textContent || '').trim())) return false; }"
            " if ((m.textContent || '').indexOf('Loading plugins') >= 0) return false;"
            " return true; }", timeout=20000)
    if view.get("settings_section"):
        section = view["settings_section"]
        page.wait_for_function(
            "(key) => { const root = document.documentElement;"
            " if (!root.classList.contains('js-settings')) return false;"
            " const groups = Array.prototype.slice.call(document.querySelectorAll('[data-settings-section]'));"
            " const shown = groups.filter(function(g) { return !g.hidden; });"
            " if (shown.length !== 1) return false;"
            " return shown[0].getAttribute('data-settings-section') === key; }",
            arg=section, timeout=15000)


def _settle_page(page) -> None:
    """Wait for fonts, network idle and a short layout settle.

    The 400 ms pause is the deterministic stand-in for the paint the
    browser would show a person; every measured page gets the same one.
    """
    try:
        page.evaluate("() => document.fonts.ready.then(() => true)")
    except Exception:  # noqa: BLE001 - a page without fonts is still measured
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(400)


def _final_path(page) -> str:
    """The pathname of the browser's current address."""
    return urllib.parse.urlsplit(page.url).path or "/"


def _final_target(page) -> str:
    """The path and query of the browser's current address, hash excluded."""
    parts = urllib.parse.urlsplit(page.url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def _screenshot_file(run_dir: Path, combo: dict, view: dict) -> Path:
    """The mechanical full-page screenshot path for one combination."""
    route = view.get("path", "/").split("#")[0]
    route_slug = _slug(route.lstrip("/")) if route != "/" else "root"
    state_slug = _slug(view.get("state", "state"))
    return (run_dir / combo["condition"] / f"{combo['width']}x{VIEWPORT_HEIGHT}"
            / combo["theme"] / f"{route_slug}__{state_slug}.png")


def _group_identity(finding: dict) -> tuple[str, str]:
    """The stable (id, key) used for root-cause grouping and crop names.

    Normal and stress findings never share a group: a normal group's crop
    must not be a tripled page.
    """
    layer = "stress" if finding.get("stress") else "normal"
    key = (f"{finding.get('kind', '')}|{finding.get('container', '')}|"
           f"{finding.get('classes', '')}|{layer}")
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return digest, key


def _crop_file(run_dir: Path, finding: dict, condition: str, view_slug: str,
               index: int) -> Path:
    """The crop path for one finding; the group id is the file name prefix.

    A stress crop carries the marker in its name so it can never be mistaken
    for a normal-page crop.
    """
    group_id, _key = _group_identity(finding)
    marker = "stress_" if finding.get("stress") else ""
    return (run_dir / "crops" /
            f"{group_id}__{condition}__{view_slug}__{marker}{index}.png")


def _capture_crop(page, finding: dict, path: Path) -> None:
    """Capture a 24 px-margin crop of the measured rectangle, or its edge.

    The element is located by the short selector and the match whose box is
    nearest the measured rectangle, then scrolled into view with Playwright
    so nested scrollers (a sheet body, a table wrapper) move too, not only
    the window. All scroll positions are restored afterwards. An element
    past the right edge (lost content in the SPA) has no visible pixels, so
    the crop falls back to that edge, which is the evidence a reader sees.
    """
    saved = finding.get("rect") or {}
    if not saved:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    viewport = page.viewport_size or {"width": 1280, "height": VIEWPORT_HEIGHT}
    page.evaluate(
        "() => { window.__layoutScroll = [];"
        " for (const el of document.querySelectorAll('*')) {"
        " if (el.scrollTop || el.scrollLeft) {"
        " window.__layoutScroll.push([el, el.scrollTop, el.scrollLeft]); } } }")
    box = None
    selector = finding.get("selector") or ""
    try:
        locator = page.locator(selector)
        count = locator.count()
        if count:
            boxes = locator.evaluate_all(
                "(els) => els.map(function(el) {"
                " const r = el.getBoundingClientRect();"
                " return {x:r.x, y:r.y, w:r.width, h:r.height}; })")
            best_index = 0
            best_distance = None
            for index, candidate in enumerate(boxes):
                distance = (abs(candidate["x"] - float(saved.get("x", 0))) +
                            abs(candidate["y"] - float(saved.get("y", 0))) +
                            abs(candidate["w"] - float(saved.get("w", 0))) +
                            abs(candidate["h"] - float(saved.get("h", 0))))
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_index = index
            target = locator.nth(best_index)
            target.scroll_into_view_if_needed(timeout=2000)
            box = target.bounding_box()
    except Exception:  # noqa: BLE001 - the saved rectangle is the fallback
        box = None
    if box is None:
        top = float(saved.get("y", 0))
        old_scroll = float(page.evaluate("() => window.scrollY"))
        page.evaluate("(y) => window.scrollTo(0, y)", max(0, old_scroll + top - 100))
        page.wait_for_timeout(80)
        now = float(page.evaluate("() => window.scrollY"))
        box = {"x": float(saved.get("x", 0)),
               "y": top - (now - old_scroll),
               "width": float(saved.get("w", 1)),
               "height": float(saved.get("h", 1))}
    margin = 24
    x = max(0, box["x"] - margin)
    y = max(0, box["y"] - margin)
    clip_w = min(viewport["width"] - x, max(32, box["width"] + margin * 2))
    clip_h = min(viewport["height"] - y, max(32, box["height"] + margin * 2))
    if x > viewport["width"] - 32:
        x = max(0, viewport["width"] - 320)
        clip_w = min(320, viewport["width"] - x)
    if y > viewport["height"] - 32:
        y = max(0, viewport["height"] - 200)
        clip_h = min(200, viewport["height"] - y)
    try:
        if clip_w > 1 and clip_h > 1:
            page.screenshot(path=str(path), clip={"x": x, "y": y,
                                                  "width": clip_w, "height": clip_h})
    except Exception:  # noqa: BLE001 - a crop is evidence, not a measurement
        pass
    finally:
        page.evaluate(
            "() => { for (const entry of (window.__layoutScroll || [])) {"
            " entry[0].scrollTop = entry[1]; entry[0].scrollLeft = entry[2]; }"
            " window.scrollTo(0, 0); }")


def _pending_controls(page) -> list[dict]:
    """The visible buttons and submit controls on the current page."""
    return page.evaluate(PENDING_ENUM_JS, {"selector": PENDING_SELECTOR})


def _pending_click(page, control: dict) -> bool:
    """Click the matching visible control by its recorded path and ordinal.

    The index among all matching elements is not the index among visible
    ones, so the match uses the path and text the enumeration recorded,
    then the same ordinal when duplicates share both.
    """
    return bool(page.evaluate(
        r"""(arg) => {
          function visible(el) {
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') < 0.01) return false;
            const r = el.getBoundingClientRect();
            return r.width >= 1 && r.height >= 1;
          }
          function path(el) {
            const parts = [el.tagName.toLowerCase()];
            const cls = Array.from(el.classList || []).slice(0, 3);
            if (cls.length) parts[0] += '.' + cls.join('.');
            return parts.join('.');
          }
          const found = [];
          for (const el of document.querySelectorAll(arg.selector)) {
            if (!visible(el)) continue;
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 160);
            if (path(el) === arg.path && text === arg.text) found.push(el);
          }
          const el = found[arg.ordinal] || found[0];
          if (!el) return false;
          el.scrollIntoView({block: 'center', inline: 'center'});
          el.click();
          return true;
        }""", {"selector": PENDING_SELECTOR, "path": control.get("path", ""),
               "text": control.get("text", ""),
               "ordinal": control.get("ordinal", 0)}))


def _pending_indicators(page) -> list[dict]:
    """The visible busy-looking elements on the current page."""
    return page.evaluate(
        r"""(selector) => {
          function visible(el) {
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') < 0.01) return false;
            const r = el.getBoundingClientRect();
            return r.width >= 1 && r.height >= 1;
          }
          const out = [];
          const seen = new Set();
          for (const sel of ['[aria-busy="true"]','[role="progressbar"]',
                             '[class*="skel"],[class*="skeleton"],[class*="busy"]']) {
            for (const node of document.querySelectorAll(sel)) {
              if (!visible(node) || seen.has(node)) continue;
              seen.add(node);
              out.push({path:node.tagName.toLowerCase() + '.' + String(node.className || '').split(/\\s+/).slice(0, 3).join('.'),
                       text:(node.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80)});
            }
          }
          const permanentWire = new Set(['wire','wire-chart','wire-copy','wire-rows','wire-lines',
                                         'wire-wide','moves-wire','setup-open-wire','wire-state']);
          for (const node of document.querySelectorAll('[class*="wire"]')) {
            const classes = String(node.className || '').split(/\s+/);
            const dynamic = classes.some(function(name) {
              return name.indexOf('wire') >= 0 && !permanentWire.has(name);
            });
            if (!dynamic || !visible(node) || seen.has(node)) continue;
            seen.add(node);
            out.push({path:node.tagName.toLowerCase() + '.' + String(node.className || '').split(/\s+/).slice(0, 3).join('.'),
                      text:(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)});
          }
          return out.slice(0, 12);
        }""", PENDING_SELECTOR)


def _pending_screenshot(run_dir: Path, combo: dict, view: dict, index: int) -> Path:
    """The screenshot path for one pending control."""
    route = view.get("path", "/").split("#")[0].lstrip("/") or "root"
    return (run_dir / "pending" / combo["condition"] / f"{combo['width']}x800"
            / combo["theme"] / f"{_slug(route)}__{_slug(view.get('state', 'state'))}"
            f"__{index:03d}.png")


def _pending_verdict(control: dict, state: dict, started: list[dict],
                     before_indicators: list[dict], file_dialog: bool) -> tuple[str, dict]:
    """Name one control's pending state and the evidence behind it."""
    if file_dialog:
        return "native-dialog", {"reason": "file chooser opened"}
    control_after = state.get("control") or {}
    indicators_after = state.get("indicators") or []
    before_keys = {(item.get("path"), item.get("text")) for item in before_indicators}
    new_indicators = [item for item in indicators_after
                      if (item.get("path"), item.get("text")) not in before_keys]
    label_changed = bool(state.get("labelChanged"))
    aria_busy = bool(state.get("ariaBusy"))
    disabled = bool(control_after.get("disabled"))
    evidence = {
        "request_started": bool(started),
        "requests": started[:4],
        "disabled": disabled,
        "aria_busy": aria_busy,
        "label_changed": label_changed,
        "busy_indicators": new_indicators[:4],
    }
    if not started:
        return "instant", evidence
    picker = any(
        marker in str(request.get("url", ""))
        for request in started
        for marker in ("/pick", "/upload", "/choose", "/browse"))
    if picker:
        evidence["reason"] = "file-picker request held"
        return "native-dialog", evidence
    if aria_busy or label_changed or new_indicators:
        return "meets", evidence
    if disabled:
        return "disabled-only", evidence
    return "silent", evidence


def _run_pending_audit(context, base: str, combos: list[dict], run_dir: Path,
                       condition: str) -> list[dict]:
    """Click every visible control on every selected page in a fresh page.

    Non-GET requests are held and never completed, so no click can mutate
    the desk. Each control gets its own page, with the same fixed clock and
    route fixture as the measured run.
    """
    records: list[dict] = []
    total = 0
    for combo in combos:
        view = combo["view"]
        page = context.new_page()
        try:
            page.clock.install(time=FIXED_TIME)
            page.clock.set_fixed_time(FIXED_TIME)
        except Exception:
            pass
        try:
            page.goto(base + view["path"], wait_until="domcontentloaded", timeout=30000)
            _wait_for_view(page, view)
            _settle_page(page)
            if view.get("kind") == "overlay":
                reason = _open_overlay(page, combo)
                if reason:
                    print(f"[{condition}] pending {view.get('state')}: {reason}",
                          flush=True)
                    page.close()
                    continue
                page.wait_for_timeout(250)
            controls = _pending_controls(page)
        except Exception as exc:  # noqa: BLE001 - one page cannot stop the audit
            print(f"[{condition}] pending {view.get('state')}: {type(exc).__name__}: {exc}",
                  flush=True)
            page.close()
            continue
        page.close()
        for control in controls:
            total += 1
            index = control["index"]
            record = {
                "condition": condition, "width": combo["width"], "theme": combo["theme"],
                "route": view["path"], "state": view.get("state", ""),
                "control": control["text"] or control["path"],
                "control_path": control["path"], "control_tag": control["tag"],
                "verdict": "skipped", "evidence": {}, "screenshot": "",
            }
            if control.get("disabled"):
                record["evidence"] = {"reason": "already disabled"}
                records.append(record)
                continue
            fresh = context.new_page()
            started: list[dict] = []
            file_dialog = [False]

            def hold(route):
                """Hold every non-GET request; let GETs through."""
                if route.request.method == "GET":
                    route.continue_()
                else:
                    started.append({"method": route.request.method,
                                    "url": route.request.url})
                    return

            def on_dialog(dialog):
                """Dismiss a JS alert or confirm so the page can continue."""
                try:
                    dialog.dismiss()
                except Exception:
                    pass

            def on_filechooser(chooser):
                """Record a native file picker and dismiss it."""
                file_dialog[0] = True
                try:
                    chooser.set_files([])
                except Exception:
                    pass

            try:
                fresh.clock.install(time=FIXED_TIME)
                fresh.clock.set_fixed_time(FIXED_TIME)
            except Exception:
                pass
            try:
                fresh.goto(base + view["path"], wait_until="domcontentloaded", timeout=30000)
                _wait_for_view(fresh, view)
                _settle_page(fresh)
                if view.get("kind") == "overlay":
                    reason = _open_overlay(fresh, combo)
                    if reason:
                        record["evidence"] = {"reason": reason}
                        records.append(record)
                        fresh.close()
                        continue
                    fresh.wait_for_timeout(250)
                fresh.evaluate("() => window.scrollTo(0, 0)")
                before_indicators = _pending_indicators(fresh)
                fresh.on("dialog", on_dialog)
                fresh.on("filechooser", on_filechooser)
                fresh.route("**/*", hold)
                if not _pending_click(fresh, control):
                    raise RuntimeError("control not found on the fresh page")
                fresh.wait_for_timeout(700)
                state = fresh.evaluate(PENDING_STATE_JS, {
                    "selector": PENDING_SELECTOR,
                    "path": control.get("path", ""),
                    "text": control.get("text", ""),
                    "ordinal": control.get("ordinal", 0),
                    "before": control.get("text") or "",
                })
                verdict, evidence = _pending_verdict(
                    control, state, started, before_indicators, file_dialog[0])
                record["verdict"] = verdict
                record["evidence"] = evidence
                if state.get("control"):
                    record["control_after"] = state["control"]
                path = _pending_screenshot(run_dir, combo, view, total)
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fresh.screenshot(path=str(path))
                    record["screenshot"] = str(path)
                except Exception:
                    pass
                records.append(record)
            except Exception as exc:  # noqa: BLE001 - one control cannot stop the audit
                record["verdict"] = "skipped"
                record["evidence"] = {"reason": f"{type(exc).__name__}: {exc}"[:200]}
                records.append(record)
            finally:
                try:
                    fresh.close()
                except Exception:
                    pass
    return records


def _annotate(findings: list[dict], combo: dict, stress: bool) -> None:
    """Attach the matrix coordinates to every finding the probe returned."""
    for finding in findings:
        finding["route"] = combo["view"]["path"]
        finding["state"] = combo["view"].get("state", "")
        finding["condition"] = combo["condition"]
        finding["width"] = combo["width"]
        finding["theme"] = combo["theme"]
        finding["stress"] = bool(stress)
        finding["kind"] = str(finding.get("kind", ""))
        finding["severity"] = str(finding.get("severity", "low"))
        finding["metrics"] = finding.get("metrics") or {}


def _dedupe(findings: list[dict]) -> list[dict]:
    """Drop exact duplicates the probe can produce through nested paths."""
    seen = set()
    out = []
    for finding in findings:
        metrics = json.dumps(finding.get("metrics") or {}, sort_keys=True)
        key = (finding.get("kind"), finding.get("container"), finding.get("selector"),
               finding.get("text"), metrics, finding.get("otherSelector", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _runtime_events(page) -> dict:
    """Collect the runtime event lists the measurement attaches to a page."""
    return {"console": [], "pageerror": [], "requestfailed": [], "http5xx": []}


def _attach_runtime(page, store: dict) -> None:
    """Subscribe to console errors, page errors, failed requests and 5xx."""
    page.on("console", lambda message: store["console"].append(message.text)
            if message.type == "error" else None)
    page.on("pageerror", lambda error: store["pageerror"].append(str(error)))
    page.on("requestfailed", lambda request: store["requestfailed"].append(
        f"{request.method} {request.url} {request.failure}"))
    page.on("response", lambda response: store["http5xx"].append(
        f"{response.status} {response.url}") if response.status >= 500 else None)


def _reset_runtime(store: dict) -> None:
    """Clear one navigation's runtime event lists."""
    for key in store:
        store[key].clear()


def _runtime_findings(store: dict, combo: dict) -> list[dict]:
    """Turn the collected runtime events into low-severity runtime findings."""
    out = []
    groups = (
        ("console", "console error"),
        ("pageerror", "page error"),
        ("requestfailed", "failed request"),
        ("http5xx", "http 5xx response"),
    )
    expected_error = bool(combo["view"].get("expected_error"))
    for key, label in groups:
        for message in sorted(set(store.get(key, []))):
            if key == "requestfailed" and "ERR_ABORTED" in message:
                continue
            if key == "console" and expected_error and "Failed to load resource" in message:
                continue
            out.append({
                "kind": "runtime",
                "severity": "low",
                "stress": False,
                "route": combo["view"]["path"],
                "state": combo["view"].get("state", ""),
                "condition": combo["condition"],
                "width": combo["width"],
                "theme": combo["theme"],
                "selector": "page",
                "container": "page",
                "classes": label,
                "text": message[:200],
                "metrics": {"runtimeType": label},
                "rect": {},
            })
    return out


def _open_overlay(page, combo: dict) -> str:
    """Open the overlay the combo names; return '' on success or a reason."""
    opener = combo["view"].get("opener", "")
    if opener == "widget-menu":
        trigger = page.locator('button[aria-label^="Widget options"]').first
        if trigger.count() == 0:
            return "no widget overflow trigger on this dashboard"
        trigger.click()
        page.wait_for_selector('[role="menu"]', timeout=5000)
        return ""
    if opener == "tracker-setup":
        buttons = page.locator(".tracker-card button")
        target = None
        for index in range(buttons.count()):
            text = (buttons.nth(index).inner_text() or "").strip()
            if text in ("Set up", "Edit"):
                target = buttons.nth(index)
                break
        if target is None:
            return "no Set up or Edit control on the tracker card"
        target.click()
        page.wait_for_selector(".setup-sheet[role=\"dialog\"]", timeout=5000)
        return ""
    if opener == "customize":
        trigger = page.locator("button", has_text="Customize").first
        if trigger.count() == 0:
            return "no Customize control on the dashboard"
        trigger.click()
        page.wait_for_selector(".cust-panel", timeout=5000)
        return ""
    if opener == "consent":
        trigger = page.locator("button", has_text="Install plugin").first
        if trigger.count() == 0:
            return "no Install plugin control (plugin may already be installed)"
        trigger.click()
        page.wait_for_selector(".mkt-sheet[role=\"dialog\"]", timeout=5000)
        return ""
    if opener == "instance-setup":
        trigger = page.locator("button", has_text="Set up a new instance").first
        if trigger.count() == 0:
            trigger = page.locator("button", has_text="Edit ").first
        if trigger.count() == 0:
            return "no instance setup control on the manage page"
        trigger.click()
        page.wait_for_selector(".setup-sheet[role=\"dialog\"]", timeout=5000)
        return ""
    if opener == "purge":
        trigger = page.locator("button", has_text="Purge data").first
        if trigger.count() == 0:
            return "no Purge data control on the installed page"
        trigger.click()
        page.wait_for_selector(".mkt-sheet[role=\"dialog\"]", timeout=5000)
        return ""
    if opener == "describe":
        trigger = page.locator("button", has_text="Describe a plugin in plain English").first
        if trigger.count() == 0:
            return "no describe-a-plugin control on the catalog page"
        trigger.click()
        try:
            page.wait_for_selector(".setup-sheet[role=\"dialog\"]", timeout=5000)
        except PlaywrightTimeoutError:
            return "the describe control submitted the walk instead of opening a dialog"
        return ""
    return f"unknown overlay opener {opener!r}"


def _measure_combo(page, combo: dict, runtime: dict, run_dir: Path,
                   calendar_fixture: Path, crop_counts: dict, base: str,
                   record_dir: Path | None = None) -> dict:
    """Visit, wait, assert and measure one combination.

    Returns the matrix entry plus the findings it produced. A page whose
    address, status or theme is not what was asked for is reported, never
    measured as if it were the page.
    """
    view = combo["view"]
    entry = {
        "condition": combo["condition"], "width": combo["width"],
        "theme": combo["theme"], "route": view["path"],
        "state": view.get("state", ""), "stress": combo["stress"],
        "status": "measured", "note": "", "http": None,
        "final_url": "", "ms": 0,
    }
    started = time.monotonic()
    findings: list[dict] = []
    screenshot = _screenshot_file(run_dir, combo, view)
    use_fixture = bool(view.get("calendar_fixture"))
    if use_fixture:
        os.environ["AGENTDESK_CALENDAR_FILE"] = str(calendar_fixture)
    record_handler = _api_recorder(record_dir, combo["condition"], view)
    if record_handler is not None:
        page.on("response", record_handler)
    try:
        _reset_runtime(runtime)
        response = page.goto(base + view["path"], wait_until="domcontentloaded",
                             timeout=30000)
        entry["http"] = response.status if response is not None else None
        _wait_for_view(page, view)
        _settle_page(page)
        state = page.evaluate(
            "() => ({theme: document.documentElement.dataset.theme || '',"
            " tripled: !!window.__AGENTDESK_LAYOUT_TRIPLED__})")
        if state.get("theme") != combo["theme"] or state.get("tripled"):
            page.reload(wait_until="domcontentloaded", timeout=30000)
            _wait_for_view(page, view)
            _settle_page(page)
        entry["final_url"] = page.url
        final_target = _final_target(page)
        expected_target = view["path"].split("#")[0]
        if final_target != expected_target:
            entry["status"] = "auth-failed" if _final_path(page).startswith("/auth") else "wrong-page"
            entry["note"] = f"final address {final_target}, expected {expected_target}"
        elif entry["http"] and entry["http"] >= 400 and not view.get("expected_error"):
            if entry["http"] in (401, 403):
                entry["status"] = "auth-failed"
            else:
                entry["status"] = "wrong-page"
            entry["note"] = f"http {entry['http']}"
        if entry["status"] == "measured":
            theme = page.evaluate("() => document.documentElement.dataset.theme || ''")
            if theme != combo["theme"]:
                entry["status"] = "theme-not-applied"
                entry["note"] = f"document theme {theme!r}"
        if entry["status"] != "measured":
            entry["ms"] = int((time.monotonic() - started) * 1000)
            return {"entry": entry, "findings": findings}
        if view.get("kind") == "overlay":
            reason = _open_overlay(page, combo)
            if reason:
                entry["status"] = "skipped"
                entry["note"] = reason
                entry["ms"] = int((time.monotonic() - started) * 1000)
                return {"entry": entry, "findings": findings}
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(300)
        page.evaluate("() => { window.scrollTo(0, 0); }")
        page.wait_for_timeout(50)
        page.evaluate("() => { window.__AGENTDESK_LAYOUT_STRESS__ = false; }")
        normal = page.evaluate(PROBE_JS)
        normal_findings = _dedupe(normal.get("findings", []))
        _annotate(normal_findings, combo, False)
        findings.extend(normal_findings)
        reference = (combo["width"] == 1280 and combo["theme"] == "unkey"
                     and (combo["condition"] in BASE_CONDITIONS
                          or combo["condition"] == "legacy-dashboard"))
        needs_shot = bool(normal_findings) or reference or view.get("kind") == "overlay"
        if needs_shot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(screenshot), full_page=True)
                entry["screenshot"] = str(screenshot)
            except Exception as exc:  # noqa: BLE001 - report, do not fail the page
                entry["note"] = (entry["note"] + " screenshot failed: " + str(exc)).strip()
        view_slug = _slug(view.get("state", "state"))
        for finding in normal_findings:
            group_id, _key = _group_identity(finding)
            count = crop_counts.get(group_id, 0)
            if count >= 3:
                continue
            path = _crop_file(run_dir, finding, combo["condition"], view_slug, count + 1)
            _capture_crop(page, finding, path)
            if path.exists():
                crop_counts[group_id] = count + 1
                finding["crop"] = str(path)
        if combo["stress"]:
            page.evaluate("() => { window.__AGENTDESK_LAYOUT_STRESS__ = true; }")
            stressed = page.evaluate(PROBE_JS)
            stress_findings = _dedupe(stressed.get("findings", []))
            _annotate(stress_findings, combo, True)
            findings.extend(stress_findings)
            for finding in stress_findings:
                group_id, _key = _group_identity(finding)
                count = crop_counts.get(group_id, 0)
                if count >= 3:
                    continue
                path = _crop_file(run_dir, finding, combo["condition"], view_slug, count + 1)
                _capture_crop(page, finding, path)
                if path.exists():
                    crop_counts[group_id] = count + 1
                    finding["crop"] = str(path)
            page.evaluate("() => { window.__AGENTDESK_LAYOUT_STRESS__ = false; }")
        page.evaluate("() => { window.__AGENTDESK_LAYOUT_STRESS__ = false; }")
    except PlaywrightTimeoutError as exc:
        entry["status"] = "error"
        entry["note"] = f"timeout: {exc}".splitlines()[0][:300]
    except Exception as exc:  # noqa: BLE001 - one page must not stop the matrix
        entry["status"] = "error"
        entry["note"] = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
    finally:
        if record_handler is not None:
            page.remove_listener("response", record_handler)
        if use_fixture:
            os.environ["AGENTDESK_CALENDAR_FILE"] = ""
    entry["ms"] = int((time.monotonic() - started) * 1000)
    if entry["status"] == "measured":
        findings.extend(_runtime_findings(runtime, combo))
    return {"entry": entry, "findings": findings}


def _condition_worker(args, condition: str, run_dir: Path) -> int:
    """Run one condition in this process: boot, seed, browse, write JSON.

    A child process per condition keeps agentdesk's module-level state and
    environment isolated, which is what makes four conditions in one run
    honest. Returns a process exit code.
    """
    tmp_root = Path(tempfile.mkdtemp(prefix=f"agentdesk-layout-{condition}-"))
    mock = None
    mock_port = None
    desk = None
    try:
        if condition in ("data", "full", "long-values", "busy"):
            mock, mock_port = _start_mock(getattr(args, "mock_delay_ms", 0))
        _pin_environment(tmp_root / "data", condition, mock_port)
        if "src" not in sys.path:
            sys.path.insert(0, str(ROOT / "src"))
        if "tools" not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        desk = _boot_desk(condition, tmp_root)
        base = desk["base"]
        calendar_fixture = _write_calendar_fixture(tmp_root)
        print(f"[{condition}] booted {base}", flush=True)
        combos = [combo for combo in build_combos(args) if combo["condition"] == condition]
        if not combos:
            print(f"[{condition}] no combinations", flush=True)
            return 0
        all_findings: list[dict] = []
        matrix: list[dict] = []
        pending_records: list[dict] = []
        record_dir = None
        if getattr(args, "record_api", ""):
            record_dir = Path(args.record_api)
            record_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{condition}] {len(combos)} combination(s)", flush=True)
        stderr_path = run_dir / f"server-stderr.{condition}.log"
        stderr_handle = open(stderr_path, "w", encoding="utf-8")
        old_stderr = sys.stderr
        sys.stderr = stderr_handle
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": combos[0]["width"], "height": VIEWPORT_HEIGHT},
                    device_scale_factor=1, reduced_motion="reduce")
                _apply_slow_routes(context, getattr(args, "slow_ms", 0))
                if getattr(args, "pending_audit", False):
                    context.add_init_script(
                        "() => { try { localStorage.removeItem('agentdesk.railCollapsed'); } catch (e) {} }")
                fixture = _api_fixture_path(args, condition)
                if fixture is not None:
                    if not Path(fixture).is_file():
                        raise AuditError(f"API fixture is missing: {fixture}")
                    _apply_api_fixture(context, Path(fixture))
                    print(f"[{condition}] API fixture {fixture}", flush=True)
                page = context.new_page()
                try:
                    page.clock.install(time=FIXED_TIME)
                    page.clock.set_fixed_time(FIXED_TIME)
                except Exception as exc:  # noqa: BLE001 - a clear failure beats silent drift
                    raise AuditError(
                        f"could not fix the browser clock at {FIXED_TIME}: {exc}") from exc
                runtime = _runtime_events(page)
                _attach_runtime(page, runtime)
                current_width = combos[0]["width"]
                current_theme = ""
                crop_counts: dict[str, int] = {}
                try:
                    page.goto(base + "/auth/" + desk["token"],
                              wait_until="domcontentloaded", timeout=20000)
                    if _final_path(page) != "/":
                        raise AuditError(f"auth landed on {_final_path(page)}, not /")
                    notes = _seed(context, base, condition, tmp_root)
                    if condition == "busy":
                        notes = _seed_busy(context, base, tmp_root, desk["server"],
                                           mock_port, notes)
                    if notes:
                        print(f"[{condition}] seeded: {', '.join(notes)}", flush=True)
                    for combo in combos:
                        if combo["width"] != current_width:
                            page.set_viewport_size(
                                {"width": combo["width"], "height": VIEWPORT_HEIGHT})
                            current_width = combo["width"]
                        if combo["theme"] != current_theme:
                            page.evaluate(
                                "(theme) => localStorage.setItem('agentdesk.theme', theme)",
                                combo["theme"])
                            current_theme = combo["theme"]
                        result = _measure_combo(page, combo, runtime, run_dir,
                                                calendar_fixture, crop_counts, base,
                                                record_dir)
                        entry = result["entry"]
                        matrix.append(entry)
                        all_findings.extend(result["findings"])
                        print(
                            f"[{entry['condition']} {entry['width']} {entry['theme']}] "
                            f"{entry['state']}: {entry['status']} "
                            f"n={len(result['findings'])} {entry['ms']}ms"
                            + (f" ({entry['note']})" if entry.get("note") else ""),
                            flush=True)
                        if entry["status"] == "measured" and view_is_overlay(combo["view"]):
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(100)
                    if getattr(args, "pending_audit", False):
                        print(f"[{condition}] pending audit over {len(combos)} page(s)",
                              flush=True)
                        pending_records = _run_pending_audit(
                            context, base, combos, run_dir, condition)
                        print(f"[{condition}] pending audit wrote {len(pending_records)} "
                              f"control record(s)", flush=True)
                finally:
                    page.close()
                    context.close()
                    browser.close()
        finally:
            sys.stderr = old_stderr
            stderr_handle.close()
        _write_json(run_dir / f"findings.{condition}.json", all_findings)
        _write_json(run_dir / f"matrix.{condition}.json", matrix)
        if pending_records:
            _write_json(run_dir / f"pending.{condition}.json", pending_records)
        skipped = [entry for entry in matrix if entry["status"] == "skipped"]
        _write_json(run_dir / f"skipped.{condition}.json", skipped)
        print(f"[{condition}] wrote {len(all_findings)} finding(s), "
              f"{len(matrix)} matrix row(s)", flush=True)
        return 0
    except KeyboardInterrupt:
        print(f"[{condition}] interrupted", flush=True)
        return 130
    except Exception as exc:  # noqa: BLE001 - the parent reports the cause
        message = f"{type(exc).__name__}: {exc}"
        print(f"[{condition}] FAILED: {message}", flush=True)
        _write_json(run_dir / f"fatal.{condition}.json", {
            "condition": condition, "message": message,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        return 1
    finally:
        if desk is not None:
            for error in _stop_desk(desk):
                print(f"[{condition}] teardown: {error}", flush=True)
        if mock is not None:
            try:
                mock.shutdown()
                mock.server_close()
            except Exception as exc:  # noqa: BLE001 - report teardown noise
                print(f"[{condition}] mock teardown: {type(exc).__name__}: {exc}",
                      flush=True)
        shutil.rmtree(tmp_root, ignore_errors=True)
        if tmp_root.exists():
            print(f"[{condition}] TEMP REMOVE FAILED {tmp_root}", flush=True)


def view_is_overlay(view: dict) -> bool:
    """True when a view is an overlay state rather than a page."""
    return view.get("kind") == "overlay"


def _child_command(condition: str, run_dir: Path, args) -> list[str]:
    """The command line for one condition's isolated child process."""
    command = [
        sys.executable, str(Path(__file__).resolve()),
        "--child", "--only-condition", condition,
        "--out", str(run_dir),
        "--conditions", condition,
        "--widths", args.widths,
        "--themes", args.themes,
        "--fail-on", "none",
    ]
    if args.routes:
        command.extend(["--routes", args.routes])
    if getattr(args, "api_fixture", ""):
        command.extend(["--api-fixture", args.api_fixture])
    if getattr(args, "record_api", ""):
        command.extend(["--record-api", args.record_api])
    if getattr(args, "mock_delay_ms", 0):
        command.extend(["--mock-delay-ms", str(args.mock_delay_ms)])
    if getattr(args, "slow_ms", 0):
        command.extend(["--slow-ms", str(args.slow_ms)])
    if getattr(args, "pending_audit", False):
        command.append("--pending-audit")
    if args.no_stress:
        command.append("--no-stress")
    return command


def _run_children(args, run_dir: Path, conditions: list[str]) -> list[dict]:
    """Run one child per condition, sequentially or with --jobs in parallel."""
    jobs = max(1, int(args.jobs))
    results: list[dict] = []
    pending = list(conditions)
    running: list[tuple[str, subprocess.Popen]] = []
    try:
        while pending or running:
            while pending and len(running) < jobs:
                condition = pending.pop(0)
                command = _child_command(condition, run_dir, args)
                process = subprocess.Popen(command)
                running.append((condition, process))
            still: list[tuple[str, subprocess.Popen]] = []
            for condition, process in running:
                code = process.poll()
                if code is None:
                    still.append((condition, process))
                else:
                    results.append({"condition": condition, "exit": code})
            running = still
            if running:
                time.sleep(0.5)
    except BaseException:
        for condition, process in running:
            if process.poll() is None:
                process.terminate()
        for condition, process in running:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    return results


def _collect_root_causes(findings: list[dict]) -> list[dict]:
    """Group findings by the smallest offending container and its classes."""
    groups: dict[str, dict] = {}
    for finding in findings:
        if finding.get("kind") == "runtime":
            continue
        group_id, key = _group_identity(finding)
        group = groups.get(group_id)
        if group is None:
            group = {
                "id": group_id, "key": key, "kind": finding.get("kind", ""),
                "selector": finding.get("container", ""),
                "classes": finding.get("classes", ""),
                "findings": [], "routes": set(), "states": set(),
                "conditions": set(), "widths": set(), "themes": set(),
            }
            groups[group_id] = group
        group["findings"].append(finding)
        group["routes"].add(finding.get("route", ""))
        group["states"].add(finding.get("state", ""))
        group["conditions"].add(finding.get("condition", ""))
        group["widths"].add(finding.get("width", 0))
        group["themes"].add(finding.get("theme", ""))
    return list(groups.values())


def _worst_metric(group: dict) -> str:
    """A short worst-case metric string for one root-cause group."""
    kind = group["kind"]
    worst = None
    for finding in group["findings"]:
        metrics = finding.get("metrics") or {}
        if kind == "tiny-type":
            value = -float(metrics.get("fontSize", 0) or 0)
            label = f"{metrics.get('fontSize')}px"
        elif kind == "squeezed-text":
            value = -float(metrics.get("width", 0) or 0) + float(metrics.get("lines", 0) or 0)
            label = f"{metrics.get('width')}px wide, {metrics.get('lines')} lines"
        elif kind in ("text-overlap", "control-collision", "control-overlap"):
            value = float(metrics.get("overlapWidth", 0) or 0) * float(
                metrics.get("overlapHeight", 0) or 0)
            label = f"{metrics.get('overlapWidth')}x{metrics.get('overlapHeight')}px"
        elif kind == "broken-word":
            value = float(metrics.get("lineCount", 0) or 0)
            label = f"{metrics.get('lineCount') or 0} lines for word {metrics.get('word') or ''!r}"
        elif kind == "offscreen-content":
            value = float(metrics.get("overBy", 0) or 0)
            label = f"scrollWidth {metrics.get('scrollWidth')} vs {metrics.get('clientWidth')}"
        elif kind == "ellipsis-no-affordance":
            value = float(metrics.get("over", 0) or 0)
            label = f"{metrics.get('over')}px clipped"
        elif kind == "text-clip":
            value = float(metrics.get("overRight", 0) or 0) + float(
                metrics.get("overLeft", 0) or 0) + float(
                metrics.get("overBottom", 0) or 0) + float(metrics.get("overTop", 0) or 0)
            label = (f"over {metrics.get('overRight')}px right, "
                     f"{metrics.get('overBottom')}px bottom")
        else:
            value = float(metrics.get("over", metrics.get("overRight", 0)) or 0)
            label = f"{metrics.get('over', metrics.get('overRight'))}px"
        if worst is None or value > worst[0]:
            worst = (value, label, finding)
    if worst is None:
        return ""
    return worst[1]


def _worst_source(group: dict) -> str:
    """The condition and width of the worst finding in a group."""
    worst = group["findings"][0]
    for finding in group["findings"]:
        if finding.get("severity") == group.get("severity"):
            worst = finding
            break
    return f"{worst.get('condition')} {worst.get('width')}px"


def _source_lines() -> list[tuple[str, int, str]]:
    """Every source line worth searching for a class or className."""
    lines: list[tuple[str, int, str]] = []
    roots = [ROOT / "frontend" / "src", ROOT / "src" / "agentdesk" / "server"]
    suffixes = {".tsx", ".ts", ".css", ".py"}
    for base in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in suffixes or not path.is_file():
                continue
            if "static" in path.parts or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(ROOT).as_posix()
            for number, line in enumerate(text.splitlines(), start=1):
                lines.append((rel, number, line))
    return lines


_SOURCE_LINES: list[tuple[str, int, str]] | None = None
_SOURCE_HITS: dict[str, list[str]] = {}


def _class_hits(token: str) -> list[str]:
    """The first file:line hits for one class token, cached per token."""
    global _SOURCE_LINES
    if token in _SOURCE_HITS:
        return _SOURCE_HITS[token]
    if _SOURCE_LINES is None:
        _SOURCE_LINES = _source_lines()
    pattern = re.compile(r"(?:^|[^A-Za-z0-9_-])" + re.escape(token) + r"(?:[^A-Za-z0-9_-]|$)")
    hits: list[str] = []
    for rel, number, line in _SOURCE_LINES:
        if token not in line:
            continue
        if ("." + token) in line or "className" in line or "class=" in line or "class='" in line:
            if pattern.search(line):
                hits.append(f"{rel}:{number}")
                if len(hits) >= 3:
                    break
    _SOURCE_HITS[token] = hits
    return hits


def _source_guess(classes: str) -> str:
    """Best-guess source locations for a container's class names."""
    tokens = [token for token in classes.split() if len(token) >= 3][:2]
    hits: list[str] = []
    for token in tokens:
        for hit in _class_hits(token):
            if hit not in hits:
                hits.append(hit)
    return ", ".join(hits[:3])


def _group_priority(group: dict) -> tuple:
    """The documented order: non-stress, then severity, then reach."""
    stress_only = all(finding.get("stress") for finding in group["findings"])
    combos = set()
    for finding in group["findings"]:
        combos.add((finding.get("route"), finding.get("state"), finding.get("condition"),
                    finding.get("width"), finding.get("theme")))
    return (stress_only, _severity_rank(group.get("severity", "low")),
            -len(combos), group.get("kind", ""), group.get("selector", ""))


def _group_crops(group: dict, run_dir: Path) -> list[str]:
    """The existing crop files for a group, up to six, deterministic order."""
    found = []
    for finding in group["findings"]:
        crop = finding.get("crop")
        if crop and Path(crop).is_file() and crop not in found:
            found.append(crop)
        if len(found) >= 6:
            break
    return found


def _public_path(path: str, run_dir: Path) -> str:
    """A path relative to the run folder for reports, or the absolute path."""
    try:
        return Path(path).relative_to(run_dir).as_posix()
    except ValueError:
        return str(path)


def _pending_counts(records: list[dict]) -> dict[str, int]:
    """The number of controls in each pending verdict."""
    counts: dict[str, int] = {}
    for record in records:
        verdict = record.get("verdict", "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def _pending_evidence(record: dict) -> str:
    """One short evidence sentence for a pending audit row."""
    evidence = record.get("evidence") or {}
    parts = []
    if evidence.get("request_started"):
        parts.append(f"{len(evidence.get('requests') or [])} request(s)")
    if evidence.get("disabled"):
        parts.append("disabled")
    if evidence.get("aria_busy"):
        parts.append("aria-busy")
    if evidence.get("label_changed"):
        parts.append("label changed")
    for item in (evidence.get("busy_indicators") or [])[:2]:
        parts.append("indicator " + str(item.get("path", "")))
    if evidence.get("reason"):
        parts.append(str(evidence["reason"]))
    return "; ".join(parts) or "no visible change"


def _pending_fail(records: list[dict], threshold: str) -> bool:
    """True when a pending verdict reaches the --fail-on threshold."""
    if threshold == "none":
        return False
    wanted = {"any": 0, "low": 2, "medium": 1, "high": 0}.get(threshold, 3)
    for record in records:
        verdict = record.get("verdict")
        if verdict == "silent":
            rank = 0
        elif verdict == "disabled-only":
            rank = 1
        else:
            continue
        if threshold == "any" or rank <= wanted:
            return True
    return False


def _write_summary(run_dir: Path, findings: list[dict], matrix: list[dict],
                   groups: list[dict], args, elapsed: float,
                   missing: list[dict], child_failures: list[dict],
                   pending: list[dict]) -> None:
    """Write summary.md: counts, coverage, then root causes in priority order."""
    lines: list[str] = []
    lines.append("# Layout audit summary")
    lines.append("")
    lines.append(f"Run folder: `{run_dir}`")
    lines.append(f"Elapsed: {elapsed:.1f}s")
    effective_conditions = sorted({str(entry.get("condition")) for entry in matrix})
    effective_widths = sorted({int(entry.get("width")) for entry in matrix if entry.get("width")})
    effective_themes = sorted({str(entry.get("theme")) for entry in matrix if entry.get("theme")})
    effective_states = {(entry.get("route"), entry.get("state")) for entry in matrix}
    lines.append(f"Command filters: conditions={','.join(effective_conditions)} "
                 f"widths={','.join(str(width) for width in effective_widths)} "
                 f"themes={','.join(effective_themes)} "
                 f"states={len(effective_states)} "
                 f"stress={'off' if args.no_stress else 'on'}")
    lines.append("")
    measured = [entry for entry in matrix if entry["status"] == "measured"]
    skipped = [entry for entry in matrix if entry["status"] == "skipped"]
    failed = [entry for entry in matrix if entry["status"] not in ("measured", "skipped")]
    real = [finding for finding in findings if finding.get("kind") != "runtime"]
    runtime = [finding for finding in findings if finding.get("kind") == "runtime"]
    stress_only = [group for group in groups
                   if all(finding.get("stress") for finding in group["findings"])]
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Matrix rows: {len(matrix)} (measured {len(measured)}, "
                 f"skipped {len(skipped)}, failed {len(failed)})")
    lines.append(f"- Findings: {len(findings)} total, {len(real)} layout, "
                 f"{len(runtime)} runtime")
    stress_count = len([finding for finding in real if finding.get("stress")])
    lines.append(f"- Stress findings: {stress_count}; stress-only groups: {len(stress_only)}")
    lines.append(f"- Root-cause groups: {len(groups)}")
    lines.append("")
    lines.append("### By kind")
    lines.append("")
    lines.append("| kind | count | stress |")
    lines.append("| --- | ---: | ---: |")
    kinds: dict[str, list[int]] = {}
    for finding in findings:
        bucket = kinds.setdefault(finding.get("kind", ""), [0, 0])
        bucket[0] += 1
        if finding.get("stress"):
            bucket[1] += 1
    for kind in sorted(kinds):
        lines.append(f"| {kind} | {kinds[kind][0]} | {kinds[kind][1]} |")
    lines.append("")
    for title, key in (("condition", "condition"), ("width", "width"), ("theme", "theme")):
        lines.append(f"### By {title}")
        lines.append("")
        counts: dict[str, int] = {}
        for finding in real:
            counts[str(finding.get(key, ""))] = counts.get(str(finding.get(key, "")), 0) + 1
        lines.append("| value | findings |")
        lines.append("| --- | ---: |")
        for value in sorted(counts):
            lines.append(f"| {value} | {counts[value]} |")
        lines.append("")
    lines.append("### Coverage")
    lines.append("")
    if not failed and not missing and not child_failures:
        lines.append("Every planned combination was measured.")
    else:
        if child_failures:
            lines.append(f"- Child processes that exited non-zero: {len(child_failures)}")
            for result in child_failures:
                lines.append(f"  - {result.get('condition')}: exit {result.get('exit')}")
        lines.append(f"- Missing matrix rows: {len(missing)}")
        for combo in missing:
            view = combo["view"]
            lines.append(f"  - {combo['condition']} {combo['width']} {combo['theme']} "
                         f"{view.get('state', '')}: not measured (no matrix row)")
        lines.append(f"- Failed matrix rows: {len(failed)}")
        for entry in failed:
            lines.append(f"  - {entry['condition']} {entry['width']} {entry['theme']} "
                         f"{entry['state']}: {entry['status']} ({entry.get('note', '')})")
    lines.append("")
    if skipped:
        lines.append("### Skipped states")
        lines.append("")
        for entry in skipped:
            lines.append(f"- {entry['condition']} {entry['width']} {entry['theme']} "
                         f"{entry['state']}: {entry.get('note', 'no reason')}")
        lines.append("")
    lines.append("## Root causes")
    lines.append("")
    lines.append("Order: non-stress before stress-only, high before medium before low, "
                 "then by number of combinations affected.")
    lines.append("")
    for number, group in enumerate(groups, start=1):
        group_findings = group["findings"]
        stress_only_group = all(finding.get("stress") for finding in group_findings)
        combos = set()
        for finding in group_findings:
            combos.add((finding.get("route"), finding.get("state"),
                        finding.get("condition"), finding.get("width"),
                        finding.get("theme")))
        stress_tag = " [stress]" if stress_only_group else ""
        lines.append(f"### {number}. [{group.get('severity')}]{stress_tag} "
                     f"{group.get('kind')}: `{group.get('selector')}`")
        lines.append("")
        lines.append(f"- Group id: `{group['id']}`")
        lines.append(f"- Classes: `{group.get('classes') or '(none)'}`")
        lines.append(f"- Stress-only: {'yes' if stress_only_group else 'no'}")
        lines.append(f"- Combinations affected: {len(combos)}")
        lines.append(f"- Routes: {', '.join(sorted({str(c[0]) for c in combos}))}")
        lines.append(f"- States: {', '.join(sorted({str(c[1]) for c in combos}))}")
        lines.append(f"- Conditions: {', '.join(sorted({str(c[2]) for c in combos}))}")
        lines.append(f"- Widths: {', '.join(str(w) for w in sorted({c[3] for c in combos}))}")
        lines.append(f"- Themes: {', '.join(sorted({str(c[4]) for c in combos}))}")
        lines.append(f"- Worst metrics: {_worst_metric(group)} ({_worst_source(group)})")
        sample = next((finding.get("text", "") for finding in group_findings
                       if finding.get("text")), "")
        lines.append(f"- Sample text: {sample[:160]!r}")
        guess = _source_guess(group.get("classes", ""))
        lines.append(f"- Source guess: {guess or 'not found by class name'}")
        crops = group.get("crops") or []
        if crops:
            lines.append("- Crops: " + ", ".join(f"`{crop}`" for crop in crops))
        lines.append("")
    lines.append("## Pending states")
    lines.append("")
    if not pending:
        lines.append("No pending audit was requested.")
    else:
        counts = _pending_counts(pending)
        lines.append("| verdict | controls |")
        lines.append("| --- | ---: |")
        for verdict in sorted(counts):
            lines.append(f"| {verdict} | {counts[verdict]} |")
        lines.append("")
        lines.append("| page | control | verdict | evidence |")
        lines.append("| --- | --- | --- | --- |")
        for record in pending:
            page = record.get("state") or record.get("route", "")
            control = (record.get("control") or record.get("control_path") or "").replace("|", "/")
            lines.append(f"| {page} | {control[:90]} | {record.get('verdict')} | "
                         f"{_pending_evidence(record)[:160]} |")
    lines.append("")
    lines.append("## Runtime findings")
    lines.append("")
    if not runtime:
        lines.append("None recorded.")
    else:
        counts: dict[str, int] = {}
        for finding in runtime:
            label = finding.get("metrics", {}).get("runtimeType", "runtime")
            counts[label] = counts.get(label, 0) + 1
        for label in sorted(counts):
            lines.append(f"- {label}: {counts[label]}")
        lines.append("")
        seen = set()
        for finding in runtime:
            key = (finding.get("route"), finding.get("state"), finding.get("text"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {finding.get('condition')} {finding.get('width')} "
                         f"{finding.get('state')}: {finding.get('text')}")
            if len(seen) >= 40:
                lines.append("- ... truncated")
                break
    lines.append("")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _relative_path(value: str, run_dir: Path) -> str:
    """The path relative to the run folder when it lives under it."""
    try:
        return Path(value).relative_to(run_dir).as_posix()
    except (ValueError, OSError):
        return value


def _relative_records(records: list[dict], run_dir: Path) -> list[dict]:
    """Copy records with their evidence paths made run-folder relative."""
    out = []
    for record in records:
        copy = dict(record)
        for key in ("crop", "screenshot"):
            value = copy.get(key)
            if isinstance(value, str) and value:
                copy[key] = _relative_path(value, run_dir)
        out.append(copy)
    return out


def _merge_outputs(args, run_dir: Path, conditions: list[str],
                   elapsed: float, child_results: list[dict]) -> int:
    """Merge child JSON, copy crops, write findings/matrix/summary, return code.

    A child that exits non-zero is incomplete coverage even when it wrote a
    full matrix: its own failure is the evidence that something went wrong.
    """
    findings: list[dict] = []
    matrix: list[dict] = []
    child_failures: list[dict] = []
    pending: list[dict] = []
    for condition in conditions:
        findings.extend(_read_json(run_dir / f"findings.{condition}.json", []))
        matrix.extend(_read_json(run_dir / f"matrix.{condition}.json", []))
        pending.extend(_read_json(run_dir / f"pending.{condition}.json", []))
        fatal = _read_json(run_dir / f"fatal.{condition}.json", None)
        if fatal:
            print(f"[{condition}] fatal: {fatal.get('message', '')}", flush=True)
    order = {condition: index for index, condition in enumerate(ALL_CONDITIONS)}
    width_order = {800: 0, 1024: 1, 1280: 2, 1920: 3}
    theme_order = {theme: index for index, theme in enumerate(THEMES)}
    matrix.sort(key=lambda entry: (
        order.get(entry.get("condition"), 99), width_order.get(entry.get("width"), 99),
        theme_order.get(entry.get("theme"), 99), entry.get("route", ""),
        entry.get("state", "")))
    findings.sort(key=lambda finding: (
        order.get(finding.get("condition"), 99), width_order.get(finding.get("width"), 99),
        theme_order.get(finding.get("theme"), 99), finding.get("route", ""),
        finding.get("state", ""), finding.get("kind", ""),
        finding.get("selector", ""), finding.get("text", "")))
    groups = _collect_root_causes(findings)
    for group in groups:
        group["severity"] = min(
            (finding.get("severity", "low") for finding in group["findings"]),
            key=_severity_rank)
    groups.sort(key=_group_priority)
    crops_dir = run_dir / "crops"
    for group in groups:
        group["crops"] = []
        if not crops_dir.exists():
            continue
        selected = _group_crops(group, run_dir)
        for index, crop in enumerate(selected, start=1):
            source = Path(crop)
            target = crops_dir / f"{group['id']}__{index}.png"
            try:
                shutil.copyfile(source, target)
            except OSError:
                continue
            group["crops"].append(f"crops/{target.name}")
    planned = _planned_combos(args, conditions)
    visited = {_entry_key(entry) for entry in matrix}
    missing = [combo for combo in planned if _combo_key(combo) not in visited]
    failed = [entry for entry in matrix
              if entry["status"] not in ("measured", "skipped")]
    skipped_entries = [entry for entry in matrix if entry["status"] == "skipped"]
    for result in child_results:
        if result.get("exit") not in (0, None):
            child_failures.append(result)
    _write_json(run_dir / "findings.json", _relative_records(findings, run_dir))
    _write_json(run_dir / "matrix.json", _relative_records(matrix, run_dir))
    if pending:
        _write_json(run_dir / "pending.json", _relative_records(pending, run_dir))
    _write_summary(run_dir, findings, matrix, groups, args, elapsed, missing,
                   child_failures, pending)
    pages = len([entry for entry in matrix if entry["status"] == "measured"])
    print(f"OUT {run_dir}")
    print(f"METRIC findings={len(findings)} groups={len(groups)} "
          f"pages={pages} skipped={len(skipped_entries)}")
    if skipped_entries:
        print(f"SKIPPED {len(skipped_entries)} overlay state(s) listed in summary")
    incomplete = len(missing) + len(failed) + len(child_failures)
    coverage_code = 0
    if incomplete:
        reasons = []
        for combo in missing[:8]:
            view = combo["view"]
            reasons.append(f"missing {combo['condition']} {combo['width']} "
                           f"{combo['theme']} {view.get('state', '')}")
        for entry in failed[:8]:
            reasons.append(f"{entry['status']} {entry['condition']} {entry['width']} "
                           f"{entry['theme']} {entry['state']} ({entry.get('note', '')})")
        for result in child_failures[:8]:
            reasons.append(f"child {result.get('condition')} exit {result.get('exit')}")
        suffix = "" if args.allow_partial else "; exit 3"
        print(f"COVERAGE INCOMPLETE {incomplete} combination(s){suffix}: "
              + "; ".join(reasons))
        if not args.allow_partial:
            coverage_code = 3
    if coverage_code:
        return coverage_code
    threshold = args.fail_on
    if threshold == "none":
        return 0
    wanted = {"any": 0, "low": 2, "medium": 1, "high": 0}.get(threshold, 3)
    for finding in findings:
        if finding.get("kind") == "runtime":
            continue
        rank = _severity_rank(finding.get("severity", "low"))
        if threshold == "any" or rank <= wanted:
            return 1
    if pending and _pending_fail(pending, threshold):
        return 1
    return 0


def _child_main(args) -> int:
    """Entry point for one isolated condition process."""
    condition = args.only_condition
    if not condition:
        print("--child needs --only-condition")
        return 2
    run_dir = Path(args.out)
    run_dir.mkdir(parents=True, exist_ok=True)
    return _condition_worker(args, condition, run_dir)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the parent or one isolated child condition."""
    parser = argparse.ArgumentParser(description="Measure text overflow on every desk screen.")
    parser.add_argument("--conditions", default=",".join(ALL_CONDITIONS),
                        help="comma-separated conditions (default all)")
    parser.add_argument("--widths", default="1024,1280,800,1920",
                        help="comma-separated viewport widths")
    parser.add_argument("--themes", default="unkey,coforge,momentuum",
                        help="comma-separated themes")
    parser.add_argument("--routes", default="", help="substring filter for routes/states")
    parser.add_argument("--no-stress", action="store_true", help="skip the tripled-text pass")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="output base directory")
    parser.add_argument("--fail-on", default="none",
                        choices=("none", "high", "medium", "low", "any"),
                        help="exit 1 when a finding reaches this severity")
    parser.add_argument("--only-condition", default="",
                        help="run exactly one condition (also the child mode)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="do not exit 3 when a planned combination is unmeasured")
    parser.add_argument("--jobs", type=int, default=1,
                        help="conditions to run in parallel (default 1)")
    parser.add_argument("--record-api", default="",
                        help="write GET /api JSON bodies under this directory")
    parser.add_argument("--api-fixture", default="",
                        help="fulfil matching GET /api requests from this JSON map")
    parser.add_argument("--mock-delay-ms", type=int, default=0,
                        help="sleep this long in the in-process mock model")
    parser.add_argument("--slow-ms", type=int, default=0,
                        help="delay every document and /api response this many ms")
    parser.add_argument("--pending-audit", action="store_true",
                        help="click every visible control and record its pending state")
    parser.add_argument("--selftest", action="store_true",
                        help="run the planted-defect fixture and check every detector")
    parser.add_argument("--child", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if sync_playwright is None:
        print(PLAYWRIGHT_HELP)
        return 2
    if args.selftest:
        return _selftest()
    if args.child:
        return _child_main(args)
    started = time.monotonic()
    run_dir = Path(args.out) / _now_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    conditions = _parse_list(args.conditions)
    if args.only_condition:
        conditions = [args.only_condition]
    conditions = [condition for condition in conditions if condition in ALL_CONDITIONS]
    if not conditions:
        print("no valid conditions selected")
        return 2
    try:
        for condition in conditions:
            child_args = argparse.Namespace(**vars(args))
            child_args.only_condition = condition
            child_args.conditions = condition
            build_combos(child_args)
    except AuditError as exc:
        print(f"invalid audit filters: {exc}")
        return 2
    print(f"run {run_dir}", flush=True)
    print(f"conditions {','.join(conditions)} widths {args.widths} themes {args.themes}",
          flush=True)
    results = _run_children(args, run_dir, conditions)
    for result in results:
        if result["exit"] != 0:
            print(f"[{result['condition']}] child exit {result['exit']}", flush=True)
    elapsed = time.monotonic() - started
    return _merge_outputs(args, run_dir, conditions, elapsed, results)


if __name__ == "__main__":
    sys.exit(main())
