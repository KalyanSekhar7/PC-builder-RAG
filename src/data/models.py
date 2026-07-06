"""Pydantic models for all PC component types."""

from pydantic import BaseModel


class CPU(BaseModel):
    name: str
    price: float
    core_count: int
    core_clock: float
    boost_clock: float
    microarchitecture: str
    tdp: int
    graphics: str  # "None" means no iGPU
    socket: str

    @property
    def has_igpu(self) -> bool:
        return self.graphics != "None"

    @property
    def value_score(self) -> float:
        """Price-performance: (cores * boost_clock) / price. Higher = better value."""
        if self.price <= 0:
            return 0.0
        return round((self.core_count * self.boost_clock) / self.price, 3)


class Motherboard(BaseModel):
    name: str
    price: float
    socket: str
    form_factor: str
    max_memory: int
    memory_slots: int
    color: str | None = None
    ddr_generation: int

    @property
    def value_score(self) -> float:
        """Value: (memory_slots * max_memory) / price. Higher = more expandable per dollar."""
        if self.price <= 0:
            return 0.0
        return round((self.memory_slots * self.max_memory) / self.price, 3)


class Memory(BaseModel):
    name: str
    price: float
    speed: str  # raw field e.g. "5,6000"
    modules: str  # raw field e.g. "2,16"
    price_per_gb: float | None = None
    color: str | None = None
    first_word_latency: float | None = None
    cas_latency: int | None = None
    ddr_generation: int
    speed_mhz: int
    module_count: int
    module_size_gb: int
    total_gb: int

    @property
    def value_score(self) -> float:
        """Value: (total_gb * speed_mhz) / price. Higher = more bandwidth per dollar."""
        if self.price <= 0:
            return 0.0
        return round((self.total_gb * self.speed_mhz) / self.price, 3)


class VideoCard(BaseModel):
    name: str
    price: float
    chipset: str
    memory: int  # VRAM in GB
    core_clock: int | None = None  # MHz
    boost_clock: int | None = None  # MHz
    color: str | None = None
    length: float | None = None  # mm
    estimated_tdp: int

    @property
    def value_score(self) -> float:
        """Value: (vram_gb * boost_clock_mhz) / price. Higher = more GPU power per dollar."""
        if self.price <= 0:
            return 0.0
        clock = self.boost_clock or self.core_clock or 1000
        return round((self.memory * clock) / self.price, 3)


class Storage(BaseModel):
    name: str
    price: float
    capacity: float  # GB
    price_per_gb: float | None = None
    type: str  # "SSD" or RPM number
    cache: int | None = None  # MB
    form_factor: str
    interface: str
    storage_type: str  # "NVMe SSD", "SATA SSD", "HDD"

    @property
    def value_score(self) -> float:
        """Value: capacity_gb / price. Higher = more storage per dollar."""
        if self.price <= 0:
            return 0.0
        return round(self.capacity / self.price, 3)


class PowerSupply(BaseModel):
    name: str
    price: float
    type: str  # ATX, SFX, etc.
    efficiency: str | None = None  # gold, platinum, etc.
    wattage: int
    modular: str  # Full, Semi, No
    color: str | None = None


class Case(BaseModel):
    name: str
    price: float
    type: str  # "ATX Mid Tower", etc.
    color: str | None = None
    psu: float | None = None  # included PSU wattage, usually None
    side_panel: str | None = None
    external_volume: float | None = None
    internal_35_bays: int | None = None
    compatible_form_factors: list[str]  # parsed from pipe-delimited
    estimated_max_gpu_length_mm: int


class CPUCooler(BaseModel):
    name: str
    price: float
    rpm: str | None = None
    noise_level: str | None = None
    color: str | None = None
    size: float | None = None
    cooler_type: str  # "Air" or "AIO Liquid"
    radiator_size_mm: int | None = None


class OS(BaseModel):
    name: str
    price: float
    mode: str  # "64", "32,64"
    max_memory: int


# ---- Peripherals ----

