import importlib.util, pathlib, re, unittest
spec=importlib.util.spec_from_file_location("r",pathlib.Path(__file__).with_name("comment-release-fixes.py")); r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
class API:
 def __init__(self,x):self.x=x;self.calls=[]
 def api(self,p,method="GET",data=None):
  self.calls.append((p,method,data)); v=self.x.get(p,self.x.get(p.split("?")[0],[]))
  if isinstance(v,Exception):raise v
  return v
 def gql(self,*args,**kw):return {"repository":{"discussion":None}}
class T(unittest.TestCase):
 def test_refs_exclude_examples_and_support_url(self):
  self.assertEqual(r.refs("Fixes #1\nResolves https://github.com/a/b/discussions/2\n`Fixes #3`\n    Fixes #4\n> Fixes #5\n~~~\nFixes #6\n~~~", "a","b"),[1,2])
 def test_tags_use_ancestry_and_exclude_identical(self):
  a=API({"repos/a/b/releases?per_page=100&page=1":[{"tag_name":"v3","draft":False,"prerelease":False},{"tag_name":"v1","draft":False,"prerelease":False},{"tag_name":"v2","draft":False,"prerelease":False},{"tag_name":"v2x","draft":False,"prerelease":False}],"repos/a/b/compare/v1...v3?per_page=1":{"status":"ahead","ahead_by":9},"repos/a/b/compare/v2...v3?per_page=1":{"status":"ahead","ahead_by":2},"repos/a/b/compare/v2x...v3?per_page=1":{"status":"identical","ahead_by":0}})
  self.assertEqual(r.base_release(a,"a/b","v3",re.compile("^v.*")),"v2")
 def test_unmerged_or_missing_merge_commit_not_shipped(self):
  a=API({"repos/a/b/pulls/1":{"number":1,"merged_at":"now","merge_commit_sha":"m"},"repos/a/b/pulls/2":{"number":2,"merged_at":None,"merge_commit_sha":"x"}})
  changes=[{"sha":"m","commit":{"message":"x (#1)"}},{"sha":"x","commit":{"message":"x (#2)"}}]
  self.assertEqual([p["number"] for p in r.shipped_prs(a,"a/b",changes)],[1])
 def test_missing_release_tag_fails_without_widening_range(self):
  a=API({"repos/a/b/releases?per_page=100&page=1":[{"tag_name":"v1","draft":False,"prerelease":False}]})
  with self.assertRaises(r.Failure): r.base_release(a,"a/b","v2",re.compile("^v.*"))
 def test_issue_dedup_paginates_and_uses_current_identity(self):
  a=API({"repos/a/b/issues/1/comments?per_page=100&page=1":[{"user":{"login":"old"},"body":"<!-- x:v -->"}]*100,"repos/a/b/issues/1/comments?per_page=100&page=2":[{"user":{"login":"new"},"body":"<!-- x:v -->"}]})
  self.assertTrue(r.has_issue_comment(a,"a/b",1,"<!-- x:v -->","new"))
 def test_dry_run_reports_historical_metadata_without_writes(self):
  a=API({"user":{"login":"robot"},"repos/a/b/releases?per_page=100&page=1":[{"tag_name":"v2","draft":False,"prerelease":False},{"tag_name":"v1","draft":False,"prerelease":False}],"repos/a/b/compare/v1...v2?per_page=1":{"status":"ahead","ahead_by":1},"repos/a/b/compare/v1...v2?per_page=100&page=1":{"commits":[{"sha":"m","commit":{"message":"x (#1)"}}]},"repos/a/b/pulls/1":{"number":1,"merged_at":"now","merge_commit_sha":"m","body":"Fixes #2"},"repos/a/b/issues/2":{"state":"closed"},"repos/a/b/issues/2/comments?per_page=100&page=1":[]})
  output=[]; r.notify(a,"a/b","v2","fixed","",True,output.append)
  self.assertIn('"base": "v1"',output[0]); self.assertFalse(any(m=="POST" for _,m,_ in a.calls))
if __name__=="__main__":unittest.main()
