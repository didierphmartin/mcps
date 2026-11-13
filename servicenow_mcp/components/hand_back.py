import json

HUMAN_GROUP = "Service Desk"   # default; the group a job goes back to when the playbook did not finish


def run(input, call_tool):
    group = (globals().get("ARGS") or {}).get("group", HUMAN_GROUP)
    job = job_of(input)
    if job is None:
        return {"route": "error", "output": "no Job: line in the playbook's output"}
    name = job.get("number") or job["task"]
    reason = ("SynergyAI could not finish: " + reason_of(input))[:4000]
    try:
        call_tool("servicenow", "hand_back", {"task": job["task"], "group": group, "reason": reason})
    except Exception as e:
        # no longer a SynergyAI task: the playbook (or someone) already handed it back
        if error_code(e) == "task_not_found":
            return {"route": "handed_back", "output": f"{name} was already handed back: {e}"}
        return {"route": "error", "output": f"{name}: {e}"}
    return {"route": "handed_back", "output": f"{name} handed back to {group}: {reason}"}


def reason_of(text):
    """The reason on the "Playbook failed: <reason>" line."""
    for line in str(text or "").splitlines():
        if line.startswith("Playbook failed: "):
            return line[len("Playbook failed: "):].strip()
    return "the playbook did not finish"


def job_of(text):
    """The job the Playbook node ran for: the last "Job: {...}" line of its output."""
    for line in reversed(str(text or "").splitlines()):
        if line.startswith("Job: "):
            try:
                job = json.loads(line[5:])
            except ValueError:
                return None
            return job if isinstance(job, dict) and job.get("task") else None
    return None


def error_code(e):
    """'servicenow.complete_job: not_claimed: ...' -> 'not_claimed'."""
    rest = str(e).split(": ", 1)[-1]
    return rest.split(":", 1)[0].strip()
