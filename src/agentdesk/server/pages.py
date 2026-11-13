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

from agentdesk.server.core import ATTENTION, FRESH, SAMPLE, SOURCE_IDS
from agentdesk.server.demo import Widget

ICON_OPTIONS = (
    '<button class="icon-btn" aria-label="Widget options">'
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" '
    'aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/>'
    '<circle cx="19" cy="12" r="1.7"/></svg></button>'
)

_ICON_DASHBOARD = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">'
    '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" '
    'height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/>'
    '<rect x="13.5" y="13.5" width="7" height="7" rx="2"/></svg>'
)
_ICON_INBOX = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M3.5 13.5 5 20h14l1.5-6.5M3.5 13.5h17M12 15v-4"/>'
    "</svg>"
)
_ICON_ASSISTANT = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-6.5L8 20.5v-4H5A1.5 1.5 0 0 1 3.5 15V7A1.5 1.5 0 0 1 5 5.5Z"/>'
    '<path d="M8.5 10h7M8.5 13h4"/>'
    "</svg>"
)
_ICON_PLUGINS = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">'
    '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M12 8v8M8 12h8"/></svg>'
)
_ICON_SETTINGS = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">'
    '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3"/><circle cx="15" cy="7" r="2"/>'
    '<circle cx="9" cy="12" r="2"/><circle cx="15" cy="17" r="2"/></svg>'
)
_ICON_ACTIVITY = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M3.5 12h4l2.5-6.5 4 13 2.5-6.5h4"/></svg>'
)
_ICON_MEMORY = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.5"/>'
    '<path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13"/>'
    '<path d="M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/></svg>'
)
_ICON_MAIL = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/>'
    '<path d="m4.5 8 7.5 5.5L19.5 8"/></svg>'
)
_ICON_CAPABILITIES = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3.5 5 6.2v4.6c0 4.6 3 8.6 7 9.7 4-1.1 7-5.1 7-9.7V6.2L12 3.5Z"/>'
    '<path d="m9 11.5 2.2 2.2 3.8-4.4"/></svg>'
)
_ICON_PEERS = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="8" cy="8" r="3"/><circle cx="16" cy="16" r="3"/>'
    '<path d="M10.5 10.5 13.5 13.5"/><path d="M3.5 8h1.5M19 16h1.5"/>'
    '</svg>'
)

