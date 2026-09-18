"""Programmatic entry point shared with the API, with explicit review boundaries."""
from services.pipeline_service import PipelineService


def create_agent(**kwargs):
    """Create an agent; call research(), review() and patch() at review boundaries."""
    return PipelineService(**kwargs)
