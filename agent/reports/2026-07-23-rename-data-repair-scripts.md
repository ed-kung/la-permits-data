# Rename data repair scripts

**Summary:** Renamed all nine `{city}_data_repair.py` scripts under `agent/scripts/` to `data_repair_{state}_{city}.py`. State is `ca` for California cities, `ny` for New York, and `pa` for Philadelphia (`phi`). Updated notebook imports that referenced the old module names.

## Renames

| Old | New |
| --- | --- |
| `burbank_data_repair.py` | `data_repair_ca_burbank.py` |
| `calabasas_data_repair.py` | `data_repair_ca_calabasas.py` |
| `compton_data_repair.py` | `data_repair_ca_compton.py` |
| `culver_city_data_repair.py` | `data_repair_ca_culver_city.py` |
| `downey_data_repair.py` | `data_repair_ca_downey.py` |
| `inglewood_data_repair.py` | `data_repair_ca_inglewood.py` |
| `lancaster_data_repair.py` | `data_repair_ca_lancaster.py` |
| `ny_data_repair.py` | `data_repair_ny_ny.py` |
| `phi_data_repair.py` | `data_repair_pa_phi.py` |

## Follow-ups

- Updated `from …_data_repair import data_repair` imports in test notebooks and `notebooks/playground.ipynb`.
- Historical agent reports still mention the old filenames.