class Monitor(BaseModel):
    name: str
    price: float
    screen_size: float | None = None
    resolution: str | None = None
    refresh_rate: int | None = None
    response_time: float | None = None
    panel_type: str | None = None
    aspect_ratio: str | None = None


class Keyboard(BaseModel):
    name: str
    price: float
    style: str | None = None
    switches: str | None = None
    backlit: str | None = None
    tenkeyless: str | None = None
    connection_type: str | None = None
    color: str | None = None


class Mouse(BaseModel):
    name: str
    price: float
    tracking_method: str | None = None
    connection_type: str | None = None
    max_dpi: int | None = None
    hand_orientation: str | None = None
    color: str | None = None


class Headphones(BaseModel):
    name: str
    price: float
    type: str | None = None
    frequency_response: str | None = None
    microphone: str | None = None
    wireless: str | None = None
    enclosure_type: str | None = None
    color: str | None = None


class Speakers(BaseModel):
    name: str
    price: float
    configuration: str | None = None
    wattage: float | None = None
    frequency_response: str | None = None
    color: str | None = None


class Webcam(BaseModel):
    name: str
    price: float
    resolutions: str | None = None
    connection: str | None = None
    focus_type: str | None = None
    os: str | None = None
    fov: float | None = None


# ---- Expansion / Networking ----

class SoundCard(BaseModel):
    name: str
    price: float
    channels: float | None = None
    digital_audio: str | None = None
    snr: float | None = None
    sample_rate: float | None = None
    chipset: str | None = None
    interface: str | None = None


class WiredNetworkCard(BaseModel):
    name: str
    price: float
    interface: str | None = None
    color: str | None = None


class WirelessNetworkCard(BaseModel):
    name: str
    price: float
    protocol: str | None = None
    interface: str | None = None
    color: str | None = None


# ---- Accessories ----

class CaseFan(BaseModel):
    name: str
    price: float
    size: float | None = None
    color: str | None = None
    rpm: str | None = None
    airflow: str | None = None
    noise_level: str | None = None
    pwm: str | None = None


class FanController(BaseModel):
    name: str
    price: float
    channels: float | None = None
    channel_wattage: float | None = None
    pwm: str | None = None
    form_factor: str | None = None
    color: str | None = None


class ThermalPaste(BaseModel):
    name: str
    price: float
    amount: float | None = None


class OpticalDrive(BaseModel):
    name: str
    price: float
    bd: str | None = None
    dvd: str | None = None
    cd: str | None = None
    bd_write: str | None = None
    dvd_write: str | None = None
    cd_write: str | None = None


class ExternalHardDrive(BaseModel):
    name: str
    price: float
    type: str | None = None
    interface: str | None = None
    capacity: float | None = None
    price_per_gb: float | None = None
    color: str | None = None


class CaseAccessory(BaseModel):
    name: str
    price: float
    type: str | None = None
    form_factor: str | None = None


class UPS(BaseModel):
    name: str
    price: float
    capacity_w: float | None = None
    capacity_va: float | None = None


class PCConfiguration(BaseModel):
    """A complete PC build configuration."""
    cpu: CPU
    motherboard: Motherboard
    memory: Memory
    gpu: VideoCard | None = None
    storage: list[Storage]
    psu: PowerSupply
    case: Case
    cooler: CPUCooler
    os: OS | None = None

    @property
    def total_price(self) -> float:
        total = (
            self.cpu.price
            + self.motherboard.price
            + self.memory.price
            + self.psu.price
            + self.case.price
            + self.cooler.price
        )
        if self.gpu:
            total += self.gpu.price
        total += sum(s.price for s in self.storage)
        if self.os:
            total += self.os.price
        return round(total, 2)

    @property
    def estimated_power_draw(self) -> int:
        draw = self.cpu.tdp
        if self.gpu:
            draw += self.gpu.estimated_tdp
        draw += self.memory.module_count * 5  # ~5W per DIMM
        draw += len(self.storage) * 8  # ~8W per drive
        draw += 30  # fans, board, misc
        return draw
