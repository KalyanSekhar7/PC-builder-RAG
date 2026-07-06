# Data Enrichment Log — `data_added/`

This folder contains enriched copies of the original CSVs from `data/csv/`. The original files are untouched. Below is a complete record of every column added, how it was derived, and what sources were used.

---

## Files Modified

### 1. `cpu.csv`

| New Column | How Filled | Source |
|---|---|---|
| `socket` | Mapped from `microarchitecture` using a static lookup table (33 architectures → sockets) | **Domain knowledge** — these are published, unchanging facts (e.g., every Zen 5 CPU uses AM5, every Alder Lake uses LGA1700). No internet lookup needed. |
| `boost_clock` (gap-fill) | Where `boost_clock` was empty (686 rows), filled with `core_clock` as a conservative fallback | **Logic** — boost is always ≥ base clock, so using base clock is a safe lower bound |
| `graphics` (gap-fill) | Where `graphics` was empty (792 rows), filled with `"None"` to explicitly mark CPUs with no integrated graphics | **Logic** — empty means the CPU has no iGPU, which is a critical signal (must pair with a discrete GPU) |

**Microarchitecture → Socket mapping used:**
```
AMD:  Zen 5/Zen 4 → AM5, Zen 3/Zen 2/Zen+/Zen → AM4, Bulldozer/Piledriver → AM3+,
      Steamroller/Excavator → FM2+, K10 → AM3, Lynx → FM1, Jaguar/Puma+ → AM1

Intel: Arrow Lake → LGA1851, Raptor Lake (Refresh)/Alder Lake → LGA1700,
       Rocket Lake/Comet Lake → LGA1200, Coffee Lake (Refresh)/Kaby Lake/Skylake → LGA1151,
       Broadwell/Haswell (Refresh) → LGA1150, Ivy Bridge/Sandy Bridge → LGA1155,
       Nehalem/Westmere → LGA1366, Cascade Lake → LGA2066,
       Wolfdale/Yorkfield/Core → LGA775
```

**Coverage:** 1413/1413 rows mapped (100%)

---

### 2. `motherboard.csv`

| New Column | How Filled | Source |
|---|---|---|
| `ddr_generation` | Multi-step derivation (see below) | **Socket-based rules + internet verification for ambiguous boards** |

**Derivation logic (in order of precedence):**

1. **Socket-based (non-ambiguous):** Most sockets support only one DDR generation. Direct mapping used for AM5→DDR5, AM4→DDR4, LGA1851→DDR5, LGA1200→DDR4, etc. Applied to 4222 rows.

2. **Integrated CPU boards:** 70 boards with `Integrated ...` sockets assigned DDR3 (default for that era).

