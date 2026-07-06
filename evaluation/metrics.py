"""
RAG Evaluation Metrics for the PC Configuration Agent.

Four layers of evaluation:
1. Retrieval Quality   — Did we find the right components from the CSV?
2. Generation Quality  — Are claims grounded in data? Does the build match the ask?
3. Agent Quality       — Did it use tools correctly? Did it achieve the goal?
4. Domain Quality      — PC-build-specific: compatibility, budget, uncompromisable items
"""

import json
import logging
import math
import re
from dataclasses import dataclass, field

logger = logging.getLogger("evaluation.metrics")


# =============================================================================
# 1. RETRIEVAL METRICS
#    Evaluate whether the component search returned the right results
# =============================================================================

def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """
    Of the top-K retrieved items, how many are relevant?

    Precision@K = |relevant ∩ retrieved[:k]| / k

    Args:
        retrieved: ordered list of retrieved component names
        relevant: set of ground-truth relevant component names
        k: number of top results to consider
    """
    if k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / k


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """
    Of all relevant items, how many did we retrieve in top-K?

    Recall@K = |relevant ∩ retrieved[:k]| / |relevant|
    """
    if not relevant:
        return 1.0  # nothing to recall
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(relevant)


def hit_rate_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """
    Did we find at least one relevant item in top-K?

    Returns 1.0 if any relevant item is in top-K, else 0.0.
    """
    top_k = retrieved[:k]
    return 1.0 if any(item in relevant for item in top_k) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """
    Reciprocal of the rank of the first relevant item.

    RR = 1 / rank_of_first_relevant_item

    Used to compute MRR (Mean Reciprocal Rank) across queries.
    """
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], relevance_scores: dict[str, float], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain at K.

    Unlike Precision@K, NDCG accounts for:
    - Graded relevance (not just binary)
    - Position (items higher up get more credit)

    NDCG@K = DCG@K / IDCG@K

    Args:
        retrieved: ordered list of retrieved component names
        relevance_scores: dict mapping component name -> relevance score (0-3)
            3 = perfect match, 2 = good, 1 = acceptable, 0 = irrelevant
        k: number of top results
    """
    def dcg(scores: list[float]) -> float:
        return sum(s / math.log2(i + 2) for i, s in enumerate(scores))

    # Actual DCG from retrieved order
    actual_scores = [relevance_scores.get(item, 0.0) for item in retrieved[:k]]
    actual_dcg = dcg(actual_scores)

    # Ideal DCG (best possible ranking)
    ideal_scores = sorted(relevance_scores.values(), reverse=True)[:k]
    ideal_dcg = dcg(ideal_scores)

    if ideal_dcg == 0:
        return 0.0
    return actual_dcg / ideal_dcg


def mean_reciprocal_rank(queries: list[tuple[list[str], set[str]]]) -> float:
    """
    MRR across multiple retrieval queries.

    Args:
        queries: list of (retrieved_items, relevant_items) tuples
    """
    if not queries:
        return 0.0
    return sum(reciprocal_rank(ret, rel) for ret, rel in queries) / len(queries)


# =============================================================================
# 2. GENERATION METRICS (LLM-as-Judge)
#    Evaluate whether the generated response is faithful and relevant
# =============================================================================

FAITHFULNESS_PROMPT = """You are an evaluation judge. Given a PC build recommendation and the actual component data it was based on, evaluate FAITHFULNESS.

Faithfulness measures: are ALL claims in the response supported by the provided data?

## Component Data (Ground Truth):
{context}

## Agent's Response:
{response}

## Task:
1. Extract every factual claim from the response (prices, specs, compatibility statements)
2. For each claim, check if it's supported by the component data
3. Return a JSON object:

{{
    "claims": [
        {{"claim": "RTX 4070 costs $579", "supported": true, "evidence": "Video card price field shows 579.0"}},
        {{"claim": "It has 16GB VRAM", "supported": false, "evidence": "Data shows 12GB, not 16GB"}}
    ],
    "faithfulness_score": <float 0.0 to 1.0>,
    "unsupported_claims": ["list of claims not backed by data"]
}}"""


ANSWER_RELEVANCY_PROMPT = """You are an evaluation judge. Given a user's PC build request and the agent's recommendation, evaluate ANSWER RELEVANCY.

Answer relevancy measures: does the response actually address what the user asked for?

## User's Request:
{question}

## Agent's Response:
{response}

