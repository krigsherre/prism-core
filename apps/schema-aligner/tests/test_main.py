import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")

from main import app, create_application


def test_app_factory():
    assert app.title == "Schema Aligner Microservice"
    assert create_application().title == "Schema Aligner Microservice"


@pytest.mark.asyncio
async def test_lifespan_starts_consumers():
    with (
        patch("main.SchemaCDCConsumer") as mock_schema_cls,
        patch("main.DictionaryCDCConsumer") as mock_dict_cls,
        patch("main.RawTableDOMConsumer") as mock_raw_cls,
        patch("main.WaterfallAlignmentStrategy"),
    ):
        for cls in (mock_schema_cls, mock_dict_cls, mock_raw_cls):
            cls.return_value.run = AsyncMock()

        test_app = create_application()
        async with test_app.router.lifespan_context(test_app):
            assert mock_schema_cls.return_value.run.called
            assert mock_dict_cls.return_value.run.called
            assert mock_raw_cls.return_value.run.called
