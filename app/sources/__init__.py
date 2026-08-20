"""소스 어댑터 레지스트리.

새 어댑터를 붙일 때 손대는 곳은 여기 하나. `.env` 로 켜고 끈다.
"""
from __future__ import annotations

from .base import Job, JobSource, normalize
from ..config import cfg

__all__ = ["Job", "JobSource", "normalize", "build_sources"]


def build_sources():
    """활성화된(키가 있고 꺼지지 않은) 소스만 만들어 돌려준다."""
    sources = []
    for name in cfg.enabled_sources():
        if name == "worknet":
            from .worknet import WorknetSource
            sources.append(WorknetSource(cfg.worknet_key))
        elif name == "saramin":
            from .saramin import SaraminSource
            sources.append(SaraminSource(cfg.saramin_key))
        elif name == "jobkorea":
            from .jobkorea import JobkoreaSource
            sources.append(JobkoreaSource(cfg.jobkorea_url))
        elif name == "greenhouse":
            from .greenhouse import GreenhouseSource
            sources.append(GreenhouseSource(cfg.greenhouse_boards.split(",")))
    return sources
