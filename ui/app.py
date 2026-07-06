"""Streamlit UI for the PC Configuration Agent."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import anthropic

from src.config import ANTHROPIC_API_KEY, MODEL_NAME, MAX_AGENT_TURNS, DATA_DIR
from src.data.loader import ComponentStore
from src.engine.compatibility import CompatibilityChecker
from src.engine.optimizer import UseCaseOptimizer, PROFILES
from src.engine.validator import RequirementValidator
from src.agent.tools import ToolDispatcher
from src.agent.loop import AgentLoop

# ---- Constants ----
CATEGORY_ICONS = {
    "cpu": "🧠", "motherboard": "🔲", "memory": "🧮", "gpu": "🎮",
    "storage": "💾", "psu": "⚡", "case": "🖥️", "cpu_cooler": "❄️",
    "monitor": "🖵", "keyboard": "⌨️", "mouse": "🖱️", "headphones": "🎧",
    "speakers": "🔊", "webcam": "📷", "sound_card": "🎵",
    "wired_network_card": "🔌", "wireless_network_card": "📶",
    "case_fan": "🌀", "fan_controller": "🎛️", "thermal_paste": "💧",
    "optical_drive": "💿", "external_hard_drive": "📦",
    "ups": "🔋", "os": "💻", "case_accessory": "🔧",
}
CATEGORY_LABELS = {
    "cpu": "Processor (CPU)", "motherboard": "Motherboard", "memory": "Memory (RAM)",
    "gpu": "Graphics Card (GPU)", "storage": "Storage", "psu": "Power Supply",
    "case": "Case", "cpu_cooler": "CPU Cooler", "monitor": "Monitor",
    "keyboard": "Keyboard", "mouse": "Mouse", "headphones": "Headphones",
    "speakers": "Speakers", "webcam": "Webcam", "sound_card": "Sound Card",
    "wired_network_card": "Wired Network Card", "wireless_network_card": "WiFi Card",
    "case_fan": "Case Fan", "fan_controller": "Fan Controller",
    "thermal_paste": "Thermal Paste", "optical_drive": "Optical Drive",
    "external_hard_drive": "External Storage", "ups": "UPS (Battery Backup)",
    "os": "Operating System", "case_accessory": "Case Accessory",
}
CORE_CATEGORIES = ["cpu", "motherboard", "memory", "gpu", "storage", "psu", "case", "cpu_cooler"]
OPTIONAL_CATEGORIES = [
    "monitor", "keyboard", "mouse", "headphones", "speakers", "webcam",
    "sound_card", "wireless_network_card", "wired_network_card",
    "case_fan", "thermal_paste", "ups", "os",
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def init_state():
    if "store" not in st.session_state:
        st.session_state.store = ComponentStore(DATA_DIR)
    for key, default in [("messages", []), ("agent", None), ("builds", []),
                          ("selected_build", None), ("_responding", False)]:
        if key not in st.session_state:
            st.session_state[key] = default


def get_agent():
    if st.session_state.agent is None:
        if not ANTHROPIC_API_KEY:
            st.error("ANTHROPIC_API_KEY not set. Add it to `.env` file.")
            return None
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        store = st.session_state.store
        checker = CompatibilityChecker(store)
        optimizer = UseCaseOptimizer(store)
        validator = RequirementValidator(client, model=MODEL_NAME)
        dispatcher = ToolDispatcher(store, optimizer, checker)
        st.session_state.agent = AgentLoop(
            client=client, dispatcher=dispatcher,
            store_stats=store.get_summary_stats(),
            validator=validator, model=MODEL_NAME,
            max_turns=MAX_AGENT_TURNS,
        )
    return st.session_state.agent


def get_key_spec(component: dict, category: str) -> str:
    specs = {
        "cpu": lambda c: f"{c.get('core_count', '?')} cores, {c.get('boost_clock', '?')} GHz, {c.get('socket', '?')}",
        "motherboard": lambda c: f"{c.get('socket', '?')}, {c.get('form_factor', '?')}, DDR{c.get('ddr_generation', '?')}",
        "memory": lambda c: f"{c.get('total_gb', '?')}GB DDR{c.get('ddr_generation', '?')}-{c.get('speed_mhz', '?')}",
        "gpu": lambda c: f"{c.get('chipset', '?')}, {c.get('memory', '?')}GB, {c.get('estimated_tdp', '?')}W",
        "storage": lambda c: f"{c.get('capacity', '?')}GB {c.get('storage_type', '?')}",
        "psu": lambda c: f"{c.get('wattage', '?')}W {c.get('efficiency', '?') or ''} {c.get('modular', '')}",
        "case": lambda c: f"{c.get('type', '?')}",
        "cpu_cooler": lambda c: f"{c.get('cooler_type', '?')}" + (f", {c.get('radiator_size_mm')}mm" if c.get('radiator_size_mm') else ""),
        "monitor": lambda c: f"{c.get('screen_size', '?')}\" {c.get('resolution', '?')} {c.get('refresh_rate', '?')}Hz",
        "keyboard": lambda c: f"{c.get('style', '?')} {c.get('switches', '') or ''}",
        "mouse": lambda c: f"{c.get('tracking_method', '?')} {c.get('max_dpi', '?')} DPI",
        "headphones": lambda c: f"{c.get('type', '?')} {c.get('enclosure_type', '') or ''}",
        "wireless_network_card": lambda c: f"{c.get('protocol', '?')} {c.get('interface', '?')}",
    }
    try:
        return specs.get(category, lambda c: "")(component)
    except Exception:
        return ""


def format_tool_step(tool_name: str, tool_input: dict) -> str:
    if tool_name == "confirm_requirements":
        return f"📋 **Confirming requirements** — {tool_input.get('use_case', '?')}, ${tool_input.get('budget', '?')}"
    elif tool_name == "get_optimization_profile":
        return f"📊 **Getting optimization profile** for {tool_input.get('use_case', '?')} @ ${tool_input.get('total_budget', '?')}"
    elif tool_name == "search_components":
        cat = tool_input.get('category', '?')
        icon = CATEGORY_ICONS.get(cat, '🔍')
        f_str = ""
        filters = tool_input.get('filters', {})
        if filters.get('max_price'): f_str += f" <${filters['max_price']}"
        if filters.get('socket'): f_str += f" {filters['socket']}"
        if filters.get('chipset_contains'): f_str += f" '{filters['chipset_contains']}'"
        return f"{icon} **Searching {CATEGORY_LABELS.get(cat, cat)}**{f_str}"
    elif tool_name == "check_compatibility":
        return "✅ **Checking compatibility...**"
    elif tool_name == "optimize_build":
        return "⚡ **Optimizing build...**"
    elif tool_name == "get_component_details":
        return f"🔎 **Looking up** {tool_input.get('name', '?')}"
    return f"🔧 **{tool_name}**"


THINKING_CSS = """
<style>
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.thinking-box {
    border: 1px solid #333; border-radius: 10px; padding: 12px 16px; margin-bottom: 8px;
    background: #0e1117;
}
.thinking-header {
    display: flex; align-items: center; gap: 10px; cursor: pointer;
}
.thinking-spinner {
    width: 18px; height: 18px; border: 2.5px solid #333; border-top: 2.5px solid #00d4ff;
    border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; flex-shrink: 0;
}
.thinking-current {
    color: #00d4ff; font-weight: 600; animation: pulse 1.5s ease-in-out infinite; font-size: 0.95em;
}
.thinking-count {
    color: #666; font-size: 0.8em; margin-left: auto;
}
</style>
"""


def _render_thinking(steps: list[str]) -> str:
    """Show only the latest step with spinner. Previous steps in a collapsed details tag."""
    if not steps:
        return THINKING_CSS + """<div class="thinking-box"><div class="thinking-header">
        <div class="thinking-spinner"></div>
        <span class="thinking-current">Connecting...</span></div></div>"""

    current = steps[-1]
    count = len(steps)

    if count <= 1:
        return THINKING_CSS + f"""<div class="thinking-box"><div class="thinking-header">
        <div class="thinking-spinner"></div>
        <span class="thinking-current">{current}</span></div></div>"""

    # Build collapsed previous steps
    prev_html = ""
    for s in steps[:-1]:
        prev_html += f'<div style="color: #666; padding: 2px 0 2px 28px; font-size: 0.85em;">✓ {s}</div>\n'

    return THINKING_CSS + f"""<div class="thinking-box">
    <div class="thinking-header">
        <div class="thinking-spinner"></div>
        <span class="thinking-current">{current}</span>
        <span class="thinking-count">{count} steps</span>
    </div>
    <details style="margin-top: 8px;">
        <summary style="color: #555; font-size: 0.8em; cursor: pointer;">Show previous steps</summary>
        <div style="margin-top: 6px;">{prev_html}</div>
    </details>
