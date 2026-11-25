"""Hàng đợi job đơn giản, lưu trạng thái ra file JSON (khởi động lại server không mất lịch sử)."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import JOBS_DIR, MAX_RESUME, MAX_WORKERS, JobOptions


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
        interrupted = []
        for d in sorted(JOBS_DIR.iterdir()) if JOBS_DIR.exists() else []:
            if (d / "job.json").exists():
                j = Job(d.name)
                self.jobs[d.name] = j
                if j.data.get("status") not in ("queued", "running", "review"):
                    continue
                if j.data.get("rerendering"):   # đang xuất lại: video cũ vẫn còn
                    j.update(status="done", progress=100, rerendering=False,
                             rerender_error="Colab/server tắt khi đang xuất lại. Bấm chỉnh chữ & xuất lại lần nữa.")
                else:
                    interrupted.append(j)
        # Colab tắt giữa chừng -> tự chạy tiếp từ bước đã lưu
        for j in interrupted:
            n = int(j.data.get("resume_count") or 0)
            if n >= MAX_RESUME:
                j.update(status="error", error=f"Bị gián đoạn {n} lần liên tiếp. Bấm ▶ Chạy tiếp để thử lại.")
            else:
                self.resume(j.id, auto=True)

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

    def resume(self, jid: str, auto=False) -> bool:
        """Chạy tiếp job bị gián đoạn (Colab tắt / lỗi giữa chừng) từ bước đã lưu."""
        j = self.jobs.get(jid)
        if not j or j.data.get("status") not in ("queued", "running", "review", "error"):
            return False
        if j.data.get("kind") == "create":
            parent = self.jobs.get(j.data.get("parent", ""))
            try:
                spec = json.loads((j.dir / "spec.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return False
            j.update(status="queued", error=None, step_label="Chờ chạy tiếp",
                     resume_count=int(j.data.get("resume_count") or 0) + (1 if auto else 0))
            j.log("↻ Chạy tiếp sau khi bị gián đoạn")
            self.pool.submit(self._run_create, j, spec, parent.dir if parent else None)
            return True
        if not (j.dir / "source.mp4").exists() and not str(j.data.get("input", "")).startswith("http"):
            return False
        j.update(status="queued", error=None, review=None, step_label="Chờ chạy tiếp",
                 resume_count=int(j.data.get("resume_count") or 0) + (1 if auto else 0))
        j.log("↻ Chạy tiếp sau khi bị gián đoạn (bỏ qua các bước đã xong)")
        self.pool.submit(self._run, j, JobOptions.from_dict(j.data.get("options") or {}))
        return True

    def _run(self, job: Job, opts: JobOptions):
        from .pipeline import process
        job.update(status="running", started=time.time())
        try:
            process(job, opts)
            job.update(status="done", finished=time.time(), resume_count=0)
            job.log("✅ Xong!")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.log("❌ " + str(e)[:500])
            job.update(status="error", error=str(e)[:1000], finished=time.time())

    def create_new(self, parent: Job, spec: dict, media: list[tuple[str, Path]]) -> Job:
        """Job 'Sáng tạo video mới' lấy cảm hứng từ job parent."""
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        title = str(spec.get("title") or "Video mới")[:80]
        job = Job(jid, {"id": jid, "kind": "create", "parent": parent.id, "status": "queued", "title": title,
                        "input": f"✨ Video mới: {title}", "options": spec.get("options") or {},
                        "created": time.time(), "progress": 0, "logs": [], "step_label": "Đang chờ"})
        mdir = job.dir / "media"
        mdir.mkdir(exist_ok=True)
        for name, tmp in media:
            tmp.replace(mdir / name)
        (job.dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        job.save()
        self.jobs[jid] = job
        self.pool.submit(self._run_create, job, spec, parent.dir)
        return job

    def _run_create(self, job: Job, spec: dict, parent_dir: Path):
        from .creator import create_video
        job.update(status="running", started=time.time())
        job.log("▶ Sáng tạo video mới theo kịch bản")
        try:
            create_video(job, spec, job.dir / "media", parent_dir)
            job.update(status="done", progress=100, result="result.mp4", srt="result.srt", finished=time.time(), resume_count=0)
            job.log("✅ Xong!")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.log("❌ " + str(e)[:500])
            job.update(status="error", error=str(e)[:1000], finished=time.time())

    def rerender(self, jid: str, decision: dict) -> bool:
        j = self.jobs.get(jid)
        if not j or j.data.get("status") != "done" or not (j.dir / "render_state.pkl").exists():
            return False
        j.update(status="queued", step_label="Chờ xuất lại", rerender_error=None, rerendering=True)
        self.pool.submit(self._rerun, j, decision)
        return True

    def _rerun(self, job: Job, decision: dict):
        from .pipeline import rerender
        try:
            rerender(job, decision)
            job.log("✅ Đã xuất lại xong!")
            job.update(status="done", finished=time.time(), rerendering=False)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.log("❌ Xuất lại lỗi: " + str(e)[:300])
            # video cũ vẫn còn nguyên -> giữ trạng thái hoàn tất, báo lỗi xuất lại
            job.update(status="done", progress=100, rerender_error=str(e)[:500], rerendering=False)

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