# The design language tokens, verbatim from docs/design-language.md. Font
# families resolve locally: the named faces when installed, otherwise the
# OS fallbacks. Nothing is fetched from the network.
STYLES = """
:root{
  --bg:#F6F4EF; --surface:#FFFFFF; --surface-2:#FBFAF7;
  --ink-1:#1F2A27; --ink-2:#4C5A55; --ink-3:#77847E; --ink-4:#A9B1AC;
  --hairline:#E5E1D6;
  --shadow-card:0 0 0 1px rgba(31,42,39,.05),0 1px 2px -1px rgba(31,42,39,.06),0 2px 4px 0 rgba(31,42,39,.04);
  --shadow-card-hover:0 0 0 1px rgba(31,42,39,.07),0 1px 2px -1px rgba(31,42,39,.08),0 2px 4px 0 rgba(31,42,39,.06);
  --primary:#14594E; --primary-ink:#F6FBF9; --primary-soft:#E4EEE9;
  --good:#14594E; --bad:#B3402A;
  --attention-bg:#FBF3E2; --attention-ink:#8A5A14;
  --r-card:12px; --r-control:8px; --r-inner:6px; --dur:160ms;
  --font-ui:"Plus Jakarta Sans",-apple-system,"Segoe UI",sans-serif;
  --font-mono:"IBM Plex Mono","Consolas",monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-ui);background:var(--bg);color:var(--ink-1);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
button{font:inherit;cursor:pointer;border:none;background:none;color:inherit}
button:disabled{opacity:.55;cursor:default}
a{color:var(--primary);text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:4px}
svg{display:block;flex:none}
.mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.app{display:grid;grid-template-columns:224px 1fr;min-height:100vh}
.rail{border-right:1px solid var(--hairline);background:var(--surface-2);padding:20px 12px;display:flex;flex-direction:column;gap:4px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;padding:2px 8px 18px}
.brand .mark{width:28px;height:28px;border-radius:8px;background:var(--primary);display:grid;place-items:center;color:var(--primary-ink)}
.brand b{font-size:14px;font-weight:800;letter-spacing:-.01em}
.rail a,.rail .nav-off{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:var(--r-control);color:var(--ink-2);text-decoration:none;font-weight:600;transition:background var(--dur) ease,color var(--dur) ease}
.rail a:hover{background:#EFEDE5;color:var(--ink-1)}
.rail a[aria-current="page"]{background:var(--primary-soft);color:var(--primary)}
.rail .nav-off{opacity:.45}
.rail .count{margin-left:auto;font-family:var(--font-mono);font-size:11px;font-weight:600;background:var(--primary);color:var(--primary-ink);border-radius:999px;padding:1px 7px}
.origin-line{font-size:12px;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.06em}
.origin-why{color:var(--ink-2);font-size:13px;border-top:1px solid var(--hairline);padding-top:8px}
.widget h3{font-size:16.5px;font-weight:800;letter-spacing:-.01em}
.cardrow{display:flex;gap:10px;margin-top:4px;flex-wrap:wrap}
.addplugin-form{display:inline-flex;margin:0}
.w-big{font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--ink-1)}
.w-note{font-size:12.5px;color:var(--ink-3)}
.settings-skill{margin-bottom:12px}
.skill-name{font-size:14.5px}
.skills-strip{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.skills-strip .skill-btn{background:var(--surface);color:var(--ink-1);border-radius:var(--r-control);box-shadow:inset 0 0 0 1px var(--hairline),var(--shadow-card);padding:8px 14px;font-weight:700;font-size:13px;transition:background var(--dur) ease}
.skills-strip .skill-btn:hover{background:var(--surface-2)}
.settings-block{display:flex;flex-direction:column;gap:8px;max-width:460px}
.cardform{display:flex;flex-direction:column;gap:8px;margin:8px 0;max-width:460px}
.cardform .btn{align-self:flex-start}
.cardform label{font-size:12px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.cardform input,.cardform select,.cardform textarea{font:inherit;font-size:13.5px;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px;min-height:36px}
.cardform input:focus,.cardform select:focus,.cardform textarea:focus{outline:2px solid var(--primary);outline-offset:1px}
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
.crumbs{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--ink-3);margin-bottom:12px}
.crumbs a{color:var(--ink-3);font-weight:600}
.crumbs a:hover{color:var(--primary)}
.crumbs .crumb-sep{color:var(--ink-4)}
.field{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.field input{font:inherit;font-size:13.5px;font-weight:400;letter-spacing:normal;text-transform:none;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px}
.field input:focus{outline:2px solid var(--primary);outline-offset:1px}
.setting-row{display:flex;align-items:center;justify-content:space-between;gap:16px;background:var(--surface);border-radius:var(--r-control);box-shadow:var(--shadow-card);padding:10px 14px;font-weight:600;font-size:13.5px}
.rail .user{margin-top:auto;display:flex;gap:10px;align-items:center;padding:10px 8px;border-top:1px solid var(--hairline)}
.rail .user .avatar{width:30px;height:30px;border-radius:999px;background:var(--primary-soft);color:var(--primary);display:grid;place-items:center;font-weight:800;font-size:12px}
.rail .user small{display:block;color:var(--ink-3);font-weight:400}
.rail .user .user-name{font-size:13px}
.rail-toggle{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border-radius:var(--r-control);color:var(--ink-3);font-weight:600;font-size:12px;margin-top:8px;transition:background var(--dur) ease,color var(--dur) ease}
.rail-toggle:hover{background:#EFEDE5;color:var(--ink-1)}
/* Collapsed: the rail keeps its marks (icons, count badge, avatar) and
   drops its text; the column narrows to the mark width. */
.app.rail-collapsed{grid-template-columns:68px 1fr}
.rail-collapsed .rail{padding:20px 10px}
.rail-collapsed .rail a{position:relative;justify-content:center;padding:8px 0;gap:0}
.rail-collapsed .rail .rail-label{display:none}
.rail-collapsed .rail .count{position:absolute;top:4px;right:4px;margin-left:0;padding:0 5px;font-size:10px}
.rail-collapsed .rail .rail-toggle{justify-content:center;gap:0}
.rail-collapsed .rail-toggle .rail-toggle-label{display:none}
.rail-collapsed .brand b,.rail-collapsed .brand-name{display:none}
.rail-collapsed .rail .user{justify-content:center;padding:10px 0}
.rail-collapsed .rail .user > div{display:none}
main{padding:28px 36px 60px;max-width:1200px;width:100%;margin:0 auto}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:22px}
.topbar h1{font-size:28px;font-weight:800;letter-spacing:-.02em}
.topbar .sub{color:var(--ink-2);margin-top:2px;display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:999px;background:var(--good);display:inline-block}
.dot.amber{background:var(--attention-ink)}
.dot.sample{background:var(--ink-4)}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:var(--r-control);padding:8px 14px;font-weight:700;transition:background var(--dur) ease,box-shadow var(--dur) ease,color var(--dur) ease;min-height:36px}
.btn-primary{background:var(--primary);color:var(--primary-ink);box-shadow:var(--shadow-card)}
.btn-secondary{background:var(--surface);color:var(--ink-1);box-shadow:inset 0 0 0 1px var(--hairline)}
.btn-secondary:hover:not(:disabled){background:var(--surface-2)}
.btn-danger{background:var(--surface);color:var(--bad);box-shadow:inset 0 0 0 1px var(--hairline)}
.btn-danger:hover:not(:disabled){background:var(--surface-2)}
.icon-btn{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:var(--r-inner);color:var(--ink-3);transition:background var(--dur) ease,color var(--dur) ease}
.icon-btn:hover{background:#EFEDE5;color:var(--ink-1)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
.widget{background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:18px 18px 14px;transition:box-shadow 200ms ease;display:flex;flex-direction:column;gap:12px}
.widget:hover{box-shadow:var(--shadow-card-hover)}
.col-7{grid-column:span 7}.col-5{grid-column:span 5}.col-8{grid-column:span 8}.col-4{grid-column:span 4}
.w-head{display:flex;align-items:center;gap:12px}
.w-head h2{font-size:16px;font-weight:700;letter-spacing:-.01em}
.stamp{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink-3);font-weight:600}
.w-foot{display:flex;align-items:flex-start;gap:10px;border-top:1px solid var(--hairline);padding-top:12px;font-size:12px;line-height:1.5;color:var(--ink-3)}
.kpi{display:flex;gap:24px;align-items:flex-start}
.kpi .label{font-size:12px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.kpi .value{font-family:var(--font-mono);font-size:28px;font-weight:600;letter-spacing:-.01em;color:var(--good);margin-top:2px;overflow-wrap:anywhere}
.kpi .sub{font-size:12px;color:var(--ink-3);margin-top:2px}
.spark{margin-left:auto;text-align:right}
.spark figcaption{font-size:11px;color:var(--ink-4);margin-top:4px}
table.rows{width:100%;border-collapse:collapse;font-size:13px}
table.rows th{text-align:left;font-size:11px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;padding:4px 8px 8px 0;border-bottom:1px solid var(--hairline)}
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
.subhead{font-size:12px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.subhead-tight{margin-bottom:4px}
.check{display:flex;gap:10px;align-items:flex-start;padding:7px 0;font-size:13.5px}
.check .box{width:18px;height:18px;border-radius:5px;border:1.5px solid var(--ink-4);display:grid;place-items:center;color:transparent;transition:all var(--dur) ease;margin-top:1px}
.check[aria-checked="true"] .box{background:var(--primary);border-color:var(--primary);color:var(--primary-ink)}
.check[aria-checked="true"] span:not(.box){text-decoration:line-through;color:var(--ink-3)}
.follow{display:inline-flex;align-items:center;gap:8px;background:var(--attention-bg);color:var(--attention-ink);border-radius:999px;padding:5px 12px;font-size:12.5px;font-weight:600}
.well{display:flex;gap:10px;align-items:flex-start;background:var(--surface-2);border:1px solid var(--hairline);border-radius:var(--r-control);padding:12px}
.well .q{flex:1;color:var(--ink-3)}
.well-input{flex:1;font:inherit;color:var(--ink-1);background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r-inner);padding:8px 10px;resize:vertical}
.well-input:focus{outline:2px solid var(--primary);outline-offset:1px}
.grow{flex:1}
.thread{display:flex;flex-direction:column;gap:12px;margin:14px 0}
.thread .ask{background:var(--surface-2);border-radius:var(--r-inner);padding:12px 14px}
.thread .ask .who{font-size:11px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.thread .reply p{margin:4px 0 0}
.thread .who{font-size:11px;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.06em}
.thread p{color:var(--ink-1);font-size:13.5px}
.answer{background:var(--surface-2);border-radius:var(--r-inner);padding:14px;font-size:13.5px;display:flex;flex-direction:column;gap:8px}
.answer .aq{font-weight:700;margin-bottom:0}
.answer .well-input{width:100%}
.src{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);font-size:11px;color:var(--ink-2);background:var(--surface);border:1px solid var(--hairline);border-radius:999px;padding:3px 10px;margin:10px 8px 0 0}
.tag-sample{font-size:10px;font-weight:700;color:var(--ink-3);text-transform:uppercase;letter-spacing:.08em}
.widget.amber{background:var(--surface);box-shadow:0 0 0 1px rgba(138,90,20,.18),0 1px 2px -1px rgba(138,90,20,.10),0 2px 4px 0 rgba(138,90,20,.08)}
.alert{display:flex;gap:10px;align-items:flex-start;color:var(--attention-ink);font-size:13.5px}
.badge-pilot{font-size:11px;font-weight:700;color:var(--attention-ink);background:var(--attention-bg);border-radius:999px;padding:2px 9px}
.btn-start{align-self:flex-start}
.empty{color:var(--ink-3);font-size:13px}
.doc{max-width:720px;margin:32px auto;padding:0 16px}
.doc h1{font-size:20px;font-weight:700;margin-bottom:6px;letter-spacing:-.01em}
.doc > h2{font-size:16px;font-weight:700;margin:24px 0 0;letter-spacing:-.01em}
.doc p{color:var(--ink-2);font-size:13.5px;margin:8px 0}
.doc ol{margin:12px 0;padding-left:20px;color:var(--ink-2);font-size:13.5px;display:flex;flex-direction:column;gap:8px}
.doc pre{background:var(--surface-2);border:1px solid var(--hairline);border-radius:var(--r-control);padding:12px;font-family:var(--font-mono);font-size:12px;overflow:auto;white-space:pre-wrap;color:var(--ink-1)}
.doc .cardrow{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
.doc a.btn{text-decoration:none}
.page-foot{margin-top:48px;color:var(--ink-3);font-size:12px;border-top:1px solid var(--hairline);padding-top:12px;display:flex;gap:16px;flex-wrap:wrap}
.page-foot a{color:var(--primary);font-weight:700;text-decoration:none}
.page-foot a:hover{text-decoration:underline}
.touches td{vertical-align:top;font-size:13px}
.touch-badge{display:inline-flex;background:var(--surface-2);color:var(--ink-3);border:1px solid var(--hairline);border-radius:999px;padding:2px 9px;font-size:11px;font-weight:700}
.touch-badge.on{background:var(--primary-soft);color:var(--primary);border-color:transparent}
.error-card{max-width:460px;margin:18vh auto 0;background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:28px;display:flex;flex-direction:column;gap:8px}
.error-card h1{font-size:20px;font-weight:800}
.error-card p{color:var(--ink-2);font-size:13.5px}
@media (max-width:980px){
  /* The single-column shell becomes a block, matching the dashboard
     SPA: a sticky grid item inside its own auto-sized row has no
     travel, so the strip would still scroll away. */
  .app{display:block}
  /* The strip stays pinned while the page scrolls and its entries wrap
     instead of clipping, matching the dashboard SPA's behavior. */
  .rail{position:sticky;top:0;height:auto;z-index:20;flex-direction:row;flex-wrap:wrap;align-items:center;border-right:none;border-bottom:1px solid var(--hairline);padding:10px 14px;gap:8px}
  .rail .brand{padding:0 12px 0 0}
  .rail .user{display:none}
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
"""

