"""Application wiring: one store, service, soundbank registry and renderer per process."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from midimcp.events import EventBus
from midimcp.model.score import Score
from midimcp.render import Renderer, RenderError, RenderResult
from midimcp.service import CompositionService
from midimcp.soundbanks import SoundbankRegistry
from midimcp.store import CommitResult, ProjectStore

_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


@dataclass
class RenderJob:
    id: str
    project_id: str
    revision: int
    future: Future = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "jobId": self.id,
            "projectId": self.project_id,
            "revision": self.revision,
        }
        if not self.future.done():
            data["status"] = "running" if self.future.running() else "queued"
            return data
        error = self.future.exception()
        if error is None:
            result: RenderResult = self.future.result()
            data["status"] = "completed"
            data["render"] = result.to_dict()
            data["downloadPath"] = f"/api/renders/{result.path.name}"
        else:
            data["status"] = "failed"
            data["error"] = (
                error.to_dict()
                if isinstance(error, RenderError)
                else {"code": "RENDER_FAILED", "message": str(error)}
            )
        return data


class RenderJobs:
    """Single-worker render queue (FluidSynth renders are CPU-bound)."""

    def __init__(
        self,
        renderer: Renderer,
        max_jobs: int = 200,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.renderer = renderer
        self._on_event = on_event
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
        self._jobs: dict[str, RenderJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def submit(self, score: Score, **kwargs: Any) -> RenderJob:
        job_id = uuid.uuid4().hex[:16]
        future = self._executor.submit(self.renderer.render, score, **kwargs)
        job = RenderJob(job_id, score.project_id, score.revision, future)
        if self._on_event is not None:
            self._on_event({"type": "render.queued", "job": job.to_dict()})
            future.add_done_callback(
                lambda _f: self._on_event({"type": "render.finished", "job": job.to_dict()})
            )
        with self._lock:
            self._jobs[job_id] = job
            while len(self._jobs) > self._max_jobs:
                oldest = next(iter(self._jobs))
                if not self._jobs[oldest].future.done():
                    break
                del self._jobs[oldest]
        return job

    def get(self, job_id: str) -> RenderJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    @staticmethod
    def wait(job: RenderJob, timeout: float) -> None:
        try:
            job.future.result(timeout=timeout)
        except FutureTimeout:
            pass
        except Exception:  # reported through job.to_dict()
            pass

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class AppContext:
    def __init__(self, data_dir: Path | str, *, renderer: Renderer | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ProjectStore(self.data_dir)
        self.service = CompositionService(self.store)
        self.registry = SoundbankRegistry(self.data_dir)
        self.renderer = renderer or Renderer(self.registry, self.data_dir / "renders")
        self.events = EventBus()
        self.jobs = RenderJobs(self.renderer, on_event=self.events.publish)
        self.store.add_listener(self._on_commit)

    def _on_commit(self, result: CommitResult) -> None:
        info = result.snapshot.info
        self.events.publish(
            {
                "type": "project.updated",
                "projectId": result.snapshot.project_id,
                "revision": result.revision,
                "title": result.snapshot.score.metadata.title,
                "author": info.author,
                "summary": info.summary,
                "createdAt": info.created_at,
            }
        )

    def render_file(self, name: str) -> Path | None:
        if not _SAFE_FILE.match(name) or not name.endswith(".wav"):
            return None
        path = self.renderer.cache_dir / name
        return path if path.is_file() else None

    def export_file(self, project_id: str, name: str) -> Path | None:
        if not _SAFE_FILE.match(name):
            return None
        try:
            directory = self.store.project_dir(project_id) / "exports"
        except Exception:
            return None
        path = directory / name
        return path if path.is_file() else None
