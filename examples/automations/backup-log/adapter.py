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
                "error": {"node_id": "copy" if rec.get("error") else "verify",
                          "message": rec.get("error") or f"{rec['copied'] - rec['verified']} copies did not match."}
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
        counts = {"find_new": (rec["found"], rec["found"], {}),
                  "copy": (rec["found"], rec["copied"], {"Can't be read": rec["unreadable"]} if rec["unreadable"] else {}),
                  "verify": (rec["copied"], rec["verified"],
                             {"Checksum differs": rec["copied"] - rec["verified"]} if rec["verified"] < rec["copied"] else {})}
        nodes = {}
        for step in self.steps:
            n = empty_node(step)
            n_in, n_out, reasons = counts[step["id"]]
            failed_here = summary["error"] and summary["error"]["node_id"] == step["id"]
            n.update(status="failed" if failed_here else "success", rows_in=n_in, rows_out=n_out,
                     rows_rejected=sum(reasons.values()), reject_reasons=reasons,
                     error={"message": summary["error"]["message"], "type": "RunError", "traceback": ""} if failed_here else None)
            nodes[step["id"]] = n
            if failed_here:
                break
        for step in self.steps:
            nodes.setdefault(step["id"], empty_node(step))
        return {**summary, "nodes": nodes, "groups": group_results(self.groups, self.steps, nodes), "contacts": [],
                "input_items": [], "output_items": None}


def create(config: dict, folder: Path) -> Automation:
    return BackupLog(config, folder)
