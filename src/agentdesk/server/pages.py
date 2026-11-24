"""Server-rendered pages for the dashboard shell.

The host renders every pixel; plugins later ship declarative UI schemas,
never HTML (research A9.2 rule 7). Pages are offline by construction: no
font CDN, no script tags from anywhere but /static, and no inline
<script> blocks. The pages may carry minimal inline style attributes for
one-off spacing; the CSP's style-src 'unsafe-inline' relaxation covers
exactly those (style attributes cannot execute code), while scripts stay
prohibited outright.
"""

import html
from typing import Iterable

from agentdesk.server.core import ATTENTION, FRESH, SAMPLE, SOURCE_IDS, Freshness
from agentdesk.server.demo import Widget

ICON_OPTIONS = (
    '<button class="icon-btn" aria-label="Widget options">'
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" '
    'aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/>'
    '<circle cx="19" cy="12" r="1.7"/></svg></button>'
)

# The design language tokens: the server sheet's statement of the
# three-theme system in docs/design-language.md. Font families resolve
# locally: the named faces when installed, otherwise the OS fallbacks.
# Nothing is fetched from the network.
STYLES = """
:root,:root[data-theme="unkey"],[data-theme-preview="unkey"]{
  color-scheme:dark;
  --bg:#060609; --surface:#101014; --surface-2:#16161A;
  --ink-1:#FBFBFB; --ink-2:#C8C8CC; --ink-3:#8E8E93; --ink-4:#5C5C61;
  --hairline:#26272A; --heading:#FBFBFB;
  --primary:#FBFBFB; --primary-ink:#060609; --primary-soft:#1C1C20;
  --accent:#E1F56A; --accent-text:#E1F56A; --on-accent:#060609; --focus:#E1F56A;
  --good:#E1F56A; --bad:#E5484D;
  --attention-bg:#16161A; --attention-ink:#E1F56A;
 --chevron:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' fill='none' stroke='%238E8E93' stroke-width='1.5' stroke-linecap='round'/></svg>");
}
:root[data-theme="coforge"],[data-theme-preview="coforge"]{
  color-scheme:dark;
  --bg:#082340; --surface:#0C2A4A; --surface-2:#10315A;
  --ink-1:#FFFFFF; --ink-2:#EBEBEB; --ink-3:#A0A1A2; --ink-4:#787A7A;
  --hairline:#1E4472; --heading:#FFFFFF;
  --primary:#FFFFFF; --primary-ink:#082340; --primary-soft:#153A68;
  --accent:#F15840; --accent-text:#F68076; --on-accent:#082340; --focus:#F68076;
  --good:#F68076; --bad:#FF6B6B;
  --attention-bg:#10315A; --attention-ink:#F68076;
 --chevron:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' fill='none' stroke='%23A0A1A2' stroke-width='1.5' stroke-linecap='round'/></svg>");
}
:root[data-theme="momentuum"],[data-theme-preview="momentuum"]{
  color-scheme:light;
  --bg:#F3F6FA; --surface:#FFFFFF; --surface-2:#EDF1F7;
  --ink-1:#082340; --ink-2:#3A4A63; --ink-3:#5B6B82; --ink-4:#A9B6C8;
  --hairline:#D5DDE8; --heading:#082340;
  --primary:#1F6BA8; --primary-ink:#FFFFFF; --primary-soft:#EDF1F7;
  --accent:#2470B0; --accent-text:#1F6BA8; --on-accent:#FFFFFF; --focus:#2470B0;
  --good:#1F6BA8; --bad:#B42318;
  --attention-bg:#EDF1F7; --attention-ink:#1F6BA8;
 --chevron:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' fill='none' stroke='%235B6B82' stroke-width='1.5' stroke-linecap='round'/></svg>");
}
:root{
  --shadow-card:none;
  --shadow-card-hover:none;
  --r-card:8px; --r-control:6px; --r-inner:4px; --dur:120ms;
  /* The memory graph's kind roles, derived from each theme's ink ramp
     and its one accent: writers and excerpts quiet, facts full ink,
     entities a step down, observations (the learned layer) the accent. */
  --kind-origin:var(--ink-3); --kind-source:var(--ink-3); --kind-fact:var(--ink-1);
  --kind-entity:var(--ink-2); --kind-observation:var(--accent-text);
  --font-display:"Geist","Segoe UI",sans-serif;
  --font-ui:"Geist","Segoe UI",sans-serif;
  --font-mono:"Geist Mono","Consolas",monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-ui);background:var(--bg);color:var(--ink-1);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
/* The static memory graph (/memory/graph without JavaScript). */
.graph-static{overflow-x:auto;border:1px solid var(--hairline);border-radius:var(--r-card);background:var(--surface);padding:8px}
.graph-edge{stroke:var(--ink-4)}
.graph-edge.edge-entity{stroke:var(--kind-entity)}
.graph-edge.edge-temporal{stroke:var(--ink-3)}
.graph-edge.edge-derived{stroke:var(--kind-observation)}
.graph-edge.edge-semantic{stroke:var(--ink-2)}
.graph-arrow{fill:var(--kind-observation)}
.graph-dot-fact{fill:var(--kind-fact)}
.graph-dot-observation{fill:var(--kind-observation)}
.graph-text{fill:var(--ink-3)}
/* Text fields scroll without a visible bar (the SPA does the same). */
textarea{scrollbar-width:none}
textarea::-webkit-scrollbar{display:none}
button{font:inherit;cursor:pointer;border:none;background:none;color:inherit}
button:disabled{opacity:.55;cursor:default}
a{color:var(--primary);text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}
svg{display:block;flex:none}
.mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.app{display:grid;grid-template-columns:200px 1fr;min-height:calc(100vh - 32px);margin:16px;background:var(--bg);border:1px solid var(--hairline);border-radius:var(--r-card);box-shadow:none}
.rail{border-right:1px solid var(--hairline);background:transparent;padding:20px 16px;display:flex;flex-direction:column;gap:2px;position:sticky;top:0;height:100%}
.brand{display:flex;align-items:center;gap:10px;padding:2px 8px 18px}
.brand .mark{display:none}
.brand b,.brand-name{font-family:var(--font-display);font-size:20px;font-weight:560;letter-spacing:-.02em}
.rail-mark{display:none;font-family:var(--font-mono);font-weight:600}
.phone-bar{display:none}
.rail a,.rail .nav-off{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:var(--r-control);color:var(--ink-2);text-decoration:none;font-weight:600;transition:background var(--dur) ease,color var(--dur) ease}
.rail a:hover{background:var(--surface-2);color:var(--ink-1);text-decoration:none}
.rail a[aria-current="page"]{background:var(--surface-2);color:var(--heading);box-shadow:inset 2px 0 0 var(--accent);border-radius:0 var(--r-control) var(--r-control) 0}
.rail .nav-off{opacity:.45}
.rail .count{margin-left:8px;font-family:var(--font-mono);font-size:14px;font-weight:500;background:transparent;color:var(--ink-1);border-radius:0;padding:0}
.origin-line{font-size:12px;font-weight:700;color:var(--primary);letter-spacing:.06em}
.origin-why{color:var(--ink-2);font-size:13px;border-top:1px solid var(--hairline);padding-top:8px}
.widget h3{font-size:16px;font-weight:800;letter-spacing:-.01em}
.cardrow{display:flex;gap:10px;margin-top:4px;flex-wrap:wrap}
.addplugin-form{display:inline-flex;margin:0}
.w-big{font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--ink-1)}
.w-note{font-size:12px;color:var(--ink-3)}
.settings-skill{margin-bottom:12px}
.skill-name{font-size:14.5px}
.skills-strip{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.skills-strip .skill-btn{background:var(--surface);color:var(--ink-1);border-radius:var(--r-control);box-shadow:inset 0 0 0 1px var(--hairline),var(--shadow-card);padding:8px 14px;font-weight:700;font-size:13px;transition:background var(--dur) ease}
.skills-strip .skill-btn:hover{background:var(--surface-2)}
.settings-block{display:flex;flex-direction:column;gap:8px;max-width:460px}
.cardform{display:flex;flex-direction:column;gap:8px;margin:8px 0;max-width:460px}
.presentation-form{max-width:none}
.template-tiles{display:flex;flex-wrap:wrap;gap:12px;border:0;padding:0;margin:0}
.template-tile{display:flex;flex-direction:column;gap:6px;width:220px;max-width:100%;padding:8px;border:1px solid var(--hairline);border-radius:var(--r-card);background:var(--surface)}
.template-tile .thumbs{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.template-tile img{width:100%;height:auto;aspect-ratio:16/9;background:var(--bg);border-radius:2px}
.variant-row{display:flex;gap:16px;border:0;padding:0;margin:0}
fieldset:disabled,.presentation-form :disabled{opacity:.55}
@media (max-width:560px){.template-tile{width:100%}}
.cardform .btn{align-self:flex-start}
.cardform label{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em}
.cardform input,.cardform select,.cardform textarea{font:inherit;font-size:14px;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px;min-height:36px}
/* Checkboxes and radios ride outside the text-field minimum: the 36px
   height and its padding are for fields, never for the small controls
   (the same release the inbox grid gives its consent checkbox). */
.cardform input[type="checkbox"],.cardform input[type="radio"]{min-height:0;padding:0}
.cardform input:focus,.cardform select:focus,.cardform textarea:focus{outline:2px solid var(--focus);outline-offset:1px}
/* The inbox card's quick actions: one shared grid so the three forms
   keep proportional columns and land their labels, controls and buttons
   on the same three baselines. The audit measured natural-width columns
   (162/132/175px), a native 17px select, and buttons on y=501/521/541;
   the subgrid rows answer all three. The .doc prefix outranks
   .doc .cardrow's flex, which would otherwise win on specificity and
   source order. */
.doc .cardrow.cardforms{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:12px;margin:12px 0 0;align-items:stretch}
.cardforms .subhead{grid-column:1/-1}
.cardforms .cardform{margin:0;max-width:none;display:grid;grid-template-rows:subgrid;grid-row:span 3;gap:8px}
.cardforms .cardform-wide{grid-column:1/-1;grid-row:span 2}
.cardforms input,.cardforms textarea,.cardforms select{width:100%}
/* The consent checkbox rides inside a label: it keeps its 18px system
   size, never the column width. */
.cardforms input[type="checkbox"]{width:18px;height:18px;min-height:0;accent-color:var(--primary);margin:0 4px 0 0;vertical-align:middle}
.cardforms textarea{field-sizing:content;min-height:60px}
.cardforms .btn{width:100%;justify-content:center}
@supports not (grid-template-rows: subgrid){
  .cardforms .cardform{display:flex;flex-direction:column}
  .cardforms .cardform .btn{margin-top:auto}
}
/* Waiting inbox cards rest in a spaced stack: the audit measured 0px
   between consecutive cards, so they read as one merged block. */
.card-stack{display:flex;flex-direction:column;gap:16px}
/* The plugin and peer entry cards. `article.card` shipped with no rule
   at all: transparent ground, no shadow, loose text on paper (the audit
   measured backgroundColor rgba(0,0,0,0) and box-shadow none). One
   rhythm block: the 12px flex gap is the only spacer, so the paragraph
   and title margins cannot double it. */
.doc .card{background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:18px 18px 14px;display:flex;flex-direction:column;gap:12px;margin:16px 0 0;transition:box-shadow 200ms ease}
.doc .card:hover{box-shadow:var(--shadow-card-hover)}
.doc .card p{margin:0}
.doc .card h3{font-size:16px;font-weight:700;letter-spacing:-.01em}
/* The Memory page's explanation (ticket #283): the card voice, its
   heading in the card-title voice, held to the reading column's width
   on the wide island page. Scoped 2026-11-23 to this one block: a
   blanket .doc .card h2 rule restyled every card heading on every
   server page, and the visual system is out of scope there. */
.doc .memory-explain h2{font-size:16px;font-weight:700;letter-spacing:-.01em}
.memory-explain{max-width:720px}
.doc .card .cardrow{margin-top:0}
/* The widget cards' internal rhythm: the 12px gap is the single spacer.
   The audit measured 20px between a gate's heading and text and 28px
   before its button, because .doc p and .cardform margins stack on the
   flex gap instead of collapsing. */
.doc .widget p{margin:0}
.doc .widget .cardform{margin:0}
.reg-origin{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:12px;color:var(--ink-3);margin:4px 0 0}
.crumbs{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--ink-3);margin-bottom:12px}
.crumbs a{color:var(--ink-3);font-weight:600}
.crumbs a:hover{color:var(--primary)}
.crumbs .crumb-sep{color:var(--ink-4)}
.field{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em}
.field input{font:inherit;font-size:14px;font-weight:400;letter-spacing:normal;text-transform:none;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px}
.field input:focus{outline:2px solid var(--primary);outline-offset:1px}
.setting-row{display:flex;align-items:center;justify-content:space-between;gap:16px;background:var(--surface);border-radius:var(--r-control);box-shadow:var(--shadow-card);padding:10px 14px;font-weight:600;font-size:14px}
.rail .user{margin-top:auto;display:flex;gap:10px;align-items:center;padding:10px 8px;border-top:1px solid var(--hairline)}
.rail .user .avatar{width:30px;height:30px;border-radius:999px;background:var(--primary-soft);color:var(--primary);display:grid;place-items:center;font-weight:800;font-size:12px}
.rail .user small{display:block;color:var(--ink-3);font-weight:400}
.rail .user .user-name{font-size:13px}
.rail-toggle{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border-radius:var(--r-control);color:var(--ink-3);font-weight:600;font-size:12px;margin-top:8px;transition:background var(--dur) ease,color var(--dur) ease}
.rail-toggle:hover{background:var(--surface-2);color:var(--ink-1)}
/* Collapsed: the rail keeps its marks (icons, count badge, avatar) and
   drops its text; the column narrows to the mark width. Scoped to the
   wide rail: below 981px the strip shows every entry and hides the
   toggle, so a collapsed state must not leak into it (the toggle that
   could undo it is not there). */
@media (min-width:981px){
.app.rail-collapsed{grid-template-columns:68px 1fr}
.rail-collapsed .rail{padding:20px 10px}
.rail-collapsed .rail a{position:relative;justify-content:center;padding:8px 0;gap:0}
.rail-collapsed .rail .rail-label{display:none}
.rail-collapsed .rail .rail-mark{display:inline}
.rail-collapsed .rail .count{position:absolute;top:4px;right:4px;margin-left:0;padding:0 5px;font-size:12px}
.rail-collapsed .rail .rail-toggle{justify-content:center;gap:0}
.rail-collapsed .rail-toggle .rail-toggle-label{display:none}
.rail-collapsed .brand b,.rail-collapsed .brand-name{display:none}
.rail-collapsed .rail .user{justify-content:center;padding:10px 0}
.rail-collapsed .rail .user > div{display:none}
}
main{padding:28px 36px 60px;max-width:1200px;width:100%;margin:0 auto}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:22px}
.topbar h1{font-family:var(--font-display);font-size:40px;font-weight:560;letter-spacing:-.03em}
.topbar .sub{color:var(--ink-2);margin-top:2px;display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:999px;background:var(--good);display:inline-block}
.dot.amber{background:var(--attention-ink)}
.dot.sample{background:var(--ink-4)}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:var(--r-control);padding:8px 14px;font-weight:700;transition:background var(--dur) ease,box-shadow var(--dur) ease,color var(--dur) ease;min-height:36px}
.btn-primary{background:var(--accent);color:var(--on-accent);box-shadow:none;border:1px solid var(--accent)}
.btn-secondary{background:var(--surface);color:var(--ink-1);box-shadow:inset 0 0 0 1px var(--hairline)}
.btn-secondary:hover:not(:disabled){background:var(--surface-2)}
.btn-danger{background:var(--surface);color:var(--bad);box-shadow:inset 0 0 0 1px var(--hairline)}
.btn-danger:hover:not(:disabled){background:var(--surface-2)}
.icon-btn{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:var(--r-inner);color:var(--ink-3);transition:background var(--dur) ease,color var(--dur) ease}
.icon-btn:hover{background:var(--surface-2);color:var(--ink-1)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
.widget{background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:18px 18px 14px;transition:box-shadow 200ms ease;display:flex;flex-direction:column;gap:12px}
.widget:hover{box-shadow:var(--shadow-card-hover)}
.col-7{grid-column:span 7}.col-5{grid-column:span 5}.col-8{grid-column:span 8}.col-4{grid-column:span 4}
.w-head{display:flex;align-items:center;gap:12px}
.w-head h2{font-size:16px;font-weight:700;letter-spacing:-.01em}
.stamp{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink-3);font-weight:600}
.w-foot{display:flex;align-items:flex-start;gap:10px;border-top:1px solid var(--hairline);padding-top:12px;font-size:12px;line-height:1.5;color:var(--ink-3)}
.kpi{display:flex;gap:24px;align-items:flex-start}
.kpi .label{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em}
.kpi .value{font-family:var(--font-mono);font-size:64px;font-weight:500;letter-spacing:-.03em;color:var(--good);margin-top:2px;overflow-wrap:anywhere}
.kpi .sub{font-size:12px;color:var(--ink-3);margin-top:2px}
.spark{margin-left:auto;text-align:right}
.spark figcaption{font-size:12px;color:var(--ink-4);margin-top:4px}
table.rows{width:100%;border-collapse:collapse;font-size:13px}
table.rows th{text-align:left;font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em;padding:4px 8px 8px 0;border-bottom:1px solid var(--hairline)}
table.rows td{padding:9px 8px 9px 0;border-bottom:1px solid var(--hairline)}
table.rows tr:last-child td{border-bottom:none}
table.rows .num{text-align:right;font-family:var(--font-mono);font-variant-numeric:tabular-nums}
table.rows td.neg{color:var(--bad)}
.delta{display:inline-flex;align-items:center;gap:4px;font-family:var(--font-mono);font-size:12px;font-weight:600}
.delta.up{color:var(--good)} .delta.down{color:var(--bad)}
.event{display:flex;gap:12px;background:var(--surface-2);border-radius:var(--r-inner);padding:12px}
.event .when{font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--primary);white-space:nowrap;padding-top:2px}
.event b{display:block}
.event small{color:var(--ink-3)}
.subhead{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em}
.subhead-tight{margin-bottom:4px}
.check{display:flex;gap:10px;align-items:flex-start;padding:7px 0;font-size:14px}
.check .box{width:18px;height:18px;border-radius:5px;border:1.5px solid var(--ink-4);display:grid;place-items:center;color:transparent;transition:all var(--dur) ease;margin-top:1px}
.check[aria-checked="true"] .box{background:var(--primary);border-color:var(--primary);color:var(--primary-ink)}
.check[aria-checked="true"] span:not(.box){text-decoration:line-through;color:var(--ink-3)}
.follow{display:inline-flex;align-items:center;gap:8px;background:var(--attention-bg);color:var(--attention-ink);border-radius:999px;padding:5px 12px;font-size:12px;font-weight:600}
.well{display:flex;gap:10px;align-items:flex-start;background:var(--surface-2);border:1px solid var(--hairline);border-radius:var(--r-control);padding:12px}
.well .q{flex:1;color:var(--ink-3)}
.well-input{flex:1;font:inherit;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px;resize:vertical}
.well-input:focus{outline:2px solid var(--primary);outline-offset:1px}
.grow{flex:1}
.thread{display:flex;flex-direction:column;gap:12px;margin:14px 0}
.thread .ask{background:var(--surface-2);border-radius:var(--r-inner);padding:12px 14px}
.thread .ask .who{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em;margin-bottom:4px}
.thread .reply p{margin:4px 0 0}
.thread .who{font-size:12px;font-weight:700;color:var(--primary);letter-spacing:.06em}
.thread p{color:var(--ink-1);font-size:14px}
.answer{background:var(--surface-2);border-radius:var(--r-inner);padding:14px;font-size:14px;display:flex;flex-direction:column;gap:8px}
.answer p{margin:0}
.answer .aq{font-weight:700}
.answer .well-input{width:100%}
.src{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);font-size:12px;color:var(--ink-2);background:var(--surface);border:1px solid var(--hairline);border-radius:999px;padding:3px 10px;margin:10px 8px 0 0}
.tag-sample{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.08em}
.widget.amber{background:var(--surface);box-shadow:inset 2px 0 0 var(--accent)}
.alert{display:flex;gap:10px;align-items:flex-start;color:var(--attention-ink);font-size:14px}
.badge-pilot{font-size:12px;font-weight:700;color:var(--attention-ink);background:var(--attention-bg);border-radius:999px;padding:2px 9px}
.btn-start{align-self:flex-start}
.empty{color:var(--ink-3);font-size:13px}
.decisions{list-style:none;margin:0;padding:0}
.decisions li{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-top:1px solid var(--hairline)}
.decisions li:first-child{border-top:none;padding-top:0}
.decision-text{display:flex;flex-direction:column;gap:2px;min-width:0}
.decision-title{font-weight:600;color:var(--ink-1);font-size:14px}
.decision-why{font-size:12.5px;color:var(--ink-3);line-height:1.4}
.decision-actions{display:flex;align-items:center;gap:8px;flex:none}
.decision-actions form{margin:0}
.btn-sm{min-height:28px;padding:4px 10px;font-size:12.5px}
.doc{max-width:720px;margin:32px auto;padding:0 16px}
.doc.doc-wide{max-width:1160px}
.doc h1{font-size:20px;font-weight:700;margin-bottom:6px;letter-spacing:-.01em}
.doc > h2{font-size:16px;font-weight:700;margin:24px 0 0;letter-spacing:-.01em}
.doc p{color:var(--ink-2);font-size:14px;margin:8px 0}
.doc ol{margin:12px 0;padding-left:20px;color:var(--ink-2);font-size:14px;display:flex;flex-direction:column;gap:8px}
.doc pre{background:var(--surface-2);border:1px solid var(--hairline);border-radius:var(--r-control);padding:12px;font-family:var(--font-mono);font-size:12px;overflow:auto;white-space:pre-wrap;color:var(--ink-1)}
.doc .cardrow{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
.doc a.btn{text-decoration:none}
.page-foot{margin-top:48px;color:var(--ink-3);font-size:12px;border-top:1px solid var(--hairline);padding-top:12px;display:flex;gap:16px;flex-wrap:wrap}
.page-foot a{color:var(--primary);font-weight:700;text-decoration:none}
.page-foot a:hover{text-decoration:underline}
.touches td{vertical-align:top;font-size:13px}
.touch-badge{display:inline-flex;background:var(--surface-2);color:var(--ink-3);border:1px solid var(--hairline);border-radius:999px;padding:2px 9px;font-size:12px;font-weight:700}
.touch-badge.on{background:var(--primary-soft);color:var(--primary);border-color:transparent}
.error-card{max-width:460px;margin:18vh auto 0;background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:28px;display:flex;flex-direction:column;gap:8px}
.error-card h1{font-size:20px;font-weight:800}
.error-card p{color:var(--ink-2);font-size:14px}
@media (max-width:980px){
  /* The single-column shell becomes a block, matching the dashboard
     SPA: a sticky grid item inside its own auto-sized row has no
     travel, so the strip would still scroll away. */
  .app{display:block}
  /* The strip stays pinned while the page scrolls and its entries wrap
     instead of clipping, matching the dashboard SPA's behavior. */
  .phone-bar{display:flex;align-items:center;gap:12px;width:100%}
  .phone-menu{margin-left:auto;border:1px solid var(--hairline);border-radius:var(--r-control);background:var(--surface);min-height:44px;padding:0 12px;font-weight:700}
  .rail{position:sticky;top:0;height:auto;z-index:20;flex-direction:row;flex-wrap:wrap;align-items:center;border-right:none;border-bottom:1px solid var(--hairline);padding:8px 12px}
  .rail > a,.rail .brand,.rail .user{display:none}
  .rail.rail-open{position:fixed;inset:0;height:100vh;flex-direction:column;align-items:stretch;background:var(--bg);padding:16px;overflow:auto}
  .rail.rail-open > a,.rail.rail-open .brand{display:flex}
  .rail a{min-height:44px}
  html{scroll-padding-top:64px}
  .topbar h1{font-size:32px}
  .grid{grid-template-columns:1fr}
  .col-7,.col-5,.col-8,.col-4{grid-column:auto}
  main{padding:20px 16px 40px}
  /* The strip already carries every entry; collapse is a tall-rail
     control and does nothing on the wrapping strip. */
  .rail-toggle{display:none}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{transition-duration:0.01ms!important}
}

/* Appearance: three theme tiles. Each swatch is drawn from the tile's
   own theme scope, so no colour is written here. */
.theme-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,200px));gap:12px;margin:8px 0 4px}
.theme-tile{display:flex;flex-direction:column;align-items:stretch;gap:8px;padding:10px;border:1px solid var(--hairline);border-radius:var(--r-card);background:var(--surface);color:var(--ink-1);text-align:left}
.theme-tile:hover{border-color:var(--ink-3)}
.theme-tile[aria-checked="true"]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.theme-tile .tile-sw{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:38px 14px;gap:4px;padding:8px;border-radius:var(--r-inner);background:var(--bg);border:1px solid var(--hairline)}
.theme-tile .tile-sw i{border-radius:2px;background:var(--surface)}
.theme-tile .tile-sw i:first-child{grid-row:span 2;border:1px solid var(--hairline)}
.theme-tile .tile-sw i:last-child{background:var(--accent)}
.theme-tile b{font-size:13px;font-weight:650;color:var(--ink-1)}
.theme-tile small{font-size:12px;color:var(--ink-3);font-weight:400}
.theme-tile .tile-sw,.theme-tile .tile-sw i{transition:none}
select,.cardform select{appearance:none;-webkit-appearance:none;padding-right:30px;background:var(--surface) var(--chevron) no-repeat right 10px center;cursor:pointer}
input[type="checkbox"],input[type="radio"]{appearance:none;-webkit-appearance:none;width:16px;height:16px;margin:0;display:inline-grid;place-items:center;border:1px solid var(--ink-4);border-radius:3px;background:var(--surface);vertical-align:middle;cursor:pointer}
input[type="radio"]{border-radius:50%}
input[type="checkbox"]:checked{background:var(--accent);border-color:var(--accent)}
input[type="checkbox"]:checked::after{content:"";width:8px;height:4px;border-left:2px solid var(--on-accent);border-bottom:2px solid var(--on-accent);transform:translateY(-1px) rotate(-45deg)}
input[type="radio"]:checked{border-color:var(--accent)}
input[type="radio"]:checked::after{content:"";width:8px;height:8px;border-radius:50%;background:var(--accent)}
@media (max-width:560px){.theme-tiles{grid-template-columns:1fr}}

/* Settings: one card per concern, a single width and one gap rhythm, so
   the page reads as a stack of live state rather than a pile of forms.
   Every rule is scoped to .doc so it wins over the generic card rules. */
.settings-stack{display:flex;flex-direction:column;gap:16px;margin-top:16px}
.doc .settings-card{margin:0}
/* Settings sections (spec 022): the bar names six sections. The page is
   rendered whole, so with no script it is an index of six titled groups;
   with script one section shows at a time and the titles step aside. A
   control that needs script is hidden until the script runs, so the page
   never offers a button that cannot work. */
.settings-bar{display:flex;flex-wrap:wrap;gap:4px;margin-top:16px;margin-bottom:16px;border-bottom:1px solid var(--hairline)}
.settings-bar a{display:inline-flex;align-items:center;min-height:38px;padding:0 14px;border-bottom:2px solid transparent;margin-bottom:-1px;border-radius:var(--r-inner) var(--r-inner) 0 0;color:var(--ink-2);font-size:14px;font-weight:600;text-decoration:none}
.settings-bar a:hover{background:var(--surface-2);color:var(--ink-1)}
.settings-bar a[aria-current="page"]{color:var(--accent-text);border-bottom-color:var(--accent-text);background:var(--surface)}
.settings-section{display:flex;flex-direction:column;gap:16px}
.settings-section[hidden]{display:none}
.settings-section-title{margin:8px 0 0;font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase}
.js-settings .settings-section-title{display:none}
.settings-status{margin:0 0 -8px;font-size:15px}
.needs-script{display:none}
.js-settings .needs-script{display:inline-flex}
.settings-disclosure{margin-top:4px}
.settings-disclosure>summary{cursor:pointer;font-weight:600;color:var(--ink-2);width:fit-content}
.settings-disclosure>summary:hover{color:var(--ink-1)}
.settings-disclosure[open]>summary{margin-bottom:12px}
.doc .settings-card h3{font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase;margin:6px 0 0}
.doc .settings-card .settings-block{max-width:none}
.settings-links{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 4px}
/* The console deep-links fold into a native details disclosure (spec
   019 #259): the summary carries the block-label style of the h3 it
   replaced, and the open and close are the browser's own, no script. */
.console-links summary{cursor:pointer;font-size:12px;font-weight:700;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase;margin:6px 0 0;width:fit-content}
.settings-skill{display:flex;flex-direction:column;gap:6px;padding-top:12px;border-top:1px solid var(--hairline)}
.settings-skill:first-of-type{border-top:none;padding-top:0}
/* Connections (spec 018): a row's Delete form sits inline with its
   Edit link instead of stacking. The provider picker is a native
   select since #263, so it shares the .cardform select styling above
   and needs no rules of its own. */
.inlineform{display:inline-block;margin:0 0 0 6px}
/* A row scans one line tall (spec 019): the base URL wraps anywhere so
   a mono URL cannot dictate the column widths, and the three actions
   hold one line per row. */
.conn-url{overflow-wrap:anywhere}
.conn-actions{white-space:nowrap}
/* The health badge (spec 018): one pill per state, colored like the
   delta arrows (good, bad) with unknown in the quiet ink; the inline
   cause under it is plain text, not part of the pill. The failure
   token (bad) stays a chromatic step apart from every quiet ink of
   its theme and 4.5:1 on the surface, so error, unknown and ok read
   as three colors in all three themes (spec 019). */
.conn-status{display:inline-block;font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;background:var(--surface);box-shadow:inset 0 0 0 1px var(--hairline);color:var(--ink-3)}
.conn-ok{color:var(--good)}
.conn-error{color:var(--bad)}
"""

