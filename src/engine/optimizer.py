"""Use-case optimization profiles and build optimization logic."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("engine.optimizer")


@dataclass
class UseCaseProfile:
    name: str
    display_name: str
    budget_allocation: dict[str, float]  # category -> percentage (sums to ~1.0)
    priority_order: list[str]  # component categories in priority order
    min_requirements: dict[str, object]  # minimum specs
    storage_strategy: dict[str, str]  # boot_drive, secondary, reasoning
    optimization_targets: list[str]  # what to optimize for
    notes: list[str]  # use-case specific advice
    # Components that should NEVER be cheaped out on for this use case
    uncompromisable: list[str] = field(default_factory=list)
    # Why each is uncompromisable — shown to the agent for reasoning
    uncompromisable_reasons: dict[str, str] = field(default_factory=dict)


PROFILES: dict[str, UseCaseProfile] = {
    "gaming": UseCaseProfile(
        name="gaming",
        display_name="Gaming PC",
        budget_allocation={
            "gpu": 0.35, "cpu": 0.20, "motherboard": 0.10, "memory": 0.08,
            "storage": 0.08, "psu": 0.07, "case": 0.07, "cooler": 0.05,
        },
        priority_order=["gpu", "cpu", "memory", "storage", "motherboard", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 16, "storage_boot_gb": 500, "storage_boot_type": "NVMe SSD",
            "cpu_cores": 6, "psu_efficiency": "bronze",
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (500GB-1TB) — OS + active games",
            "secondary": "SATA SSD (1-2TB) for game library, or HDD for budget builds",
            "reasoning": "Games need fast load times. NVMe for active titles, SATA SSD for the rest. HDD too slow for modern games.",
        },
        optimization_targets=[
            "GPU: maximize FPS per dollar — this is the #1 priority",
            "CPU: prioritize boost_clock over core_count (single-thread perf matters for gaming)",
            "RAM: 32GB DDR5 is the sweet spot; prioritize low cas_latency over raw speed",
            "Storage: NVMe for boot + active games, 1TB minimum",
        ],
        notes=[
            "GPU is the primary bottleneck for gaming. Allocate the largest budget share here.",
            "6-8 CPU cores is sufficient. Higher clock speed > more cores for gaming.",
            "32GB RAM is the modern sweet spot. DDR5 if budget allows.",
            "NVMe SSD essential for load times. 1TB+ recommended.",
            "1 strong GPU is ALWAYS better than 2 weaker GPUs for gaming.",
        ],
        uncompromisable=["gpu", "cpu", "monitor", "memory"],
        uncompromisable_reasons={
            "gpu": "GPU directly determines FPS. A weak GPU makes the whole build pointless for gaming.",
            "cpu": "CPU bottlenecks the GPU if too slow. Must match GPU tier.",
            "monitor": "A 60Hz monitor on a high-end GPU wastes the GPU's power. Match refresh rate to GPU capability.",
            "memory": "16GB is absolute minimum, 32GB preferred. Too little RAM causes stuttering in modern games.",
        },
    ),

    "ml_training": UseCaseProfile(
        name="ml_training",
        display_name="ML/AI Training Workstation",
        budget_allocation={
            "gpu": 0.45, "cpu": 0.15, "memory": 0.12, "motherboard": 0.08,
            "storage": 0.08, "psu": 0.06, "case": 0.03, "cooler": 0.03,
        },
        priority_order=["gpu", "memory", "cpu", "storage", "psu", "motherboard", "cooler", "case"],
        min_requirements={
            "memory_gb": 32, "gpu_vram_gb": 12, "storage_boot_gb": 1000,
            "cpu_cores": 8,
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (1-2TB) — OS + active datasets + models",
            "secondary": "HDD 7200rpm (4-8TB) for dataset archive at $0.02-0.04/GB",
            "reasoning": "Training reads huge datasets sequentially — NVMe helps. But storing all datasets on NVMe is wasteful. HDD for cold data.",
        },
        optimization_targets=[
            "GPU: maximize VRAM first (16GB minimum, 24GB+ strongly preferred), then compute performance",
            "RAM: maximize capacity (64GB+). Use 2 sticks in 4-slot board for expandability to 128GB",
            "CPU: core_count matters for data preprocessing. 8+ cores, 12+ preferred",
            "Storage: fast NVMe for active datasets, bulk HDD for archive",
        ],
        notes=[
            "GPU VRAM is critical: models and batch data must fit in VRAM.",
            "16GB VRAM minimum for serious training, 24GB+ strongly preferred.",
            "64GB+ system RAM for large datasets. Prefer 2x32GB for expandability.",
            "Fast NVMe storage for dataset I/O. 2TB+ recommended.",
            "PSU headroom is critical — GPU power spikes can exceed TDP.",
        ],
        uncompromisable=["gpu", "cpu", "memory", "psu"],
        uncompromisable_reasons={
            "gpu": "VRAM determines what models you can train. Insufficient VRAM = can't train at all.",
            "cpu": "Data preprocessing is CPU-bound. Weak CPU starves the GPU of data.",
            "memory": "Datasets must fit in RAM for efficient training. Too little = constant disk swapping.",
            "psu": "GPU power spikes can exceed rated TDP by 30-50%. Underpowered PSU = crashes during training runs.",
        },
    ),

    "ml_inference": UseCaseProfile(
        name="ml_inference",
        display_name="ML/AI Inference Server",
        budget_allocation={
            "gpu": 0.40, "cpu": 0.15, "memory": 0.15, "motherboard": 0.08,
            "storage": 0.08, "psu": 0.06, "case": 0.04, "cooler": 0.04,
        },
        priority_order=["gpu", "memory", "cpu", "storage", "motherboard", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 32, "gpu_vram_gb": 8, "storage_boot_gb": 500,
            "cpu_cores": 6,
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (500GB-1TB) — OS + models",
            "secondary": "Optional — models are usually small",
            "reasoning": "Inference loads models once. Fast storage for startup, but steady-state is GPU-bound.",
        },
        optimization_targets=[
            "GPU: VRAM to fit the model, then inference throughput",
            "RAM: enough to load model + preprocessing pipeline (32-64GB)",
            "CPU: moderate — inference is GPU-bound, CPU just feeds data",
        ],
        notes=[
            "VRAM must fit your target model. LLMs need 16-24GB+.",
            "Inference is less power-hungry than training.",
            "Lower TDP GPU is fine if VRAM is sufficient.",
        ],
        uncompromisable=["gpu", "memory"],
        uncompromisable_reasons={
            "gpu": "Model must fit in VRAM. No VRAM = no inference.",
            "memory": "Model loading + preprocessing pipeline needs adequate system RAM.",
        },
    ),

    "content_creation": UseCaseProfile(
        name="content_creation",
        display_name="Content Creation / Video Editing Workstation",
        budget_allocation={
            "gpu": 0.25, "cpu": 0.25, "memory": 0.12, "motherboard": 0.10,
            "storage": 0.10, "psu": 0.07, "case": 0.06, "cooler": 0.05,
        },
        priority_order=["cpu", "gpu", "memory", "storage", "motherboard", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 32, "cpu_cores": 8, "storage_boot_gb": 1000,
            "gpu_vram_gb": 6,
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (1-2TB) — OS + active projects + scratch disk",
            "secondary": "HDD 7200rpm (4-8TB) for raw footage archive",
            "reasoning": "Video editing scratch disk MUST be NVMe. Raw footage is huge — archive on HDD at $0.02/GB.",
        },
        optimization_targets=[
            "CPU: core_count is king — rendering, encoding, effects all scale with cores. 12+ cores preferred.",
            "RAM: 64GB for 4K, 128GB for 8K or After Effects heavy use",
            "GPU: VRAM for GPU-accelerated effects (DaVinci Resolve, Premiere)",
            "Storage: fast NVMe scratch + bulk HDD archive",
        ],
        notes=[
            "CPU core count directly impacts render times.",
            "DaVinci Resolve is very GPU-dependent. Premiere Pro is more CPU-dependent.",
            "64GB RAM minimum for 4K editing. 128GB for 8K or complex After Effects projects.",
            "Fast NVMe scratch disk is critical for timeline performance.",
        ],
        uncompromisable=["cpu", "memory", "storage", "gpu"],
        uncompromisable_reasons={
            "cpu": "Render times scale directly with core count. Weak CPU = hours-long renders.",
            "memory": "4K timelines with effects eat 32-64GB easily. Too little = constant caching to disk.",
            "storage": "NVMe scratch disk is mandatory. Slow storage = choppy timeline playback.",
            "gpu": "DaVinci Resolve and GPU-accelerated effects need adequate VRAM.",
        },
    ),

    "office": UseCaseProfile(
        name="office",
        display_name="Office / Productivity PC",
        budget_allocation={
            "cpu": 0.25, "motherboard": 0.15, "memory": 0.12, "storage": 0.15,
            "case": 0.12, "psu": 0.10, "cooler": 0.08, "gpu": 0.03,
        },
        priority_order=["cpu", "storage", "memory", "motherboard", "case", "psu", "cooler", "gpu"],
        min_requirements={
            "memory_gb": 8, "storage_boot_gb": 250, "storage_boot_type": "NVMe SSD",
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (250-500GB) — everything fits here",
            "secondary": "Not needed for typical office use",
            "reasoning": "Documents, spreadsheets, email — 500GB NVMe is plenty. No second drive needed.",
        },
        optimization_targets=[
            "CPU: pick one with integrated graphics to skip discrete GPU. Prioritize price.",
            "Storage: NVMe SSD for snappy boot and app launches. 250-500GB sufficient.",
            "RAM: 16GB is comfortable for multitasking. 8GB bare minimum.",
            "GPU: use integrated graphics — no discrete GPU needed",
        ],
        notes=[
            "Pick a CPU with integrated graphics (AMD 'G' series or any Intel with UHD).",
            "No discrete GPU needed — saves $150-500.",
            "Quiet operation matters for office — consider low-noise cooler.",
            "Smaller form factor (mATX/ITX) often preferred for desk space.",
        ],
        uncompromisable=["storage", "psu"],
        uncompromisable_reasons={
            "storage": "SSD is essential for responsive boot and app launches. HDD makes office work painful.",
            "psu": "Reliability matters — a bad PSU can fry the whole system. Get a reputable brand.",
        },
    ),

    "software_dev": UseCaseProfile(
        name="software_dev",
        display_name="Software Development Workstation",
        budget_allocation={
            "cpu": 0.25, "memory": 0.15, "storage": 0.15, "motherboard": 0.12,
            "gpu": 0.10, "psu": 0.08, "case": 0.08, "cooler": 0.07,
        },
        priority_order=["cpu", "memory", "storage", "motherboard", "gpu", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 16, "cpu_cores": 6, "storage_boot_gb": 500,
            "storage_boot_type": "NVMe SSD",
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (1TB) — OS + IDEs + repos + Docker images",
            "secondary": "Optional second NVMe or SATA SSD if running VMs/containers heavily",
            "reasoning": "Compilation, Docker, VMs all hammer storage I/O. NVMe is essential. 1TB fills fast with containers.",
        },
        optimization_targets=[
            "CPU: high core_count for compilation parallelism (make -j). 8+ cores.",
            "RAM: 32GB minimum. 64GB if running VMs or many Docker containers.",
            "Storage: fast NVMe for repo operations, Docker layers, build artifacts",
            "GPU: basic display output is fine unless doing GPU compute dev",
        ],
        notes=[
            "Compilation scales linearly with cores — more cores = faster builds.",
            "32GB RAM minimum. Docker + browser + IDE + containers adds up fast.",
            "NVMe SSD is critical — git operations, builds, and container pulls are I/O heavy.",
            "Integrated GPU is fine unless doing CUDA/graphics development.",
        ],
        uncompromisable=["cpu", "memory", "storage"],
        uncompromisable_reasons={
            "cpu": "Compilation parallelism scales with cores. Weak CPU = slow builds.",
            "memory": "Docker + VMs + IDE + browser easily consume 32GB+. Too little = constant swapping.",
            "storage": "Git, Docker, build artifacts hammer I/O. NVMe is non-negotiable.",
        },
    ),

    "streaming": UseCaseProfile(
        name="streaming",
        display_name="Gaming + Streaming PC",
        budget_allocation={
            "gpu": 0.30, "cpu": 0.25, "memory": 0.08, "motherboard": 0.10,
            "storage": 0.08, "psu": 0.07, "case": 0.07, "cooler": 0.05,
        },
        priority_order=["gpu", "cpu", "memory", "storage", "motherboard", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 32, "cpu_cores": 8, "storage_boot_gb": 1000,
            "storage_boot_type": "NVMe SSD",
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (1TB) — OS + games + streaming software",
            "secondary": "HDD or SATA SSD for VOD recordings (raw recordings are huge)",
            "reasoning": "Streaming + gaming simultaneously needs fast storage. Recordings go to bulk storage.",
        },
        optimization_targets=[
            "CPU: MUST have high core_count (8+). Gaming + encoding simultaneously needs threads.",
            "GPU: strong for gaming + NVENC hardware encoding on NVIDIA GPUs",
            "RAM: 32GB minimum — game + OBS + browser + chat all running",
        ],
        notes=[
            "CPU needs to handle game + encoding simultaneously. 8+ cores mandatory.",
            "NVIDIA GPUs have NVENC encoder — offloads encoding from CPU. Strong advantage.",
            "32GB RAM minimum — streaming setup runs many apps simultaneously.",
            "Fast NVMe for game + stream capture. Bulk storage for VOD archive.",
        ],
        uncompromisable=["cpu", "gpu", "memory", "webcam"],
        uncompromisable_reasons={
            "cpu": "Must handle gaming + encoding simultaneously. Weak CPU = dropped frames on stream.",
            "gpu": "Needs to run the game AND provide NVENC encoding. NVIDIA strongly preferred.",
            "memory": "Game + OBS + browser + overlays + chat = 32GB minimum.",
            "webcam": "Stream quality depends on camera. A bad webcam ruins viewer experience.",
        },
    ),

    "home_server": UseCaseProfile(
        name="home_server",
        display_name="Home Server / NAS",
        budget_allocation={
            "cpu": 0.15, "motherboard": 0.15, "storage": 0.30, "memory": 0.10,
            "case": 0.10, "psu": 0.10, "cooler": 0.08, "gpu": 0.02,
        },
        priority_order=["storage", "cpu", "motherboard", "memory", "psu", "case", "cooler", "gpu"],
        min_requirements={
            "memory_gb": 8, "cpu_cores": 4,
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (250-500GB) — OS only",
            "secondary": "Multiple HDD 5400rpm — bulk storage, lower heat/noise, 24/7 durability",
            "reasoning": "NAS is about capacity and reliability. 5400rpm HDDs run cooler and last longer in 24/7 operation.",
        },
        optimization_targets=[
            "Storage: maximize total capacity at lowest $/GB. HDD 5400rpm preferred for 24/7.",
            "CPU: low power, integrated graphics. Efficiency over performance.",
            "Case: must have 3.5\" bays for HDDs. internal_35_bays matters.",
            "PSU: efficient (Gold+), reliable. 24/7 operation.",
        ],
        notes=[
            "Pick a CPU with integrated graphics — no discrete GPU needed.",
            "Low TDP CPU preferred — this runs 24/7, power bill matters.",
            "Case MUST have enough 3.5\" bays for HDDs.",
            "5400rpm HDDs are preferred: quieter, cooler, more reliable for 24/7.",
        ],
        uncompromisable=["storage", "psu", "ups"],
        uncompromisable_reasons={
            "storage": "Data integrity is everything for a server. Reliable drives are non-negotiable.",
            "psu": "Runs 24/7. A failed PSU = data loss. Gold efficiency saves on power bill.",
            "ups": "Power loss protection prevents data corruption. Critical for any server.",
        },
    ),

    "workstation": UseCaseProfile(
        name="workstation",
        display_name="Professional Workstation (CAD/3D/Simulation)",
        budget_allocation={
            "cpu": 0.25, "gpu": 0.25, "memory": 0.15, "motherboard": 0.10,
            "storage": 0.10, "psu": 0.06, "case": 0.04, "cooler": 0.05,
        },
        priority_order=["cpu", "gpu", "memory", "storage", "motherboard", "psu", "cooler", "case"],
        min_requirements={
            "memory_gb": 32, "cpu_cores": 8, "storage_boot_gb": 1000,
            "gpu_vram_gb": 8,
        },
        storage_strategy={
            "boot_drive": "NVMe SSD (1-2TB) — OS + project files + scratch",
            "secondary": "SATA SSD or HDD for project archive",
            "reasoning": "CAD/3D files can be large. Active projects on NVMe, completed projects on archive.",
        },
        optimization_targets=[
            "CPU: high core_count + high clock for rendering and simulation",
            "GPU: Quadro/Pro for certified drivers, or consumer GPU if not needed",
            "RAM: 64GB+ for large assemblies, simulations, renders",
            "Storage: fast NVMe for active projects",
        ],
        notes=[
            "Some CAD software (SolidWorks, CATIA) requires Quadro/Pro GPU for certified drivers.",
            "Other software (Blender, Cinema 4D) works great with consumer GPUs.",
            "ECC memory support may be needed for mission-critical work.",
            "64GB+ RAM for large CAD assemblies or simulation datasets.",
        ],
        uncompromisable=["cpu", "gpu", "memory", "storage"],
        uncompromisable_reasons={
            "cpu": "Simulation and rendering are heavily CPU-bound. Core count + clock speed both matter.",
            "gpu": "Certified Quadro/Pro drivers are required by some CAD software. Consumer GPU may crash.",
            "memory": "Large assemblies consume 64-128GB easily. Insufficient RAM = out-of-memory errors.",
            "storage": "Project files can be huge. NVMe scratch is mandatory for responsive viewport.",
        },
    ),
}


# Floor prices — minimum to get a functional component in each category
# Based on actual dataset analysis (cheapest usable modern parts)
FLOOR_PRICES = {
    "cpu": 45, "motherboard": 90, "memory": 23, "gpu": 140,
    "storage": 30, "psu": 32, "case": 37, "cooler": 10,
}
FLOOR_TOTAL_WITH_GPU = sum(FLOOR_PRICES.values())  # ~$407
FLOOR_TOTAL_NO_GPU = FLOOR_TOTAL_WITH_GPU - FLOOR_PRICES["gpu"]  # ~$267


class UseCaseOptimizer:
    """Provides use-case profiles and build optimization."""

    def __init__(self, store):
        self.store = store

    def get_profile(self, use_case: str, total_budget: float) -> dict:
        """Return profile with DYNAMIC budget allocation based on total budget."""
        profile = PROFILES.get(use_case)
        if not profile:
            available = list(PROFILES.keys())
            return {"error": f"Unknown use case: '{use_case}'. Available: {available}"}

        budget_usd = self._dynamic_allocation(profile, total_budget)
        dynamic_pct = {k: round(v / total_budget, 3) for k, v in budget_usd.items()} if total_budget > 0 else {}

        return {
            "use_case": profile.name,
            "display_name": profile.display_name,
            "budget_allocation_pct": dynamic_pct,
            "budget_allocation_usd": budget_usd,
            "base_allocation_pct": profile.budget_allocation,
            "priority_order": profile.priority_order,
            "min_requirements": profile.min_requirements,
            "storage_strategy": profile.storage_strategy,
            "optimization_targets": profile.optimization_targets,
            "notes": profile.notes,
            "uncompromisable": profile.uncompromisable,
            "uncompromisable_reasons": profile.uncompromisable_reasons,
        }

    def _dynamic_allocation(self, profile: UseCaseProfile, budget: float) -> dict[str, float]:
        """
        Dynamically allocate budget based on total amount.

        Strategy: floor-price-aware allocation.
        1. Reserve floor price for each non-priority component
        2. Distribute remaining budget by priority weights (uncompromisable get more)
        3. At low budgets: priority components get bigger share because floors eat more
        4. At high budgets: approaches the base percentage split
        """
        has_gpu = "gpu" in profile.budget_allocation and profile.budget_allocation["gpu"] > 0.05
        floor_total = FLOOR_TOTAL_WITH_GPU if has_gpu else FLOOR_TOTAL_NO_GPU

        if budget <= floor_total:
            # Budget is at or below floor — just split proportionally, nothing smart to do
            return {k: round(v * budget, 2) for k, v in profile.budget_allocation.items()}

        # Step 1: Assign floor price to every category
        allocation = {}
        categories = list(profile.budget_allocation.keys())
        for cat in categories:
            allocation[cat] = FLOOR_PRICES.get(cat, 20)

        # Step 2: Calculate remaining budget after floors
        used = sum(allocation.values())
        remaining = budget - used

        # Step 3: Distribute remaining by priority-weighted percentages
        # Uncompromisable items get 1.5x their base weight for the remaining pool
        weights = {}
        for cat in categories:
            base_weight = profile.budget_allocation[cat]
            if cat in profile.uncompromisable:
                weights[cat] = base_weight * 1.5  # boost uncompromisable
            else:
                weights[cat] = base_weight

        total_weight = sum(weights.values())
        for cat in categories:
            share = (weights[cat] / total_weight) * remaining if total_weight > 0 else 0
            allocation[cat] = round(allocation[cat] + share, 2)

        return allocation

    def optimize_build(self, use_case: str, budget: float, current_build: dict) -> dict:
        """Analyze a draft build and suggest optimizations."""
        profile = PROFILES.get(use_case)
        if not profile:
            return {"error": f"Unknown use case: '{use_case}'"}

        suggestions = []
        budget_usd = {k: round(v * budget, 2) for k, v in profile.budget_allocation.items()}

        # Resolve components
        components = {}
        actual_spend = {}
        for category, name in current_build.items():
            if isinstance(name, list):
                # Storage can be a list
                objs = [self.store.get_component_object("storage", n) for n in name]
                components[category] = [o for o in objs if o]
                actual_spend[category] = sum(o.price for o in components[category])
            else:
                cat_key = category
                if category == "gpu":
                    cat_key = "gpu"
                obj = self.store.get_component_object(category, name)
                if obj:
                    components[category] = obj
                    actual_spend[category] = obj.price

        # 1. Budget distribution check
        total_spent = sum(actual_spend.values())
        for cat, target_usd in budget_usd.items():
            actual = actual_spend.get(cat, 0)
            if actual > target_usd * 1.5 and target_usd > 0:
                suggestions.append({
                    "category": cat,
                    "type": "overspend",
                    "detail": f"Spending ${actual:.0f} on {cat} vs recommended ${target_usd:.0f} "
                              f"({actual/budget*100:.0f}% vs {profile.budget_allocation.get(cat, 0)*100:.0f}% target). "
                              f"Consider reallocating to higher-priority components.",
                })

        # 2. RAM expandability check
        mem = components.get("memory")
        mobo = components.get("motherboard")
        if mem and mobo and hasattr(mem, "module_count") and hasattr(mobo, "memory_slots"):
            if mem.module_count >= mobo.memory_slots:
                suggestions.append({
                    "category": "memory",
                    "type": "expandability",
                    "detail": f"All {mobo.memory_slots} RAM slots used ({mem.module_count}x{mem.module_size_gb}GB). "
                              f"No room for expansion. Consider {mem.total_gb}GB as "
                              f"2x{mem.total_gb//2}GB instead for future upgradability.",
                })

        # 3. Storage tier check
        storage_list = components.get("storage", [])
        if isinstance(storage_list, list) and storage_list:
            has_nvme = any(s.storage_type == "NVMe SSD" for s in storage_list)
            if not has_nvme:
                suggestions.append({
                    "category": "storage",
                    "type": "performance",
                    "detail": "No NVMe SSD in build. An NVMe boot drive dramatically improves "
                              "system responsiveness. Strongly recommended.",
                })

            total_capacity = sum(s.capacity for s in storage_list)
            min_boot = profile.min_requirements.get("storage_boot_gb", 500)
            if total_capacity < min_boot:
                suggestions.append({
                    "category": "storage",
                    "type": "capacity",
                    "detail": f"Total storage {total_capacity}GB is below recommended "
                              f"{min_boot}GB for {profile.display_name}.",
                })

        # 4. GPU check for use case
        gpu = components.get("gpu")
        min_vram = profile.min_requirements.get("gpu_vram_gb")
        if min_vram and gpu and gpu.memory < min_vram:
            suggestions.append({
                "category": "gpu",
                "type": "underpowered",
                "detail": f"GPU has {gpu.memory}GB VRAM, but {profile.display_name} "
                          f"recommends minimum {min_vram}GB.",
            })

        # 5. CPU check
        cpu = components.get("cpu")
        min_cores = profile.min_requirements.get("cpu_cores")
        if min_cores and cpu and cpu.core_count < min_cores:
            suggestions.append({
                "category": "cpu",
                "type": "underpowered",
                "detail": f"CPU has {cpu.core_count} cores, but {profile.display_name} "
                          f"recommends minimum {min_cores} cores.",
            })

        # 6. Memory check
        min_mem = profile.min_requirements.get("memory_gb")
        if min_mem and mem and mem.total_gb < min_mem:
            suggestions.append({
                "category": "memory",
                "type": "underpowered",
                "detail": f"Memory is {mem.total_gb}GB, but {profile.display_name} "
                          f"recommends minimum {min_mem}GB.",
            })

        return {
            "use_case": profile.display_name,
            "total_spent": round(total_spent, 2),
            "budget": budget,
            "budget_remaining": round(budget - total_spent, 2),
            "suggestions": suggestions,
            "suggestion_count": len(suggestions),
        }
