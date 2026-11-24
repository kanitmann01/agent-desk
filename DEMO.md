# DEMO.md: one manager's morning

The script for an 8 minute demo of Agent Desk on one Windows laptop. It is
one person's story, not a tour of the product: a desk that asks for three
things once, then reads my pipeline, knows my day, answers questions about
my own work, and remembers what I tell it.

It is written for the build of spec 022 (branch `spec022/demo-ready`). On
`main` the home screen has no Get started strip and Settings is still one
long page, so check the branch before you rehearse.

Every click below exists in the product and was walked on 2026-11-23. The
whole first-ten-minutes path is proven without a browser by
`python tools/demo_readiness.py`, which boots the real app on a fresh folder
and prints one PASS line per check (`METRIC ready=23`).

## The story in one sentence

SAY: "This is Agent Desk. I tell it three things once. After that it reads
my pipeline, knows my day, answers questions about my own work, and
remembers what I teach it. Nothing leaves this machine except the question
I type, and that goes to the AI I choose with my own key."

## The day before (10 minutes, do not skip)

1. **Get the build.** This file ships with branch `spec022/demo-ready`.
   Double-click `tools\agent-desk.cmd` in the checkout that holds that
   branch (tonight: `.worktrees\022-demo-ready`; after the pull request is
   merged: your usual checkout). It prints
   `Agent Desk is running: http://127.0.0.1:8765/auth/<one-time-token>` and
   opens the browser itself. The link is the session: there is no sign-in.
   Before the purge below, copy the whole data folder
   (`C:\Users\<you>\.agent-desk`) beside itself once: a plain copy named
   `.agent-desk-backup` is enough. Every step after this one changes that
   folder, and "Forget everything" cannot be undone.
2. **Clean the memory.** Rail: Memory. Read "How memory works" once so the
   words are yours tomorrow. Click **Forget everything**, confirm. The page
   should say 0 facts.
3. **Switch learning on.** Rail: Settings, tab **Memory**. Three switches:
   **Learn automatically**, **Learn from Assistant conversations**, **Learn
   from Research questions**. All three read On.
4. **Add your key once.** Settings, tab **Your AI**. Pick your provider,
   paste the key, the model is already filled in, click **Save**. The line
   at the top changes from "No AI key is saved yet" to "<name> answers
   everything with <model>". Have this key in a text file for tomorrow's
   live run.
5. **Have ready** your sales workbook (`.xlsx`) and your calendar as a JSON
   export, in folders you can find with a file dialog in front of a room.
6. **Rehearse once, end to end**, with the timer. Then reset for tomorrow:
   Memory: Forget everything; Settings: Your tools: Workbook: leave it (it
   can stay), or start tomorrow from a fresh data folder (step 1 of
   "Fresh start" below) if you want the strip to read 0 of 3 again.
7. **Do not click "Not now" on the Get started strip** during the
   rehearsal. It hides the strip for that browser sitting. If you did, the
   header shows **Finish setup**: one click brings it back.

**If the desk already shows SAMPLE DATA tags** (sample data is on in
Settings, as it is today): switch it off first, in Settings, Advanced,
Desk, **Sample data**. That one click removes the sample cards and the
sample memory facts with them, and the Get started strip comes back with
"Try it with sample data" for tomorrow's first beat. Then continue at
step 2. On a desk that has never been shown sample data, skip this.

### Fresh start (only if you want to open on an empty desk)

Stop the app. In a command window:
`set AGENTDESK_DATA=%TEMP%\demo-desk-1`, then start `tools\agent-desk.cmd`
from that same window. The desk is brand new and empty; your real folder is
not touched. Do the three steps live, as beats 2 to 4 below.

## The morning (8 minutes)

### Beat 0: it starts (20 seconds)

Double-click `tools\agent-desk.cmd`.

SAY: one double-click, no admin rights, no terminal. It binds to this
machine only.

### Beat 1: the desk asks for three things (1 minute)

CLICKS: land on the dashboard. Above the tiles: **GET STARTED**, three
steps in order: 1 Add your AI key, 2 Open your sales workbook, 3 Connect
your calendar. "0 of 3 done". In the question bar: **Connect your AI**.

CLICKS: the strip's line "Nothing is connected yet." Click **Try it with
sample data**. Every tile fills, each tagged **SAMPLE DATA**. The strip
still says 0 of 3 done.

SAY: it does not hand me fifty switches. It asks for three things, in
order, and each is one click. This is sample data: it is labelled on every
card, and it never counts as set up. The checklist is still at zero.

### Beat 2: the AI key, once (1 minute)

CLICKS: step 1, **Add**. Settings opens on **Your AI**: provider, key,
model, Save. Pick the provider, paste the key, **Save**.

CLICKS: rail, Dashboard. The strip says 1 of 3 done, step 1 is ticked, and
the question bar's button is now **Research**.