# The scripts the shell ships: the workbook picker flow, the Re-test
# calls for the live widgets, and the card actions. Same-origin only;
# no frameworks.
# The desk theme, applied before first paint. A byte-for-byte copy of
# frontend/public/theme-boot.js (a test holds them equal), so pages work
# with or without a built SPA.
THEME_BOOT_JS = """\
// Applies the stored desk theme before the first paint, so a page never
// flashes the default theme first. Loaded as a plain blocking script in
// <head> (the CSP allows scripts from 'self' only, never inline).
(function () {
  var themes = { unkey: 1, coforge: 1, momentuum: 1 };
  var id = 'unkey';
  try {
    var stored = window.localStorage.getItem('agentdesk.theme');
    if (stored && Object.prototype.hasOwnProperty.call(themes, stored)) id = stored;
  } catch (e) {
    // Storage unavailable: the default theme.
  }
  document.documentElement.setAttribute('data-theme', id);
})();
"""

APP_JS = """\
// Same-origin POST helper: every call here stays on 127.0.0.1.
function post(url, body) {
  return fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : '{}'});
}

// Workbook connect: the app opens the native file dialog, the chosen
// path registers the watch, and the dashboard reloads with real data.
// The picker is the only connect path (never a typed one); a cancelled
// or invisible dialog is never silent, the amber note says so and every
// failed call is reported in the same place instead of reloading
// nothing.
(function () {
  var btn = document.querySelector('[data-pick]');
  if (!btn) return;
  var note = document.getElementById('pick-note');
  var show = function (text) {
    if (note) { note.hidden = false; note.textContent = text; }
  };
  var connect = function (path) {
    fetch('/sources/excel-watch', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path})})
      .then(function (r) {
        return r.json().then(function (d) { return {ok: r.ok, data: d}; });
      })
      .then(function (res) {
        if (!res.ok || res.data.error) {
          show(res.data.error || 'The workbook was not connected; nothing changed.');
          return;
        }
        location.reload();
      })
      .catch(function () {
        show('The dashboard could not reach its own server; nothing was connected.');
      });
  };
  btn.addEventListener('click', function () {
    post('/sources/excel-watch/pick').then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.path) {
          show('The file dialog did not open. Try Connect a workbook again; if it keeps failing, restart the app.');
          return;
        }
        connect(d.path);
      })
      .catch(function () {
        show('The dashboard could not reach its own server; the file dialog was not opened.');
      });
  });
})();

// Live Re-test: one poll right now, then the fresh state renders.
document.querySelectorAll('[data-retest]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/sources/excel-watch/retest').then(function () { location.reload(); });
  });
});

// Calendar Re-test: re-read the OneDrive file right now.
document.querySelectorAll('[data-calendar-retest]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/sources/calendar-bridge/retest').then(function () { location.reload(); });
  });
});

// Calendar source: pick a file, paste a path, upload the JSON by hand,
// or go back to automatic discovery. Nothing fails silently: the note
// on the page carries every refusal from the server.
(function () {
  var note = document.getElementById('calendar-note');
  if (!note) return;
  var show = function (text) { note.hidden = false; note.textContent = text; };
  var couldNotReach = 'The dashboard could not reach its own server; nothing changed.';
  var apply = function (url, body) {
    post(url, body).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { show(d.error); return; }
        location.reload();
      })
      .catch(function () { show(couldNotReach); });
  };
  var pick = document.querySelector('[data-calendar-pick]');
  if (pick) pick.addEventListener('click', function () {
    post('/sources/calendar-bridge/pick').then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.path) { show('The file dialog did not open. Paste the path below instead.'); return; }
        apply('/sources/calendar-bridge/path', {path: d.path});
      })
      .catch(function () { show(couldNotReach); });
  });
  var usePath = document.querySelector('[data-calendar-path]');
  if (usePath) usePath.addEventListener('click', function () {
    var input = document.getElementById('calendar-path');
    var path = input ? input.value.trim() : '';
    if (!path) { show('Paste the full path to the calendar file first.'); return; }
    apply('/sources/calendar-bridge/path', {path: path});
  });
  var upload = document.querySelector('[data-calendar-upload]');
  if (upload) upload.addEventListener('click', function () {
    var input = document.getElementById('calendar-file');
    var file = input && input.files && input.files[0];
    if (!file) { show('Choose the calendar JSON file first.'); return; }
    var reader = new FileReader();
    reader.onload = function () {
      fetch('/sources/calendar-bridge/upload', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: reader.result})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error) { show(d.error); return; }
          location.reload();
        })
        .catch(function () { show('The dashboard could not reach its own server; nothing was uploaded.'); });
    };
    reader.onerror = function () { show('The browser could not read that file.'); };
    reader.readAsText(file);
  });
  var reset = document.querySelector('[data-calendar-reset]');
  if (reset) reset.addEventListener('click', function () {
    apply('/sources/calendar-bridge/reset');
  });
})();

// Inbox decisions: dismiss is immediate and reversible, accept consumes.
document.querySelectorAll('[data-accept]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/inbox/cards/' + btn.dataset.accept + '/accept').then(function () { location.reload(); });
  });
});
document.querySelectorAll('[data-dismiss]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/inbox/cards/' + btn.dataset.dismiss + '/dismiss').then(function () { location.reload(); });
  });
});
document.querySelectorAll('[data-restore]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/inbox/dismissed/' + btn.dataset.restore + '/restore').then(function () { location.reload(); });
  });
});

// Settings: one click flips a toggle or cycles a choice; nothing to type.
document.querySelectorAll('[data-setting]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/settings/toggle', {key: btn.dataset.setting}).then(function () { location.reload(); });
  });
});

// Settings sections (spec 022): the page is rendered whole, so with no
// script it works as an index of six titled groups. With script the bar
// shows one section at a time, and an address that names a card (a form's
// return_to, a saved link) opens the section that holds it. A reload
// keeps the address, so a switched toggle lands back on its section.
(function () {
  var bar = document.querySelector('[data-settings-bar]');
  if (!bar) return;
  var groups = Array.prototype.slice.call(document.querySelectorAll('[data-settings-section]'));
  if (!groups.length) return;
  document.documentElement.classList.add('js-settings');
  var links = Array.prototype.slice.call(bar.querySelectorAll('a[href^="#"]'));
  var owner = {};
  groups.forEach(function (group) {
    owner[group.getAttribute('data-settings-section')] = group;
    Array.prototype.forEach.call(group.querySelectorAll('[id]'), function (el) {
      owner[el.id] = group;
    });
  });
  function show(group) {
    groups.forEach(function (g) { g.hidden = g !== group; });
    links.forEach(function (a) {
      if (a.getAttribute('href') === '#' + group.getAttribute('data-settings-section')) {
        a.setAttribute('aria-current', 'page');
      } else {
        a.removeAttribute('aria-current');
      }
    });
  }
  function sync() {
    var id = (window.location.hash || '').slice(1);
    var group = owner[id] || groups[0];
    show(group);
    // A section's own address shows the page from its top, so the bar that
    // just changed stays in reach; a card's address brings that card into
    // view inside the section that holds it.
    if (id && group.getAttribute('data-settings-section') !== id) {
      var target = document.getElementById(id);
      if (target && target.scrollIntoView) target.scrollIntoView();
    } else {
      // The browser's own jump to the fragment runs after this script, so
      // the return to the top waits one frame.
      window.requestAnimationFrame(function () { window.scrollTo(0, 0); });
    }
  }
  window.addEventListener('hashchange', sync);
  // The browser jumps to the fragment once more when the page finishes
  // loading, so the same address is settled again then.
  window.addEventListener('load', sync);
  sync();
})();

// The endpoint fields retired to the Connections card (spec 018 #234);
// the presentation timeout is a plain form post and needs no script.

// Connections (spec 018): the key field reveals only while the box is
// checked (the full value is visible exactly once, in the form), and
// picking a provider fills its default base URL and its default model,
// both editable afterwards. On a new connection the model field starts
// with the selected provider's default (spec 022). All are enhancements:
// a new connection saves without any script just as well, because the
// server fills both defaults when they arrive empty.
(function () {
  var reveal = document.querySelector('[data-key-reveal]');
  var key = document.getElementById('conn-key');
  if (reveal && key) reveal.addEventListener('change', function () {
    key.type = reveal.checked ? 'text' : 'password';
  });
  var base = document.getElementById('conn-base');
  var provider = document.getElementById('conn-provider');
  if (base && provider) provider.addEventListener('change', function () {
    var chosen = provider.selectedOptions[0];
    if (chosen && chosen.dataset.base) base.value = chosen.dataset.base;
  });
  // A provider without an address of its own (Custom) needs one, and the
  // address sits under "More options" (spec 022): choosing it opens them.
  var more = document.getElementById('conn-more');
  if (more && provider) provider.addEventListener('change', function () {
    var picked = provider.selectedOptions[0];
    if (picked && !picked.dataset.base) more.open = true;
  });
  var model = document.getElementById('conn-model');
  if (model && provider) {
    var fillModel = function () {
      var chosen = provider.selectedOptions[0];
      if (!chosen) return;
      if (model.tagName === 'SELECT') {
        // A listed model belongs to the provider it was listed for, so a
        // text field takes the list's place. The id moves with it, so the
        // label keeps naming the field.
        var field = document.createElement('input');
        field.type = 'text';
        field.id = 'conn-model';
        field.name = 'model';
        field.placeholder = 'default';
        field.autocomplete = 'off';
        model.parentNode.replaceChild(field, model);
        model = field;
      }
      model.value = chosen.dataset.model || '';
    };
    provider.addEventListener('change', fillModel);
    // Only the add form starts with the default; a saved connection
    // shows the model it already has.
    if (provider.form && provider.form.getAttribute('action') === '/api/connections') {
      fillModel();
    }
  }
})();

// Skills: one click re-runs the saved ask; undo is on the settings page.
document.querySelectorAll('[data-skill-run]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var answerBox = document.getElementById('research-answer');
    var status = document.getElementById('research-status');
    if (status) status.textContent = 'Running the saved ask';
    post('/skills/' + btn.dataset.skillRun + '/run').then(function (r) { return r.json(); })
      .then(function (d) {
        if (status) status.textContent = '';
        if (!answerBox) return;
        answerBox.hidden = false;
        answerBox.innerHTML = '';
        var head = document.createElement('div');
        head.className = 'aq';
        head.textContent = d.status === 'ok' ? 'Skill result' : 'Skill unavailable';
        answerBox.appendChild(head);
        answerBox.appendChild(document.createTextNode(
          d.status === 'ok' ? (d.summary || d.reply || '') : (d.cause || '')));
      });
  });
});
document.querySelectorAll('[data-skill-undo]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    post('/skills/' + btn.dataset.skillUndo + '/undo').then(function () { location.reload(); });
  });
});

// Commitment subtasks: the click is the truth; the app persists it.
document.querySelectorAll('[data-check]').forEach(function (el) {
  var flip = function () {
    var on = el.getAttribute('aria-checked') === 'true';
    el.setAttribute('aria-checked', on ? 'false' : 'true');
    post('/widgets/commitments/check', {
      eventId: el.dataset.event,
      idx: Number(el.dataset.idx),
      checked: !on
    });
  };
  el.addEventListener('click', flip);
  el.addEventListener('keydown', function (e) {
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flip(); }
  });
});

// Research: the label stays put while the status line tells you exactly
// what is happening; answers arrive with their sources as chips.
(function () {
  var btn = document.getElementById('research-ask');
  var input = document.getElementById('research-question');
  var answerBox = document.getElementById('research-answer');
  var status = document.getElementById('research-status');
  if (!btn || !input) return;
  btn.addEventListener('click', function () {
    var question = input.value.trim();
    if (!question) { input.focus(); return; }
    btn.disabled = true;
    status.textContent = status.dataset.busyText;
    post('/research', {question: question}).then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (d.status === 'degraded') {
          answerBox.hidden = true;
          status.textContent = d.cause;
          return;
        }
        status.textContent = '';
        answerBox.hidden = false;
        answerBox.innerHTML = '';
        var head = document.createElement('div');
        head.className = 'aq';
        head.textContent = question;
        answerBox.appendChild(head);
        answerBox.appendChild(document.createTextNode(d.summary));
        var chips = document.createElement('div');
        (d.sources || []).forEach(function (name) {
          var chip = document.createElement('span');
          chip.className = 'src';
          chip.textContent = name;
          chips.appendChild(chip);
        });
        answerBox.appendChild(chips);
      })
      .catch(function () {
        btn.disabled = false;
        status.textContent = 'The dashboard could not reach its own server; nothing was sent.';
      });
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); btn.click(); }
  });
})();

// The rail collapse: one control, persisted, applied as the script
// loads. The class narrows the column and keeps the marks (icons, the
// inbox count, the avatar); the label span text stays for the wide rail.
// The button expands the nav, so its aria-expanded reads the rail's
// state: expanded true, collapsed false.
(function () {
  var KEY = 'agentdesk.railCollapsed';
  var app = document.querySelector('.app');
  var btn = document.querySelector('.rail-toggle');
  if (!app || !btn) return;
  var apply = function (collapsed) {
    app.classList.toggle('rail-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
    var label = btn.querySelector('.rail-toggle-label');
    if (label) label.textContent = collapsed ? 'Expand' : 'Collapse';
  };
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }
  apply(stored === '1');
  btn.addEventListener('click', function () {
    var next = !app.classList.contains('rail-collapsed');
    try { localStorage.setItem(KEY, next ? '1' : '0'); } catch (e) {}
    apply(next);
  });
})();
(function () {
  var rail = document.querySelector('.rail');
  var menu = document.querySelector('.phone-menu');
  if (!rail || !menu) return;
  menu.addEventListener('click', function () {
    var open = rail.classList.toggle('rail-open');
    menu.setAttribute('aria-expanded', open ? 'true' : 'false');
    menu.textContent = open ? 'Close' : 'Menu';
  });
})();

// Appearance: the three theme tiles on Settings. Same key and the same
// attribute as the desk, so the choice holds on every page.
(function () {
  var tiles = Array.prototype.slice.call(document.querySelectorAll('[data-theme-option]'));
  if (!tiles.length) return;
  var KEY = 'agentdesk.theme';
  function mark(id) {
    tiles.forEach(function (t) {
      var on = t.getAttribute('data-theme-option') === id;
      t.setAttribute('aria-checked', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
  }
  function choose(id, focus) {
    document.documentElement.setAttribute('data-theme', id);
    try { window.localStorage.setItem(KEY, id); } catch (e) { /* storage off: this page only */ }
    mark(id);
    if (focus) tiles.filter(function (t) { return t.getAttribute('data-theme-option') === id; })[0].focus();
  }
  mark(document.documentElement.getAttribute('data-theme') || 'unkey');
  tiles.forEach(function (t, i) {
    t.addEventListener('click', function () { choose(t.getAttribute('data-theme-option'), false); });
    t.addEventListener('keydown', function (e) {
      var step = (e.key === 'ArrowRight' || e.key === 'ArrowDown') ? 1
        : (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      var next = tiles[(i + step + tiles.length) % tiles.length];
      choose(next.getAttribute('data-theme-option'), true);
    });
  });
})();
"""

