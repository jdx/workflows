#!/usr/bin/env python3
"""Notify closed, explicit same-repository fixes after a release ships."""
import json, os, re, subprocess, sys

KEYWORD = r"(?:close(?:s|d)?|fix(?:es|ed)?|resolve(?:s|d)?)"
REF = re.compile(rf"\b{KEYWORD}\s*:?\s+(?:discussion\s+)?(?:(?P<url>https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?:issues|discussions)/(?P<urlnum>[1-9]\d*))|#(?P<num>[1-9]\d*))\b", re.I)
SUBJECT = re.compile(r"(?:\(#(?P<squash>[1-9]\d*)\)|Merge pull request #(?P<merge>[1-9]\d*))", re.I)

class Failure(Exception): pass

def clean(body):
    body = re.sub(r"<!--[\s\S]*?-->", "", body or "")
    body = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", "", body)
    return "\n".join(re.sub(r"`[^`]*`", "", l) for l in body.splitlines()
                     if not re.match(r"^(?:\s{4}|\t|\s*>).*", l))

def refs(body, owner, repo):
    result=[]
    for m in REF.finditer(clean(body)):
        if m["num"]: result.append(int(m["num"]))
        elif m["owner"].lower()==owner.lower() and m["repo"].lower()==repo.lower(): result.append(int(m["urlnum"]))
    return list(dict.fromkeys(result))

class GH:
    def api(self, path, method="GET", data=None):
        cmd=["gh","api",path,"-X",method]
        if data is not None: cmd += ["--input","-"]
        r=subprocess.run(cmd,input=json.dumps(data) if data is not None else None,text=True,capture_output=True)
        if r.returncode: raise Failure(f"{path}: {r.stderr.strip() or 'GitHub API request failed'}")
        try: return json.loads(r.stdout)
        except json.JSONDecodeError as e: raise Failure(f"{path}: invalid JSON response") from e
    def gql(self, query, **values):
        cmd=["gh","api","graphql","-f",f"query={query}"]
        for k,v in values.items():
            if v is not None: cmd += ["-F" if isinstance(v,int) else "-f",f"{k}={v}"]
        r=subprocess.run(cmd,text=True,capture_output=True)
        if r.returncode: raise Failure(f"GraphQL: {r.stderr.strip() or 'request failed'}")
        d=json.loads(r.stdout)
        if d.get("errors"): raise Failure("GraphQL: "+"; ".join(x["message"] for x in d["errors"]))
        return d["data"]

def paged(gh, path):
    for page in range(1, 10000):
        items=gh.api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        yield from items
        if len(items)<100: return

def base_release(gh, repo, tag, pattern):
    rs=[r for r in paged(gh,f"repos/{repo}/releases") if not r["draft"] and not r["prerelease"] and pattern.fullmatch(r["tag_name"])]
    if tag not in {r["tag_name"] for r in rs}: raise Failure(f"{tag} is not a stable published release in this tag family")
    choices=[]; errors=[]
    for i,r in enumerate(rs):
        old=r["tag_name"]
        if old==tag: continue
        try: cmp=gh.api(f"repos/{repo}/compare/{old}...{tag}?per_page=1")
        except Failure as e: errors.append(str(e)); continue
        # Identical tag aliases do not represent a fresh shipment.
        if cmp.get("status")=="ahead" and cmp.get("ahead_by",0)>0: choices.append((cmp["ahead_by"],i,old))
    if errors: raise Failure("cannot safely establish release ancestry:\n"+"\n".join(errors))
    if not choices: raise Failure(f"no earlier contained release found for {tag}; refusing to widen the range")
    return min(choices)[2]

def commits(gh, repo, base, tag):
    out=[]
    for page in range(1,10000):
        part=gh.api(f"repos/{repo}/compare/{base}...{tag}?per_page=100&page={page}").get("commits",[]); out+=part
        if len(part)<100:return out

def shipped_prs(gh, repo, changes):
    shas={c["sha"] for c in changes}; nums=set()
    for c in changes:
        m=SUBJECT.search(c.get("commit",{}).get("message","").split("\n",1)[0])
        if m: nums.add(int(m["squash"] or m["merge"]))
    out=[]
    for n in sorted(nums):
        pr=gh.api(f"repos/{repo}/pulls/{n}")
        # Subject syntax is only a lead: require a merged PR and its merge commit
        # in the compared range, preventing unmerged/spoofed PR notifications.
        if pr.get("merged_at") and pr.get("merge_commit_sha") in shas: out.append(pr)
    return out

