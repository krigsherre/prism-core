import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from repositories.sql_repo import SQLRepository

@pytest.fixture
def mock_session():
    session = AsyncMock()
    begin_mgr = MagicMock()
    begin_mgr.__aenter__ = AsyncMock(return_value=None)
    begin_mgr.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_mgr)
    
    session.execute = AsyncMock()
    return session

@pytest.fixture
def mock_session_maker(mock_session):
    mock_local = MagicMock()
    mock_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_local.return_value.__aexit__ = AsyncMock(return_value=None)
    with patch('repositories.sql_repo.AsyncSessionLocal', mock_local):
        yield mock_session

@pytest.mark.asyncio
async def test_update_aligned_table(mock_session_maker):
    repo = SQLRepository()

    await repo.update_aligned_table(
        row_id=1,
        mapping_status="SUCCESS",
        strict_columns={"test": "data"},
        unmapped_jsonb={},
        target_table="test_table"
    )

    assert mock_session_maker.execute.called
    args, kwargs = mock_session_maker.execute.call_args
    stmt_str = str(args[0])
    assert "UPDATE extracted_tables SET " in stmt_str
    assert "mapping_status=:mapping_status" in stmt_str
    assert "WHERE extracted_tables.id = " in stmt_str

@pytest.mark.asyncio
async def test_insert_aligned_rows(mock_session_maker):
    repo = SQLRepository()
    await repo.insert_aligned_rows(
        tenant_id="t1",
        document_id="d1",
        node_id="n1",
        target_table="tab",
        mapping_status="SUCCESS",
        strict_columns_list=[{"a": 1}],
        unmapped_jsonb_list=[{"b": 2}],
        user_id="u1"
    )
    assert mock_session_maker.execute.called

@pytest.mark.asyncio
async def test_get_unmapped_rows_by_table(mock_session_maker):
    repo = SQLRepository()
    mock_result = MagicMock()
    mock_row = MagicMock()
    mock_row.id = 1
    mock_row.tenant_id = "t1"
    mock_row.document_id = "d1"
    mock_row.strict_columns = {}
    mock_row.unmapped_jsonb = {}
    mock_result.scalars.return_value.all.return_value = [mock_row]
    mock_session_maker.execute.return_value = mock_result
    
    rows = await repo.get_unmapped_rows_by_table("tab")
    assert len(rows) == 1
    assert rows[0]["id"] == 1