_DOT_CLASS = {FRESH: "dot", ATTENTION: "dot amber", SAMPLE: "dot sample"}


def _stamp_html(widget: Widget) -> str:
    """The freshness contract, rendered and exposed as data attributes."""
    f = widget.freshness
    dot = _DOT_CLASS[f.status]
    return (
        f'<span class="stamp" data-freshness data-status="{f.status}" '
        f'data-updated-iso="{html.escape(f.updated_iso)}">'
        f'<span class="{dot}" aria-hidden="true"></span>{html.escape(f.stamp)}</span>'
    )


def _widget_html(widget: Widget) -> str:
    """One dashboard widget's article markup, header chrome included.

    body_html, foot_html and the column class are inserted as the widget rendered them;
    the id, title and badge are escaped here. The widget id appears again as a data
    attribute for the client's sparkline and freshness code, which reads the freshness
    status off the same element.
    """
    badge = f'<span class="badge-pilot">{html.escape(widget.badge)}</span>' if widget.badge else ""
    extra = f" {widget.extra_classes}" if widget.extra_classes else ""
    return (
        f'<article class="widget {widget.col}{extra}" id="widget-{html.escape(widget.id)}" '
        f'data-widget-id="{html.escape(widget.id)}" data-freshness-status="{widget.freshness.status}">'
        f'<div class="w-head"><h2>{html.escape(widget.title)}</h2>{badge}'
        f"{_stamp_html(widget)}{ICON_OPTIONS}</div>"
        f"{widget.body_html}"
        f'<div class="w-foot">{widget.foot_html}</div></article>'
    )