</div>"""


def send_message_and_get_response(user_msg: str):
    """Send a user message to the agent and get the response with live thinking display."""
    agent = get_agent()
    if not agent:
        return

    with st.chat_message("assistant"):
        thinking = st.empty()
        steps = []

        # Show spinner immediately before any LLM call
        thinking.markdown(
            _render_thinking(["Connecting to AI..."]),
            unsafe_allow_html=True,
        )

        original_execute = agent.dispatcher.execute

        # Also patch the LLM call to show "Reasoning..." between tool calls
        original_call_llm = agent._call_llm
        call_count = [0]

        def tracked_llm():
            call_count[0] += 1
            if call_count[0] > 1:
                # Between tool results and next response — LLM is reasoning
                steps.append("💭 *Reasoning over results...*")
                thinking.markdown(_render_thinking(steps), unsafe_allow_html=True)
            else:
                steps.clear()
                steps.append("💭 *Reading your message...*")
                thinking.markdown(_render_thinking(steps), unsafe_allow_html=True)
            return original_call_llm()

        def tracked_tool(tool_name, tool_input):
            steps.append(format_tool_step(tool_name, tool_input))
            thinking.markdown(_render_thinking(steps), unsafe_allow_html=True)
            return original_execute(tool_name, tool_input)

        agent.dispatcher.execute = tracked_tool
        agent._call_llm = tracked_llm
        response = agent.chat(user_msg)
        agent.dispatcher.execute = original_execute
        agent._call_llm = original_call_llm

        thinking.empty()

        # Typewriter effect — stream the response character by character
        response_container = st.empty()
        displayed = ""
        # Stream in chunks of words for natural feel
        words = response.split(" ")
        for i, word in enumerate(words):
            displayed += word + " "
            # Render every few words for smooth but fast streaming
            if i % 3 == 0 or i == len(words) - 1:
                response_container.markdown(displayed + "▌")
                import time as _time
                _time.sleep(0.02)
        # Final render without cursor
        response_container.markdown(response)

        # Price verification — catch LLM arithmetic errors
        price_warning = verify_prices_in_response(response, agent)
        if price_warning:
            st.warning(price_warning, icon="⚠️")
            response += f"\n\n---\n*⚠️ Price correction: {price_warning}*"

    st.session_state.messages.append({"role": "assistant", "content": response})
    extract_builds_from_trace(agent)


def verify_prices_in_response(response: str, agent) -> str | None:
    """
    Mechanical price check — catches LLM arithmetic errors on the FULL BUILD total.
    Only flags when the agent claims a total that should match check_compatibility but doesn't.
    Does NOT flag peripheral subtotals, option prices, or partial sums.
    """
    import re

    # 1. Get the actual total from the last check_compatibility call
    actual_total = None
    for event in agent.get_trace():
        if (event.get("event") == "tool_call"
                and event.get("data", {}).get("tool") == "check_compatibility"):
            try:
                result_str = event["data"].get("result_preview", "{}")
                result = json.loads(result_str)
                if result.get("total_price"):
                    actual_total = result["total_price"]
            except (json.JSONDecodeError, KeyError):
                pass

    if actual_total is None:
        return None  # no compatibility check was run, nothing to verify

    # 2. Look for a FULL BUILD total — not peripheral subtotals
    # Only match patterns that look like THE build total, not option/subtotals
    # e.g. "Total Build Cost: $1,234" or "Grand Total: $1234" or "**Total: $1234**"
    # Exclude: "Option A Total: $120" or "Peripherals Total: $68"
    build_total_patterns = [
        r'(?:build|pc|system|core|grand|overall|full)\s*(?:cost|price)?\s*(?:total)?[:\s]*\*?\*?\$?([\d,]+\.?\d*)',
        r'(?:total|Total|TOTAL)\s*(?:build|pc|system|cost|price)?[:\s]*\*?\*?\$?([\d,]+\.?\d*)',
    ]

    # Exclude context: if "total" appears near peripheral/option words, skip it
    peripheral_context_words = [
        "option a", "option b", "option c", "peripheral", "keyboard", "mouse",
        "combo", "setup total", "accessories total", "add-on",
    ]

    claimed_build_totals = []
    response_lower = response.lower()

    for pattern in build_total_patterns:
        for match in re.finditer(pattern, response_lower):
            try:
                val = float(match.group(1).replace(",", ""))
                if val < 200:
                    continue  # too small to be a full build total

                # Check surrounding context — is this near peripheral words?
                start = max(0, match.start() - 80)
                context = response_lower[start:match.end()]
                is_peripheral = any(pw in context for pw in peripheral_context_words)
                if is_peripheral:
                    continue

                claimed_build_totals.append(val)
            except ValueError:
                pass

    if not claimed_build_totals:
        return None  # no build total found

    # 3. Check if the closest claimed total matches the actual
    # Find the claimed total closest to the actual (in case there are multiple)
    closest = min(claimed_build_totals, key=lambda x: abs(x - actual_total))

    warnings = []
    if abs(closest - actual_total) > 10.0:
        warnings.append(
            f"The stated build total (${closest:.2f}) doesn't match the verified total "
            f"(${actual_total:.2f}) from the compatibility check. "
            f"The correct total for the core build is **${actual_total:.2f}**."
        )

    return " ".join(warnings) if warnings else None


def extract_builds_from_trace(agent):
    for event in agent.get_trace():
        if event.get("event") == "tool_call" and event.get("data", {}).get("tool") == "check_compatibility":
            try:
                result_str = event["data"].get("result_preview", "{}")
                result = json.loads(result_str) if isinstance(result_str, str) else result_str
                if result.get("compatible", False):
                    build_input = event["data"].get("input", {})
                    build = {
                        "name": f"Build {len(st.session_state.builds) + 1}",
                        "components": build_input,
                        "total_price": result.get("total_price", 0),
                        "power_draw": result.get("estimated_power_draw", 0),
                        "compatible": True,
                        "warnings": result.get("warnings", []),
                    }
                    existing = [b["components"] for b in st.session_state.builds]
                    if build_input not in existing:
                        st.session_state.builds.append(build)
            except (json.JSONDecodeError, KeyError):
                pass


def render_build_sidebar():
    """Render the build in the sidebar."""
    with st.sidebar:
        st.divider()
        if st.session_state.builds:
            st.markdown("### 🔧 Your Build")
            build = st.session_state.builds[-1]  # latest build
            components = build.get("components", {})
            for cat in CORE_CATEGORIES:
                comp_name = components.get(cat)
                if comp_name:
                    if isinstance(comp_name, list):
                        comp_name = ", ".join(comp_name)
                    icon = CATEGORY_ICONS.get(cat, "📦")
                    st.markdown(f"{icon} **{CATEGORY_LABELS.get(cat, cat)}**")
                    st.caption(f"  {comp_name}")
            st.divider()
            st.markdown(f"💰 **Total: ${build.get('total_price', 0):.2f}**")
            st.caption(f"⚡ ~{build.get('power_draw', 0)}W")
        else:
            st.markdown("""<div style="text-align: center; padding: 20px; color: #666;">
            <div style="font-size: 2em;">🔧</div><p>Build appears here</p></div>""",
                        unsafe_allow_html=True)

        if st.button("🔄 Start Over", use_container_width=True):
            for key in ["messages", "builds", "selected_build"]:
                st.session_state[key] = [] if key != "selected_build" else None
            st.session_state.agent = None
            st.session_state._responding = False
            st.rerun()


def generate_sample_builds(store, use_case, budget):
    builds = []
    profile = PROFILES.get(use_case)
    if not profile:
        return []
    for tier_name, mult in [("💰 Budget", 0.70), ("⭐ Recommended", 1.0), ("🚀 Premium", 1.25)]:
        alloc = {k: v * budget * mult for k, v in profile.budget_allocation.items()}
        comp = {}
        cpus = store.search_cpus(max_price=alloc.get("cpu", 200), min_cores=4, sort_by="value", limit=5)
        if cpus:
            comp["cpu"] = cpus[0]["name"]
            socket = cpus[0].get("socket")
            mobos = store.search_motherboards(socket=socket, max_price=alloc.get("motherboard", 150), limit=5)
            if mobos:
                comp["motherboard"] = mobos[-1]["name"]
                ddr = mobos[-1].get("ddr_generation")
                mems = store.search_memory(ddr_generation=ddr, min_total_gb=16, max_price=alloc.get("memory", 100), limit=5)
                if mems: comp["memory"] = mems[-1]["name"]
        if use_case not in ("office", "home_server"):
            gpus = store.search_gpus(max_price=alloc.get("gpu", 400), sort_by="value", limit=5)
            if gpus: comp["gpu"] = gpus[0]["name"]
        drives = store.search_storage(storage_type="NVMe SSD", min_capacity_gb=500, max_price=alloc.get("storage", 100), sort_by="value", limit=3)
        if drives: comp["storage"] = [drives[0]["name"]]
        coolers = store.search_coolers(max_price=alloc.get("cooler", 50), limit=3)
        if coolers: comp["cpu_cooler"] = coolers[-1]["name"]
        psus = store.search_psus(min_wattage=550, max_price=alloc.get("psu", 80), limit=3)
        if psus: comp["psu"] = psus[-1]["name"]
        cases = store.search_cases(max_price=alloc.get("case", 70), limit=3)
        if cases: comp["case"] = cases[-1]["name"]
        total = sum(store.get_component_by_name(c, n).get("price", 0) for c, n in
                    ((c, nn) for c, v in comp.items() for nn in (v if isinstance(v, list) else [v]))
                    if store.get_component_by_name(c, n))
        builds.append({"name": tier_name, "components": comp, "total_price": round(total, 2),
                        "power_draw": 350, "compatible": True, "warnings": []})
    return builds


# =============================================================================
# PAGE CONFIG & STYLES
# =============================================================================
st.set_page_config(page_title="PC Configuration Agent", page_icon="🖥️", layout="wide",
                   initial_sidebar_state="expanded")
init_state()

st.markdown("""<style>
/* Smooth fade-in for all content */
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
.stApp > header + div { animation: fadeIn 0.4s ease-out; }

