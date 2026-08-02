import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_main():
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.run_sync = AsyncMock()
    mock_conn.execute = AsyncMock()

    with patch("main.BifurcationConsumer") as mock_bifurcation, \
         patch("main.AlignedSQLConsumer") as mock_aligned, \
         patch("main.AutoPromoteConsumer") as mock_auto_promote, \
         patch("main.DebeziumObserver") as mock_cdc, \
         patch("main.StatusConsumer") as mock_status, \
         patch("main.SystemDlqConsumer") as mock_dlq, \
         patch("main.HitlConsumer") as mock_hitl, \
         patch("main.SQLRepository"), \
         patch("main.QdrantRepository") as mock_qdrant, \
         patch("db.postgres.engine", mock_engine), \
         patch("db.models.Base"), \
         patch("db.views.generate_schema_views", new_callable=AsyncMock), \
         patch("db.postgres.AsyncSessionLocal"):

        for mock_cls in (
            mock_bifurcation,
            mock_aligned,
            mock_auto_promote,
            mock_cdc,
            mock_status,
            mock_dlq,
            mock_hitl,
        ):
            mock_cls.return_value.run = AsyncMock()

        mock_qdrant.return_value.initialize_collection = AsyncMock()

        from main import main

        await main()

        assert mock_bifurcation.return_value.run.called
        assert mock_aligned.return_value.run.called
        assert mock_auto_promote.return_value.run.called
        assert mock_cdc.return_value.run.called
        assert mock_status.return_value.run.called
        assert mock_dlq.return_value.run.called
        assert mock_hitl.return_value.run.called
