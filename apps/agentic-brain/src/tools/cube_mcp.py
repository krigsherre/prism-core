import os
import httpx
from typing import Dict, Any

class CubeMCPClient:
    """
    Real MCP (Model Context Protocol) Client for Cube.dev Semantic Layer.
    Implements the Command Pattern for UI/LLM interaction.
    """
    
    def __init__(self, endpoint: str = None, token: str = None):
        self.endpoint = endpoint or os.environ.get("CUBE_API_URL", "http://localhost:4000/cubejs-api/v1")
        self.token = token or os.environ.get("CUBE_API_TOKEN", "")
        
    def execute_sql(self, query: str) -> Dict[str, Any]:
        """
        Executes a real SQL query against the Cube semantic layer via REST API.
        """
        print(f"[CubeMCPClient] Executing Semantic SQL: {query}")
        
        headers = {
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        url = f"{self.endpoint}/sql"
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    url,
                    json={"query": query},
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            print(f"[CubeMCPClient] HTTP Status Error: {e.response.text}")
            return {
                "status": "error",
                "error": e.response.text,
                "query_executed": query
            }
        except httpx.RequestError as e:
            print(f"[CubeMCPClient] Network Error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "query_executed": query
            }