# The scripts the shell ships: the workbook picker flow, the Re-test
# calls for the live widgets, and the card actions. Same-origin only;
# no frameworks.
APP_JS = """\
// Same-origin POST helper: every call here stays on 127.0.0.1.
function post(url, body) {
  return fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : '{}'});
}

// Workbook connect: the app opens the native file dialog, the chosen
// path registers the watch, and the dashboard reloads with real data.
// A cancelled or invisible dialog is never silent: the amber note and
// the manual path input appear on the card, and every failed call is
// reported in the same place instead of reloading nothing.
(function () {
  var btn = document.querySelector('[data-pick]');
  var manual = document.querySelector('[data-manual-connect]');
  if (!btn && !manual) return;
  var note = document.getElementById('pick-note');
  var input = document.getElementById('workbook-path');
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
  if (btn) btn.addEventListener('click', function () {
    post('/sources/excel-watch/pick').then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.path) {
          show('The file dialog did not open. Type the workbook path below and press Connect.');
          return;
        }
        connect(d.path);
      })
      .catch(function () {
        show('The dashboard could not reach its own server; the file dialog was not opened.');
      });
  });
  if (manual) manual.addEventListener('click', function () {
    var path = input ? input.value.trim() : '';
    if (!path) { show('Type the full path to the workbook first.'); return; }
    connect(path);
  });
  if (input) input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); if (manual) manual.click(); }
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

// Endpoint form: Save and Clear reload (the masked key state re-renders),
// Test answers inline using exactly what is typed, saved or not.
(function () {
  var save = document.querySelector('[data-endpoint-save]');
  if (!save) return;
  var note = document.getElementById('endpoint-note');
  var show = function (text) {
    if (note) { note.hidden = false; note.textContent = text; }
  };
  var typed = function () {
    return {
      base: (document.getElementById('llm-base') || {}).value || '',
      key: (document.getElementById('llm-key') || {}).value || '',
      model: (document.getElementById('llm-model') || {}).value || ''
    };
  };
  save.addEventListener('click', function () {
    post('/settings/endpoint/save', typed()).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { show(d.error); return; }
        location.reload();
      })
      .catch(function () { show('The dashboard could not reach its own server; nothing was saved.'); });
  });
  var test = document.querySelector('[data-endpoint-test]');
  if (test) test.addEventListener('click', function () {
    show('Testing the connection');
    post('/settings/endpoint/test', typed()).then(function (r) { return r.json(); })
      .then(function (d) {
        // The cause is a full sentence from the adapter's vocabulary;
        // it already says what to fix, so it is shown as-is.
        show(d.ok ? 'The endpoint answered.' : (d.cause || 'The test did not run.'));
      })
      .catch(function () { show('The dashboard could not reach its own server; the test did not run.'); });
  });
  var clear = document.querySelector('[data-endpoint-clear]');
  if (clear) clear.addEventListener('click', function () {
    post('/settings/endpoint/save', {base: '', key: '', model: ''})
      .then(function () { location.reload(); })
      .catch(function () { show('The dashboard could not reach its own server; nothing was cleared.'); });
  });
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
(function () {
  var KEY = 'agentdesk.railCollapsed';
  var app = document.querySelector('.app');
  var btn = document.querySelector('.rail-toggle');
  if (!app || !btn) return;
  var apply = function (collapsed) {
    app.classList.toggle('rail-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
    btn.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
    var label = btn.querySelector('.rail-toggle-label');
    if (label) label.textContent = collapsed ? 'Expand' : 'Collapse';
  };
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }
  apply(stored === '1');
  btn.addEventListener('click', function () {
    var next = btn.getAttribute('aria-expanded') !== 'true';
    try { localStorage.setItem(KEY, next ? '1' : '0'); } catch (e) {}
    apply(next);
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
        '<button type="button" class="rail-toggle" aria-expanded="false" '
        'aria-label="Collapse navigation">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.7" stroke-linecap="round" aria-hidden="true">'
        '<path d="M14.5 6.5 8 12l6.5 5.5"/></svg>'
        '<span class="rail-toggle-label">Collapse</span></button>'
    )

    def entry(href: str, icon: str, label: str, extra: str = "") -> str:
        current = ' aria-current="page"' if href == active else ""
        return f'<a href="{href}"{current}>{icon}<span class="rail-label">{label}</span>{extra}</a>'

    return (
        '<nav class="rail" aria-label="Main">'
        '<div class="brand"><span class="mark" aria-hidden="true">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.4" stroke-linecap="round"><path d="M4 12h6M8 8v8M14 10h6M17 7v10"/></svg>'
        '</span><b>Agent Desk</b></div>'
        f'{entry("/", _ICON_DASHBOARD, "Dashboard")}'
        # The count rides inside the link: one row on the rail, and
        # the accessible name carries the waiting number.
        f'{entry("/inbox", _ICON_INBOX, "Inbox", badge)}'
        f'{entry("/assistant", _ICON_ASSISTANT, "Assistant")}'
        f'{entry("/activity", _ICON_ACTIVITY, "Activity")}'
        f'{entry("/memory", _ICON_MEMORY, "Memory")}'
        f'{entry("/mail", _ICON_MAIL, "Mail")}'
        f'{entry("/capabilities", _ICON_CAPABILITIES, "Capabilities")}'
        f'{entry("/plugins", _ICON_PLUGINS, "Plugins")}'
        f'{entry("/peers", _ICON_PEERS, "Peers")}'
        f'{entry("/settings", _ICON_SETTINGS, "Settings")}'
        f'{toggle}'
        '<div class="user"><span class="avatar" aria-hidden="true">AD</span>'
        '<div><b class="user-name">Agent Desk</b><small>local only</small></div></div>'
        "</nav>"
    )


def page_shell(
    title: str,
    active: str,
    content_html: str,
    version: str,
    inbox_count: int = 0,
) -> str:
    """The shared document shell for the server-rendered pages: the rail
    beside the content column, a breadcrumb naming where you are, then
    the footer inside the same column that owns the version and the
    what-this-touches link. Navigation lives in the rail, so no page
    carries a dangling back-link.

    `content_html` is authored by the caller (each view escapes its own
    dynamic values) and sits inside the .doc column; the app.js actions
    script ships with every page.
    """
    esc_version = html.escape(version)
    esc_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc_title}, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="app">{_rail(active, inbox_count)}
<main><div class="doc">
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Agent Desk</a><span class="crumb-sep" aria-hidden="true">/</span><span aria-current="page">{esc_title}</span></nav>
{content_html}
<footer class="page-foot"><span>Agent Desk <span class="mono">{esc_version}</span>.</span><a href="/what-this-touches">What this app touches</a></footer>
</div>
</main>
<script src="/static/app.js"></script>
</body>
</html>
"""


