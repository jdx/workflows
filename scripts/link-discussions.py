#!/usr/bin/env python3
"""Comment on, and optionally close, discussions referenced by a merged pull request.

GitHub closes issues named with closing keywords, but not discussions. This
fills that gap. Closing references are parsed by comment-release-fixes.py's
`refs`, so a discussion this closes is the one that later gets the
"Fixed in vX" comment.
"""
import importlib.util, json, os, pathlib, re, sys

_spec = importlib.util.spec_from_file_location("comment_release_fixes", pathlib.Path(__file__).with_name("comment-release-fixes.py"))
release = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(release)
Failure = release.Failure

# Comment-only references: `Refs #N`, `Discussion: #N`, or a same-repository URL.
REFERENCE = re.compile(r"\b(?:ref|refs|reference|references|discussion)[:\s]+(?:(?P<url>https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?:issues|discussions)/(?P<urlnum>[1-9]\d*))|#(?P<num>[1-9]\d*))\b", re.I)
CLOSE = "mutation($id:ID!){closeDiscussion(input:{discussionId:$id,reason:RESOLVED}){discussion{id}}}"

def targets(body, owner, repo):
    """Return [(number, close)]; a closing reference wins over a comment-only one."""
    found = dict.fromkeys(release.refs(body, owner, repo), True)
    for m in REFERENCE.finditer(release.clean(body)):
        if m["num"]: found.setdefault(int(m["num"]), False)
        elif m["owner"].lower()==owner.lower() and m["repo"].lower()==repo.lower(): found.setdefault(int(m["urlnum"]), False)
    return list(found.items())

def mark(pr): return f"<!-- link-discussions:#{pr} -->"

def link(gh, repo, number, dry, actor, out=print):
    owner, name = repo.split("/", 1)
    pr = gh.api(f"repos/{repo}/pulls/{number}")
    if not pr.get("merged_at"): out(f"skip: #{number} is not merged"); return
    found = targets(pr.get("body") or "", owner, name)
    out(json.dumps({"pull": number, "refs": [{"number": n, "close": c} for n, c in found], "dry_run": dry}))
    marker = mark(number)
    body = f"{marker}\nImplemented in [#{number}]({pr['html_url']}): {pr['title']}"
    failures = []
    for n, close in found:
        try:
            try:
                gh.api(f"repos/{repo}/issues/{n}")
                out(f"skip #{n}: not a discussion"); continue
            except Failure as e:
                if e.status != 404: raise
            d = release.get_discussion(gh, owner, name, n)
            if not d: out(f"skip #{n}: not an accessible discussion"); continue
            if any(release.owned((c.get("author") or {}).get("login"), actor) and (c.get("body") or "").split("\n", 1)[0].strip() == marker for c in d["all_comments"]):
                out(f"skip comment on discussion #{n}: already linked")
            elif dry: out(f"[dry run] would comment on discussion #{n}")
            else: gh.gql(release.ADD, id=d["id"], body=body); out(f"commented on discussion #{n}")
            if not close: continue
            if d["closed"]: out(f"discussion #{n} already closed")
            elif dry: out(f"[dry run] would close discussion #{n}")
            else: gh.gql(CLOSE, id=d["id"]); out(f"closed discussion #{n} (RESOLVED)")
        except Exception as e: failures.append(f"#{n}: {e}")
    if failures: raise Failure("discussion link failures:\n" + "\n".join(failures))

if __name__ == "__main__":
    try:
        number = os.environ.get("PR_NUMBER", "")
        if not number.isdigit(): raise Failure("PR_NUMBER must be a pull request number")
        link(release.GH(), os.environ["GITHUB_REPOSITORY"], int(number), os.environ.get("DRY_RUN") == "1",
             os.environ.get("COMMENT_AUTHOR") or "github-actions[bot]")
    except Failure as e: print(f"error: {e}", file=sys.stderr); sys.exit(1)