SAY: that used to be the thing people could not find. Now it is the first
thing on the first screen, three fields. It is stored in this computer's
keychain, so tomorrow I will not do this again.

### Beat 3: my pipeline (1 minute)

CLICKS: step 2, **Open**. The file dialog opens. Pick the sales workbook.

The Pipeline tile fills with your rows, no sample tag. 2 of 3 done.

SAY: it copies the workbook before it reads it. Nothing is written back.

### Beat 4: my day (1 minute 30 seconds)

CLICKS: step 3, **Connect**. The calendar page opens. **Pick a file** and
choose your calendar JSON, or **Upload** it. Back on the dashboard
(rail: Dashboard) the Digest shows today's meetings. 3 of 3 done, and the
strip is gone.

SAY: the checklist leaves when it is finished. From here the desk is mine.

### Beat 5: the morning loop (2 minutes)

CLICKS: rail, Assistant. Type: "Please remember this: the Acme renewal is
due December 15." Send. Rail, Memory: the fact is there, with the
Assistant named as where it came from.

CLICKS: rail, Dashboard. **Decisions** (right column) now holds a card for
that deadline, quoting the fact and the day it was saved. If the calendar
has a meeting with Acme, a second card offers to prepare for it.

CLICKS: the question bar. Type a question about your own work, for example
"What is coming due in my pipeline?" Press Enter.

SAY: I did not open a memory page to teach it. It learned from the
conversation, it shows me what it holds and where each thing came from,
and it used it by itself in Decisions.

### Beat 6: it forgets when I say (40 seconds)

CLICKS: Memory, **Forget everything**, confirm. The page says 0 facts.

SAY: it is my memory, not its own. One click and a confirmation, and it
is recorded in the activity trail.

### Beat 7: where the rest lives (30 seconds)

CLICKS: rail, **Plugins**: two tabs, Find plugins and Installed, and
**Describe a plugin in plain English**. Rail, Settings: six tabs; the last
one, Advanced, starts with "The defaults are right for most people."

SAY: everything else is still there, under one more click. Plugins only
bring data in. The desk is what connects it.

## If something fails

- **The key is refused.** The card says why, next to the row. Fix the key
  and Save again, or carry on without an AI: beats 1, 3, 4 and 7 need none.
  Skip beat 2 and the question in beat 5; show the Memory page instead.
- **The workbook dialog does not open.** Settings, Your tools, Workbook,
  **Open a workbook**. If it still fails, say so and carry on with sample
  data: the rest of the story is the same.
- **The calendar file is refused.** The page says what it needs (a JSON
  export). Carry on with the sample calendar and say that it is sample.
- **The fact is not in Memory after a few seconds.** The model decides what
  is durable. On the Memory page add the sentence by hand (the page's own
  add box). SAY: the step is the same, this time typed.
- **"Session required" in the browser.** The app was restarted. A restart
  ends the browser session; double-click `tools\agent-desk.cmd` again and
  it opens a fresh link. SAY, and mean it: a restart keeps the key, the
  workbook and the calendar. Nothing from the day before is lost.
- **Nothing on the screen works.** In a command window:
  `python tools\demo_readiness.py`. It prints one line per check and ends
  with `METRIC ready=23` on a clean folder. Read the first FAIL out loud if
  there is one: that is the thing to fix, named.

## Appendix: where the rest lives (for questions only)

- Inbox, what the desk initiates: `/inbox`. Assistant: `/assistant`.
  Memory: `/memory`.
  Activity trail, every decision with its audit row: `/activity` (also
  Settings, tab Activity).
- Mail digest, headers only, off by default: `/mail`, switched on in
  Settings, Your tools, Mail.
- Plugins: the rail's **Plugins** (the old `/plugins` address redirects
  there). **Describe a plugin in plain English** is on Find plugins (the
  old "Add plugin" and "Add widget" buttons). Install from the registry is one click on a card, digest
  pinned. Publish to the registry is the Publish action on an installed
  plugin. Studio, Publishers, Admin and the Trust center keep their
  addresses (`/marketplace/studio` and so on) and are not linked.
- Dashboard layout, re-test a source, run a saved ask: **Customize** in
  the dashboard header.
- Settings: `/settings`, six tabs. The readiness walk that proves the
  first ten minutes is `tools/demo_readiness.py`.
- Two desks sharing plugins: `/peers`. Pair with **Generate a fresh code**.
- Computer check for IT: `/capabilities`, linked from Settings, Advanced,
  Record as "Computer check (for IT)". Test connection for a saved AI:
  **Test** on its row in Settings, Your AI.
- The older twenty-step platform tour, kept for reference:
  `docs/demo/platform-tour-2026-11.md`, proven by
  `python tools/demo_walkthrough.py`.