## Task:
Evaluate on these dimensions:
1. Does the build match the stated use case? (gaming build should have strong GPU, ML should have VRAM, etc.)
2. Is the build within the stated budget?
3. Were stated preferences respected? (brand, form factor, etc.)
4. Are all required components included for a functional build?
5. Is the response helpful and complete?

Return a JSON object:
{{
    "relevancy_score": <float 0.0 to 1.0>,
    "use_case_match": <true/false>,
    "budget_match": <true/false>,
    "preferences_respected": <true/false>,
    "complete_build": <true/false>,
    "issues": ["list of relevancy issues, if any"]
}}"""


class LLMJudge:
    """Uses an LLM to evaluate generation quality (faithfulness, relevancy)."""

    def __init__(self, client, model: str = "claude-sonnet-4-5-20250929"):
        self.client = client
        self.model = model

    def evaluate_faithfulness(self, response: str, context: str) -> dict:
        """Score how faithfully the response reflects the retrieved component data."""
        prompt = FAITHFULNESS_PROMPT.format(context=context, response=response)
        return self._call_judge(prompt)

    def evaluate_answer_relevancy(self, question: str, response: str) -> dict:
        """Score how relevant the response is to the user's request."""
        prompt = ANSWER_RELEVANCY_PROMPT.format(question=question, response=response)
        return self._call_judge(prompt)

    def _call_judge(self, prompt: str) -> dict:
        """Call the LLM judge and parse JSON response."""
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            # Extract JSON from potential markdown code blocks
            if "```" in text:
                text = re.sub(r"```(?:json)?\n?", "", text).strip()
            return json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"LLM judge failed: {e}")
            return {"error": str(e), "faithfulness_score": None, "relevancy_score": None}


# =============================================================================
# 3. AGENT METRICS
#    Evaluate the agent's tool usage and goal achievement
# =============================================================================