def _rail(active: str = "/", inbox_count: int = 0) -> str:
    """The rail, shared by every page. The entry whose href is `active`
    is the one marked as the page you are on. Each entry's label rides
    in a .rail-label span so collapse can drop the words and keep the
    marks; the collapse control sits under the entries."""
    badge = f'<span class="count">{inbox_count}</span>' if inbox_count else ""
    toggle = (
        '<button type="button" class="rail-toggle" aria-expanded="true" '
        'aria-label="Collapse navigation">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.7" stroke-linecap="round" aria-hidden="true">'
        '<path d="M14.5 6.5 8 12l6.5 5.5"/></svg>'
        '<span class="rail-toggle-label">Collapse</span></button>'
    )

    def entry(href: str, label: str, extra: str = "") -> str:
        """The markup for one rail link, including the name the collapsed rail still
        announces.

        The visible label hides when the rail narrows, so every link carries its own
        aria-label (the Inbox link adding its waiting count) and a single-letter mark
        for the collapsed state; aria-current marks the page being viewed. The rail
        is words: no icon rides in the markup.
        """
        current = ' aria-current="page"' if href == active else ""
        # The accessible name survives collapse: the visible label hides
        # with the wide rail, so every link carries its own aria-label,
        # and the Inbox link names its waiting count. The letter is the
        # collapsed mark.
        name = label
        if href == "/inbox" and inbox_count:
            name = f"{label}, {inbox_count} waiting"
        mark = label[:1]
        return (
            f'<a href="{href}"{current} aria-label="{name}">'
            f'<span class="rail-mark" aria-hidden="true">{mark}</span>'
            f'<span class="rail-label">{label}</span>{extra}</a>'
        )

    current_label = {
        "/": "Dashboard",
        "/inbox": "Inbox",
        "/assistant": "Assistant",
        "/agents": "Agents",
        "/memory": "Memory",
        "/settings": "Settings",
        "/marketplace": "Plugins",
    }.get(active, "Agent Desk")
    phone = (
        '<div class="phone-bar">'
        '<b class="brand-name">Agent Desk</b>'
        f'<span class="phone-current">{current_label}</span>'
        '<button type="button" class="phone-menu" aria-expanded="false" '
        'aria-controls="main-rail">Menu</button></div>'
    )
    return (
        f'<nav class="rail" id="main-rail" aria-label="Main">{phone}'
        '<div class="brand"><b class="brand-name">Agent Desk</b></div>'
        f'{entry("/", "Dashboard")}'
        # The count rides inside the link: one row on the rail, and
        # the accessible name carries the waiting number.
        f'{entry("/inbox", "Inbox", badge)}'
        f'{entry("/assistant", "Assistant")}'
        # Agents beside Assistant: both are host surfaces over the one
        # endpoint, one per question, one per task.
        f'{entry("/agents", "Agents")}'
        # Activity, Capabilities and Peers moved under Settings: the rail
        # carries the surfaces a person uses every day, not every URL the
        # server can render. Their routes still answer for deep links.
        f'{entry("/memory", "Memory")}'
        f'{entry("/mail", "Mail")}'
        # The marketplace is the Plugins page (spec 022); the address is
        # unchanged so every saved link still opens it.
        f'{entry("/marketplace", "Plugins")}'
        f'{entry("/settings", "Settings")}'
        f'{toggle}'
        '<div class="user"><span class="avatar" aria-hidden="true">AD</span>'
        '<div><b class="user-name">Agent Desk</b><small>local only</small></div></div>'
        "</nav>"
    )


