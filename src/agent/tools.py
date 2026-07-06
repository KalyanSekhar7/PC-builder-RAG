"""Tool definitions and dispatch for the PC Configuration Agent."""

import json
import logging

from ..data.loader import ComponentStore
from ..engine.compatibility import CompatibilityChecker
from ..engine.optimizer import UseCaseOptimizer

logger = logging.getLogger("agent.tools")


# All searchable component categories — matches every CSV in the dataset
ALL_CATEGORIES = [
    # Core components (required for every build)
    "cpu", "motherboard", "memory", "gpu", "storage", "psu", "case", "cpu_cooler",
    # Peripherals
    "monitor", "keyboard", "mouse", "headphones", "speakers", "webcam",
    # Expansion / networking
    "sound_card", "wired_network_card", "wireless_network_card",
    # Accessories
    "case_fan", "fan_controller", "thermal_paste", "optical_drive",
    "external_hard_drive", "case_accessory",
    # Power / OS
    "ups", "os",
]


# ---- Tool Schemas (Anthropic format) ----

TOOL_DEFINITIONS = [
    {
        "name": "confirm_requirements",
        "description": (
            "Call this tool ONCE you have gathered the user's requirements through conversation. "
            "You MUST call this before searching for any components. "
            "Record everything the user has told you — use case, budget, expertise, preferences. "
            "If you don't have budget, use case, and expertise level yet, keep asking — do NOT call this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "use_case": {
                    "type": "string",
                    "description": "Primary use case (gaming, ml_training, ml_inference, content_creation, office, software_dev, streaming, home_server, workstation)",
                },
                "budget": {
                    "type": "number",
                    "description": "Total budget in USD",
                },
                "expertise_level": {
                    "type": "string",
                    "enum": ["newbie", "intermediate", "expert"],
                    "description": (
                        "User's PC building expertise. "
                        "newbie: knows what they want to DO with the PC but not hardware details. "
                        "intermediate: knows about CPUs, GPUs, RAM, storage but not coolers, PSUs, fans, thermal paste. "
                        "expert: knows every component, wants to choose/approve each one individually."
                    ),
                },
                "preferences": {
                    "type": "object",
                    "description": "All user preferences gathered so far",
                    "properties": {
                        "cpu_brand": {"type": "string", "description": "AMD or Intel preference"},
                        "gpu_brand": {"type": "string", "description": "NVIDIA, AMD, or Intel preference"},
                        "form_factor": {"type": "string", "description": "Full tower, mid tower, ITX, etc."},
                        "noise_preference": {"type": "string", "description": "silent, quiet, don't care"},
                        "color_preference": {"type": "string"},
                        "resolution": {"type": "string", "description": "1080p, 1440p, 4K"},
                        "needs_monitor": {"type": "boolean", "description": "Include monitor in budget?"},
                        "needs_peripherals": {"type": "boolean", "description": "Include keyboard/mouse/headphones?"},
                        "needs_wifi": {"type": "boolean", "description": "Need wireless networking?"},
                        "needs_os": {"type": "boolean", "description": "Include OS in budget?"},
                        "expandability": {"type": "boolean", "description": "Want room to upgrade later?"},
                        "cooling_preference": {"type": "string", "description": "air, liquid, no preference"},
                        "specific_requirements": {"type": "string", "description": "Any other specific needs mentioned"},
                    },
                },
            },
            "required": ["use_case", "budget", "expertise_level"],
        },
    },
    {
        "name": "search_components",
        "description": (
            "Search the PC component database by category with optional filters. "
            "Returns top results sorted by the specified criterion. "
            "Always filter by relevant constraints (socket, DDR gen, budget) to get compatible results. "
            "Covers ALL component types: core parts, peripherals, networking, cooling, accessories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ALL_CATEGORIES,
                    "description": (
                        "Component category. Core: cpu, motherboard, memory, gpu, storage, psu, case, cpu_cooler. "
                        "Peripherals: monitor, keyboard, mouse, headphones, speakers, webcam. "
                        "Networking: sound_card, wired_network_card, wireless_network_card. "
                        "Accessories: case_fan, fan_controller, thermal_paste, optical_drive, external_hard_drive, case_accessory. "
                        "Other: ups, os."
                    ),
                },
                "filters": {
                    "type": "object",
                    "description": "Category-specific filters (all optional)",
                    "properties": {
                        "max_price": {"type": "number", "description": "Maximum price in USD"},
                        "min_price": {"type": "number", "description": "Minimum price in USD"},
                        # CPU filters
                        "socket": {"type": "string", "description": "CPU socket (e.g., AM5, LGA1700)"},
                        "min_cores": {"type": "integer", "description": "Minimum CPU core count"},
                        "brand": {"type": "string", "description": "Brand filter (AMD or Intel for CPUs)"},
                        # Motherboard filters
                        "ddr_generation": {"type": "integer", "description": "DDR generation (4 or 5)"},
                        "form_factor": {"type": "string", "description": "Motherboard form factor (ATX, Micro ATX, Mini ITX)"},
                        # Memory filters
                        "min_total_gb": {"type": "integer", "description": "Minimum total RAM in GB"},
                        "max_modules": {"type": "integer", "description": "Maximum RAM module count"},
                        # GPU filters
                        "min_memory_gb": {"type": "integer", "description": "Minimum GPU VRAM in GB"},
                        "chipset_contains": {"type": "string", "description": "GPU chipset substring (e.g., RTX, Radeon)"},
                        # Storage filters
                        "storage_type": {"type": "string", "enum": ["NVMe SSD", "SATA SSD", "HDD"]},
                        "min_capacity_gb": {"type": "number", "description": "Minimum storage capacity in GB"},
                        # PSU filters
                        "min_wattage": {"type": "integer", "description": "Minimum PSU wattage"},
                        "efficiency": {"type": "string", "description": "PSU efficiency (bronze, gold, platinum)"},
                        "modular": {"type": "string", "description": "PSU modularity (Full, Semi, No)"},
                        # Case filters
                        "compatible_form_factor": {"type": "string", "description": "Case must fit this mobo form factor"},
                        "min_gpu_length": {"type": "integer", "description": "Minimum GPU clearance in mm"},
                        # Cooler filters
                        "cooler_type": {"type": "string", "enum": ["Air", "AIO Liquid"]},
                        # Monitor filters
                        "min_screen_size": {"type": "number", "description": "Minimum screen size in inches"},
                        "min_refresh_rate": {"type": "integer", "description": "Minimum refresh rate in Hz"},
                        "panel_type": {"type": "string", "description": "Panel type (IPS, VA, TN, OLED)"},
                        # Peripheral filters
                        "connection_type": {"type": "string", "description": "Wired, Wireless, Bluetooth, etc."},
                        "interface": {"type": "string", "description": "PCIe, USB, etc."},
                    },
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by. Default: price.",
                    "default": "price",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10, max: 20)",
                    "default": 10,
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_optimization_profile",
        "description": (
            "Get the recommended budget allocation, component priorities, storage strategy, "
            "and optimization targets for a specific use case. Call this FIRST after confirming requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "use_case": {
                    "type": "string",
                    "enum": [
                        "gaming", "ml_training", "ml_inference", "content_creation",
                        "office", "software_dev", "streaming", "home_server", "workstation",
                    ],
                },
                "total_budget": {"type": "number", "description": "Total budget in USD"},
            },
            "required": ["use_case", "total_budget"],
        },
    },
    {
        "name": "check_compatibility",
        "description": (
            "Check compatibility between selected core components. Returns errors (deal-breakers), "
            "warnings (suboptimal), estimated power draw, and total price. "
            "MUST be called before presenting any build to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cpu": {"type": "string", "description": "CPU name"},
                "motherboard": {"type": "string", "description": "Motherboard name"},
                "memory": {"type": "string", "description": "Memory kit name"},
                "gpu": {"type": "string", "description": "GPU name (optional for iGPU builds)"},
                "storage": {"type": "array", "items": {"type": "string"}, "description": "Storage device names"},
                "psu": {"type": "string", "description": "PSU name"},
                "case": {"type": "string", "description": "Case name"},
                "cooler": {"type": "string", "description": "CPU cooler name"},
            },
            "required": ["cpu", "motherboard", "memory", "psu", "case", "cooler"],
        },
    },
    {
        "name": "optimize_build",
        "description": (
            "Analyze a draft build against the use-case profile and suggest improvements. "
            "Checks budget distribution, RAM expandability, storage tiering, GPU/CPU adequacy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "use_case": {
                    "type": "string",
                    "enum": [
                        "gaming", "ml_training", "ml_inference", "content_creation",
                        "office", "software_dev", "streaming", "home_server", "workstation",
                    ],
                },
                "budget": {"type": "number"},
                "current_build": {
                    "type": "object",
                    "properties": {
                        "cpu": {"type": "string"},
                        "motherboard": {"type": "string"},
                        "memory": {"type": "string"},
                        "gpu": {"type": "string"},
                        "storage": {"type": "array", "items": {"type": "string"}},
                        "psu": {"type": "string"},
                        "case": {"type": "string"},
                        "cooler": {"type": "string"},
                    },
                },
            },
            "required": ["use_case", "budget", "current_build"],
        },
    },
    {
        "name": "get_component_details",
        "description": (
            "Get full specifications for a specific component by name. "
            "Works for ALL categories including peripherals and accessories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ALL_CATEGORIES,
                },
                "name": {"type": "string", "description": "Component name (exact or partial match)"},
            },
            "required": ["category", "name"],
        },
    },
]