def tool_call_accuracy(actual_tools: list[str], expected_tools: list[str]) -> float:
    """
    Did the agent call the right tools in the right order?

    Measures overlap between actual tool sequence and expected tool sequence.
    Order-aware: uses longest common subsequence.
    """
    if not expected_tools:
        return 1.0 if not actual_tools else 0.0

    # LCS-based accuracy (order-aware)
    n, m = len(actual_tools), len(expected_tools)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if actual_tools[i - 1] == expected_tools[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_length = dp[n][m]
    return lcs_length / len(expected_tools)


def tool_call_f1(actual_tools: list[str], expected_tools: list[str]) -> dict:
    """
    F1 score for tool usage — combines precision and recall.

    Precision: of the tools the agent called, how many were expected?
    Recall: of the expected tools, how many did the agent call?
    """
    actual_set = set(actual_tools)
    expected_set = set(expected_tools)

    if not actual_set and not expected_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    true_positives = len(actual_set & expected_set)
    precision = true_positives / len(actual_set) if actual_set else 0.0
    recall = true_positives / len(expected_set) if expected_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def agent_goal_accuracy(trace: list[dict], expected_outcome: dict) -> dict:
    """
    Did the agent achieve its goal? Checks multiple success criteria.

    Args:
        trace: agent's full trace (list of events)
        expected_outcome: dict with expected results

    Returns:
        dict with goal achievement metrics
    """
    results = {
        "requirements_gathered": False,
        "compatibility_checked": False,
        "build_presented": False,
        "no_errors": True,
    }

    for event in trace:
        ev = event.get("event", "")
        data = event.get("data", {})

        if ev == "requirements_confirmed":
            results["requirements_gathered"] = True

        if ev == "tool_call" and data.get("tool") == "check_compatibility":
            results["compatibility_checked"] = True
            result_str = data.get("result_preview", "")
            if '"compatible": false' in result_str.lower():
                results["no_errors"] = False

        if ev == "final_response":
            content = data.get("content", "")
            # Check if it looks like a build presentation (has price/component info)
            if "$" in content and any(kw in content.lower() for kw in ["cpu", "gpu", "total"]):
                results["build_presented"] = True

    achieved = sum(results.values())
    total = len(results)
    results["goal_accuracy"] = round(achieved / total, 3)
    return results


# =============================================================================
# 4. DOMAIN-SPECIFIC METRICS
#    PC-build-specific quality checks
# =============================================================================

@dataclass
class DomainEvalResult:
    """Results from domain-specific PC build evaluation."""
    compatibility_pass: bool = False
    budget_adherence: float = 0.0  # 0-1, how close to budget (1.0 = exact)
    budget_utilization: float = 0.0  # fraction of budget used
    uncompromisable_compliance: float = 0.0  # 0-1, did we properly fund critical items
    has_boot_drive: bool = False
    has_display_output: bool = False
    ram_expandability: bool = False
    psu_headroom: bool = False
    overall_score: float = 0.0
    details: dict = field(default_factory=dict)


def evaluate_domain(
    build: dict,
    compatibility_result: dict,
    budget: float,
    use_case: str,
    uncompromisable: list[str],
    budget_allocation: dict[str, float],
) -> DomainEvalResult:
    """
    Evaluate a PC build on domain-specific quality metrics.

    Args:
        build: dict of category -> component details
        compatibility_result: output of check_compatibility
        budget: user's total budget
        use_case: e.g. "gaming", "ml_training"
        uncompromisable: list of category names that shouldn't be cheaped out on
        budget_allocation: recommended budget % per category
    """
    result = DomainEvalResult()

    # 1. Compatibility pass
    result.compatibility_pass = compatibility_result.get("compatible", False)

    # 2. Budget adherence
    total_price = compatibility_result.get("total_price", 0)
    if budget > 0:
        ratio = total_price / budget
        if ratio <= 1.0:
            # Under budget: score based on utilization (using 90%+ of budget is ideal)
            result.budget_utilization = ratio
            result.budget_adherence = min(ratio / 0.9, 1.0)  # 90% utilization = 1.0
        else:
            # Over budget: penalty
            overage = ratio - 1.0
            result.budget_adherence = max(0, 1.0 - overage * 5)  # 20% over = score 0
            result.budget_utilization = ratio

    # 3. Uncompromisable compliance
    # Check if uncompromisable items got at least their fair share of budget
    if uncompromisable and budget_allocation and build:
        compliance_scores = []
        for category in uncompromisable:
            target_pct = budget_allocation.get(category, 0.1)
            target_usd = target_pct * budget
            # Get actual spend on this category
            comp = build.get(category, {})
            actual_usd = comp.get("price", 0) if isinstance(comp, dict) else 0
            if target_usd > 0:
                ratio = actual_usd / target_usd
                # Score: 1.0 if at or above target, penalize if below
                score = min(ratio, 1.0)
                compliance_scores.append(score)
        if compliance_scores:
            result.uncompromisable_compliance = sum(compliance_scores) / len(compliance_scores)

    # 4. Has NVMe boot drive
    storage_list = build.get("storage", [])
    if isinstance(storage_list, list):
        result.has_boot_drive = any(
            isinstance(s, dict) and s.get("storage_type") == "NVMe SSD"
            for s in storage_list
        )
    elif isinstance(storage_list, dict):
        result.has_boot_drive = storage_list.get("storage_type") == "NVMe SSD"

    # 5. Has display output (GPU or iGPU)
    has_gpu = "gpu" in build and build["gpu"] is not None and build["gpu"] != {}
    cpu_data = build.get("cpu", {})
    has_igpu = isinstance(cpu_data, dict) and cpu_data.get("graphics", "None") != "None"
    result.has_display_output = bool(has_gpu or has_igpu)

    # 6. RAM expandability (2 sticks in 4-slot board)
    mem = build.get("memory", {})
    mobo = build.get("motherboard", {})
    if isinstance(mem, dict) and isinstance(mobo, dict):
        module_count = mem.get("module_count", 0)
        slot_count = mobo.get("memory_slots", 0)
        result.ram_expandability = module_count < slot_count

    # 7. PSU headroom (at least 20% over estimated draw)
    power_draw = compatibility_result.get("estimated_power_draw", 0)
    psu = build.get("psu", {})
    psu_wattage = psu.get("wattage", 0) if isinstance(psu, dict) else 0
    if power_draw > 0 and psu_wattage > 0:
        result.psu_headroom = psu_wattage >= power_draw * 1.2

    # Overall score (weighted)
    weights = {
        "compatibility": 0.25,
        "budget": 0.20,
        "uncompromisable": 0.20,
        "boot_drive": 0.10,
        "display": 0.10,
        "ram_expand": 0.08,
        "psu_headroom": 0.07,
    }
    score = (
        weights["compatibility"] * (1.0 if result.compatibility_pass else 0.0)
        + weights["budget"] * result.budget_adherence
        + weights["uncompromisable"] * result.uncompromisable_compliance
        + weights["boot_drive"] * (1.0 if result.has_boot_drive else 0.0)
        + weights["display"] * (1.0 if result.has_display_output else 0.0)
        + weights["ram_expand"] * (1.0 if result.ram_expandability else 0.0)
        + weights["psu_headroom"] * (1.0 if result.psu_headroom else 0.0)
    )
    result.overall_score = round(score, 3)

    result.details = {
        "total_price": total_price,
        "budget": budget,
        "power_draw": power_draw,
        "psu_wattage": psu_wattage,
        "use_case": use_case,
    }

    return result


# =============================================================================
# 5. AGGREGATE EVALUATION
#    Combines all metrics into a single evaluation report
# =============================================================================

@dataclass
class EvaluationReport:
    """Complete evaluation report for one agent run."""
    scenario_id: str
    scenario_name: str

    # Retrieval metrics
    retrieval_precision_at_5: float | None = None
    retrieval_mrr: float | None = None
    retrieval_hit_rate: float | None = None
    retrieval_ndcg_at_5: float | None = None

    # Generation metrics (LLM-judged)
    faithfulness_score: float | None = None
    answer_relevancy_score: float | None = None

    # Agent metrics
    tool_call_accuracy_score: float | None = None
    tool_call_f1_score: float | None = None
    goal_accuracy: float | None = None

    # Domain metrics
    domain_score: float | None = None
    compatibility_pass: bool | None = None
    budget_adherence: float | None = None
    uncompromisable_compliance: float | None = None

    # Overall
    overall_score: float | None = None

    def compute_overall(self) -> float:
        """Weighted average of all available metrics."""
        scores = []
        weights = []

        metric_weights = {
            "faithfulness": (self.faithfulness_score, 0.20),
            "relevancy": (self.answer_relevancy_score, 0.15),
            "domain": (self.domain_score, 0.25),
            "goal": (self.goal_accuracy, 0.15),
            "tool_f1": (self.tool_call_f1_score, 0.10),
            "retrieval_mrr": (self.retrieval_mrr, 0.10),
            "retrieval_ndcg": (self.retrieval_ndcg_at_5, 0.05),
        }

        for name, (value, weight) in metric_weights.items():
            if value is not None:
                scores.append(value * weight)
                weights.append(weight)

        if not weights:
            return 0.0

        # Normalize weights to sum to 1
        total_weight = sum(weights)
        self.overall_score = round(sum(scores) / total_weight, 3)
        return self.overall_score

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "retrieval": {
                "precision_at_5": self.retrieval_precision_at_5,
                "mrr": self.retrieval_mrr,
                "hit_rate": self.retrieval_hit_rate,
                "ndcg_at_5": self.retrieval_ndcg_at_5,
            },
            "generation": {
                "faithfulness": self.faithfulness_score,
                "answer_relevancy": self.answer_relevancy_score,
            },
            "agent": {
                "tool_call_accuracy": self.tool_call_accuracy_score,
                "tool_call_f1": self.tool_call_f1_score,
                "goal_accuracy": self.goal_accuracy,
            },
            "domain": {
                "overall": self.domain_score,
                "compatibility_pass": self.compatibility_pass,
                "budget_adherence": self.budget_adherence,
                "uncompromisable_compliance": self.uncompromisable_compliance,
            },
            "overall_score": self.overall_score,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f"=== {self.scenario_name} ==="]
        if self.retrieval_mrr is not None:
            lines.append(f"  Retrieval MRR:           {self.retrieval_mrr:.3f}")
        if self.retrieval_ndcg_at_5 is not None:
            lines.append(f"  Retrieval NDCG@5:        {self.retrieval_ndcg_at_5:.3f}")
        if self.faithfulness_score is not None:
            lines.append(f"  Faithfulness:            {self.faithfulness_score:.3f}")
        if self.answer_relevancy_score is not None:
            lines.append(f"  Answer Relevancy:        {self.answer_relevancy_score:.3f}")
        if self.tool_call_f1_score is not None:
            lines.append(f"  Tool Call F1:            {self.tool_call_f1_score:.3f}")
        if self.goal_accuracy is not None:
            lines.append(f"  Goal Accuracy:           {self.goal_accuracy:.3f}")
        if self.domain_score is not None:
            lines.append(f"  Domain Score:            {self.domain_score:.3f}")
        if self.compatibility_pass is not None:
            lines.append(f"    Compatibility:         {'PASS' if self.compatibility_pass else 'FAIL'}")
        if self.budget_adherence is not None:
            lines.append(f"    Budget Adherence:      {self.budget_adherence:.3f}")
        if self.uncompromisable_compliance is not None:
            lines.append(f"    Uncompromisable:       {self.uncompromisable_compliance:.3f}")
        if self.overall_score is not None:
            lines.append(f"  OVERALL:                 {self.overall_score:.3f}")
        return "\n".join(lines)
