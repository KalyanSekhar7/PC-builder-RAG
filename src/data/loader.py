"""CSV data loader with filtering, indexing, and query methods."""

import bisect
import csv
import logging
from collections import defaultdict
from pathlib import Path

from .models import (
    CPU, Motherboard, Memory, VideoCard, Storage,
    PowerSupply, Case, CPUCooler, OS,
    Monitor, Keyboard, Mouse, Headphones, Speakers, Webcam,
    SoundCard, WiredNetworkCard, WirelessNetworkCard,
    CaseFan, FanController, ThermalPaste, OpticalDrive,
    ExternalHardDrive, CaseAccessory, UPS,
)

logger = logging.getLogger("data.loader")


def _safe_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: str | None) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


class ComponentStore:
    """Loads all enriched CSVs, filters to priced-only, indexes for fast lookup."""

    def __init__(self, csv_dir: str | Path):
        self.csv_dir = Path(csv_dir)
        self.cpus: list[CPU] = []
        self.motherboards: list[Motherboard] = []
        self.memory: list[Memory] = []
        self.gpus: list[VideoCard] = []
        self.storage: list[Storage] = []
        self.psus: list[PowerSupply] = []
        self.cases: list[Case] = []
        self.coolers: list[CPUCooler] = []
        self.os_list: list[OS] = []

        # All other categories — stored generically as list of Pydantic models
        self._generic: dict[str, list] = {
            "monitor": [], "keyboard": [], "mouse": [],
            "headphones": [], "speakers": [], "webcam": [],
            "sound_card": [], "wired_network_card": [], "wireless_network_card": [],
            "case_fan": [], "fan_controller": [], "thermal_paste": [],
            "optical_drive": [], "external_hard_drive": [], "case_accessory": [],
            "ups": [],
        }

        # Indexes for fast filtering
        self._cpu_by_socket: dict[str, list[CPU]] = defaultdict(list)
        self._mobo_by_socket: dict[str, list[Motherboard]] = defaultdict(list)
        self._memory_by_ddr: dict[int, list[Memory]] = defaultdict(list)
        self._storage_by_type: dict[str, list[Storage]] = defaultdict(list)

        self._load_all()

    def _load_csv(self, filename: str) -> list[dict]:
        filepath = self.csv_dir / filename
        if not filepath.exists():
            logger.warning(f"File not found: {filepath}")
            return []
        with open(filepath, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    # Mapping from category key to (csv_filename, pydantic_model_class)
    GENERIC_CATEGORY_MAP = {
        "monitor": ("monitor.csv", Monitor),
        "keyboard": ("keyboard.csv", Keyboard),
        "mouse": ("mouse.csv", Mouse),
        "headphones": ("headphones.csv", Headphones),
        "speakers": ("speakers.csv", Speakers),
        "webcam": ("webcam.csv", Webcam),
        "sound_card": ("sound-card.csv", SoundCard),
        "wired_network_card": ("wired-network-card.csv", WiredNetworkCard),
        "wireless_network_card": ("wireless-network-card.csv", WirelessNetworkCard),
        "case_fan": ("case-fan.csv", CaseFan),
        "fan_controller": ("fan-controller.csv", FanController),
        "thermal_paste": ("thermal-paste.csv", ThermalPaste),
        "optical_drive": ("optical-drive.csv", OpticalDrive),
        "external_hard_drive": ("external-hard-drive.csv", ExternalHardDrive),
        "case_accessory": ("case-accessory.csv", CaseAccessory),
        "ups": ("ups.csv", UPS),
    }

    def _load_all(self) -> None:
        # Core components (specialized loaders)
        self._load_cpus()
        self._load_motherboards()
        self._load_memory()
        self._load_gpus()
        self._load_storage()
        self._load_psus()
        self._load_cases()
        self._load_coolers()
        self._load_os()
        # All other categories (generic loader)
        self._load_all_generic()
        # Pre-sort all core lists by price for fast range queries
        self._presort_all()
        logger.info(self._stats_summary())

    def _presort_all(self) -> None:
        """Pre-sort all component lists by price. Also sort indexed sublists."""
        self.cpus.sort(key=lambda x: x.price)
        self.motherboards.sort(key=lambda x: x.price)
        self.memory.sort(key=lambda x: x.price)
        self.gpus.sort(key=lambda x: x.price)
        self.storage.sort(key=lambda x: x.price)
        self.psus.sort(key=lambda x: x.price)
        self.cases.sort(key=lambda x: x.price)
        self.coolers.sort(key=lambda x: x.price)
        # Sort indexed sublists too
        for items in self._cpu_by_socket.values():
            items.sort(key=lambda x: x.price)
        for items in self._mobo_by_socket.values():
            items.sort(key=lambda x: x.price)
        for items in self._memory_by_ddr.values():
            items.sort(key=lambda x: x.price)
        for items in self._storage_by_type.values():
            items.sort(key=lambda x: x.price)
        for items in self._generic.values():
            items.sort(key=lambda x: x.price)
        # Build price arrays for bisect (fast price range lookups)
        self._cpu_prices = [c.price for c in self.cpus]
        self._gpu_prices = [g.price for g in self.gpus]
        self._mobo_prices = {s: [m.price for m in lst] for s, lst in self._mobo_by_socket.items()}
        self._mem_prices = {d: [m.price for m in lst] for d, lst in self._memory_by_ddr.items()}

    def _load_all_generic(self) -> None:
        """Load all peripheral/accessory categories using generic CSV parsing."""
        for category, (filename, model_class) in self.GENERIC_CATEGORY_MAP.items():
            rows = self._load_csv(filename)
            total = len(rows)
            loaded = 0
            for row in rows:
                if not row.get("price", "").strip():
                    continue
                try:
                    # Build kwargs from CSV row, matching model fields
                    kwargs = {"name": row["name"], "price": float(row["price"])}
                    for field_name, field_info in model_class.model_fields.items():
                        if field_name in ("name", "price"):
                            continue
                        csv_val = row.get(field_name, "")
                        if not csv_val or not csv_val.strip():
                            kwargs[field_name] = None
                        else:
                            # Try to cast to the field's annotation
                            annotation = field_info.annotation
                            # Handle Optional types (str | None, float | None, etc.)
                            origin = getattr(annotation, "__origin__", None)
                            if origin is type(int | None):
                                # It's a union — get the non-None type
                                args = [a for a in annotation.__args__ if a is not type(None)]
                                target_type = args[0] if args else str
                            else:
                                target_type = annotation

                            try:
                                if target_type in (int,):
                                    kwargs[field_name] = int(float(csv_val))
                                elif target_type in (float,):
                                    kwargs[field_name] = float(csv_val)
                                else:
                                    kwargs[field_name] = csv_val.strip()
                            except (ValueError, TypeError):
                                kwargs[field_name] = csv_val.strip()

                    obj = model_class(**kwargs)
                    self._generic[category].append(obj)
                    loaded += 1
                except Exception as e:
                    logger.debug(f"Skipping {category} row: {row.get('name', '?')} — {e}")
            if loaded > 0:
                logger.info(f"{category}: {loaded} loaded from {total} rows")

    def _load_cpus(self) -> None:
        rows = self._load_csv("cpu.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                cpu = CPU(
                    name=row["name"],
                    price=float(row["price"]),
                    core_count=int(row["core_count"]),
                    core_clock=float(row["core_clock"]),
                    boost_clock=float(row["boost_clock"]),
                    microarchitecture=row["microarchitecture"],
                    tdp=int(float(row["tdp"])),
                    graphics=row.get("graphics", "None") or "None",
                    socket=row["socket"],
                )
                self.cpus.append(cpu)
                self._cpu_by_socket[cpu.socket].append(cpu)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping CPU row: {row.get('name', '?')} — {e}")
        logger.info(f"CPUs: {len(self.cpus)} loaded from {total} rows")

    def _load_motherboards(self) -> None:
        rows = self._load_csv("motherboard.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                mobo = Motherboard(
                    name=row["name"],
                    price=float(row["price"]),
                    socket=row["socket"],
                    form_factor=row["form_factor"],
                    max_memory=int(row["max_memory"]),
                    memory_slots=int(row["memory_slots"]),
                    color=row.get("color") or None,
                    ddr_generation=int(row["ddr_generation"]),
                )
                self.motherboards.append(mobo)
                self._mobo_by_socket[mobo.socket].append(mobo)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping motherboard row: {row.get('name', '?')} — {e}")
        logger.info(f"Motherboards: {len(self.motherboards)} loaded from {total} rows")

    def _load_memory(self) -> None:
        rows = self._load_csv("memory.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                mem = Memory(
                    name=row["name"],
                    price=float(row["price"]),
                    speed=row["speed"],
                    modules=row["modules"],
                    price_per_gb=_safe_float(row.get("price_per_gb")),
                    color=row.get("color") or None,
                    first_word_latency=_safe_float(row.get("first_word_latency")),
                    cas_latency=_safe_int(row.get("cas_latency")),
                    ddr_generation=int(row["ddr_generation"]),
                    speed_mhz=int(row["speed_mhz"]),
                    module_count=int(row["module_count"]),
                    module_size_gb=int(row["module_size_gb"]),
                    total_gb=int(row["total_gb"]),
                )
                self.memory.append(mem)
                self._memory_by_ddr[mem.ddr_generation].append(mem)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping memory row: {row.get('name', '?')} — {e}")
        logger.info(f"Memory: {len(self.memory)} loaded from {total} rows")

    def _load_gpus(self) -> None:
        rows = self._load_csv("video-card.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                gpu = VideoCard(
                    name=row["name"],
                    price=float(row["price"]),
                    chipset=row["chipset"],
                    memory=int(row["memory"]),
                    core_clock=_safe_int(row.get("core_clock")),
                    boost_clock=_safe_int(row.get("boost_clock")),
                    color=row.get("color") or None,
                    length=_safe_float(row.get("length")),
                    estimated_tdp=int(row["estimated_tdp"]),
                )
                self.gpus.append(gpu)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping GPU row: {row.get('name', '?')} — {e}")
        logger.info(f"GPUs: {len(self.gpus)} loaded from {total} rows")

    def _load_storage(self) -> None:
        rows = self._load_csv("internal-hard-drive.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                stor = Storage(
                    name=row["name"],
                    price=float(row["price"]),
                    capacity=float(row["capacity"]),
                    price_per_gb=_safe_float(row.get("price_per_gb")),
                    type=row.get("type", ""),
                    cache=_safe_int(row.get("cache")),
                    form_factor=row["form_factor"],
                    interface=row["interface"],
                    storage_type=row["storage_type"],
                )
                self.storage.append(stor)
                self._storage_by_type[stor.storage_type].append(stor)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping storage row: {row.get('name', '?')} — {e}")
        logger.info(f"Storage: {len(self.storage)} loaded from {total} rows")

    def _load_psus(self) -> None:
        rows = self._load_csv("power-supply.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                psu = PowerSupply(
                    name=row["name"],
                    price=float(row["price"]),
                    type=row["type"],
                    efficiency=row.get("efficiency") or None,
                    wattage=int(row["wattage"]),
                    modular=row["modular"],
                    color=row.get("color") or None,
                )
                self.psus.append(psu)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping PSU row: {row.get('name', '?')} — {e}")
        logger.info(f"PSUs: {len(self.psus)} loaded from {total} rows")

    def _load_cases(self) -> None:
        rows = self._load_csv("case.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                compat_str = row.get("compatible_form_factors", "")
                compat = [f.strip() for f in compat_str.split("|") if f.strip()] if compat_str else []
                case = Case(
                    name=row["name"],
                    price=float(row["price"]),
                    type=row["type"],
                    color=row.get("color") or None,
                    psu=_safe_float(row.get("psu")),
                    side_panel=row.get("side_panel") or None,
                    external_volume=_safe_float(row.get("external_volume")),
                    internal_35_bays=_safe_int(row.get("internal_35_bays")),
                    compatible_form_factors=compat,
                    estimated_max_gpu_length_mm=int(float(row.get("estimated_max_gpu_length_mm", 340))),
                )
                self.cases.append(case)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping case row: {row.get('name', '?')} — {e}")
        logger.info(f"Cases: {len(self.cases)} loaded from {total} rows")

    def _load_coolers(self) -> None:
        rows = self._load_csv("cpu-cooler.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                cooler = CPUCooler(
                    name=row["name"],
                    price=float(row["price"]),
                    rpm=row.get("rpm") or None,
                    noise_level=row.get("noise_level") or None,
                    color=row.get("color") or None,
                    size=_safe_float(row.get("size")),
                    cooler_type=row["cooler_type"],
                    radiator_size_mm=_safe_int(row.get("radiator_size_mm")),
                )
                self.coolers.append(cooler)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping cooler row: {row.get('name', '?')} — {e}")
        logger.info(f"Coolers: {len(self.coolers)} loaded from {total} rows")

    def _load_os(self) -> None:
        rows = self._load_csv("os.csv")
        total = len(rows)
        for row in rows:
            if not row.get("price", "").strip():
                continue
            try:
                os_item = OS(
                    name=row["name"],
                    price=float(row["price"]),
                    mode=row["mode"],
                    max_memory=int(row["max_memory"]),
                )
                self.os_list.append(os_item)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping OS row: {row.get('name', '?')} — {e}")
        logger.info(f"OS: {len(self.os_list)} loaded from {total} rows")

    # ---- Price range helper (bisect on pre-sorted lists) ----

    def _price_slice(self, items: list, prices: list[float],
                     min_price: float | None, max_price: float | None) -> list:
        """Use bisect on pre-sorted price array to get items in [min_price, max_price] range. O(log n)."""
        lo = bisect.bisect_left(prices, min_price) if min_price else 0
        hi = bisect.bisect_right(prices, max_price) if max_price else len(prices)
        return items[lo:hi]

    # ---- Query Methods ----

    # Modern sockets — exclude ancient platforms from searches without explicit socket
    MODERN_SOCKETS = {"AM5", "AM4", "LGA1700", "LGA1851", "LGA1200"}

    def search_cpus(
        self,
        socket: str | None = None,
        min_cores: int | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        brand: str | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        if socket:
            candidates = self._cpu_by_socket.get(socket, [])
        else:
            # No socket specified — filter to modern platforms only to avoid
            # returning ancient Bulldozer/Phenom/Core2 CPUs
            candidates = [c for c in self.cpus if c.socket in self.MODERN_SOCKETS]
            # Apply bisect price narrowing
            if min_price or max_price:
                prices = [c.price for c in candidates]
                candidates = self._price_slice(candidates, prices, min_price, max_price)

        filtered = []
        for c in candidates:
            if min_cores and c.core_count < min_cores:
                continue
            if max_price and c.price > max_price:
                continue
            if min_price and c.price < min_price:
                continue
            if brand and not c.name.lower().startswith(brand.lower()):
                continue
            filtered.append(c)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_motherboards(
        self,
        socket: str | None = None,
        form_factor: str | None = None,
        ddr_generation: int | None = None,
        max_price: float | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        results = self._mobo_by_socket.get(socket, []) if socket else self.motherboards
        filtered = []
        for m in results:
            if form_factor and m.form_factor != form_factor:
                continue
            if ddr_generation and m.ddr_generation != ddr_generation:
                continue
            if max_price and m.price > max_price:
                continue
            filtered.append(m)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_memory(
        self,
        ddr_generation: int | None = None,
        min_total_gb: int | None = None,
        max_modules: int | None = None,
        max_price: float | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        results = self._memory_by_ddr.get(ddr_generation, []) if ddr_generation else self.memory
        filtered = []
        for m in results:
            if min_total_gb and m.total_gb < min_total_gb:
                continue
            if max_modules and m.module_count > max_modules:
                continue
            if max_price and m.price > max_price:
                continue
            filtered.append(m)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_gpus(
        self,
        max_price: float | None = None,
        min_memory_gb: int | None = None,
        chipset_contains: str | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        filtered = []
        for g in self.gpus:
            if max_price and g.price > max_price:
                continue
            if min_memory_gb and g.memory < min_memory_gb:
                continue
            if chipset_contains and chipset_contains.lower() not in g.chipset.lower():
                continue
            filtered.append(g)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_storage(
        self,
        storage_type: str | None = None,
        min_capacity_gb: float | None = None,
        max_price: float | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        results = self._storage_by_type.get(storage_type, []) if storage_type else self.storage
        filtered = []
        for s in results:
            if min_capacity_gb and s.capacity < min_capacity_gb:
                continue
            if max_price and s.price > max_price:
                continue
            filtered.append(s)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_psus(
        self,
        min_wattage: int | None = None,
        efficiency: str | None = None,
        modular: str | None = None,
        max_price: float | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        filtered = []
        for p in self.psus:
            if min_wattage and p.wattage < min_wattage:
                continue
            if efficiency and p.efficiency and p.efficiency.lower() != efficiency.lower():
                continue
            if modular and p.modular.lower() != modular.lower():
                continue
            if max_price and p.price > max_price:
                continue
            filtered.append(p)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_cases(
        self,
        compatible_form_factor: str | None = None,
        max_price: float | None = None,
        min_gpu_length: int | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        filtered = []
        for c in self.cases:
            if compatible_form_factor and compatible_form_factor not in c.compatible_form_factors:
                continue
            if max_price and c.price > max_price:
                continue
            if min_gpu_length and c.estimated_max_gpu_length_mm < min_gpu_length:
                continue
            filtered.append(c)
        return self._sort_and_limit(filtered, sort_by, limit)

    def search_coolers(
        self,
        max_price: float | None = None,
        cooler_type: str | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        filtered = []
        for c in self.coolers:
            if max_price and c.price > max_price:
                continue
            if cooler_type and c.cooler_type.lower() != cooler_type.lower():
                continue
            filtered.append(c)
        return self._sort_and_limit(filtered, sort_by, limit)

    # ---- Generic search for peripherals/accessories ----

    def search_generic(
        self,
        category: str,
        max_price: float | None = None,
        sort_by: str = "price",
        limit: int = 10,
    ) -> list[dict]:
        """Search any category (peripherals, accessories, etc.) with price filter."""
        # Check core categories first
        if category == "os":
            items = self.os_list
        elif category == "cpu_cooler":
            items = self.coolers
        elif category in self._generic:
            items = self._generic[category]
        else:
            return []

        filtered = items
        if max_price:
            filtered = [i for i in items if i.price <= max_price]
        return self._sort_and_limit(filtered, sort_by, limit)

    # ---- Lookups ----

    def _get_all_categories(self) -> dict[str, list]:
        """Returns a map of category name -> list of items (for lookups)."""
        core = {
            "cpu": self.cpus, "motherboard": self.motherboards,
            "memory": self.memory, "gpu": self.gpus,
            "storage": self.storage, "psu": self.psus,
            "case": self.cases, "cpu_cooler": self.coolers,
            "os": self.os_list,
        }
        return {**core, **self._generic}

    def get_component_by_name(self, category: str, name: str) -> dict | None:
        """Look up a specific component by exact name (returns dict)."""
        all_cats = self._get_all_categories()
        components = all_cats.get(category, [])
        for comp in components:
            if comp.name == name:
                return comp.model_dump()
        # Fuzzy match: check if name is a substring
        for comp in components:
            if name.lower() in comp.name.lower():
                return comp.model_dump()
        return None

    def get_component_object(self, category: str, name: str):
        """Look up a component and return the Pydantic object (not dict)."""
        all_cats = self._get_all_categories()
        components = all_cats.get(category, [])
        for comp in components:
            if comp.name == name:
                return comp
        for comp in components:
            if name.lower() in comp.name.lower():
                return comp
        return None

    def get_summary_stats(self) -> dict:
        """Returns counts per category, price ranges. Used in system prompt."""
        stats = {}
        all_cats = self._get_all_categories()
        for cat_name, items in all_cats.items():
            if items:
                prices = [i.price for i in items]
                stats[cat_name] = {
                    "count": len(items),
                    "price_min": round(min(prices), 2),
                    "price_max": round(max(prices), 2),
                }
            else:
                stats[cat_name] = {"count": 0, "price_min": 0, "price_max": 0}
        stats["total_components"] = sum(
            s["count"] for s in stats.values() if isinstance(s, dict) and "count" in s
        )
        stats["category_count"] = sum(
            1 for s in stats.values() if isinstance(s, dict) and s.get("count", 0) > 0
        )
        return stats

    def _sort_and_limit(self, items: list, sort_by: str, limit: int) -> list[dict]:
        """Sort by field, limit results, return as dicts.

        Supports sort_by="value" to sort by price-performance score (descending).
        Supports sort_by="price" (ascending — cheapest first, default).
        Any other field sorts ascending.
        """
        if sort_by == "value":
            # Sort by value_score descending (best value first)
            try:
                items.sort(key=lambda x: getattr(x, "value_score", 0) or 0, reverse=True)
            except (AttributeError, TypeError):
                items.sort(key=lambda x: x.price)
        else:
            try:
                items.sort(key=lambda x: getattr(x, sort_by, 0) or 0)
            except (AttributeError, TypeError):
                items.sort(key=lambda x: x.price)

        limited = items[:min(limit, 20)]
        results = []
        for item in limited:
            d = item.model_dump()
            # Include value_score if the model has it
            if hasattr(item, "value_score"):
                try:
                    d["value_score"] = item.value_score
                except Exception:
                    pass
            results.append(d)
        return results

    def _stats_summary(self) -> str:
        all_cats = self._get_all_categories()
        core = f"{len(self.cpus)} CPUs, {len(self.motherboards)} mobos, {len(self.memory)} memory, {len(self.gpus)} GPUs, {len(self.storage)} storage, {len(self.psus)} PSUs, {len(self.cases)} cases, {len(self.coolers)} coolers"
        peripheral_count = sum(len(items) for items in self._generic.values())
        total = sum(len(items) for items in all_cats.values())
        return f"ComponentStore loaded: {core}, {peripheral_count} peripherals/accessories, {total} total"
