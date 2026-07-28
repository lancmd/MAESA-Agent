# Copilot project creation / Copilot 自然语言建项目

MAESA Copilot can turn a research goal and a user-reviewed local input list
into a `project.json`.  It does not let an LLM write shell commands or discover
arbitrary files.  The model may only select paths already listed in the input
manifest; the resulting plan is validated and still needs confirmation before
the local MCP builder runs.

## 1. Prepare an input inventory

Copy [copilot_project_inputs.example.json](../templates/copilot_project_inputs.example.json)
and replace its example paths with existing local data.  Put multi-period
imagery in `imagery_periods`; use `training_roi` for ENVI, or `model_package`
for PyTorch.  A one-off classification can use
`accuracy_config.validation_samples`.

For `classification_invest`, put the ROI and validation contract on **each**
imagery-period item instead of relying on a global sample file.  The selected
Carbon model also needs `carbon_density`, unless the inventory supplies an
explicit Carbon datastack.  The shipped inventory template shows the dated
form:

```json
{
  "year": 2020,
  "path": "data/imagery_2020.tif",
  "roi": "data/roi_2020.gpkg",
  "accuracy": {"validation_samples": "data/validation_2020.csv"}
}
```

The inventory is not a project.  It is a whitelist of inputs available to the
Copilot.  A missing data item should remain absent rather than being guessed.

## 2. Ask for a controlled creation plan

```powershell
python .\scripts\maesa_copilot.py `
  --input-manifest .\inputs.json `
  --output-project .\outputs\huaibei\project.json `
  --workspace .\outputs\huaibei\runtime `
  --message "使用六期影像和各期 ROI 做土地利用、碳储量和生境质量分析" `
  --write-project-plan .\outputs\huaibei\project_creation_plan.json
```

Read the plan before confirming.  The plan contains its fixed output project,
workspace, selected files, task mode, and expected inputs.  It cannot add a
path that was not present in `inputs.json`.

Before a plan is saved, Copilot runs the project builder and full project
validator in a temporary directory.  This does not create the selected
`project.json` or write into its workspace.  A plan is rejected when it would
fail task prerequisites; for example, `classification_invest` is rejected if
one period has no independent validation samples, or if its default Carbon
model has no carbon-density table.  Any non-blocking `pending_inputs` are
reported with the plan so they can be resolved before execution.

## 3. Confirm creation, then create an execution plan

```powershell
python .\scripts\maesa_copilot.py `
  --execute-project-plan .\outputs\huaibei\project_creation_plan.json --confirm

python .\scripts\maesa_copilot.py --project .\outputs\huaibei\project.json `
  --message "检查并执行这个项目" `
  --write-execution-plan .\outputs\huaibei\execution_plan.json
```

Project creation validates the generated document but does not run LULC,
PLUS, InVEST, or mapping.  Review the second plan and confirm it separately.
