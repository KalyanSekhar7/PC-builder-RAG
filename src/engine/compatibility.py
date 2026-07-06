"""Deterministic compatibility checker for PC builds."""

import logging
from dataclasses import dataclass, field

from ..data.loader import ComponentStore

logger = logging.getLogger("engine.compatibility")


@dataclass
class CompatibilityResult:
    compatible: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimated_power_draw: int = 0
    recommended_psu_wattage: int = 0
    total_price: float = 0.0


class CompatibilityChecker:
    """Runs all deterministic compatibility checks on a PC build."""

    def __init__(self, store: ComponentStore):
        self.store = store

    def check(
        self,
        cpu: str,
        motherboard: str,
        memory: str,
        psu: str,
        case: str,
        cooler: str,
        gpu: str | None = None,
        storage: list[str] | None = None,
    ) -> dict:
        errors = []
        warnings = []
        total_price = 0.0

        # Resolve all components by name
        cpu_obj = self.store.get_component_object("cpu", cpu)
        mobo_obj = self.store.get_component_object("motherboard", motherboard)
        mem_obj = self.store.get_component_object("memory", memory)
        gpu_obj = self.store.get_component_object("gpu", gpu) if gpu else None
        psu_obj = self.store.get_component_object("psu", psu)
        case_obj = self.store.get_component_object("case", case)
        cooler_obj = self.store.get_component_object("cpu_cooler", cooler)
        storage_objs = []
        for s_name in (storage or []):
            s_obj = self.store.get_component_object("storage", s_name)
            if s_obj:
                storage_objs.append(s_obj)
            else:
                errors.append(f"Storage not found in database: '{s_name}'")

        # Check all components exist
        if not cpu_obj:
            errors.append(f"CPU not found in database: '{cpu}'")
        if not mobo_obj:
            errors.append(f"Motherboard not found in database: '{motherboard}'")
        if not mem_obj:
            errors.append(f"Memory not found in database: '{memory}'")
        if not psu_obj:
            errors.append(f"PSU not found in database: '{psu}'")
        if not case_obj:
            errors.append(f"Case not found in database: '{case}'")
        if not cooler_obj:
            errors.append(f"Cooler not found in database: '{cooler}'")
        if gpu and not gpu_obj:
            errors.append(f"GPU not found in database: '{gpu}'")

        if any(obj is None for obj in [cpu_obj, mobo_obj, mem_obj, psu_obj, case_obj, cooler_obj]):
            return CompatibilityResult(
                compatible=False, errors=errors, warnings=warnings
            ).__dict__

        # --- CHECK 1: CPU socket matches motherboard socket ---
        if cpu_obj.socket != mobo_obj.socket:
            errors.append(
                f"Socket mismatch: CPU '{cpu_obj.name}' uses {cpu_obj.socket}, "
                f"but motherboard '{mobo_obj.name}' uses {mobo_obj.socket}"
            )
            logger.info(f"CHECK FAIL: socket {cpu_obj.socket} != {mobo_obj.socket}")

        # --- CHECK 2: DDR generation match ---
        if mem_obj.ddr_generation != mobo_obj.ddr_generation:
            errors.append(
                f"DDR mismatch: Memory '{mem_obj.name}' is DDR{mem_obj.ddr_generation}, "
                f"but motherboard '{mobo_obj.name}' supports DDR{mobo_obj.ddr_generation}"
            )
            logger.info(f"CHECK FAIL: DDR{mem_obj.ddr_generation} != DDR{mobo_obj.ddr_generation}")

        # --- CHECK 3: RAM capacity within motherboard limits ---
        if mem_obj.total_gb > mobo_obj.max_memory:
            errors.append(
                f"RAM exceeds motherboard max: {mem_obj.total_gb}GB > {mobo_obj.max_memory}GB limit"
            )

        # --- CHECK 4: RAM stick count within slot count ---
        if mem_obj.module_count > mobo_obj.memory_slots:
            errors.append(
                f"Too many RAM sticks: {mem_obj.module_count} sticks for "
                f"{mobo_obj.memory_slots} slots on '{mobo_obj.name}'"
            )

        # --- CHECK 5: Motherboard form factor fits in case ---
        if mobo_obj.form_factor not in case_obj.compatible_form_factors:
            errors.append(
                f"Form factor mismatch: Motherboard '{mobo_obj.name}' is {mobo_obj.form_factor}, "
                f"but case '{case_obj.name}' ({case_obj.type}) supports "
                f"{', '.join(case_obj.compatible_form_factors)}"
            )

        # --- CHECK 6: GPU length vs case clearance ---
        if gpu_obj and gpu_obj.length:
            if gpu_obj.length > case_obj.estimated_max_gpu_length_mm:
                warnings.append(
                    f"GPU may not fit: '{gpu_obj.name}' is {gpu_obj.length}mm, "
                    f"estimated case clearance is ~{case_obj.estimated_max_gpu_length_mm}mm. "
                    f"Verify with case manufacturer specs."
                )

        # --- CHECK 7: CPU without iGPU needs discrete GPU ---
        if not cpu_obj.has_igpu and gpu_obj is None:
            errors.append(
                f"CPU '{cpu_obj.name}' has no integrated graphics (graphics={cpu_obj.graphics}). "
                f"A discrete GPU is required."
            )

        # --- CHECK 8: PSU wattage adequacy ---
        power_draw = self._estimate_power_draw(cpu_obj, gpu_obj, mem_obj, storage_objs)
        recommended_psu = self._recommended_psu_wattage(power_draw)

        if psu_obj.wattage < power_draw:
            errors.append(
                f"PSU underpowered: estimated draw ~{power_draw}W exceeds "
                f"PSU capacity {psu_obj.wattage}W"
            )
        elif psu_obj.wattage < power_draw * 1.2:
            warnings.append(
                f"PSU has low headroom: {psu_obj.wattage}W for ~{power_draw}W estimated draw. "
                f"Recommend {recommended_psu}W+ for reliability and future upgrades."
            )

        # --- CHECK 9: AIO cooler radiator size vs case ---
        if cooler_obj.cooler_type == "AIO Liquid" and cooler_obj.radiator_size_mm:
            if "Mini ITX" in case_obj.type and cooler_obj.radiator_size_mm > 240:
                warnings.append(
                    f"360mm AIO radiator may not fit in '{case_obj.name}' ({case_obj.type}). "
                    f"Consider 240mm or smaller."
                )

        # --- WARNINGS ---

        # No NVMe boot drive
        has_nvme = any(s.storage_type == "NVMe SSD" for s in storage_objs)
        if storage_objs and not has_nvme:
            warnings.append("No NVMe SSD in build. Strongly recommend NVMe for boot drive.")

        # All RAM slots filled — no expansion
        if mem_obj.module_count == mobo_obj.memory_slots:
            warnings.append(
                f"All {mobo_obj.memory_slots} RAM slots will be used. "
                f"No room for future memory expansion."
            )

        # Calculate total price
        total_price = cpu_obj.price + mobo_obj.price + mem_obj.price + psu_obj.price + case_obj.price + cooler_obj.price
        if gpu_obj:
            total_price += gpu_obj.price
        total_price += sum(s.price for s in storage_objs)

        result = CompatibilityResult(
            compatible=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            estimated_power_draw=power_draw,
            recommended_psu_wattage=recommended_psu,
            total_price=round(total_price, 2),
        )
        logger.info(
            f"Compatibility check: {'PASS' if result.compatible else 'FAIL'} | "
            f"{len(errors)} errors, {len(warnings)} warnings | "
            f"~{power_draw}W draw | ${total_price:.2f}"
        )
        return result.__dict__

    def _estimate_power_draw(self, cpu, gpu, memory, storage_list) -> int:
        draw = cpu.tdp
        if gpu:
            draw += gpu.estimated_tdp
        draw += memory.module_count * 5  # ~5W per DIMM
        draw += len(storage_list) * 8  # ~8W per drive
        draw += 30  # fans, board, misc
        return draw

    def _recommended_psu_wattage(self, power_draw: int) -> int:
        """Round up to nearest 50W with 25% headroom."""
        target = int(power_draw * 1.25)
        return ((target + 49) // 50) * 50
