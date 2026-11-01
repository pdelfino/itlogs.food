from itlogs.config import settings
from itlogs.providers.base import LLMProvider, VisionProvider
from itlogs.providers.fake import FakeLLM, FakeVision


def make_providers() -> tuple[VisionProvider, LLMProvider]:
    """The one place that knows which provider is live. Everything else sees the protocols."""
    if settings.provider == "meta":
        from itlogs.providers.meta import make_parser, make_reader

        return make_reader(), make_parser()
    return FakeVision(), FakeLLM()
