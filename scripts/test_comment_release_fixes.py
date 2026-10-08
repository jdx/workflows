import importlib.util
import pathlib
import re
import unittest

spec = importlib.util.spec_from_file_location("release", pathlib.Path(__file__).with_name("comment-release-fixes.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class API:
    def __init__(self, responses=None, discussions=None):
        self.responses = responses or {}
        self.discussions = discussions or {}
        self.calls = []

    def api(self, path, method="GET", data=None):
        self.calls.append((path, method, data))
        response = self.responses.get(path, self.responses.get(path.split("?")[0], []))
        if callable(response):
            return response(path, method, data)
        if isinstance(response, Exception):
            raise response
        return response

    def gql(self, query, **values):
        self.calls.append(("graphql", "POST", values))
        if "addDiscussionComment" in query:
            return {}
        item = self.discussions.get(values["number"])
        return {"repository": {"discussion": item}}


def release_fixture(pulls, issues=None, discussions=None):
    responses = {
        "user": {"login": "automation-user"},
        "repos/acme/tool/releases?per_page=100&page=1": [
            {"tag_name": "v2", "draft": False, "prerelease": False},
            {"tag_name": "v1", "draft": False, "prerelease": False},
        ],
        "repos/acme/tool/compare/v1...v2?per_page=1": {"status": "ahead", "ahead_by": len(pulls)},
        "repos/acme/tool/compare/v1...v2?per_page=100&page=1": {
            "commits": [{"sha": p["merge_commit_sha"], "commit": {"message": f"x (#{p['number']})"}} for p in pulls]
        },
    }
    for pull in pulls:
        responses[f"repos/acme/tool/pulls/{pull['number']}"] = pull
    responses.update(issues or {})
    return API(responses, discussions)


class ReleaseTests(unittest.TestCase):
    def test_template_and_full_url_refs_exclude_all_code_examples(self):
        body = """Fixes #12
Resolves https://github.com/acme/tool/discussions/13
`Fixes #14`
    Fixes #15
> Fixes #16
~~~
Fixes #17
~~~
Fixes https://github.com/other/tool/issues/18"""
        self.assertEqual(release.refs(body, "acme", "tool"), [12, 13])

    def test_four_backtick_double_and_multiline_inline_examples_are_ignored(self):
        body = """Fixes #1
````markdown
Fixes #2
```
still an example
````
``Fixes #3``
`Fixes
#4`"""
        self.assertEqual(release.refs(body, "acme", "tool"), [1])

    def test_interleaved_tags_choose_closest_ancestor_not_list_order(self):
        api = API({
            "repos/acme/tool/releases?per_page=100&page=1": [
                {"tag_name": "v3", "draft": False, "prerelease": False},
                {"tag_name": "v1", "draft": False, "prerelease": False},
                {"tag_name": "v2", "draft": False, "prerelease": False},
                {"tag_name": "v2-alias", "draft": False, "prerelease": False},
            ],
            "repos/acme/tool/compare/v1...v3?per_page=1": {"status": "ahead", "ahead_by": 9},
            "repos/acme/tool/compare/v2...v3?per_page=1": {"status": "ahead", "ahead_by": 2},
            "repos/acme/tool/compare/v2-alias...v3?per_page=1": {"status": "identical", "ahead_by": 0},
        })
        self.assertEqual(release.base_release(api, "acme/tool", "v3", re.compile(r"^v.*")), "v2")

    def test_missing_and_uncomparable_tags_fail_closed(self):
        missing = API({"repos/acme/tool/releases?per_page=100&page=1": [{"tag_name": "v1", "draft": False, "prerelease": False}]})
        with self.assertRaisesRegex(release.Failure, "not a stable"):
            release.base_release(missing, "acme/tool", "v2", re.compile(r"^v.*"))
        blocked = API({
            "repos/acme/tool/releases?per_page=100&page=1": [{"tag_name": "v2", "draft": False, "prerelease": False}, {"tag_name": "v1", "draft": False, "prerelease": False}],
            "repos/acme/tool/compare/v1...v2?per_page=1": release.Failure("404 tag missing"),
        })
        with self.assertRaisesRegex(release.Failure, "cannot safely"):
            release.base_release(blocked, "acme/tool", "v2", re.compile(r"^v.*"))

    def test_paginated_comparison_and_only_verified_merged_prs_ship(self):
        api = API({
            "repos/acme/tool/compare/v1...v2?per_page=100&page=1": {"commits": [{"sha": "m", "commit": {"message": "x (#1)"}}] * 100},
            "repos/acme/tool/compare/v1...v2?per_page=100&page=2": {"commits": [{"sha": "last", "commit": {"message": "x (#2)"}}]},
            "repos/acme/tool/pulls/1": {"number": 1, "merged_at": "yes", "merge_commit_sha": "m"},
            "repos/acme/tool/pulls/2": {"number": 2, "merged_at": None, "merge_commit_sha": "last"},
        })
        changes = release.commits(api, "acme/tool", "v1", "v2")
        self.assertEqual(len(changes), 101)
        self.assertEqual([p["number"] for p in release.shipped_prs(api, "acme/tool", changes)], [1])

    def test_squash_subject_uses_only_terminal_pr_number_and_skips_bad_leads(self):
        api = API({
            "repos/acme/tool/pulls/345": {"number": 345, "merged_at": "yes", "merge_commit_sha": "m"},
        })
        changes = [{"sha": "m", "commit": {"message": "Fix regression (#12) (#345)"}}]
        self.assertEqual([p["number"] for p in release.shipped_prs(api, "acme/tool", changes)], [345])

    def test_issue_dedup_paginates_and_requires_current_token_identity(self):
        api = API({
            "repos/acme/tool/issues/4/comments?per_page=100&page=1": [{"user": {"login": "old-bot"}, "body": "<!-- x:v1 -->"}] * 100,
            "repos/acme/tool/issues/4/comments?per_page=100&page=2": [{"user": {"login": "token-user"}, "body": "<!-- x:v1 -->"}],
        })
        self.assertTrue(release.has_issue_comment(api, "acme/tool", 4, "<!-- x:v1 -->", "token-user"))

    def test_reopened_discussion_is_skipped(self):
        pull = {"number": 1, "merged_at": "yes", "merge_commit_sha": "m", "body": "Fixes discussion #9"}
        api = release_fixture([pull], {"repos/acme/tool/issues/9": release.Failure("404 Not Found")}, {
            9: {"id": "D_9", "closed": False, "comments": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        })
        output = []
        release.notify(api, "acme/tool", "v2", "fixed", "", False, output.append)
        self.assertIn("skip discussion #9: still open", output)
        self.assertFalse(any(path == "graphql" and values.get("id") == "D_9" for path, _, values in api.calls))

    def test_actual_owner_name_is_used_for_discussion_full_url_contract(self):
        pull = {"number": 1, "merged_at": "yes", "merge_commit_sha": "m", "body": "Fixes https://github.com/acme/tool/discussions/9"}
        api = release_fixture([pull], {"repos/acme/tool/issues/9": release.Failure("404 Not Found")}, {
            9: {"id": "D_9", "closed": True, "comments": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        })
        release.notify(api, "acme/tool", "v2", "fixed", "", False, lambda _: None)
        lookups = [values for path, _, values in api.calls if path == "graphql" and "number" in values]
        self.assertEqual(lookups[0]["owner"], "acme")
        self.assertEqual(lookups[0]["repo"], "tool")
        self.assertTrue(any(path == "graphql" and values.get("id") == "D_9" for path, _, values in api.calls))

    def test_partial_failure_then_retry_deduplicates_first_target(self):
        pulls = [
            {"number": 1, "merged_at": "yes", "merge_commit_sha": "m1", "body": "Fixes #2"},
            {"number": 2, "merged_at": "yes", "merge_commit_sha": "m2", "body": "Fixes #3"},
        ]
        state = {"first": False, "second_fails": True, "comments": []}
        def issues(path, method, data):
            if method == "POST": state["comments"].append(data["body"]); return {"id": 1}
            if path.endswith("/issues/2"): return {"state": "closed"}
            if path.endswith("/issues/3"):
                if state["second_fails"]: raise release.Failure("403 private-repo permission denied")
                return {"state": "closed"}
            if "/comments?" in path: return [{"user": {"login": "github-actions[bot]"}, "body": body} for body in state["comments"]] if path.endswith("2/comments?per_page=100&page=1") else []
        api = release_fixture(pulls)
        api.responses.update({
            "repos/acme/tool/issues/2": issues, "repos/acme/tool/issues/3": issues,
            "repos/acme/tool/issues/2/comments": issues, "repos/acme/tool/issues/3/comments": issues,
        })
        with self.assertRaisesRegex(release.Failure, "PR #2"):
            release.notify(api, "acme/tool", "v2", "fixed", "", False, lambda _: None)
        state["second_fails"] = False
        release.notify(api, "acme/tool", "v2", "fixed", "", False, lambda _: None)
        self.assertEqual(len(state["comments"]), 2)

    def test_normal_and_manual_recovery_use_same_dry_run_and_write_no_comments(self):
        pull = {"number": 1, "merged_at": "yes", "merge_commit_sha": "m", "body": "Fixes #2"}
        api = release_fixture([pull], {
            "repos/acme/tool/issues/2": {"state": "closed"},
            "repos/acme/tool/issues/2/comments?per_page=100&page=1": [],
        })
        output = []
        release.notify(api, "acme/tool", "v2", "fixed", "", True, output.append)
        self.assertIn('"dry_run": true', output[0])
        self.assertTrue(any("[dry run] would comment on issue #2" in line for line in output))
        self.assertFalse(any(method == "POST" for _, method, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
