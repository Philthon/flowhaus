"""Generic adapter for a script that leaves one folder per run.

    folder_runs:
      path: ~/scripts/exports                # where the run folders are
      pattern: '^\\d{4}-\\d\\d-\\d\\d_\\d\\d-\\d\\d-\\d\\d$'   # which sub-folders are runs (regex on the name)
      time_format: '%Y-%m-%d_%H-%M-%S'       # read the start time from the name (else: folder time)
      input: orders.csv                      # file(s) shown as "what came in"
      output: 'invoices*.csv'                # file(s) shown as "what came out"
      preview_words: 0                       # opening words of text outputs to show (0 = never)
      log: log.txt                           # optional: the run's own log; its last error line explains a failure
    map:
      steps:
        - {id: pull_orders, label: Pull orders, ..., produces: orders.csv, count: rows, show: [size]}
        - {id: make_invoices, label: Make invoices, ..., produces: 'invoices*.csv', count: rows}

`count` is what a step's number means: files (default), rows (CSV lines minus the header), lines or words.

A step succeeded in a run when its `produces` glob matches a file in that run folder. The run
failed when a step after the first produced nothing. Only file metadata is read (size, time,
WAV length, word count); text is read only for `preview_words`.
"""

from __future__ import annotations

import re
import wave
from datetime import datetime
from pathlib import Path

from server.automations.base import Automation, empty_node, expand, group_results, run_totals

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log", ".srt", ".vtt"}