DISC="""query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){discussion(number:$number){id closed comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{body author{login}}}}}}"""
ADD="mutation($id:ID!,$body:String!){addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id}}}"

def get_discussion(gh, owner, repo, number):
    cursor=None; comments=[]
    while True:
        d=gh.gql(DISC,owner=owner,repo=repo,number=number,cursor=cursor).get("repository",{}).get("discussion")
        if not d:return None
        comments += d["comments"]["nodes"]; pi=d["comments"]["pageInfo"]
        if not pi["hasNextPage"]: return {**d,"all_comments":comments}
        cursor=pi["endCursor"]

def mark(prefix,tag): return f"<!-- {prefix}:{tag} -->"
def text(repo,tag,pr,prefix,upgrade): return f"{mark(prefix,tag)}\nFixed in [{tag}](https://github.com/{repo}/releases/tag/{tag}) by #{pr}."+(f" {upgrade}" if upgrade else "")
def has_issue_comment(gh,repo,num,marker,actor):
    return any(c.get("user",{}).get("login")==actor and marker in (c.get("body") or "") for c in paged(gh,f"repos/{repo}/issues/{num}/comments"))

def notify(gh,repo,tag,prefix,upgrade,dry,out=print):
    owner,_=repo.split("/",1); pattern=re.compile(os.environ.get("TAG_PATTERN",r"^v[0-9][0-9A-Za-z._+-]*$"))
    if not pattern.fullmatch(tag): raise Failure(f"{tag} does not match TAG_PATTERN")
    actor=gh.api("user").get("login")
    if not actor: raise Failure("cannot determine token identity for safe deduplication")
    base=base_release(gh,repo,tag,pattern); changes=commits(gh,repo,base,tag); pulls=shipped_prs(gh,repo,changes)
    out(json.dumps({"tag":tag,"base":base,"commits":len(changes),"pulls":[p["number"] for p in pulls],"dry_run":dry}))
    failures=[]; seen=set()
    for pr in pulls:
      try:
       for n in refs(pr.get("body") or "",owner,repo):
        if n in seen: continue
        body=text(repo,tag,pr["number"],prefix,upgrade); marker=mark(prefix,tag)
        try:
            issue=gh.api(f"repos/{repo}/issues/{n}")
            if issue.get("state")!="closed" or issue.get("pull_request"): out(f"skip issue #{n}: not a closed issue")
            elif has_issue_comment(gh,repo,n,marker,actor): out(f"skip issue #{n}: already commented for {tag}")
            elif dry: out(f"[dry run] would comment on issue #{n} (from #{pr['number']})")
            else: gh.api(f"repos/{repo}/issues/{n}/comments","POST",{"body":body}); out(f"commented on issue #{n} (from #{pr['number']})")
        except Failure as e:
            if "404" not in str(e): raise
            d=get_discussion(gh,owner,repo,n)
            if not d: raise Failure(f"target #{n} is neither an accessible issue nor discussion")
            if not d["closed"]: out(f"skip discussion #{n}: still open")
            elif any(c.get("author",{}).get("login")==actor and marker in (c.get("body") or "") for c in d["all_comments"]): out(f"skip discussion #{n}: already commented for {tag}")
            elif dry: out(f"[dry run] would comment on discussion #{n} (from #{pr['number']})")
            else: gh.gql(ADD,id=d["id"],body=body); out(f"commented on discussion #{n} (from #{pr['number']})")
        seen.add(n)
      except Exception as e: failures.append(f"PR #{pr['number']}: {e}")
    if failures: raise Failure("release notification failures:\n"+"\n".join(failures))

if __name__=="__main__":
 try: notify(GH(),os.environ["GITHUB_REPOSITORY"],os.environ["TAG"],os.environ["MARKER_PREFIX"],os.environ.get("UPGRADE_TEXT",""),os.environ.get("DRY_RUN")=="1")
 except Failure as e: print(f"error: {e}",file=sys.stderr); sys.exit(1)