3. **LGA1700 (ambiguous — supports both DDR4 and DDR5):** 681 boards required special handling:
   - **Name contains "DDR4" or "D4"** → DDR4 (73 boards)
   - **Name contains "DDR5" or "D5"** → DDR5 (1 board)
   - **`max_memory` ≥ 192GB** → DDR5 (105 boards — DDR4 can't reach 192GB on consumer boards)
   - **Remaining 38 boards** with `max_memory` 64–128GB and no DDR hint in name → **verified individually via internet lookup**

**Internet-verified boards (38 total, 9 had wrong heuristic guesses):**

Corrections made (heuristic was wrong):
| Board | Heuristic Said | Actually Is | Source |
|---|---|---|---|
| Gigabyte H610M K V2 | DDR4 | **DDR5** | Product page |
| Asus ROG STRIX Z690-I GAMING WIFI | DDR4 | **DDR5** | ASUS specs |
| MSI PRO H610M-E | DDR4 | **DDR5** | MSI specs |
| Asus ROG STRIX B660-I GAMING WIFI | DDR4 | **DDR5** | ASUS specs |
| NZXT N7-Z69XT-B1 | DDR5 | **DDR4** | NZXT product page |
| NZXT N7-Z69XT-W1 | DDR5 | **DDR4** | NZXT product page |
| MSI PRO H610M-G | DDR4 | **DDR5** | MSI specs |
| MSI MEG Z690 UNIFY-X | DDR4 | **DDR5** | MSI specs |
| Asus ROG MAXIMUS Z690 APEX | DDR4 | **DDR5** | ASUS specs |

**Coverage:** 4973/4973 rows mapped (100%), 0 missing for priced rows

---

### 3. `memory.csv`

| New Column | How Filled | Source |
|---|---|---|
| `ddr_generation` | Parsed from `speed` field — first value before comma (e.g., `"5,6000"` → DDR5) | **Parsed from existing data** |
| `speed_mhz` | Parsed from `speed` field — second value after comma (e.g., `"5,6000"` → 6000 MHz) | **Parsed from existing data** |
| `module_count` | Parsed from `modules` field — first value (e.g., `"2,16"` → 2 sticks) | **Parsed from existing data** |
| `module_size_gb` | Parsed from `modules` field — second value (e.g., `"2,16"` → 16 GB each) | **Parsed from existing data** |
| `total_gb` | Computed: `module_count × module_size_gb` | **Computed** |

**Special cases (4 rows with non-standard format):**
These had a single number in `speed` (e.g., `400`) instead of `"DDR_GEN,FREQ"` format. Verified via internet:

| Module | Identified As | Source |
|---|---|---|
| Mushkin 971130A 1 GB (speed=400) | DDR1-400 | Newegg product listing |
| Mushkin 971307B 1 GB (speed=333) | DDR1-333 | Newegg product listing |
| Silicon Power SP001GBRDE400O01 (speed=400) | DDR1-400 | Silicon Power product page |
| Silicon Power SP001GBRDE333O01 (speed=333) | DDR1-333 | Silicon Power product page |

**Coverage:** 13553/13553 rows parsed (100%)

---

### 4. `video-card.csv`

| New Column | How Filled | Source |
|---|---|---|
| `estimated_tdp` | Static lookup table mapping GPU chipset → TDP in watts | **Published manufacturer specs (NVIDIA, AMD, Intel)** |
| `boost_clock` (gap-fill) | Where `boost_clock` was empty, filled with `core_clock` as conservative fallback | **Logic** |

**TDP sources by GPU family:**
- **NVIDIA GeForce RTX 50/40/30/20 series, GTX 16/10/9 series, older:** NVIDIA official specs, TechPowerUp GPU database
- **AMD Radeon RX 9000/7000/6000/5000 series, R9/R7, HD series:** AMD official specs, TechPowerUp
- **Intel Arc A/B series:** Intel specs, Tom's Hardware reviews
- **NVIDIA Quadro/RTX Pro/Tesla:** NVIDIA datasheets
- **AMD Radeon Pro/FirePro:** AMD datasheets

**18 chipsets required internet verification** (had been assigned a default of 150W). Corrections:
| Chipset | Corrected TDP | Source |
|---|---|---|
| Arc B580 | 190W | Tom's Hardware review |
| Radeon PRO W7600 | 130W | AMD product page |
| Radeon PRO W7700 | 190W | AMD product page |
| Radeon RX 7600 XT | 190W | AMD product page |
| GeForce RTX 5060 | 145W | TechPowerUp review |
| Radeon RX 570 | 120W | Notebookcheck specs |
| FirePro V8750 | 151W | TechPowerUp GPU specs |

(Remaining 11 of the 18 were confirmed at 150W — the default was correct.)

**Coverage:** ~190 unique chipsets mapped. All priced GPU rows have verified TDP values. Unpriced rows with truly unknown chipsets default to 150W.

---

### 5. `internal-hard-drive.csv`

| New Column | How Filled | Source |
|---|---|---|
| `storage_type` | Derived from `type` and `interface` columns | **Logic applied to existing data** |

**Derivation rules:**
```
IF type == "SSD" AND interface contains "PCIe" or "NVMe"  → "NVMe SSD"
IF type == "SSD" AND interface contains "SATA"             → "SATA SSD"
IF type is a number (RPM value like 5400, 7200)            → "HDD"
```

**Result distribution:** 2124 NVMe SSD, 2553 SATA SSD, 1784 HDD

**Coverage:** 6461/6461 rows classified (100%)

---

### 6. `case.csv`

| New Column | How Filled | Source |
|---|---|---|
| `compatible_form_factors` | Mapped from `type` using standard ATX compatibility rules (pipe-delimited) | **Industry standard rules** |
| `estimated_max_gpu_length_mm` | Estimated by case type category | **Typical clearances by case category** (estimated, not per-model exact) |

**Form factor compatibility rules used:**
```
ATX Full Tower     → EATX, ATX, Micro ATX, Mini ITX
ATX Mid Tower      → ATX, Micro ATX, Mini ITX
ATX Desktop        → ATX, Micro ATX, Mini ITX
MicroATX Mid Tower → Micro ATX, Mini ITX
MicroATX Mini/Slim → Micro ATX, Mini ITX
Mini ITX Tower     → Mini ITX, Mini DTX
Mini ITX Desktop   → Mini ITX, Mini DTX
HTPC               → Mini ITX, Micro ATX
```

**GPU clearance estimates used:**
```
ATX Full Tower: 420mm, ATX Mid Tower: 360mm, ATX Desktop: 340mm
MicroATX Mid Tower: 330mm, MicroATX Mini Tower: 300mm, MicroATX Slim: 250mm
Mini ITX Tower: 310mm, Mini ITX Desktop: 250mm, HTPC: 250mm
```

**2 special cases verified via internet:**
| Case | Type | Form Factors | GPU Clearance | Source |
|---|---|---|---|---|
| PrimoChill Praxis WetBench | ATX Test Bench | EATX, ATX, Micro ATX, Mini ITX | ~500mm (open-air, no limit) | PrimoChill product page |
| Streacom DA6 | Mini ITX Test Bench | Mini ITX | 323mm | Streacom product page, TechPowerUp review |

**Note:** `estimated_max_gpu_length_mm` values are category-level estimates, not per-model exact measurements. Marked as "estimated" — actual clearance varies by specific case model.

**Coverage:** 6551/6626 rows mapped from rules + 2 from internet. 73 unpriced rows with rare types (ATX Mini Tower) use 340mm default.

---

### 7. `cpu-cooler.csv`

| New Column | How Filled | Source |
|---|---|---|
| `cooler_type` | "Air" or "AIO Liquid" — derived from `size` field and name keywords | **Logic applied to existing data + 1 internet verification** |
| `radiator_size_mm` | Taken from `size` field for AIO coolers (120/240/280/360) | **Parsed from existing data** |

**Derivation rules:**
```
IF size field has a numeric value (120, 240, 280, 360)  → AIO Liquid, radiator = that value
IF name contains LIQUID, AIO, KRAKEN, H100, H150, etc. → AIO Liquid (size may be unknown)
OTHERWISE                                                → Air cooler
```

**1 internet correction:**
| Cooler | Issue | Correction | Source |
|---|---|---|---|
| Rosewill RCX-ZAIO-92 | "ZAIO" in name triggered AIO classification | Actually an **air cooler** (tower heatsink with 92mm fan) | Newegg listing, Hardware Secrets review |

**Result distribution:** 1556 Air, 1295 AIO Liquid

**Coverage:** 2851/2851 rows classified (100%). All priced AIO coolers have radiator sizes.

---

## Files NOT Modified

These CSVs were copied as-is from `data/csv/` with no enrichment:
`case-accessory.csv`, `case-fan.csv`, `external-hard-drive.csv`, `fan-controller.csv`,
`headphones.csv`, `keyboard.csv`, `monitor.csv`, `mouse.csv`, `optical-drive.csv`,
`os.csv`, `power-supply.csv`, `sound-card.csv`, `speakers.csv`, `thermal-paste.csv`,
`ups.csv`, `webcam.csv`, `wired-network-card.csv`, `wireless-network-card.csv`

---

## Remaining Known Gaps (by design)

These empty values exist in the data but are handled at the application level, not filled in the CSV:

| Column | File | % Empty (priced) | Why Not Filled |
|---|---|---|---|
| `color` | various | 1–63% | Cosmetic — only used if user specifies a color preference |
| `psu` | case.csv | 98.3% | Empty = no included PSU. Semantically correct as-is. |
| `cache` | internal-hard-drive.csv | 63.5% | Not used in compatibility checks or recommendations |
| `switches` | keyboard.csv | 46% | Preference-based, not fillable without per-model lookup |
| `noise_level` | cpu-cooler.csv | 11.8% | Nice-to-have filter, not critical |
| `response_time` | monitor.csv | 21.7% | Preference-based, not used in compatibility |
| `max_dpi` | mouse.csv | 18.6% | Preference-based |
| `efficiency` | power-supply.csv | 7% | Could default to "bronze" but left as-is to avoid false data |
