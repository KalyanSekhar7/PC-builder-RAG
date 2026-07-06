"""Evaluation runner — runs test scenarios through the agent and scores results."""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic

from src.config import ANTHROPIC_API_KEY, MODEL_NAME, DATA_DIR, MAX_AGENT_TURNS
from src.utils.logging_config import setup_logging
from src.data.loader import ComponentStore
from src.engine.compatibility import CompatibilityChecker
from src.engine.optimizer import UseCaseOptimizer
from src.engine.validator import RequirementValidator  # noqa: F811
from src.agent.tools import ToolDispatcher
from src.agent.loop import AgentLoop

logger = logging.getLogger("evaluation")


def load_scenarios(path: str = None) -> list[dict]:
    if path is None:
        path = Path(__file__).parent / "scenarios.json"
    with open(path) as f:
        return json.load(f)


def run_scenario(agent: AgentLoop, scenario: dict) -> dict:
    """Run a single scenario through the agent."""
    agent.reset()
    logger.info(f"Running scenario: {scenario['id']} — {scenario['name']}")

    responses = []
    for i, msg in enumerate(scenario["user_messages"]):
        logger.info(f"  User message {i+1}: {msg[:80]}...")
        start = time.time()
        response = agent.chat(msg)
        duration = time.time() - start
        responses.append({
            "user_message": msg,
            "agent_response": response,
            "duration_s": round(duration, 1),
        })
        logger.info(f"  Agent responded in {duration:.1f}s ({len(response)} chars)")

    return {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "responses": responses,
        "trace": agent.get_trace(),
        "final_response": responses[-1]["agent_response"] if responses else "",
    }


def score_scenario(result: dict, expected: dict) -> dict:
    """Score a scenario result against expected outcomes."""
    checks = []
    final = result["final_response"].lower()
    trace_str = json.dumps(result["trace"], default=str).lower()

    # Budget range check (look for price in the response)
    if "budget_range" in expected:
        lo, hi = expected["budget_range"]
        # Try to find a total price in the response
        import re
        price_matches = re.findall(r'\$[\d,]+\.?\d*', result["final_response"])
        prices = []
        for p in price_matches:
            try:
                prices.append(float(p.replace("$", "").replace(",", "")))
            except ValueError:
                pass

        if prices:
            # Use the largest price as likely total
            total = max(prices)
            in_range = lo <= total <= hi
            checks.append({
                "check": "budget_in_range",
                "passed": in_range,
                "detail": f"Found ${total:.0f}, expected ${lo}-${hi}",
            })
        else:
            checks.append({
                "check": "budget_in_range",
                "passed": None,
                "detail": "Could not extract total price from response",
            })

    # Must-have checks
    must_have = expected.get("must_have", {})

    if "gpu_present" in must_have and must_have["gpu_present"]:
        has_gpu = any(
            kw in final for kw in ["geforce", "radeon", "rtx", "gtx", "arc "]
        )
        checks.append({"check": "gpu_present", "passed": has_gpu})

    if "gpu_chipset_contains" in must_have:
        target = must_have["gpu_chipset_contains"].lower()
        checks.append({
            "check": f"gpu_chipset_contains_{target}",
            "passed": target in final,
        })

    if "memory_gb_min" in must_have:
        target = must_have["memory_gb_min"]
        # Check if adequate RAM is mentioned
        ram_matches = re.findall(r'(\d+)\s*gb', final)
        ram_vals = [int(x) for x in ram_matches if int(x) in (8, 16, 32, 64, 128, 256)]
        has_enough = any(v >= target for v in ram_vals) if ram_vals else None
        checks.append({
            "check": f"memory_gb_min_{target}",
            "passed": has_enough,
            "detail": f"Found RAM values: {ram_vals}",
        })

    if "storage_has_nvme" in must_have and must_have["storage_has_nvme"]:
        has_nvme = "nvme" in final or "m.2 pcie" in final or "990 pro" in final or "p3 plus" in final
        checks.append({"check": "storage_has_nvme", "passed": has_nvme})

    if "storage_has_ssd" in must_have and must_have["storage_has_ssd"]:
        has_ssd = "ssd" in final or "nvme" in final or "m.2" in final
        checks.append({"check": "storage_has_ssd", "passed": has_ssd})

    if "cpu_cores_min" in must_have:
        target = must_have["cpu_cores_min"]
        core_matches = re.findall(r'(\d+)[\s-]*core', final)
        core_vals = [int(x) for x in core_matches]
        has_enough = any(v >= target for v in core_vals) if core_vals else None
        checks.append({
            "check": f"cpu_cores_min_{target}",
            "passed": has_enough,
            "detail": f"Found core counts: {core_vals}",
        })

    if "cpu_brand" in must_have:
        brand = must_have["cpu_brand"].lower()
        checks.append({
            "check": f"cpu_brand_{brand}",
            "passed": brand in final or ("ryzen" in final if brand == "amd" else "intel" in final),
        })

    if "case_type_contains" in must_have:
        target = must_have["case_type_contains"].lower()
        checks.append({
            "check": f"case_type_{target}",
            "passed": target in final,
        })

    if "motherboard_form_factor" in must_have:
        target = must_have["motherboard_form_factor"].lower()
        checks.append({
            "check": f"mobo_form_factor_{target}",
            "passed": target in final,
        })

    if "cooler_type" in must_have:
        target = must_have["cooler_type"].lower()
        if target == "air":
            passed = "air" in final and "liquid" not in final.replace("air cooling", "").replace("air cooler", "")
        else:
            passed = "aio" in final or "liquid" in final
        checks.append({"check": f"cooler_type_{target}", "passed": passed})

    if "gpu_vram_min" in must_have:
        target = must_have["gpu_vram_min"]
        vram_matches = re.findall(r'(\d+)\s*gb\s*(?:vram|gddr|memory)', final)
        vram_vals = [int(x) for x in vram_matches]
        has_enough = any(v >= target for v in vram_vals) if vram_vals else None
        checks.append({
            "check": f"gpu_vram_min_{target}",
            "passed": has_enough,
            "detail": f"Found VRAM values: {vram_vals}",
        })

    # Compatibility check — look in trace for check_compatibility results
    must_not = expected.get("must_not_have", {})
    if "compatibility_errors" in must_not:
        # Search trace for compatibility check results
        had_errors = False
        for event in result["trace"]:
            if event.get("event") == "tool_call" and event.get("data", {}).get("tool") == "check_compatibility":
                result_str = event["data"].get("result_preview", "")
                if '"compatible": false' in result_str.lower() or '"errors": [' in result_str:
                    had_errors = True
        checks.append({
            "check": "no_final_compatibility_errors",
            "passed": not had_errors,
        })

    # Score
    total = len(checks)
    passed = sum(1 for c in checks if c.get("passed") is True)
    failed = sum(1 for c in checks if c.get("passed") is False)
    unknown = sum(1 for c in checks if c.get("passed") is None)

    return {
        "total_checks": total,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "score_pct": round(passed / total * 100, 1) if total > 0 else 0,
        "checks": checks,
    }


