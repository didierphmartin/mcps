import json
import re


def run(input, call_tool):
    job = job_of(input)
    if job is None:
        return {"route": "error", "output": "no Job: line in the playbook's output"}
    name = job.get("number") or job["task"]
    try:
        call_tool("servicenow", "complete_job", {"task": job["task"], "notes": summary_of(input)})
    except Exception as e:
        # the playbook handed the task back itself, or someone else took it
        if error_code(e) in ("task_not_found", "not_claimed"):
            return {"route": "already_handed_back", "output": f"{name}: {e}"}
        return {"route": "error", "output": f"{name}: {e}"}
    return {"route": "closed", "output": f"{name} closed by SynergyAI."}


def summary_of(text):
    """The playbook's resolve summary (its ## Result section), else the transcript's last line; <= 4000 chars."""
    text = str(text or "")
    m = re.search(r"## Result\n(.*?)(?:\n\n\[playbook run |\n\nJob: |\Z)", text, re.S)
    summary = m.group(1).strip() if m else ""
    if not summary:
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("Job: ")]
        summary = lines[-1] if lines else "Completed by SynergyAI."
    return summary[:4000]


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
