"""LLM-based requirement validator — self-critique layer."""

import json
import logging
import time

import anthropic

logger = logging.getLogger("engine.validator")

VALIDATION_PROMPT = """You are a PC build validator. Given a user's original requirements and a proposed PC build, evaluate whether the build actually satisfies what the user asked for.

## User's Requirements
{requirements}

## Proposed Build
{build}

## Compatibility Check Results
{compatibility}

## Your Task
Evaluate this build and return a JSON object (no markdown, just raw JSON) with exactly these fields:
{{
    "satisfies_requirements": true/false,
    "score": <1-10 integer>,
    "issues": ["list of unmet requirements or concerns"],
    "strengths": ["list of things done well"],
    "suggestions": ["optional improvements within budget"]
}}

Be specific and practical. Focus on whether the build actually matches the USE CASE, not just whether parts are compatible.
Examples of issues: "User wanted ML training but GPU only has 8GB VRAM", "Budget office PC has a $500 GPU that's unnecessary".
Examples of strengths: "Good RAM expandability with 2x16GB in 4-slot board", "NVMe boot drive for fast load times"."""


class RequirementValidator:
    """Uses a separate LLM call to validate the final build against user requirements."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client
        self.model = model

    def validate(
        self,
        user_requirements: str,
        final_build: dict,
        compatibility_result: dict,
    ) -> dict:
        """Validate a build against requirements. Returns validation result dict."""
        prompt = VALIDATION_PROMPT.format(
            requirements=user_requirements,
            build=json.dumps(final_build, indent=2, default=str),
            compatibility=json.dumps(compatibility_result, indent=2, default=str),
        )

        logger.info("Running requirement validation...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text

            # Parse JSON from response (handle markdown code blocks)
            json_str = text.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1])

            result = json.loads(json_str)
            logger.info(
                f"Validation result: score={result.get('score')}/10, "
                f"satisfies={result.get('satisfies_requirements')}, "
                f"issues={len(result.get('issues', []))}"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse validator response as JSON: {e}")
            return {
                "satisfies_requirements": None,
                "score": None,
                "issues": ["Validator response was not valid JSON"],
                "strengths": [],
                "suggestions": [],
                "raw_response": text if "text" in dir() else "No response",
            }
        except anthropic.APIError as e:
            logger.error(f"Validator API error: {e}")
            return {
                "satisfies_requirements": None,
                "score": None,
                "issues": [f"Validator API error: {str(e)}"],
                "strengths": [],
                "suggestions": [],
            }
