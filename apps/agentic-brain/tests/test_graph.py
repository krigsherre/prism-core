from graph.workflow import should_retry, supervisor_router


class TestSupervisorRouter:
    def test_routes_all_modalities(self):
        assert set(supervisor_router({"required_modalities": ["SQL", "CYPHER", "VECTOR"]})) == {
            "generate_sql",
            "generate_cypher",
            "generate_vector",
        }

    def test_defaults_to_vector_when_empty(self):
        assert supervisor_router({"required_modalities": []}) == ["generate_vector"]

    def test_sql_only(self):
        assert supervisor_router({"required_modalities": ["SQL"]}) == ["generate_sql"]


class TestShouldRetry:
    def test_retries_on_error_under_limit(self):
        assert should_retry({"error_message": "boom", "retries": 1}) == "retry"

    def test_ends_when_retries_exhausted(self):
        assert should_retry({"error_message": "boom", "retries": 3}) == "end"

    def test_ends_without_error(self):
        assert should_retry({"error_message": "", "retries": 0}) == "end"
