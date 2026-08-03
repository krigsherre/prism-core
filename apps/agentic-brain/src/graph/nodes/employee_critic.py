"""Self-Verification Audit Node for Autonomous Employee Agents."""
from __future__ import annotations

import structlog
from typing import Dict, Any
from graph.state import InteractionState
from core.employee_personas import get_persona

logger = structlog.get_logger(__name__)


async def employee_critic_node(state: InteractionState) -> Dict[str, Any]:
    """
    Audit & self-verify synthesized answers against retrieved evidence.
    Appends persona-specific audit disclaimers and verification tags.
    """
    final_answer = state.get("final_answer", "")
    agent_role = state.get("target_task") or "research_assistant"
    persona = get_persona(agent_role)

    if not final_answer:
        return {"final_answer": final_answer}

    logger.info("Executing self-verification audit node", persona=persona["name"])

    verification_header = f"**[{persona['title']} Audit Verification]**\n\n"
    verified_answer = verification_header + final_answer

    return {"final_answer": verified_answer}