def document_head(title: str) -> str:
    """The head every server-rendered document shares, through the four
    shells: local stylesheet and theme boot only, nothing fetched from
    the network, no inline script. The CSP story (script-src 'self', the
    bundled .woff2 fonts, the hashed SPA bundles) is told here, once.

    `title` is the raw document title; it is escaped here.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script src="/static/theme-boot.js"></script>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>"""


def page_footer(version: str, note: str = "", touches: bool = True) -> str:
    """The shared footer line: the version, an optional page note, and
    the what-this-touches link unless `touches` is False (the shells
    that are not full app pages keep the version line only).
    """
    note_html = f"<span>{html.escape(note)}</span>" if note else ""
    link = '<a href="/what-this-touches">What this app touches</a>' if touches else ""
    return (
        '<footer class="page-foot">'
        f'<span>Agent Desk <span class="mono">{html.escape(version)}</span>.</span>'
        f"{note_html}{link}</footer>"
    )


def page_shell(
    title: str,
    active: str,
    content_html: str,
    version: str,
    inbox_count: int = 0,
    wide: bool = False,
) -> str:
    """The shared document shell for the server-rendered pages: the rail
    beside the content column, a breadcrumb naming where you are, then
    the footer inside the same column that owns the version and the
    what-this-touches link. Navigation lives in the rail, so no page
    carries a dangling back-link.

    `content_html` is authored by the caller (each view escapes its own
    dynamic values) and sits inside the .doc column; the app.js actions
    script ships with every page. `wide` widens the column for a page
    laid out as a grid of tiles (the Memory page).
    """
    esc_title = html.escape(title)
    return f"""{document_head(f"{title}, Agent Desk")}
<div class="app">{_rail(active, inbox_count)}
<main><div class="{'doc doc-wide' if wide else 'doc'}">
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Agent Desk</a><span class="crumb-sep" aria-hidden="true">/</span><span aria-current="page">{esc_title}</span></nav>
{content_html}
{page_footer(version)}
</div>
</main>
<script src="/static/app.js"></script>
</body>
</html>
"""


