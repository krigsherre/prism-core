import sys
from unittest.mock import MagicMock

sys.modules["langchain_google_genai"] = MagicMock()
sys.modules["google.ai.generativelanguage_v1beta"] = MagicMock()
sys.modules["google.ai"] = MagicMock()
