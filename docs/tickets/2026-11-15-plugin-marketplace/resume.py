
import json, subprocess, sys, time
base = r"D:/20-projects/Personal Agents/.worktrees/plugin-marketplace"
d = base + "/docs/tickets/2026-11-15-plugin-marketplace"
plan = json.load(open(d + "/plan.json", encoding="utf-8"))

def gh(args, check=True, tries=5):
    last = None
    for i in range(tries):
        r = subprocess.run(["gh"] + args, cwd=base, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            return r.stdout.strip()
        last = (r.stdout, r.stderr)
        time.sleep(2 + 2*i)
    if check:
        print("FAIL", args, last); sys.exit(1)
    return ""

created = {}
for t in plan:
    n = t["n"]; num = 98 + n - 1
    title = gh(["api", f"repos/kanitmann01/agent-desk/issues/{num}", "--jq", ".title"])
    if not title.startswith(f"T{n}:"):
        print("TITLE MISMATCH", n, num, title); sys.exit(1)
    created[n] = {"number": num, "title": title, "blockers": t["blockers"], "id": int(gh(["api", f"repos/kanitmann01/agent-desk/issues/{num}", "--jq", ".id"]))}
    print(f"T{n} #{num} id={created[n]['id']} {title}", flush=True)

existing = {}
for t in plan:
    child = created[t["n"]]
    raw = gh(["api", f"repos/kanitmann01/agent-desk/issues/{child['number']}/dependencies/blocked_by", "--jq", "[.[].number]|sort|join(\",\")"])
    existing[t["n"]] = [int(x) for x in raw.split(",") if x]
    print(f"T{t['n']} existing blocked_by={existing[t['n']]}", flush=True)

for t in plan:
    child = created[t["n"]]
    for b in t["blockers"]:
        if created[b]["number"] in existing[t["n"]]:
            continue
        gh(["api","--method","POST",f"repos/kanitmann01/agent-desk/issues/{child['number']}/dependencies/blocked_by","-F",f"issue_id={created[b]['id']}"])
        print(f"edge T{b} -> T{t['n']}", flush=True)

print("VERIFY")
bad = 0
for t in plan:
    child = created[t["n"]]
    out = gh(["api",f"repos/kanitmann01/agent-desk/issues/{child['number']}/dependencies/blocked_by","--jq","[.[].number]|sort|join(\",\")"])
    got = [int(x) for x in out.split(",") if x]
    expect = sorted(created[b]["number"] for b in t["blockers"])
    ok = got == expect
    if not ok: bad += 1
    print(f"T{t['n']} #{child['number']} got={got} expected={expect} {'OK' if ok else 'MISMATCH'}", flush=True)
json.dump(created, open(d + "/created.json","w",encoding="utf-8"), indent=2)
print("bad", bad)