def render_decisions_widget(recommendations: list[dict], now, setup: list[dict] | None = None) -> Widget:
    """The Decisions card for the server-rendered dashboard.

    Shows the three soonest recommendations, each quoting the rule's own title
    and why line, with Not now as a plain form post so the card is dismissible
    without JavaScript. With no recommendations and a desk that is not set up
    yet, it shows the same setup rows as the SPA; with neither, it says so in
    the same words as the SPA: nothing is invented to fill it.
    """
    items = list(recommendations)
    rows = []
    for item in items[:3]:
        sample = '<span class="tag-sample">SAMPLE DATA</span>' if item.get("sample") else ""
        title = html.escape(str(item.get("title") or "A recommendation"))
        why_text = str(item.get("why") or "")
        if item.get("whySource") == "model":
            why_text += " · ranked by your endpoint"
        why = html.escape(why_text)
        href = html.escape(str(item.get("href") or "/agents"))
        label = html.escape(str(item.get("actionLabel") or "Open Agents"))
        card_id = html.escape(str(item.get("cardId") or ""))
        rows.append(
            "<li><div class=\"decision-text\">"
            f'<span class="decision-title">{title} {sample}</span>'
            f'<span class="decision-why">{why}</span></div>'
            '<span class="decision-actions">'
            f'<a class="btn btn-secondary btn-sm" href="{href}">{label}</a>'
            f'<form method="post" action="/inbox/cards/{card_id}/dismiss">'
            '<button class="btn btn-secondary btn-sm" type="submit">Not now</button>'
            "</form></span></li>"
        )
    setup_rows = []
    if not rows:
        for item in list(setup or [])[:4]:
            title = html.escape(str(item.get("title") or ""))
            why = html.escape(str(item.get("why") or ""))
            href = html.escape(str(item.get("href") or "/settings"))
            label = html.escape(str(item.get("actionLabel") or "Open settings"))
            setup_rows.append(
                "<li><div class=\"decision-text\">"
                f'<span class="decision-title">{title}</span>'
                f'<span class="decision-why">{why}</span></div>'
                '<span class="decision-actions">'
                f'<a class="btn btn-secondary btn-sm" href="{href}">{label}</a>'
                "</span></li>"
            )
    if rows:
        body = '<ul class="decisions">' + "".join(rows) + "</ul>"
        extra = len(items) - len(rows)
        if extra > 0:
            body += f'<p class="empty">{extra} more in inbox.</p>'
    elif setup_rows:
        body = '<ul class="decisions">' + "".join(setup_rows) + "</ul>"
    else:
        body = '<div class="well"><p class="q">Nothing needs a decision.</p></div>'
    status = SAMPLE if any(item.get("sample") for item in items) else FRESH
    if items:
        stamp = f"{len(items)} waiting"
    elif setup_rows:
        stamp = "Getting set up"
    else:
        stamp = "Up to date"
    return Widget(
        id="decisions",
        title="Decisions",
        col="col-5",
        freshness=Freshness(status, stamp, now.strftime("%Y-%m-%dT%H:%M:%S")),
        body_html=body,
        foot_html="Built from facts you saved. Nothing leaves this machine.",
    )