def _duration(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


def _words(path: Path) -> int | None:
    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 50_000_000:
        return None
    return len(path.read_text(errors="replace").split())


def count_in(path: Path, what: str) -> int | None:
    """How many items a file holds: rows (CSV/TSV without the header), lines or words."""
    if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix.lower() != ".tsv" or path.stat().st_size > 50_000_000:
        return None
    if what == "words":
        return _words(path)
    with path.open(errors="replace") as f:
        n = sum(1 for line in f if line.strip())
    return max(0, n - 1) if what == "rows" else n


ERROR_LINE = re.compile(r"\b(error|exception|failed|traceback|quota|denied|refused|timed? ?out)\b", re.I)


def describe_file(path: Path, show: list[str]) -> dict:
    row = {"file": path.name}
    if "size" in show:
        size = path.stat().st_size
        row["size"] = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.1f} KB"
    if "duration" in show and (d := _duration(path)) is not None:
        row["length"] = f"{d / 60:.1f} min"
    if "words" in show and (w := _words(path)) is not None:
        row["words"] = w
    if "lines" in show and path.suffix.lower() in TEXT_SUFFIXES:
        row["lines"] = sum(1 for _ in path.open(errors="replace"))
    if "modified" in show:
        row["saved"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ", timespec="minutes")
    return row


class FolderRunsAutomation(Automation):
    extra_keys = {"folder_runs"}
    step_keys = {"produces", "show", "count"}
    def __init__(self, config: dict, folder: Path):
        super().__init__(config, folder)
        fr = config.get("folder_runs") or {}
        self.runs_dir = expand(fr.get("path"), self.local_path() or folder)
        self.pattern = re.compile(fr.get("pattern") or r".+")
        self.time_format = fr.get("time_format")
        self.input_glob = fr.get("input")
        self.output_glob = fr.get("output")
        self.preview_words = int(fr.get("preview_words", 0))
        self.log_glob = fr.get("log")
        self._counted: dict[tuple, dict] = {}

    def source_label(self) -> str:
        return "this computer"

    def meta(self) -> dict:
        m = super().meta()
        scheduled = (self.config.get("trigger") or {}).get("type") == "schedule"
        m.update({"state_label": self.config.get("state_label") or ("Runs on its schedule" if scheduled else "Runs when you start it"),
                  "next_run": self.config.get("next_run") or ("On its schedule" if scheduled else "When you next run it")})
        return m

    def _log_reason(self, folder: Path) -> str | None:
        """The last error-looking line of the run's own log, if it has one (a short, plain hint, not the whole log)."""
        if not self.log_glob:
            return None
        for f in sorted(folder.glob(self.log_glob)):
            if f.stat().st_size > 20_000_000:
                continue
            lines = [line.strip() for line in f.read_text(errors="replace").splitlines() if ERROR_LINE.search(line)]
            if lines:
                return lines[-1][:240]
        return None

    def private_paths(self) -> list[Path]:
        # run folders often hold personal data (recordings, exports): never readable by the agent
        return [*super().private_paths(), *([self.runs_dir] if self.runs_dir else [])]

    def _folders(self) -> list[Path]:
        if not self.runs_dir or not self.runs_dir.is_dir():
            return []
        return sorted((p for p in self.runs_dir.iterdir() if p.is_dir() and self.pattern.search(p.name)), reverse=True)

    def _started(self, folder: Path) -> datetime:
        if self.time_format:
            try:
                return datetime.strptime(folder.name, self.time_format)
            except ValueError:
                pass
        return datetime.fromtimestamp(folder.stat().st_mtime)

    def _produced(self, folder: Path, step: dict) -> list[Path]:
        glob = step.get("produces")
        return sorted(folder.glob(glob)) if glob else []

    def _summary(self, folder: Path) -> dict:
        produced = {s["id"]: self._produced(folder, s) for s in self.steps}
        files = [f for fs in produced.values() for f in fs]
        failed_step = next((s["id"] for s in self.steps[1:] if s.get("produces") and not produced[s["id"]]), None)
        if self.steps and self.steps[0].get("produces") and not produced[self.steps[0]["id"]]:
            failed_step = self.steps[0]["id"]
        label = next((s["label"] for s in self.steps if s["id"] == failed_step), "")
        finished = max((f.stat().st_mtime for f in files), default=None)
        message = None
        if failed_step:
            reason = self._log_reason(folder)
            message = f"“{label}” produced nothing in this run." + (f" The run's log says: {reason}" if reason else "")
        trigger = "schedule" if (self.config.get("trigger") or {}).get("type") == "schedule" else "manual"
        return {"run_id": folder.name, "flow_id": self.id, "status": "failed" if failed_step else "success",
                "started_at": self._started(folder).isoformat(timespec="seconds"),
                "finished_at": datetime.fromtimestamp(finished).isoformat(timespec="seconds") if finished else None,
                "input_file": "folder", "trigger": trigger,
                "error": {"node_id": failed_step, "message": message} if failed_step else None,
                "summary": None}

    def list_runs(self) -> list[dict]:
        out = []
        for f in self._folders():
            key = (f.name, f.stat().st_mtime_ns)  # a run folder changes when files are added: recount then
            if key not in self._counted:
                run = self.get_run(f.name) or self._summary(f)
                self._counted[key] = {k: v for k, v in run.items() if k not in ("nodes", "groups", "contacts",
                                                                                  "input_items", "output_items")}
            out.append(self._counted[key])
        return out

    def get_run(self, run_id: str) -> dict | None:
        if not self.runs_dir or "/" in run_id or run_id.startswith(".") or not self.pattern.search(run_id):
            return None
        folder = self.runs_dir / run_id
        if not folder.is_dir():
            return None
        summary = self._summary(folder)
        nodes, prev_ok, prev_out, prev_what = {}, True, None, None
        for step in self.steps:
            n = empty_node(step)
            files = self._produced(folder, step)
            show = step.get("show") or ["size"]
            if files:
                n["status"] = "success"
                n["sample_out"] = [{"_row_id": i + 1, **describe_file(f, show)} for i, f in enumerate(files)]
                # what the step's number means: files (default), rows, lines or words (`show: [words]` implies words)
                what = step.get("count") or ("words" if "words" in show else "files")
                if what == "files":
                    n["rows_out"] = len(files)
                else:
                    counts = [c for f in files if (c := count_in(f, what)) is not None]
                    n["rows_out"] = sum(counts) if counts else len(files)
                    n["unit"] = step.get("unit") or (what if what in ("words", "lines") else None)
                n["rows_in"] = prev_out if prev_out is not None else n["rows_out"]
                if what == prev_what and n["rows_in"] > n["rows_out"]:  # same kind of item: the rest was dropped
                    n["rows_rejected"] = n["rows_in"] - n["rows_out"]
                prev_out, prev_what = n["rows_out"], what
                n["log"] = [{"level": "info", "text": f"Saved {f.name}"} for f in files]
            elif step.get("produces"):
                n["status"] = "failed" if prev_ok else "not_run"
                if prev_ok:
                    n["error"] = {"message": f"No file matching “{step['produces']}” was saved.", "type": "RunError", "traceback": ""}
            prev_ok = prev_ok and n["status"] == "success"
            nodes[step["id"]] = n

        def items(glob: str | None, preview: bool) -> list[dict]:
            out = []
            for f in sorted(folder.glob(glob)) if glob else []:
                row = {"_row_id": len(out) + 1, **describe_file(f, ["size", "duration", "words"])}
                if preview and self.preview_words and f.suffix.lower() in TEXT_SUFFIXES:
                    words = f.read_text(errors="replace").split()
                    row["opening words"] = " ".join(words[: self.preview_words]) + ("…" if len(words) > self.preview_words else "")
                out.append(row)
            return out

        summary["summary"] = run_totals(self.steps, nodes, self.config.get("io"))
        return {**summary, "nodes": nodes, "groups": group_results(self.groups, self.steps, nodes), "contacts": [],
                "input_items": items(self.input_glob, False), "output_items": items(self.output_glob, True) or None}

    def agent_context(self, run: dict | None) -> dict:
        ctx = super().agent_context(run)
        if ctx.get("run_being_viewed"):  # never send file previews (personal content) to the model
            for step in ctx["run_being_viewed"]["steps"].values():
                step.pop("sample_out", None)
        return ctx

    def check(self) -> list[str]:
        from server.automations.base import unknown_keys

        problems = super().check()
        problems += unknown_keys("folder_runs", self.config.get("folder_runs") or {},
                                 {"path", "pattern", "time_format", "input", "output", "preview_words", "log"})
        for s in self.steps:
            if s.get("count") not in (None, "files", "rows", "lines", "words"):
                problems.append(f"Step '{s['id']}': count must be files, rows, lines or words")
        if not self.runs_dir or not self.runs_dir.is_dir():
            problems.append(f"folder_runs.path does not exist: {(self.config.get('folder_runs') or {}).get('path')}")
        elif not self._folders():
            problems.append("No run folders match folder_runs.pattern")
        if not any(s.get("produces") for s in self.steps):
            problems.append("No step has `produces`, so no step can show success or failure")
        return problems
