"""Example custom adapter: one JSON line per run in a log file.

Implement list_runs() and get_run() and return dicts in the app's run shape (see
server/automations/base.py). Everything else (map, meta, checks) comes from the base class.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.automations.base import Automation, empty_node, expand, group_results


class BackupLog(Automation):
    def __init__(self, config: dict, folder: Path):
        super().__init__(config, folder)
        self.log_file = expand(config.get("log_file", "backup.jsonl"), folder)

    def _lines(self) -> list[dict]:
        if not self.log_file or not self.log_file.exists():
            return []
        return [json.loads(line) for line in self.log_file.read_text().splitlines() if line.strip()]

    def _summary(self, rec: dict) -> dict:
        failed = bool(rec.get("error")) or rec["verified"] < rec["copied"]
        return {"run_id": rec["run"].replace(":", "-"), "flow_id": self.id, "status": "failed" if failed else "success",
                "started_at": rec["run"], "finished_at": rec.get("finished"), "trigger": "schedule",
                "input_file": "photos",
                "error": {"node_id": "drive_ok" if rec.get("error") else "all_match",
                          "message": rec.get("error") or (lambda n: f"{n} {'copy' if n == 1 else 'copies'} didn't match the original.")(rec["copied"] - rec["verified"])}
                if failed else None,
                "summary": {"rows_read": rec["found"], "rows_written": rec["verified"],
                            "rows_rejected": rec["found"] - rec["verified"]}}

    def list_runs(self) -> list[dict]:
        return [self._summary(r) for r in reversed(self._lines())]

    def get_run(self, run_id: str) -> dict | None:
        rec = next((r for r in self._lines() if r["run"].replace(":", "-") == run_id), None)
        if rec is None:
            return None
        summary = self._summary(rec)
        mounted = not rec.get("error")
        differ = rec["copied"] - rec["verified"]
        # (status, in, out, skip reasons) per step; steps on the path this run didn't take stay "not run"
        took = {"find_new": ("success", rec["found"], rec["found"], {}), "drive_ok": ("success", None, None, {})}
        if not mounted:
            took.update(retry=("success", rec["found"], rec["found"], {}), stopped=("success", None, None, {}))
        else:
            took["copy"] = ("success", rec["found"], rec["copied"], {"Can't be read": rec["unreadable"]} if rec["unreadable"] else {})
            took["verify"] = ("success", rec["copied"], rec["copied"], {})
            took["all_match"] = ("success", None, None, {})
            took.update({"done": ("success", None, None, {})} if differ == 0 else
                        {"review": ("success", differ, differ, {}), "flagged": ("success", None, None, {})})
        nodes = {}
        for step in self.steps:
            n = empty_node(step)
            if step["id"] in took:
                status, n_in, n_out, reasons = took[step["id"]]
                n.update(status=status, rows_in=n_in, rows_out=n_out, rows_rejected=sum(reasons.values()), reject_reasons=reasons)
            nodes[step["id"]] = n
        # the step the run's error names is where it failed: show it as failed, with the reason (the path after it,
        # e.g. waiting and stopping, still shows what happened next)
        if (error := summary.get("error")) and error.get("node_id") in nodes:
            nodes[error["node_id"]].update(status="failed", error={"message": error["message"], "type": "RunError",
                                                                    "traceback": ""})
        return {**summary, "nodes": nodes, "groups": group_results(self.groups, self.steps, nodes), "contacts": [],
                "input_items": [], "output_items": None}


def create(config: dict, folder: Path) -> Automation:
    return BackupLog(config, folder)