# ---- Tool Dispatch ----

class ToolDispatcher:
    """Executes tool calls by routing to the appropriate backend."""

    def __init__(self, store: ComponentStore, optimizer: UseCaseOptimizer, checker: CompatibilityChecker):
        self.store = store
        self.optimizer = optimizer
        self.checker = checker

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return JSON string result."""
        logger.info(f"Tool call: {tool_name}({json.dumps(tool_input, default=str)[:200]})")

        try:
            if tool_name == "search_components":
                result = self._search_components(tool_input)
            elif tool_name == "get_optimization_profile":
                result = self._get_optimization_profile(tool_input)
            elif tool_name == "check_compatibility":
                result = self._check_compatibility(tool_input)
            elif tool_name == "optimize_build":
                result = self._optimize_build(tool_input)
            elif tool_name == "get_component_details":
                result = self._get_component_details(tool_input)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            logger.info(f"Tool result: {json.dumps(result, default=str)[:300]}")
            return json.dumps(result, default=str)

        except Exception as e:
            logger.error(f"Tool error: {tool_name}: {e}")
            return json.dumps({"error": str(e)})

    def _search_components(self, inp: dict) -> dict:
        category = inp["category"]
        filters = inp.get("filters", {})
        sort_by = inp.get("sort_by", "price")
        limit = min(inp.get("limit", 10), 20)

        # Core components with specialized search methods
        specialized = {
            "cpu": lambda: self.store.search_cpus(
                socket=filters.get("socket"), min_cores=filters.get("min_cores"),
                max_price=filters.get("max_price"), min_price=filters.get("min_price"),
                brand=filters.get("brand"), sort_by=sort_by, limit=limit,
            ),
            "motherboard": lambda: self.store.search_motherboards(
                socket=filters.get("socket"), form_factor=filters.get("form_factor"),
                ddr_generation=filters.get("ddr_generation"),
                max_price=filters.get("max_price"), sort_by=sort_by, limit=limit,
            ),
            "memory": lambda: self.store.search_memory(
                ddr_generation=filters.get("ddr_generation"),
                min_total_gb=filters.get("min_total_gb"),
                max_modules=filters.get("max_modules"),
                max_price=filters.get("max_price"), sort_by=sort_by, limit=limit,
            ),
            "gpu": lambda: self.store.search_gpus(
                max_price=filters.get("max_price"), min_memory_gb=filters.get("min_memory_gb"),
                chipset_contains=filters.get("chipset_contains"),
                sort_by=sort_by, limit=limit,
            ),
            "storage": lambda: self.store.search_storage(
                storage_type=filters.get("storage_type"),
                min_capacity_gb=filters.get("min_capacity_gb"),
                max_price=filters.get("max_price"), sort_by=sort_by, limit=limit,
            ),
            "psu": lambda: self.store.search_psus(
                min_wattage=filters.get("min_wattage"), efficiency=filters.get("efficiency"),
                modular=filters.get("modular"), max_price=filters.get("max_price"),
                sort_by=sort_by, limit=limit,
            ),
            "case": lambda: self.store.search_cases(
                compatible_form_factor=filters.get("compatible_form_factor"),
                max_price=filters.get("max_price"),
                min_gpu_length=filters.get("min_gpu_length"),
                sort_by=sort_by, limit=limit,
            ),
            "cpu_cooler": lambda: self.store.search_coolers(
                max_price=filters.get("max_price"),
                cooler_type=filters.get("cooler_type"),
                sort_by=sort_by, limit=limit,
            ),
        }

        if category in specialized:
            results = specialized[category]()
        else:
            # Generic search for all other categories (peripherals, accessories, etc.)
            results = self.store.search_generic(
                category=category,
                max_price=filters.get("max_price"),
                sort_by=sort_by,
                limit=limit,
            )

        return {"category": category, "count": len(results), "results": results}

    def _get_optimization_profile(self, inp: dict) -> dict:
        return self.optimizer.get_profile(inp["use_case"], inp["total_budget"])

    def _check_compatibility(self, inp: dict) -> dict:
        return self.checker.check(
            cpu=inp["cpu"], motherboard=inp["motherboard"],
            memory=inp["memory"], gpu=inp.get("gpu"),
            storage=inp.get("storage", []), psu=inp["psu"],
            case=inp["case"], cooler=inp["cooler"],
        )

    def _optimize_build(self, inp: dict) -> dict:
        return self.optimizer.optimize_build(
            use_case=inp["use_case"], budget=inp["budget"],
            current_build=inp["current_build"],
        )

    def _get_component_details(self, inp: dict) -> dict:
        result = self.store.get_component_by_name(inp["category"], inp["name"])
        if result:
            return {"found": True, "component": result}
        return {"found": False, "error": f"Component not found: '{inp['name']}' in category '{inp['category']}'"}
