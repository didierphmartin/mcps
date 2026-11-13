def run(input, call_tool):
    args = globals().get("ARGS") or {}
    tag = args.get("tag")

    # 1. Oldest open, unclaimed task in the SynergyAI group (only this workflow's tag, when it has one).
    try:
        job = call_tool("servicenow", "poll_jobs", {"tag": tag} if tag else {}).get("job")
    except Exception as e:
        return {"route": "error", "output": f"poll_jobs: {e}"}
    if job is None:
        return {"route": "no_job", "output": None}

    # 2. Claim it before acting, so a second run can't take the same task.
    #    Someone took or closed it in between: stop quietly. Anything else is an error.
    try:
        call_tool("servicenow", "claim_job", {"task": job["task"]})
    except Exception as e:
        if error_code(e) == "not_claimable":
            return {"route": "no_job", "output": f"{job['number']} not claimable: {e}"}
        return {"route": "error", "output": f"{job['number']}: {e}"}

    # 3. The task was made by another version of the automation: give it back to a human.
    wv, jv = args.get("version"), job.get("version")
    if wv and jv and wv != jv:
        job_key = key_of(job.get("tag"))
        reason = f"out of sync: task {job_key}@{jv}, workflow {key_of(tag) or job_key}@{wv}"
        try:
            call_tool("servicenow", "hand_back", {
                "task": job["task"],
                "group": args.get("hand_back_group", "Service Desk"),
                "reason": reason,
            })
        except Exception as e:
            return {"route": "error", "output": f"{job['number']}: {e}"}
        return {"route": "no_job", "output": f"{job['number']} handed back: {reason}"}

    # 4. Hand the job to the Playbook node: the tag names the playbook
    #    (synergyai:okta-reset -> playbook "okta-reset"), the answers are its inputs.
    return {"route": "job", "output": {
        "task": job["task"],
        "number": job["number"],
        "playbook": key_of(job.get("tag")),
        "requested_for": job["requested_for"],
        "answers": {k: v["value"] for k, v in job["answers"].items()},
    }}


def key_of(tag):
    tag = tag or ""
    return tag[len("synergyai:"):] if tag.startswith("synergyai:") else tag


def error_code(e):
    """'servicenow.claim_job: not_claimable: ...' -> 'not_claimable'."""
    rest = str(e).split(": ", 1)[-1]
    return rest.split(":", 1)[0].strip()
