import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("link", pathlib.Path(__file__).with_name("link-discussions.py"))
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)
Failure = link.Failure


def discussion(number, closed=False, comments=()):
    return {
        "id": f"D{number}",
        "closed": closed,
        "comments": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(comments)},
    }


class API:
    """Fake GitHub client: REST paths map to responses; unknown issue paths 404."""

    def __init__(self, pull, issues=(), discussions=None):
        self.pull = pull
        self.issues = set(issues)
        self.discussions = discussions or {}
        self.writes = []

    def api(self, path, method="GET", data=None):
        if path == f"repos/acme/tool/pulls/{self.pull['number']}":
            return self.pull
        number = int(path.rsplit("/", 1)[1])
        if number in self.issues:
            return {"number": number}
        raise Failure(f"{path}: HTTP 404", 404)

    def gql(self, query, **values):
        if "mutation" in query:
            self.writes.append(("close" if "closeDiscussion" in query else "comment", values))
            return {}
        return {"repository": {"discussion": self.discussions.get(values["number"])}}


def pull(body, merged=True):
    return {
        "number": 99,
        "title": "Add the thing",
        "html_url": "https://github.com/acme/tool/pull/99",
        "merged_at": "2026-01-01T00:00:00Z" if merged else None,
        "body": body,
    }


def run(api, dry=False):
    log = []
    link.link(api, "acme/tool", 99, dry, "github-actions[bot]", out=log.append)
    return log


class TargetTests(unittest.TestCase):
    def targets(self, body):
        return link.targets(body, "acme", "tool")

    def test_closing_and_reference_keywords(self):
        body = "Closes #1\nFixes: discussion #2\nRefs #3\nDiscussion: #4\nfrom discussion #5"
        self.assertEqual(self.targets(body), [(1, True), (2, True), (3, False), (4, False), (5, False)])

    def test_closing_wins_over_reference(self):
        self.assertEqual(self.targets("Refs #7\nCloses #7"), [(7, True)])

    def test_same_repo_urls_only(self):
        body = """Fixes https://github.com/acme/tool/discussions/10
Refs https://github.com/ACME/Tool/issues/11
Fixes https://github.com/other/tool/discussions/12
Refs https://github.com/acme/other/discussions/13"""
        self.assertEqual(self.targets(body), [(10, True), (11, False)])

    def test_code_comments_and_quotes_are_ignored(self):
        body = """<!-- Fixes #1 -->
```
Fixes #2
```
~~~
Refs #3
~~~
`Fixes #4` ``Refs #5``
    Fixes #6
> Closes #7
Closes #8"""
        self.assertEqual(self.targets(body), [(8, True)])

    def test_closing_matches_release_script(self):
        body = "Fixes #1\nResolves: https://github.com/acme/tool/discussions/2\n> Fixes #3"
        closing = [n for n, close in self.targets(body) if close]
        self.assertEqual(closing, link.release.refs(body, "acme", "tool"))


class LinkTests(unittest.TestCase):
    def test_comments_and_closes_open_discussion(self):
        api = API(pull("Fixes #5"), discussions={5: discussion(5)})
        run(api)
        self.assertEqual(api.writes, [
            ("comment", {"id": "D5", "body": "<!-- link-discussions:#99 -->\nImplemented in [#99](https://github.com/acme/tool/pull/99): Add the thing"}),
            ("close", {"id": "D5"}),
        ])

    def test_reference_only_comments_without_closing(self):
        api = API(pull("Refs #5"), discussions={5: discussion(5)})
        run(api)
        self.assertEqual([kind for kind, _ in api.writes], ["comment"])

    def test_already_closed_discussion_is_not_closed_again(self):
        api = API(pull("Fixes #5"), discussions={5: discussion(5, closed=True)})
        run(api)
        self.assertEqual([kind for kind, _ in api.writes], ["comment"])

    def test_rerun_does_not_comment_twice(self):
        posted = {"author": {"login": "github-actions"}, "body": "<!-- link-discussions:#99 -->\nImplemented"}
        api = API(pull("Fixes #5"), discussions={5: discussion(5, closed=True, comments=[posted])})
        run(api)
        self.assertEqual(api.writes, [])

    def test_marker_from_another_author_is_not_trusted(self):
        spoof = {"author": {"login": "someone"}, "body": "<!-- link-discussions:#99 -->"}
        api = API(pull("Refs #5"), discussions={5: discussion(5, comments=[spoof])})
        run(api)
        self.assertEqual([kind for kind, _ in api.writes], ["comment"])

    def test_issues_and_pull_requests_are_skipped(self):
        api = API(pull("Fixes #5\nRefs #6"), issues={5, 6})
        log = run(api)
        self.assertEqual(api.writes, [])
        self.assertIn("skip #5: not a discussion", log)

    def test_unmerged_pull_request_does_nothing(self):
        api = API(pull("Fixes #5", merged=False), discussions={5: discussion(5)})
        run(api)
        self.assertEqual(api.writes, [])

    def test_dry_run_writes_nothing(self):
        api = API(pull("Fixes #5"), discussions={5: discussion(5)})
        log = run(api, dry=True)
        self.assertEqual(api.writes, [])
        self.assertIn("[dry run] would close discussion #5", log)

    def test_one_failure_does_not_stop_other_discussions(self):
        api = API(pull("Fixes #5\nFixes #6"), discussions={6: discussion(6)})
        api.api = lambda path, method="GET", data=None, orig=api.api: (
            (_ for _ in ()).throw(Failure("boom", 500)) if path.endswith("/issues/5") else orig(path, method, data))
        with self.assertRaisesRegex(Failure, "#5: boom"):
            run(api)
        self.assertEqual([kind for kind, _ in api.writes], ["comment", "close"])


if __name__ == "__main__":
    unittest.main()