def main():
    """Run all evaluation scenarios."""
    setup_logging(level="INFO", log_file="evaluation.log")

    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set. Cannot run evaluation.")
        sys.exit(1)

    # Initialize
    print("Loading component database...")
    store = ComponentStore(DATA_DIR)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    checker = CompatibilityChecker(store)
    optimizer = UseCaseOptimizer(store)
    validator = RequirementValidator(client, model=MODEL_NAME)
    dispatcher = ToolDispatcher(store, optimizer, checker)

    scenarios = load_scenarios()
    print(f"Loaded {len(scenarios)} test scenarios.\n")

    results = []
    for scenario in scenarios:
        print(f"{'='*60}")
        print(f"Scenario: {scenario['name']}")
        print(f"{'='*60}")

        agent = AgentLoop(
            client=client,
            dispatcher=dispatcher,
            store_stats=store.get_summary_stats(),
            validator=validator,
            model=MODEL_NAME,
            max_turns=MAX_AGENT_TURNS,
        )

        result = run_scenario(agent, scenario)
        score = score_scenario(result, scenario["expected"])

        print(f"\nScore: {score['passed']}/{score['total_checks']} checks passed ({score['score_pct']}%)")
        for check in score["checks"]:
            status = "PASS" if check["passed"] else ("FAIL" if check["passed"] is False else "UNKNOWN")
            detail = f" — {check.get('detail', '')}" if check.get("detail") else ""
            print(f"  [{status}] {check['check']}{detail}")

        results.append({
            "scenario": scenario,
            "result": {
                "scenario_id": result["scenario_id"],
                "responses": result["responses"],
                "final_response": result["final_response"],
            },
            "score": score,
        })
        print()

    # Summary
    print("=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    total_checks = sum(r["score"]["total_checks"] for r in results)
    total_passed = sum(r["score"]["passed"] for r in results)
    for r in results:
        s = r["score"]
        print(f"  {r['scenario']['name']:40} {s['passed']}/{s['total_checks']} ({s['score_pct']}%)")
    print(f"\n  Overall: {total_passed}/{total_checks} ({total_passed/total_checks*100:.1f}%)" if total_checks > 0 else "")

    # Save report
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = reports_dir / f"eval_{timestamp}.json"

    with open(report_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull report saved to: {report_file}")


if __name__ == "__main__":
    main()
