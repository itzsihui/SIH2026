# Verified Resources Ledger (Audited 9 Nov 2026)

This ledger contains only primary-verified papers, repositories, and datasets that passed direct URL and content checks.
Unchecked figures and preliminary items are explicitly flagged. For the full audit log, see [docs/35_resource_scan_audit.md](../docs/35_resource_scan_audit.md).

---

## 1. Verified Academic Research

### Parametric Design & Basis Risk Optimization
- **Maier, M. J., & Scherer, M. (arXiv:2604.21372)**  
  *Optimal basis risk weighting in expectile-based parametric insurance*  
  [https://arxiv.org/abs/2604.21372](https://arxiv.org/abs/2604.21372)  
  *Finding:* Proves that conditional expectiles strictly minimize asymmetric basis risk for risk-averse policyholders. Directly supports DayCover+'s multi-tiered payout structure.
- **Maier, M. J., & Scherer, M. (arXiv:2505.02607)**  
  *Expectiles as basis risk-optimal payment schemes in parametric insurance*  
  [https://arxiv.org/abs/2505.02607](https://arxiv.org/abs/2505.02607)

### Anticipatory Payouts & Forecast-Based Cash Transfers
- **Pople, A., Hill, R. V., Dercon, S., & Brunckhorst, B.**  
  *The importance of being early: anticipatory cash transfers for flood-affected households*  
  Oxford University / Centre for the Study of African Economies (CSAE) Working Paper.  
  *Empirical Result:* Evaluated ~23,000 households in Bangladesh receiving mobile money transfers 5 days before flood peak. Treated households were 36% less likely to go a day without eating compared to traditional post-disaster aid recipients.

### Singapore Climate Impact & Worker Economics
- **Project HeatSafe (NUS Medicine / Singapore-ETH Centre, 18 Mar 2024)**  
  *Macroeconomic and worker productivity toll of extreme heat in Singapore*  
  [https://heatsafe.org/](https://heatsafe.org/)  
  *Verified Numbers:*  
  - Median income loss of **S$21 per outdoor worker per hot day** (~24% of daily median earnings of surveyed workers).  
  - Economy-wide output loss in Singapore estimated at **S$1.18 billion in 2018**.  
  - *(Note: The S$2.22 billion figure often cited is a projected macroeconomic forecast for the year 2035, not a current annual loss).*
- **Quah, E., Chia, W. M., & Tan, T. S. (Aug 2021)**  
  *Economic impact of 2015 transboundary haze on Singapore*, Journal of Asian Economics, Vol. 74, 101329.  
  *(Note: Specific headline totals like S$1.83B are unverified pending direct journal retrieval; cite paper title and journal only).*
- **Chu, Y., Liu, P., & Salvo, A. (Oct 2020)**  
  *Air pollution as a determinant of food delivery and related plastic waste*, Nature Human Behaviour.  
  *(Note: Study examines food delivery orders and plastic packaging under air pollution; study setting is not Singapore, do NOT describe as Singapore data).*

---

## 2. Verified Open-Source Codebases & Libraries

### GitHub Repositories (Verified Owners & Active Codebases)
- **[GeoStat-Framework/PyKrige](https://github.com/GeoStat-Framework/PyKrige)** — Python 2D & 3D ordinary and universal kriging toolkit.
- **[georgebv/pyextremes](https://github.com/georgebv/pyextremes)** — Extreme Value Analysis (EVA), Peaks-Over-Threshold (POT), and GEV distribution fitting in Python.
- **[pySTEPS/pysteps](https://github.com/pySTEPS/pysteps)** — Python library for short-term probabilistic radar-based precipitation nowcasting.
- **[OasisLMF/OasisLMF](https://github.com/OasisLMF/OasisLMF)** — Open-source catastrophe loss modeling framework supported by global insurers and reinsurers.
- **[aisingapore/sealion](https://github.com/aisingapore/sealion)** — AI Singapore Southeast Asian Language in One Network repository.
- **[CompVis/weather-rf](https://github.com/CompVis/weather-rf)** — Generative rectified-flow radar nowcasting framework.

### Hugging Face Verified Models & Checkpoints
- **`it4lia/irene`** — Pretrained ConvGRU radar precipitation nowcasting model.
- **`CompVis/weather-rf`** — Frame-wise encoder-decoder model weights for precipitation forecasting.
- **`FarrasArchi/nowcasting-checkpoints`** — Benchmark nowcasting model checkpoints.
- **`climatebert`** — ClimateBERT text and physical risk categorization models.

---

## 3. Verified Sovereign Datasets (data.gov.sg)

- **MOH Polyclinic Attendances for Selected Diseases**  
  Dataset ID: `d_5d5508f1c954f5630d7b3aa7875d01f9`  
  Fields: `epi_week`, `disease`, `no_of_cases`.  
  *Coverage:* Weekly national attendances for acute respiratory infections, conjunctivitis, etc.  
  *Appropriate Use:* Background epidemiological context for health shocks during haze weeks. *(Do NOT cite as proof of insurable interest; stallholder insurable interest arises from the NEA stall licence and financial revenue exposure).*
- **Daily Weather Records (Admiralty, 2009–2017)**  
  Dataset ID: `d_03bb2eb67ad645d0188342fa74ad7066`  
  *Status:* Verified, stored in `data/raw/daily_weather_records.csv`.
- **Hawker Centres Directory & Closures**  
  Dataset IDs: `d_68a42f09f350881996d83f9cd73ab02f` (Hawker Centres) and `d_bda4baa634dd1cc7a6c7cad5f19e2d68` (Closures).  
  *Status:* Verified, stored in `data/raw/`.

---

## 4. Unverified / Hallucinated Items (DO NOT CITE)

- ❌ `arXiv:1806.01424` (Guo & Li): Points to an unrelated differential geometry mathematics paper.
- ❌ `doi:10.1093/wber/lhae017` (Pople et al.): Belongs to a Tanzanian road infrastructure paper.
- ❌ `doi:10.1080/10920277.2021.1944111` (North American Actuarial Journal): Non-existent DOI.
- ❌ Kaggle links (404 / bot-blocked).
- ❌ `aisingapore/sea-lionv3-8b-instruct` on Hugging Face (returns 401).
- ❌ Overstated claim that polyclinic attendances "prove insurable interest".
- ❌ SEWA "3 to 2 days, 0.5°C threshold" unverified specifics (only verified that 2023 paid zero, 2024 paid ~92%).
- ❌ Droplet claimed as "at drop-off" (official press release specifies rain at *pick-up* location).
