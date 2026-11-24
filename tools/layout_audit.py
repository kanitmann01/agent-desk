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
DEFAULT_OUT = Path("D:/20-projects/Personal Agents/.scratch/ui-text-overflow/layout-audit")
VIEWPORT_HEIGHT = 800
BASE_WIDTHS = (1024, 1280)
THEME_WIDTHS = (1024, 1280)
EXTREME_WIDTHS = (800, 1920)
BASE_CONDITIONS = ("fresh", "data", "plugins", "full")
ALL_CONDITIONS = ("fresh", "data", "plugins", "full", "legacy-dashboard")
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
    print(PLAYWRIGHT_HELP)
    raise SystemExit(2)

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
  function tripleText() {
    const root = document.body || document.documentElement;
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const p = node.parentElement;
        if (!p || SKIP_TEXT_TAGS[p.tagName]) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) { node.nodeValue = node.nodeValue.trim().repeat(3); }
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
      if ((s.position === 'fixed' || s.position === 'absolute') && over <= 1) continue;
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
    if (t === 'BUTTON' || t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' || t === 'TD' || t === 'TH') return 'high';
    if (t === 'A' && GENERIC_HIGH_CLASS.test(classString(el))) return 'high';
    if (GENERIC_HIGH_CLASS.test(classString(el))) return 'high';
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
    const byContainer = new Map();
    for (const c of raw) {
      const prev = byContainer.get(c.container);
      if (!prev || c.over > prev.over) byContainer.set(c.container, c);
    }
    const kept = Array.from(byContainer.values());
    const containers = kept.map(function(c) { return c.container; });
    for (const c of kept) {
      let hasDeeper = false;
      for (const other of containers) {
        if (other !== c.container && c.container.contains(other)) { hasDeeper = true; break; }
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
                   a.scrollHeight <= a.clientHeight + 1 && (outB > 1 || outT > 1)) hit = 'y';
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
      if (fitterScroller(p, true)) continue;
      let affordance = false;
      let b = p;
      let steps = 0;
      while (b && steps < 40) {
        const s = styleOf(b);
        if (s) {
          if ((s.textOverflow || '').indexOf('ellipsis') >= 0 &&
              (s.overflowX === 'hidden' || s.overflowX === 'clip')) affordance = true;
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
      const focusable = el.closest('a,button,select,input,textarea,[tabindex],[contenteditable="true"],[role="button"],[role="link"]');
      const reachable = el.hasAttribute('title') || el.hasAttribute('aria-label') ||
                        !!el.closest('[title]') || !!focusable;
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
      add('text-overlap', 'high', primary.el, primary.text, {
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
  }

  function blockOf(node) {
    let a = node.parentElement;
    let hops = 0;
    while (a && a !== document.body && hops < 40) {
      const s = styleOf(a);
      if (s) {
        if (s.whiteSpace === 'normal' && s.display.indexOf('inline') !== 0 &&
            s.display !== 'contents' && s.display !== 'none' &&
            s.display !== 'table-row') return a;
      }
      a = a.parentElement;
      hops++;
    }
    return null;
  }

  function detectSqueezed(nodes) {
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
      add('squeezed-text', 'high', el, textOf(el), {
        width: r2(cw), lines: tops.size, chars: chars,
        fontSize: r2(parseFloat(s.fontSize) || 0)
      }, {
        rect: {x:r2(union.x), y:r2(union.y), w:r2(union.w), h:r2(union.h)}
      });
    }
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

  function detectBrokenWords(nodes) {
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
      const s = styleOf(el);
      if (!s) continue;
      const cw = contentWidth(el);
      for (const node of textNodes) {
        const text = node.nodeValue || '';
        const re = /\S+/g;
        let match;
        while ((match = re.exec(text))) {
          const word = match[0];
          if (word.length < 2) continue;
          if (/[-\/_.:]/.test(word)) continue;
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
  detectSqueezed(nodes);
  detectBrokenWords(nodes);
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
    measurement.
    """
    conditions = _parse_list(args.conditions)
    widths = [int(value) for value in _parse_list(args.widths)]
    themes = _parse_list(args.themes)
    views = [view for view in build_views() if _route_matches(view, _parse_list(args.routes))]
    overlay_filters = _parse_list(args.routes)
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
    os.environ["AGENTDESK_DATA"] = str(data_dir)
    os.environ["AGENTDESK_CALENDAR_FILE"] = ""
    if condition in ("data", "full") and mock_port:
        os.environ["AGENTDESK_LLM_BASE"] = f"http://127.0.0.1:{mock_port}/v1"
        os.environ["AGENTDESK_LLM_KEY"] = "sk-local"
        os.environ["AGENTDESK_LLM_MODEL"] = "mock-chat"
    if condition == "full":
        os.environ["AGENTDESK_MARKETPLACE_ADMIN"] = "1"


def _start_mock():
    """Start the loopback mock chat endpoint on an ephemeral port."""
    from http.server import ThreadingHTTPServer

    module = _load_mock_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.MockEndpointHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _boot_desk(condition: str, tmp_root: Path) -> dict:
    """Boot the real app over a fresh data folder and a file-backed keychain.

    Mirrors tools/demo_readiness.Desk: ephemeral port, announce on a free
    UDP port, daemon thread, background polls started the way the launcher
    starts them. No real keychain, no real data folder.
    """
    data_dir = tmp_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    keychain = tmp_root / "keychain.json"
    from agentdesk.keys.secrets import KeychainSecrets
    from agentdesk.server import app as server_app

    server = server_app.create_server(
        port=0, announce_port=_free_udp_port(),
        keychain=KeychainSecrets(backend=FileKeychain(keychain)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server_app.start_background_polls(server)
    if condition == "legacy-dashboard":
        server_app.SPA_DIR = tmp_root / "missing-spa-build"
    base = f"http://127.0.0.1:{server.port}"
    return {"server": server, "thread": thread, "base": base,
            "token": server.sessions.bootstrap_token()}


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


def _stop_desk(desk: dict) -> None:
    """Stop the server, its watchers, its stores and its thread, best effort."""
    server = desk["server"]
    try:
        for name in ("excel", "calendar"):
            watcher = getattr(server, name, None)
            if watcher is not None:
                watcher.stop_polling()
        server.shutdown()
        server.server_close()
        desk["thread"].join(timeout=5)
        _close_stores(server)
    except Exception:  # noqa: BLE001 - teardown noise is not a finding
        pass


def _post_json(context, url: str, payload: dict):
    """POST a JSON document through the browser context's request client."""
    return context.request.post(
        url, data=json.dumps(payload),
        headers={"Content-Type": "application/json"})


def _seed(context, base: str, condition: str, tmp_root: Path) -> list[str]:
    """Seed one condition through the app's own routes, as a browser would.

    Sample data, registry installs and the opened sample tracker all use
    the routes the pages use. A refusal raises AuditError with the route
    and status, so a half-seeded desk is never measured as if it were the
    intended condition.
    """
    notes: list[str] = []
    if condition in ("data", "full"):
        response = _post_json(context, f"{base}/settings/toggle", {"key": "sample_data"})
        if response.status != 200:
            raise AuditError(f"sample data toggle answered {response.status}")
        notes.append("sample data on")
    if condition in ("plugins", "full"):
        for plugin_id in _plugin_ids():
            response = _post_json(context, f"{base}/api/registry/install", {"id": plugin_id})
            if response.status != 200:
                raise AuditError(
                    f"installing {plugin_id} answered {response.status}: {response.text()[:200]}")
        notes.append(f"{len(_plugin_ids())} plugin(s) installed")
    if condition == "full":
        from agentdesk.server import demo_data

        sample = demo_data.sample_workbook_path()
        if not sample.is_file():
            raise AuditError(f"the sample workbook is not at {sample}")
        upload_url = (f"{base}/api/plugins/excel-report/instances/main/upload/"
                      f"{urllib.parse.quote(sample.name)}")
        response = context.request.post(
            upload_url, data=sample.read_bytes(),
            headers={"Content-Type": "application/octet-stream"})
        if response.status != 200:
            raise AuditError(f"tracker upload answered {response.status}: {response.text()[:200]}")
        response = _post_json(
            context, f"{base}/api/plugins/excel-report/instances/main/confirm",
            {"tracking": {"labelColumn": "Deal", "valueColumn": "Amount",
                          "aggregate": "sum"}})
        if response.status != 200:
            raise AuditError(f"tracker confirm answered {response.status}: {response.text()[:200]}")
        notes.append("sample tracker open")
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


def _screenshot_file(run_dir: Path, combo: dict, view: dict) -> Path:
    """The mechanical full-page screenshot path for one combination."""
    route = view.get("path", "/").split("#")[0]
    route_slug = _slug(route.lstrip("/")) if route != "/" else "root"
    state_slug = _slug(view.get("state", "state"))
    return (run_dir / combo["condition"] / f"{combo['width']}x{VIEWPORT_HEIGHT}"
            / combo["theme"] / f"{route_slug}__{state_slug}.png")


def _group_identity(finding: dict) -> tuple[str, str]:
    """The stable (id, key) used for root-cause grouping and crop names."""
    key = f"{finding.get('kind', '')}|{finding.get('container', '')}|{finding.get('classes', '')}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return digest, key


def _crop_file(run_dir: Path, finding: dict, condition: str, view_slug: str,
               index: int) -> Path:
    """The crop path for one finding; the group id is the file name prefix."""
    group_id, _key = _group_identity(finding)
    return run_dir / "crops" / f"{group_id}__{condition}__{view_slug}__{index}.png"


def _capture_crop(page, finding: dict, path: Path) -> None:
    """Capture a 24 px-margin crop of the measured rectangle, or its edge.

    The rectangle the probe recorded is used first: a short selector path
    can match several sibling rows, and the first match would show the
    wrong row. The page is scrolled only when the rectangle is outside the
    viewport, then the scroll is restored. An element past the right edge
    (lost content in the SPA) has no visible pixels, so the crop falls
    back to that edge, which is the evidence a reader can see.
    """
    saved = finding.get("rect") or {}
    if not saved:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    viewport = page.viewport_size or {"width": 1280, "height": VIEWPORT_HEIGHT}
    old = page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
    old_x = float(old.get("x", 0))
    old_y = float(old.get("y", 0))
    top = float(saved.get("y", 0))
    height = float(saved.get("h", 1))
    width = float(saved.get("w", 1))
    left = float(saved.get("x", 0))
    fully_visible = top >= 0 and top + height <= viewport["height"]
    if not fully_visible:
        target = max(0, old_y + top - 100)
        page.evaluate("(y) => window.scrollTo(0, y)", target)
        page.wait_for_timeout(80)
        now = page.evaluate("() => window.scrollY")
        top = top - (float(now) - old_y)
    margin = 24
    x = max(0, left - margin)
    y = max(0, top - margin)
    clip_w = min(viewport["width"] - x, max(32, width + margin * 2))
    clip_h = min(viewport["height"] - y, max(32, height + margin * 2))
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
        if not fully_visible:
            page.evaluate("(p) => window.scrollTo(p.x, p.y)", {"x": old_x, "y": old_y})


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
                   calendar_fixture: Path, crop_counts: dict, base: str) -> dict:
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
        final_path = _final_path(page)
        expected_path = view["path"].split("#")[0].split("?")[0] or "/"
        if final_path != expected_path:
            entry["status"] = "auth-failed" if final_path.startswith("/auth") else "wrong-page"
            entry["note"] = f"final path {final_path}, expected {expected_path}"
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
        if condition in ("data", "full"):
            mock, mock_port = _start_mock()
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
                page = context.new_page()
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
                                                calendar_fixture, crop_counts, base)
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
                finally:
                    page.close()
                    context.close()
                    browser.close()
        finally:
            sys.stderr = old_stderr
            stderr_handle.close()
        _write_json(run_dir / f"findings.{condition}.json", all_findings)
        _write_json(run_dir / f"matrix.{condition}.json", matrix)
        skipped = [entry for entry in matrix if entry["status"] == "skipped"]
        _write_json(run_dir / f"skipped.{condition}.json", skipped)
        print(f"[{condition}] wrote {len(all_findings)} finding(s), "
              f"{len(matrix)} matrix row(s)", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - the parent reports the cause
        message = f"{type(exc).__name__}: {exc}"
        print(f"[{condition}] FAILED: {message}", flush=True)
        _write_json(run_dir / f"fatal.{condition}.json", {
            "condition": condition, "message": message,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        return 1
    finally:
        if desk is not None:
            _stop_desk(desk)
        if mock is not None:
            try:
                mock.shutdown()
                mock.server_close()
            except Exception:  # noqa: BLE001 - teardown noise
                pass
        shutil.rmtree(tmp_root, ignore_errors=True)


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
    if args.no_stress:
        command.append("--no-stress")
    return command


def _run_children(args, run_dir: Path, conditions: list[str]) -> list[dict]:
    """Run one child per condition, sequentially or with --jobs in parallel."""
    jobs = max(1, int(args.jobs))
    results: list[dict] = []
    pending = list(conditions)
    running: list[tuple[str, subprocess.Popen]] = []
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
        elif kind in ("text-overlap", "control-collision"):
            value = float(metrics.get("overlapWidth", 0) or 0) * float(
                metrics.get("overlapHeight", 0) or 0)
            label = f"{metrics.get('overlapWidth')}x{metrics.get('overlapHeight')}px"
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


def _write_summary(run_dir: Path, findings: list[dict], matrix: list[dict],
                   groups: list[dict], args, elapsed: float,
                   missing: list[dict]) -> None:
    """Write summary.md: counts, coverage, then root causes in priority order."""
    lines: list[str] = []
    lines.append("# Layout audit summary")
    lines.append("")
    lines.append(f"Run folder: `{run_dir}`")
    lines.append(f"Elapsed: {elapsed:.1f}s")
    lines.append(f"Command filters: conditions={args.conditions} widths={args.widths} "
                 f"themes={args.themes} routes={args.routes or '(all)'} "
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
    if not failed and not missing:
        lines.append("Every planned combination was measured.")
    else:
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
        lines.append(f"### {number}. [{group.get('severity')}] {group.get('kind')}: "
                     f"`{group.get('selector')}`")
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


def _merge_outputs(args, run_dir: Path, conditions: list[str],
                   elapsed: float) -> int:
    """Merge child JSON, copy crops, write findings/matrix/summary, return code."""
    findings: list[dict] = []
    matrix: list[dict] = []
    for condition in conditions:
        findings.extend(_read_json(run_dir / f"findings.{condition}.json", []))
        matrix.extend(_read_json(run_dir / f"matrix.{condition}.json", []))
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
    _write_json(run_dir / "findings.json", findings)
    _write_json(run_dir / "matrix.json", matrix)
    _write_summary(run_dir, findings, matrix, groups, args, elapsed, missing)
    pages = len([entry for entry in matrix if entry["status"] == "measured"])
    print(f"OUT {run_dir}")
    print(f"METRIC findings={len(findings)} groups={len(groups)} "
          f"pages={pages} skipped={len(skipped_entries)}")
    if skipped_entries:
        print(f"SKIPPED {len(skipped_entries)} overlay state(s) listed in summary")
    incomplete = len(missing) + len(failed)
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
    parser.add_argument("--child", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
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
    print(f"run {run_dir}", flush=True)
    print(f"conditions {','.join(conditions)} widths {args.widths} themes {args.themes}",
          flush=True)
    results = _run_children(args, run_dir, conditions)
    for result in results:
        if result["exit"] != 0:
            print(f"[{result['condition']}] child exit {result['exit']}", flush=True)
    elapsed = time.monotonic() - started
    return _merge_outputs(args, run_dir, conditions, elapsed)


if __name__ == "__main__":
    sys.exit(main())
