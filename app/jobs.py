"""Hàng đợi job đơn giản, lưu trạng thái ra file JSON (khởi động lại server không mất lịch sử)."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import JOBS_DIR, MAX_WORKERS, JobOptions


class Job:
    def __init__(self, jid: str, data: dict | None = None):
        self.id = jid
        self.dir: Path = JOBS_DIR / jid
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._review_evt = threading.Event()
        self._review_result = None
        self.data = data or self._read()

    @property
    def _file(self):
        return self.dir / "job.json"

    def _read(self):
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"id": self.id, "status": "unknown"}

    def save(self):
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._file)

    def update(self, **kw):
        with self._lock:
            self.data.update(kw)
            self.data["updated"] = time.time()
            self.save()

    def begin_review(self):
        self._review_evt.clear()
        self._review_result = None

    def wait_review(self, timeout=None):
        self._review_evt.wait(timeout)
        return self._review_result

    def submit_review(self, result: dict):
        self._review_result = result
        self._review_evt.set()

    def log(self, msg: str):
        print(f"[{self.id}] {msg}", flush=True)
        with self._lock:
            logs = self.data.setdefault("logs", [])
            logs.append(msg)
            del logs[:-300]
            self.save()


class JobManager:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.jobs: dict[str, Job] = {}
        for d in sorted(JOBS_DIR.iterdir()) if JOBS_DIR.exists() else []:
            if (d / "job.json").exists():
                j = Job(d.name)
                if j.data.get("status") in ("queued", "running", "review"):
                    j.update(status="error", error="Server đã khởi động lại khi job đang chạy. Hãy tạo lại.")
                self.jobs[d.name] = j

    def create(self, input_text: str, opts: JobOptions, uploaded: Path | None = None) -> Job:
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        job = Job(jid, {"id": jid, "status": "queued", "input": input_text, "options": opts.to_dict(),
                        "created": time.time(), "progress": 0, "logs": [], "step_label": "Đang chờ"})
        if uploaded:
            uploaded.replace(job.dir / "source.mp4")
            job.data["input"] = input_text or "(file tải lên)"
        job.save()
        self.jobs[jid] = job
        self.pool.submit(self._run, job, opts)
        return job

    def _run(self, job: Job, opts: JobOptions):
        from .pipeline import process
        job.update(status="running", started=time.time())
        try:
            process(job, opts)
            job.update(status="done", finished=time.time())
            job.log("✅ Xong!")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.log("❌ " + str(e)[:500])
            job.update(status="error", error=str(e)[:1000], finished=time.time())

    def rerender(self, jid: str, decision: dict) -> bool:
        j = self.jobs.get(jid)
        if not j or j.data.get("status") != "done" or not (j.dir / "render_state.pkl").exists():
            return False
        j.update(status="queued", step_label="Chờ xuất lại", rerender_error=None)
        self.pool.submit(self._rerun, j, decision)
        return True

    def _rerun(self, job: Job, decision: dict):
        from .pipeline import rerender
        try:
            rerender(job, decision)
            job.log("✅ Đã xuất lại xong!")
            job.update(status="done", finished=time.time())
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.log("❌ Xuất lại lỗi: " + str(e)[:300])
            # video cũ vẫn còn nguyên -> giữ trạng thái hoàn tất, báo lỗi xuất lại
            job.update(status="done", progress=100, rerender_error=str(e)[:500])

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def list(self, limit=30):
        js = sorted(self.jobs.values(), key=lambda j: j.data.get("created", 0), reverse=True)
        return js[:limit]

    def delete(self, jid: str) -> bool:
        import shutil
        j = self.jobs.get(jid)
        if not j or j.data.get("status") in ("queued", "running", "review"):
            return False
        shutil.rmtree(j.dir, ignore_errors=True)
        del self.jobs[jid]
        return True