def render_dashboard(widgets: Iterable[Widget], version: str, greeting: str, date_line: str, inbox_count: int = 0, skills: Iterable[dict] | None = None, connected_sources: int = 0, banner: str = "", sample: bool = False) -> str:
    """The full dashboard document: rail, greeting, skills, widgets, footer.

    The one source line is only ever the truth: nothing connected gets a
    gentle pointer to each card's connect step, anything connected gets a
    live count, and the labelled sample set is named as sample and never
    counted among the live sources. No card carries invented values.
    """
    cards = "".join(_widget_html(w) for w in widgets)
    strip = ""
    if skills:
        buttons = "".join(
            f"<button class='skill-btn' data-skill-run='{html.escape(str(s['id']))}'>"
            f"{html.escape(s['name'])}</button>"
            for s in skills
        )
        strip = f"<div class='skills-strip' aria-label='Your skills'>{buttons}</div>"
    if connected_sources > 0:
        dot_class, source_line = "dot", f"Live: {connected_sources} of {len(SOURCE_IDS)} sources connected."
    elif sample:
        dot_class, source_line = "dot sample", "Sample data is on: nothing here is from your own files yet."
    else:
        dot_class, source_line = "dot sample", "Not connected yet: each card below has its own one-step connect."
    banner_html = (
        f"<div class='alert' role='status'>{html.escape(banner)}</div>"
        if banner else ""
    )
    return f"""{document_head("Agent Desk")}
<div class="app">
{_rail("/", inbox_count)}
<main>
<div class="topbar">
  <div>
    <h1>{html.escape(greeting)}</h1>
    <p class="sub"><span class="{dot_class}" aria-hidden="true"></span>{html.escape(date_line)} {html.escape(source_line)}</p>
  </div>
</div>
{banner_html}
{strip}
<section class="grid" aria-label="Dashboard">
{cards}
</section>
{page_footer(version, note="Cards show only what their connected sources report.")}
</main>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""


def render_error_page(title: str, message: str) -> str:
    """The minimal same-language page for 401/403/404 answers."""
    return f"""{document_head(f"{title}, Agent Desk")}
