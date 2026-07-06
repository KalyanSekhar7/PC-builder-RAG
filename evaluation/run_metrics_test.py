"""
Full RAGAS-style evaluation test.
Runs the agent on a real scenario, then evaluates with all 4 metric layers.
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ANTHROPIC_API_KEY, MODEL_NAME, DATA_DIR
from src.data.loader import ComponentStore
from src.engine.compatibility import CompatibilityChecker
from src.engine.optimizer import UseCaseOptimizer, PROFILES
from src.engine.validator import RequirementValidator
from src.agent.tools import ToolDispatcher
from src.agent.loop import AgentLoop
from evaluation.metrics import (
    precision_at_k, recall_at_k, hit_rate_at_k, reciprocal_rank,
    ndcg_at_k, mean_reciprocal_rank,
    LLMJudge,
    tool_call_accuracy, tool_call_f1, agent_goal_accuracy,
    evaluate_domain,
    EvaluationReport,
)

import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("eval_test")


def run_full_evaluation():
    """Run a gaming PC scenario and evaluate with all metrics."""
    print("=" * 70)
    print("  FULL RAGAS-STYLE EVALUATION")
    print("  Scenario: Gaming PC, $1500, 1440p, NVIDIA, Expert user")
    print("=" * 70)

    # ---- Setup ----
    print("\n[1/6] Loading components...")
    store = ComponentStore(DATA_DIR)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    checker = CompatibilityChecker(store)
    optimizer = UseCaseOptimizer(store)
    validator = RequirementValidator(client, model=MODEL_NAME)
    dispatcher = ToolDispatcher(store, optimizer, checker)
    agent = AgentLoop(
        client=client, dispatcher=dispatcher,
        store_stats=store.get_summary_stats(),
        validator=validator, model=MODEL_NAME, max_turns=20,
    )

    # ---- Run Agent ----
    print("\n[2/6] Running agent (multi-turn conversation)...")
    start = time.time()

    # Turn 1: user request
    r1 = agent.chat(
        "I'm an expert PC builder. I want to build a gaming PC for $1500. "
        "1440p AAA gaming at high settings. I prefer NVIDIA GPUs and AMD CPUs."
    )
    print(f"\n  Agent (turn 1): {r1[:200]}...")

    # Turn 2: answer follow-ups
    r2 = agent.chat(
        "Go with air cooling, mid tower ATX, no peripherals needed, no OS. "
        "I want DDR5 and at least 32GB RAM. NVMe storage, 1TB minimum."
    )
    print(f"\n  Agent (turn 2): {r2[:200]}...")

    # If agent asked more questions, give final push
    if "?" in r2:
        r3 = agent.chat("That's all my preferences. Please go ahead and build it.")
        print(f"\n  Agent (turn 3): {r3[:200]}...")

    duration = time.time() - start
    print(f"\n  Total agent time: {duration:.1f}s")

    # ---- Extract data from trace ----
    trace = agent.get_trace()
    print(f"\n[3/6] Analyzing trace ({len(trace)} events)...")

    # Extract tool calls
    tool_calls = []
    search_results = {}  # category -> list of retrieved component names
    compat_result = None
    final_response = ""

    for event in trace:
        ev = event.get("event", "")
        data = event.get("data", {})

        if ev == "tool_call":
            tool_name = data.get("tool", "")
            tool_calls.append(tool_name)

            # Capture search results
            if tool_name == "search_components":
                cat = data.get("input", {}).get("category", "")
                try:
                    result = json.loads(data.get("result_preview", "{}"))
                    names = [r["name"] for r in result.get("results", [])]
                    search_results[cat] = names
                except (json.JSONDecodeError, KeyError):
                    pass

            # Capture compatibility result
            if tool_name == "check_compatibility":
                try:
                    compat_result = json.loads(data.get("result_preview", "{}"))
                except json.JSONDecodeError:
                    pass

        if ev == "final_response":
            final_response = data.get("content", "")

    print(f"  Tool calls made: {tool_calls}")
    print(f"  Categories searched: {list(search_results.keys())}")
    print(f"  Compatibility result: {'PASS' if compat_result and compat_result.get('compatible') else 'FAIL or N/A'}")

    # ---- LAYER 1: Retrieval Metrics ----
    print("\n[4/6] Computing RETRIEVAL metrics...")

    # Define ground truth: what components SHOULD be found for a $1500 gaming build
    # These are the "ideal" components an expert would consider
    ground_truth = {
        "cpu": {
            "AMD Ryzen 7 9800X3D", "AMD Ryzen 7 7800X3D", "AMD Ryzen 5 7600X",
            "AMD Ryzen 5 9600X", "AMD Ryzen 7 9700X",
        },
        "gpu": {
            "GeForce RTX 4070", "GeForce RTX 4060 Ti", "GeForce RTX 4070 SUPER",
            "Radeon RX 7800 XT", "Radeon RX 9070",
        },
        "memory": {
            # Any 32GB DDR5 kit is relevant
        },
    }

    # Graded relevance for NDCG
    cpu_relevance = {
        "AMD Ryzen 7 9800X3D": 3.0, "AMD Ryzen 7 7800X3D": 3.0,
        "AMD Ryzen 5 9600X": 2.0, "AMD Ryzen 5 7600X": 2.0,
        "AMD Ryzen 7 9700X": 2.0, "AMD Ryzen 9 7900X": 1.0,
    }

    retrieval_metrics = {}

    # CPU retrieval quality
    cpu_retrieved = search_results.get("cpu", [])
    if cpu_retrieved and ground_truth["cpu"]:
        retrieval_metrics["cpu_precision_at_5"] = precision_at_k(cpu_retrieved, ground_truth["cpu"], 5)
        retrieval_metrics["cpu_recall_at_5"] = recall_at_k(cpu_retrieved, ground_truth["cpu"], 5)
        retrieval_metrics["cpu_hit_rate"] = hit_rate_at_k(cpu_retrieved, ground_truth["cpu"], 5)
        retrieval_metrics["cpu_mrr"] = reciprocal_rank(cpu_retrieved, ground_truth["cpu"])
        retrieval_metrics["cpu_ndcg_at_5"] = ndcg_at_k(cpu_retrieved, cpu_relevance, 5)

    # GPU retrieval quality — check chipset names in retrieved GPU names
    gpu_retrieved = search_results.get("gpu", [])
    gpu_relevant_chipsets = ground_truth["gpu"]
    if gpu_retrieved:
        # Match by chipset substring (GPU names include model name like "MSI GeForce RTX 4070...")
        gpu_relevant_found = set()
        for name in gpu_retrieved:
            for chipset in gpu_relevant_chipsets:
                if chipset.lower().replace("geforce ", "").replace("radeon ", "") in name.lower():
                    gpu_relevant_found.add(name)
        retrieval_metrics["gpu_hit_rate"] = 1.0 if gpu_relevant_found else 0.0
        retrieval_metrics["gpu_relevant_found"] = len(gpu_relevant_found)

    for k, v in retrieval_metrics.items():
        print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

    # ---- LAYER 2: Generation Metrics (LLM Judge) ----
    print("\n[5/6] Computing GENERATION metrics (LLM judge)...")

    judge = LLMJudge(client, model=MODEL_NAME)

    # Build context from what the agent actually retrieved
    context_parts = []
    for cat, names in search_results.items():
        for name in names[:3]:  # top 3 per category
            comp = store.get_component_by_name(cat, name)
            if comp:
                context_parts.append(f"{cat}: {json.dumps(comp, default=str)}")
    context = "\n".join(context_parts[:15])  # limit context size

    # Faithfulness: are claims in the response backed by data?
    faithfulness_result = {}
    if final_response and context:
        print("  Running faithfulness check...")
        faithfulness_result = judge.evaluate_faithfulness(final_response, context)
        faith_score = faithfulness_result.get("faithfulness_score")
        if faith_score is not None:
            print(f"  Faithfulness score: {faith_score:.3f}")
            unsupported = faithfulness_result.get("unsupported_claims", [])
            if unsupported:
                print(f"  Unsupported claims: {unsupported[:3]}")
        else:
            print(f"  Faithfulness: could not compute — {faithfulness_result.get('error', '?')}")

    # Answer relevancy: does the response match the request?
    relevancy_result = {}
    if final_response:
        print("  Running relevancy check...")
        user_request = (
            "Expert PC builder wants a $1500 gaming PC for 1440p AAA gaming. "
            "NVIDIA GPU, AMD CPU, DDR5 32GB, NVMe 1TB+, air cooling, mid tower ATX."
        )
        relevancy_result = judge.evaluate_answer_relevancy(user_request, final_response)
        rel_score = relevancy_result.get("relevancy_score")
        if rel_score is not None:
            print(f"  Relevancy score: {rel_score:.3f}")
            print(f"  Use case match: {relevancy_result.get('use_case_match')}")
            print(f"  Budget match: {relevancy_result.get('budget_match')}")
            print(f"  Preferences respected: {relevancy_result.get('preferences_respected')}")
            issues = relevancy_result.get("issues", [])
            if issues:
                print(f"  Issues: {issues[:3]}")
        else:
            print(f"  Relevancy: could not compute — {relevancy_result.get('error', '?')}")

    # ---- LAYER 3: Agent Metrics ----
    print("\n[6/6] Computing AGENT & DOMAIN metrics...")

    expected_tools = [
        "confirm_requirements", "get_optimization_profile",
        "search_components", "search_components", "search_components",
        "search_components", "search_components", "search_components",
        "search_components", "search_components",
        "check_compatibility",
    ]

    tool_acc = tool_call_accuracy(tool_calls, expected_tools)
    tool_f1 = tool_call_f1(tool_calls, expected_tools)
    goal = agent_goal_accuracy(trace, {})

    print(f"  Tool call accuracy (LCS): {tool_acc:.3f}")
    print(f"  Tool call F1: {tool_f1}")
    print(f"  Goal accuracy: {goal}")

    # ---- LAYER 4: Domain Metrics ----
    if compat_result:
        profile = PROFILES.get("gaming")
        domain = evaluate_domain(
            build={},  # we don't have structured build dict from trace
            compatibility_result=compat_result,
            budget=1500,
            use_case="gaming",
            uncompromisable=profile.uncompromisable if profile else [],
            budget_allocation=profile.budget_allocation if profile else {},
        )
        print(f"\n  Domain score: {domain.overall_score:.3f}")
        print(f"    Compatibility: {'PASS' if domain.compatibility_pass else 'FAIL'}")
        print(f"    Budget adherence: {domain.budget_adherence:.3f}")
        print(f"    Budget utilization: {domain.budget_utilization:.3f}")
        print(f"    PSU headroom: {domain.psu_headroom}")

    # ---- Build Evaluation Report ----
    report = EvaluationReport(
        scenario_id="gaming_1500_expert",
        scenario_name="Expert Gaming PC $1500",
        retrieval_mrr=retrieval_metrics.get("cpu_mrr"),
        retrieval_ndcg_at_5=retrieval_metrics.get("cpu_ndcg_at_5"),
        retrieval_precision_at_5=retrieval_metrics.get("cpu_precision_at_5"),
        retrieval_hit_rate=retrieval_metrics.get("cpu_hit_rate"),
        faithfulness_score=faithfulness_result.get("faithfulness_score"),
        answer_relevancy_score=relevancy_result.get("relevancy_score"),
        tool_call_accuracy_score=tool_acc,
        tool_call_f1_score=tool_f1["f1"],
        goal_accuracy=goal.get("goal_accuracy"),
        domain_score=domain.overall_score if compat_result else None,
        compatibility_pass=domain.compatibility_pass if compat_result else None,
        budget_adherence=domain.budget_adherence if compat_result else None,
    )
    report.compute_overall()

    print("\n" + "=" * 70)
    print(report.summary())
    print("=" * 70)

    # Save report
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_file = reports_dir / "metrics_test_result.json"
    with open(report_file, "w") as f:
        json.dump({
            "report": report.to_dict(),
            "trace_length": len(trace),
            "tool_calls": tool_calls,
            "search_categories": list(search_results.keys()),
            "retrieval_metrics": retrieval_metrics,
            "faithfulness": faithfulness_result,
            "relevancy": relevancy_result,
            "agent_goal": goal,
            "duration_seconds": round(duration, 1),
        }, f, indent=2, default=str)
    print(f"\nFull report saved to: {report_file}")


if __name__ == "__main__":
    run_full_evaluation()