def render_dashboard(widgets: Iterable[Widget], version: str, greeting: str, date_line: str, inbox_count: int = 0, skills: Iterable[dict] | None = None, connected_sources: int = 0) -> str:
    """The full dashboard document: rail, greeting, skills, widgets, footer.

    The one source line is only ever the truth: nothing connected gets a
    gentle pointer to each card's connect step, anything connected gets a
    live count. No card carries invented values, so there is no sample
    state to confess in a banner.
    """
    cards = "".join(_widget_html(w) for w in widgets)
    esc_version = html.escape(version)
    strip = ""
    if skills:
        buttons = "".join(
            f"<button class='skill-btn' data-skill-run='{s['id']}'>{html.escape(s['name'])}</button>"
            for s in skills
        )
        strip = f"<div class='skills-strip' aria-label='Your skills'>{buttons}</div>"
    if connected_sources > 0:
        dot_class, source_line = "dot", f"Live: {connected_sources} of {len(SOURCE_IDS)} sources connected."
    else:
        dot_class, source_line = "dot sample", "Not connected yet: each card below has its own one-step connect."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="app">
{_rail("/", inbox_count)}
<main>
<div class="topbar">
  <div>
    <h1>{html.escape(greeting)}</h1>
    <p class="sub"><span class="{dot_class}" aria-hidden="true"></span>{html.escape(date_line)} {html.escape(source_line)}</p>
  </div>
  <form method="post" action="/wizard/start" class="addplugin-form"><button class="btn btn-primary" type="submit">Add plugin</button></form>
</div>
{strip}
<section class="grid" aria-label="Dashboard">
{cards}
</section>
<footer class="page-foot"><span>Agent Desk <span class="mono">{esc_version}</span>.</span><span>Cards show only what their connected sources report.</span><a href="/what-this-touches">What this app touches</a></footer>
</main>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""


def render_error_page(title: str, message: str) -> str:
    """The minimal same-language page for 401/403/404 answers."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="error-card">
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
</div>
</body>
</html>
"""


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
