import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, args=None):
    """Exec a component the way the harness does: ARGS is a module global when the node has any."""
    ns = {}
    if args is not None:
        ns["ARGS"] = args
    with open(os.path.join(HERE, "..", name + ".py")) as f:
        exec(compile(f.read(), name, "exec"), ns)
    return ns["run"]


class Tool:
    def __init__(self, job=None, claim_error=None):
        self.job, self.claim_error, self.calls = job, claim_error, []

    def __call__(self, server, tool, args=None):
        self.calls.append((tool, args))
        if tool == "poll_jobs":
            return {"job": self.job}
        if tool == "claim_job" and self.claim_error:
            raise self.claim_error
        return {}

    def named(self, tool):
        return [a for t, a in self.calls if t == tool]


def job(version=2, tag="synergyai:okta"):
    return {"task": "sys1", "number": "SCTASK1", "tag": tag, "version": version,
            "requested_for": "bob", "answers": {"q": {"value": "v"}}}


class GetNewJob(unittest.TestCase):
    def test_equal_version_gives_job(self):
        t = Tool(job(2))
        r = load("get_new_job", {"tag": "synergyai:okta", "version": 2})(None, t)
        self.assertEqual(r["route"], "job")
        self.assertEqual(r["output"], {"task": "sys1", "number": "SCTASK1", "playbook": "okta",
                                       "requested_for": "bob", "answers": {"q": "v"}})
        self.assertEqual(t.named("hand_back"), [])

    def test_differing_version_hands_back(self):
        t = Tool(job(2))
        r = load("get_new_job", {"tag": "synergyai:okta", "version": 3})(None, t)
        self.assertEqual(r["route"], "no_job")
        self.assertEqual(t.named("hand_back"), [{
            "task": "sys1", "group": "Service Desk",
            "reason": "out of sync: task okta@2, workflow okta@3"}])

    def test_hand_back_group_from_args(self):
        t = Tool(job(2))
        load("get_new_job", {"tag": "synergyai:okta", "version": 3, "hand_back_group": "IT"})(None, t)
        self.assertEqual(t.named("hand_back")[0]["group"], "IT")

    def test_job_version_none_gives_job(self):
        t = Tool(job(None))
        r = load("get_new_job", {"tag": "synergyai:okta", "version": 3})(None, t)
        self.assertEqual(r["route"], "job")
        self.assertEqual(t.named("hand_back"), [])

    def test_no_args_polls_everything(self):
        for args in (None, {}):
            t = Tool(job(2))
            r = load("get_new_job", args)(None, t)
            self.assertEqual(t.named("poll_jobs"), [{}])
            self.assertEqual(r["route"], "job")

    def test_tag_is_polled(self):
        t = Tool(None)
        r = load("get_new_job", {"tag": "synergyai:okta"})(None, t)
        self.assertEqual(t.named("poll_jobs"), [{"tag": "synergyai:okta"}])
        self.assertEqual(r["route"], "no_job")

    def test_not_claimable_is_no_job(self):
        t = Tool(job(2), claim_error=Exception("servicenow.claim_job: not_claimable: taken"))
        self.assertEqual(load("get_new_job", {})(None, t)["route"], "no_job")


JOB_LINE = 'Job: {"task": "sys1", "number": "SCTASK1"}'


class HandBack(unittest.TestCase):
    def test_group_from_args(self):
        t = Tool()
        r = load("hand_back", {"group": "Network"})(JOB_LINE + "\nPlaybook failed: boom", t)
        self.assertEqual(r["route"], "handed_back")
        self.assertEqual(t.named("hand_back")[0]["group"], "Network")

    def test_default_group(self):
        for args in (None, {}):
            t = Tool()
            load("hand_back", args)(JOB_LINE, t)
            self.assertEqual(t.named("hand_back")[0]["group"], "Service Desk")


class CompleteJob(unittest.TestCase):
    def test_closes(self):
        t = Tool()
        r = load("complete_job")(JOB_LINE + "\n", t)
        self.assertEqual(r["route"], "closed")
        self.assertEqual(t.named("complete_job")[0]["task"], "sys1")

    def summary_of(self):
        ns = {}
        with open(os.path.join(HERE, "..", "complete_job.py")) as f:
            exec(compile(f.read(), "complete_job", "exec"), ns)
        return ns["summary_of"]

    def test_summary_of_result_section_before_playbook_run(self):
        text = "steps...\n## Result\nPassword reset for bob.\nMFA kept.\n\n[playbook run 12]\n" + JOB_LINE
        self.assertEqual(self.summary_of()(text), "Password reset for bob.\nMFA kept.")

    def test_summary_of_result_section_before_job_line(self):
        text = "## Result\nDone.\n\n" + JOB_LINE
        self.assertEqual(self.summary_of()(text), "Done.")

    def test_summary_of_result_section_at_end(self):
        self.assertEqual(self.summary_of()("x\n## Result\nAll good.  \n"), "All good.")

    def test_summary_of_without_result_is_last_line(self):
        self.assertEqual(self.summary_of()("first\nlast line\n" + JOB_LINE), "last line")
        self.assertEqual(self.summary_of()(""), "Completed by SynergyAI.")

    def test_summary_regex_is_one_line(self):
        # the source is copied into the database; a regex split over lines breaks on any whitespace pass
        with open(os.path.join(HERE, "..", "complete_job.py")) as f:
            src = f.read()
        self.assertIn('r"## Result\\n(.*?)(?:\\n\\n\\[playbook run |\\n\\nJob: |\\Z)"', src)


if __name__ == "__main__":
    unittest.main()
