"""Check the three-component subsidence-water carbon calculation with synthetic inputs."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from subsidence_water_carbon import calculate_components, calculate_invest_replacement  # noqa: E402
from project_validator import validate  # noqa: E402


components = calculate_components(
    water_volume_m3=1000,
    water_carbon_density_g_c_m3=10,
    aquatic_vegetation_area_ha=2,
    aquatic_vegetation_carbon_density_t_c_ha=5,
    bottom_sediment_area_ha=3,
    bottom_sediment_carbon_density_t_c_ha=20,
)
assert abs(components["subsidence_water_composite_carbon_t_c"] - 70.01) < 1e-9, components
assert abs(calculate_invest_replacement(
    invest_total_carbon_t_c=1000,
    invest_subsidence_water_carbon_t_c=100,
    composite_carbon_t_c=200,
) - 1100) < 1e-9
project_report = validate(ROOT / "tests" / "fixtures" / "local_project" / "subsidence_water_project.json")
assert project_report["status"] == "valid", project_report
print(round(components["subsidence_water_composite_carbon_t_c"], 2))