/* Landing cards hover effect */
.landing-card {
    border: 1px solid #333; border-radius: 16px; padding: 28px; text-align: center;
    min-height: 200px; transition: all 0.3s ease; cursor: pointer;
}
.landing-card:hover {
    border-color: #00d4ff; transform: translateY(-4px);
    box-shadow: 0 8px 25px rgba(0, 212, 255, 0.15);
}

/* Chat input pinned to bottom */
[data-testid="stChatInput"] { position: sticky; bottom: 0; z-index: 100; }

/* Smooth build sidebar */
.build-item { padding: 4px 0; border-bottom: 1px solid #222; }
</style>""", unsafe_allow_html=True)

# Sidebar nav
st.sidebar.title("🖥️ PC Config Agent")
page = st.sidebar.radio("Navigate", ["💬 Build Assistant", "📊 Browse Components", "🔍 Compare Builds"],
                        label_visibility="collapsed")

# =============================================================================
# PAGE 1: Build Assistant
# =============================================================================
if page == "💬 Build Assistant":
    has_conversation = len(st.session_state.messages) > 0

    if not has_conversation:
        # ---- LANDING PAGE ----
        st.markdown("")
        st.markdown("")
        st.markdown("""<div style="text-align: center; padding: 30px 0 10px 0; animation: fadeIn 0.6s ease-out;">
            <h1 style="font-size: 2.8em; margin-bottom: 0; background: linear-gradient(135deg, #00d4ff, #7b68ee);
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                PC Build Assistant
            </h1>
            <p style="font-size: 1.15em; color: #888; margin-top: 12px;">
                Tell me what you need — I'll configure the perfect build.
            </p>
        </div>""", unsafe_allow_html=True)

        st.markdown("")
        st.markdown("")

        def _on_quick_start(msg):
            """on_click callback — sets state BEFORE the next render cycle."""
            st.session_state.messages = [{"role": "user", "content": msg}]

        c1, c2, c3 = st.columns(3, gap="large")
        cards = [
            (c1, "🎮", "Gaming PC", "$1,500 budget", "1440p AAA gaming", "qs_g",
             "I want to build a gaming PC for about $1500. I play AAA games at 1440p."),
            (c2, "🧪", "ML Workstation", "$3,000 budget", "Maximum GPU VRAM", "qs_m",
             "I need a machine learning training workstation. Budget is $3000. I need maximum GPU VRAM."),
            (c3, "💼", "Office PC", "$500 budget", "Web & spreadsheets", "qs_o",
             "I need a basic office computer for web browsing and spreadsheets. Under $500."),
        ]
        for col, emoji, title, line1, line2, key, msg in cards:
            with col:
                st.markdown(f"""<div class="landing-card">
                    <div style="font-size: 3.5em; margin-bottom: 8px;">{emoji}</div>
                    <h3 style="margin: 0;">{title}</h3>
                    <p style="color: #888; font-size: 0.9em; margin-top: 8px;">{line1}<br/>{line2}</p>
                </div>""", unsafe_allow_html=True)
                st.button(f"Start {title.split()[0]} Build", use_container_width=True, key=key,
                          on_click=_on_quick_start, args=(msg,))

        st.markdown("")
        st.markdown("---")

        if prompt := st.chat_input("Or just describe what you need..."):
            st.session_state.messages.append({"role": "user", "content": prompt})

    else:
        # ---- CONVERSATION VIEW (full-width chat, build in sidebar) ----
        render_build_sidebar()

        # Check if we need to auto-respond (last message is user, no assistant reply yet)
        needs_response = (
            st.session_state.messages
            and st.session_state.messages[-1]["role"] == "user"
            and not st.session_state._responding
        )

        # Render all existing messages FIRST (so user sees the chat immediately)
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # NOW auto-respond — the chat UI is already visible, user sees their message
        # and the thinking indicator appears below it in real-time
        if needs_response:
            st.session_state._responding = True
            last_msg = st.session_state.messages[-1]["content"]
            send_message_and_get_response(last_msg)
            st.session_state._responding = False
            # Rerun to clean up state and show the final response properly
            st.rerun()

        # Chat input — full width, pinned to bottom
        if prompt := st.chat_input("Type your message..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()


# =============================================================================
# PAGE 2: Browse Components
# =============================================================================
elif page == "📊 Browse Components":
    st.title("📊 Browse Components")
    store = st.session_state.store
    stats = store.get_summary_stats()

    categories = sorted([c for c, i in stats.items() if isinstance(i, dict) and i.get("count", 0) > 0])
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        selected_cat = st.selectbox("Category", categories,
            format_func=lambda x: f"{CATEGORY_ICONS.get(x, '📦')} {CATEGORY_LABELS.get(x, x)} ({stats[x]['count']})")
    with c2:
        max_price = st.number_input("Max Price ($)", min_value=0, value=0, step=50, help="0 = no limit")
    with c3:
        limit = st.slider("Results", 5, 50, 20)

    search_map = {
        "cpu": lambda: store.search_cpus(max_price=max_price or None, limit=limit),
        "motherboard": lambda: store.search_motherboards(max_price=max_price or None, limit=limit),
        "memory": lambda: store.search_memory(max_price=max_price or None, limit=limit),
        "gpu": lambda: store.search_gpus(max_price=max_price or None, limit=limit),
        "storage": lambda: store.search_storage(max_price=max_price or None, limit=limit),
        "psu": lambda: store.search_psus(max_price=max_price or None, limit=limit),
        "case": lambda: store.search_cases(max_price=max_price or None, limit=limit),
        "cpu_cooler": lambda: store.search_coolers(max_price=max_price or None, limit=limit),
    }
    results = search_map.get(selected_cat, lambda: store.search_generic(selected_cat, max_price=max_price or None, limit=limit))()

    if results:
        st.markdown(f"**{len(results)} results** in {CATEGORY_LABELS.get(selected_cat, selected_cat)}")
        for comp in results:
            icon = CATEGORY_ICONS.get(selected_cat, "📦")
            spec = get_key_spec(comp, selected_cat)
            cc1, cc2, cc3 = st.columns([3, 4, 1])
            with cc1: st.markdown(f"### {icon} {comp['name']}")
            with cc2: st.caption(spec)
            with cc3: st.markdown(f"**${comp['price']:.2f}**")
            with st.expander("Full Specs"):
                cols = st.columns(3)
                for idx, (k, v) in enumerate((k, v) for k, v in comp.items() if v is not None and k != "name"):
                    with cols[idx % 3]: st.metric(k.replace("_", " ").title(), str(v))
            st.divider()
    else:
        st.warning("No components found.")


# =============================================================================
# PAGE 3: Compare Builds
# =============================================================================
elif page == "🔍 Compare Builds":
    st.title("🔍 Compare Builds")
    store = st.session_state.store

    if not st.session_state.builds:
        st.info("No builds yet. Generate sample builds or use the Build Assistant.")
        use_case = st.selectbox("Use Case", list(PROFILES.keys()), format_func=lambda x: PROFILES[x].display_name)
        budget = st.number_input("Budget ($)", 300, 10000, 1500, 100)
        if st.button("Generate Sample Builds"):
            st.session_state.builds = generate_sample_builds(store, use_case, budget)
            st.rerun()
    else:
        cols = st.columns(min(len(st.session_state.builds), 3))
        for idx, build in enumerate(st.session_state.builds[:3]):
            with cols[idx]:
                is_sel = st.session_state.selected_build == idx
                border = "#00d4ff" if is_sel else "#444"
                st.markdown(f"""<div style="border: 2px solid {border}; border-radius: 12px; padding: 16px;">
                <h3>{'✅ ' if is_sel else ''}{build['name']}</h3></div>""", unsafe_allow_html=True)
                for cat in CORE_CATEGORIES:
                    name = build["components"].get(cat)
                    if name:
                        if isinstance(name, list): name = ", ".join(name)
                        st.markdown(f"{CATEGORY_ICONS.get(cat, '📦')} **{CATEGORY_LABELS.get(cat, cat)}**")
                        st.caption(f"  {name}")
                st.divider()
                st.markdown(f"💰 **${build['total_price']:.2f}**")
                if st.button("Select" if not is_sel else "✅ Selected", key=f"sel_{idx}",
                             type="primary" if is_sel else "secondary", use_container_width=True):
                    st.session_state.selected_build = idx
                    st.rerun()

        if st.button("Clear Builds"):
            st.session_state.builds = []
            st.session_state.selected_build = None
            st.rerun()

        st.divider()
        st.subheader("🎮 Optional Peripherals")
        pcols = st.columns(4)
        for i, cat in enumerate(c for c in OPTIONAL_CATEGORIES if c not in ("os", "ups", "case_fan", "thermal_paste")):
            with pcols[i % 4]:
                if st.checkbox(f"{CATEGORY_ICONS.get(cat, '📦')} {CATEGORY_LABELS.get(cat, cat)}", key=f"p_{cat}"):
                    for comp in store.search_generic(cat, limit=3):
                        st.markdown(f"**{comp['name']}** — ${comp['price']:.2f}")
                        st.caption(get_key_spec(comp, cat))
