
import json, subprocess, sys, time
base = r"D:/20-projects/Personal Agents/.worktrees/plugin-marketplace"
d = base + "/docs/tickets/2026-11-15-plugin-marketplace"
plan = json.load(open(d + "/plan.json", encoding="utf-8"))

def gh(args, check=True):
    r = subprocess.run(["gh"] + args, cwd=base, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        print("FAIL", args, r.stdout, r.stderr); sys.exit(1)
    return r.stdout.strip()

created = {}
for t in plan:
    num = f"{t['n']:02d}"
    title = f"T{t['n']}: {t['title']}"
    url = gh(["issue","create","--title",title,"--body-file",f"{d}/T{num}.md","--label","ready-for-agent"])
    n = int(url.rsplit("/",1)[1])
    created[t["n"]] = {"number": n, "url": url, "title": title, "blockers": t["blockers"]}
    print(f"T{t['n']} -> #{n} {url}", flush=True)
    time.sleep(1)

# database ids
for t in plan:
    c = created[t["n"]]
    c["id"] = int(gh(["api", f"repos/kanitmann01/agent-desk/issues/{c['number']}", "--jq", ".id"]))

for t in plan:
    child = created[t["n"]]
    for b in t["blockers"]:
        gh(["api","--method","POST",f"repos/kanitmann01/agent-desk/issues/{child['number']}/dependencies/blocked_by","-F",f"issue_id={created[b]['id']}"])
        print(f"edge T{b} -> T{t['n']}", flush=True)

print("VERIFY")
for t in plan:
    child = created[t["n"]]
    out = gh(["api",f"repos/kanitmann01/agent-desk/issues/{child['number']}/dependencies/blocked_by","--jq","[.[].number]|sort|join(\",\")"], check=False)
    expect = ",".join(str(created[b]["number"]) for b in sorted(t["blockers"]))
    print(f"T{t['n']} #{child['number']} blocked_by=[{out}] expected=[{expect}] {'OK' if out==expect else 'MISMATCH'}", flush=True)

json.dump(created, open(d + "/created.json","w",encoding="utf-8"), indent=2)
print("done")