<div class="error-card">
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
</div>
</body>
</html>
"""


def render_press_page(
    label: str,
    disclosure: list[str],
    version: str,
    text: str = "",
    source: str = "",
    note: str = "",
    refusal: str = "",
    stage_html: str = "",
    staged_id: str = "",
    inbox_count: int = 0,
) -> str:
    """What one pressed card answered, as a page of its own.

    The disclosure comes first and the answer second, because the promise
    and the result are read together: a person decides whether to press
    again from the same screen that shows what the press sent. A refusal
    is the whole answer when it happens: the page keeps the sentence and
    offers nothing to press.
    """
    lines = "".join(
        '<li>' + html.escape(str(line)) + "</li>" for line in disclosure
    )
    disclosed = f'<ul class="empty" aria-label="What this press sends">{lines}</ul>' if lines else ""
    if refusal:
        answer_html = '<div class="alert"><p>' + html.escape(refusal) + "</p></div>"
    else:
        answer_html = '<pre class="press-draft">' + html.escape(text) + "</pre>"
        if note:
            answer_html += '<p class="empty">' + html.escape(note) + "</p>"
        if source:
            answer_html += (
                '<p class="empty">Source: <span class="mono">'
                + html.escape(source)
                + "</span></p>"
            )
    staged = ""
    if staged_id:
        staged = (
            '<p class="empty">Staged as a card: <span class="mono">'
            + html.escape(staged_id)
            + '</span>. <a href="/inbox">Open the inbox</a> to accept or edit it.</p>'
        )
    content = (
        '<section class="card">'
        "<h2>" + html.escape(label) + "</h2>"
        + disclosed
        + answer_html
        + stage_html
        + staged
        + "</section>"
    )
    return page_shell(label, "/", content, version, inbox_count=inbox_count)


def render_walkthrough(watch_hint: str, explicit_path: str, version: str, inbox_count: int = 0) -> str:
    """The calendar connection walkthrough: three browser steps, no terminal.

    The user creates the Power Automate flow themselves in their browser;
    this page says exactly what to click, what the app expects to find,
    and where it watches. The source section below the steps is for the
    days automatic discovery is not enough: pick a file, paste a path,
    upload the JSON by hand, or go back to automatic. The Check-now
    button re-reads, so the moment data arrives, the dashboard confirms.
    """
    hint = html.escape(watch_hint)
    if explicit_path:
        watch_line = (
            "<p>You chose a specific file, so automatic discovery is set "
            "aside and the app reads exactly:</p>"
        )
        reset_html = (
            '<button class="btn btn-secondary" data-calendar-reset>'
            "Back to automatic discovery</button>"
        )
    else:
        watch_line = "<p>Once the flow has run, the app finds the file here:</p>"
        reset_html = (
            '<button class="btn btn-secondary" data-calendar-reset>'
            "Reset to automatic discovery</button>"
        )
    content = """<h1>Connect your calendar</h1>
<p>Agent Desk reads one file that a small Power Automate flow keeps fresh
in your OneDrive. You create that flow once, in your browser: no admin,
no terminal, nothing installed.</p>
<ol>
<li>Open <b>make.powerautomate.com</b> in your browser and sign in with
your work account. Choose <b>Create</b>, then <b>Scheduled cloud flow</b>,
and let it run <b>every 30 minutes</b>.</li>
<li>Add the action <b>Get calendar view of events (V3)</b>. Point it at
your calendar, with today as the start date.</li>
<li>Add the action <b>Create file</b> (OneDrive for Business). Set the
folder path to <b>/agent-desk</b> (create it), the file name to
<b>calendar_sync.json</b>, and File Content to the calendar events value
from the previous step. Save the flow.</li>
</ol>
""" + watch_line + """
<pre>""" + hint + """</pre>
<p>The file looks like this (the flow builds it; this is only the shape):</p>
<pre>{
  "generatedAt": "2026-11-11T08:00:00",
  "events": [
    {"id": "evt-1", "subject": "Q4 pipeline review",
     "start": "2026-11-11T14:00:00", "end": "2026-11-11T15:00:00",
     "location": "Room Beaufort", "attendees": 6}
  ]
}</pre>
<h2>Use a different calendar file</h2>
<p>If your data lands somewhere else, choose the file here: pick it with
the file dialog, paste its full path, or upload the JSON by hand. Your
choice wins over automatic discovery, survives restarts, and the card
refreshes immediately. Reset returns to automatic.</p>
<div class="cardrow">
<button class="btn btn-secondary" data-calendar-pick>Pick a file</button>
""" + reset_html + """
</div>
<div class="well">
<input id="calendar-path" class="well-input" type="text"
placeholder="Full path to the calendar JSON file" aria-label="Calendar file path">
<button class="btn btn-secondary" data-calendar-path>Use this path</button>
</div>
<div class="well">
<input id="calendar-file" type="file" accept=".json,application/json"
aria-label="Calendar JSON file to upload">
<button class="btn btn-secondary" data-calendar-upload>Upload this file</button>
</div>
<div class="alert" id="calendar-note" hidden></div>
<div class="cardrow">
<button class="btn btn-primary" data-calendar-retest>Check for calendar data now</button>
</div>
<p>If your tenant blocks personal flows, ask the
technical owner: the same file can be produced any way IT prefers. The
app only ever reads it.</p>
"""
    return page_shell("Connect your calendar", "", content, version, inbox_count=inbox_count)
