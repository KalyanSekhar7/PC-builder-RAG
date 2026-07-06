"""Core agent loop: reason → plan → act → observe → respond."""

import json
import logging
import time
from datetime import datetime, timezone

import anthropic

from .prompts import build_system_prompt
from .tools import TOOL_DEFINITIONS, ToolDispatcher
from ..engine.validator import RequirementValidator

logger = logging.getLogger("agent.loop")


class AgentLoop:
    """Conversational agent loop with tool calling for PC configuration."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        dispatcher: ToolDispatcher,
        store_stats: dict,
        validator: RequirementValidator | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_turns: int = 20,
        max_retries: int = 3,
    ):
        self.client = client
        self.dispatcher = dispatcher
        self.validator = validator
        self.system_prompt = build_system_prompt(store_stats)
        self.model = model
        self.max_turns = max_turns
        self.max_retries = max_retries
        self.messages: list[dict] = []
        self.trace: list[dict] = []
        self.requirements_confirmed = False
        self._confirmed_requirements: dict = {}  # stored when confirm_requirements is called

    def chat(self, user_message: str) -> str:
        """Send a user message and get the agent's response (may involve tool calls)."""
        self.messages.append({"role": "user", "content": user_message})
        self._log_trace("user_message", {"content": user_message})

        for turn in range(self.max_turns):
            logger.info(f"--- Agent turn {turn + 1} ---")

            response = self._call_llm()
            if response is None:
                return "I'm sorry, I encountered an error communicating with the AI service. Please try again."

            self._log_trace("assistant_response", {
                "stop_reason": response.stop_reason,
                "content_types": [b.type for b in response.content],
                "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens},
            })

            # Append full assistant message
            self.messages.append({"role": "assistant", "content": response.content})

            # If the model wants to use tools, execute them
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block)
                        tool_results.append(result)

                # Send tool results back
                self.messages.append({"role": "user", "content": tool_results})
                continue  # Let the model process tool results

            # Model produced a final text response
            if response.stop_reason == "end_turn":
                text = self._extract_text(response.content)
                self._log_trace("final_response", {"content": text[:500]})
                return text

        return "I've reached the maximum number of reasoning steps. Please try simplifying your request."

    def get_trace(self) -> list[dict]:
        """Return the full agent trace for evaluation/debugging."""
        return self.trace

    def reset(self) -> None:
        """Clear conversation history and trace."""
        self.messages = []
        self.trace = []
        self.requirements_confirmed = False

    def _call_llm(self) -> anthropic.types.Message | None:
        """Call the Anthropic API with retry logic."""
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    messages=self.messages,
                    tools=TOOL_DEFINITIONS,
                )
                return response

            except anthropic.RateLimitError:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(wait)
            except anthropic.APIStatusError as e:
                logger.error(f"API error: {e.status_code} {e.message}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)
            except anthropic.APIConnectionError as e:
                logger.error(f"Connection error: {e}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)

        return None

    def _execute_tool(self, tool_block) -> dict:
        """Execute a single tool call and return the result message."""
        tool_name = tool_block.name
        tool_input = tool_block.input
        tool_id = tool_block.id

        # Handle confirm_requirements — this is the LLM telling us it has gathered enough info
        if tool_name == "confirm_requirements":
            self.requirements_confirmed = True
            self._confirmed_requirements = tool_input
            logger.info(f"Requirements confirmed: {json.dumps(tool_input, default=str)[:200]}")
            self._log_trace("requirements_confirmed", {"requirements": tool_input})
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps({
                    "status": "confirmed",
                    "message": "Requirements recorded. You may now proceed with component selection. "
                               "Start by calling get_optimization_profile, then search for components.",
                }),
            }

        # Handle update_build_list — LLM is declaring the current build state
        if tool_name == "update_build_list":
            logger.info(f"Build list updated: {json.dumps(tool_input, default=str)[:300]}")
            self._log_trace("build_updated", tool_input)
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps({
                    "status": "updated",
                    "message": "Build list updated in the UI sidebar.",
                }),
            }

        # Guard: block component search tools until requirements are confirmed by the LLM
        tools_needing_requirements = {
            "search_components", "get_optimization_profile",
            "check_compatibility", "optimize_build",
        }
        if tool_name in tools_needing_requirements and not self.requirements_confirmed:
            logger.info(f"Tool BLOCKED: {tool_name} — requirements not yet confirmed")
            self._log_trace("tool_blocked", {"tool": tool_name})
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps({
                    "error": "You must call confirm_requirements first before searching for components. "
                             "Ask the user about their use case, budget, and any preferences, "
                             "then call confirm_requirements with the gathered information.",
                }),
                "is_error": True,
            }

        logger.info(f"Executing tool: {tool_name}")
        start = time.time()

        try:
            result_json = self.dispatcher.execute(tool_name, tool_input)
            duration = time.time() - start

            # Self-critique: after check_compatibility passes, run the validator
            if tool_name == "check_compatibility" and self.validator and self._confirmed_requirements:
                compat_result = json.loads(result_json)
                if compat_result.get("compatible", False):
                    logger.info("Running RequirementValidator (self-critique)...")
                    validation = self.validator.validate(
                        user_requirements=json.dumps(self._confirmed_requirements, default=str),
                        final_build=tool_input,
                        compatibility_result=compat_result,
                    )
                    self._log_trace("validation_result", validation)
                    # Append validation feedback to the tool result
                    compat_result["validation"] = validation
                    result_json = json.dumps(compat_result, default=str)

            # Store full result for search/compatibility (needed by metrics), truncate others
            preview_limit = 2000 if tool_name in ("search_components", "check_compatibility") else 500
            self._log_trace("tool_call", {
                "tool": tool_name,
                "input": tool_input,
                "result_preview": result_json[:preview_limit],
                "duration_ms": round(duration * 1000),
            })

            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result_json,
            }
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}")
            self._log_trace("tool_error", {
                "tool": tool_name,
                "input": tool_input,
                "error": str(e),
            })
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps({"error": str(e)}),
                "is_error": True,
            }

    def _extract_text(self, content: list) -> str:
        """Extract text blocks from a response."""
        texts = []
        for block in content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts) if texts else ""

    def _log_trace(self, event_type: str, data: dict) -> None:
        """Append to trace for evaluation/debugging."""
        self.trace.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "data": data,
        })
