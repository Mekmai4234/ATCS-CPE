# PR12 follow-up verification — 20 October 2026

Scope: only `MiniProject/07_testing_deployment`. The feature branch synchronizes with
`develop@6520b4cd2361ce1acd4121a6ea4dd1663c73da10`; pending PR implementation changes
were tested in an ignored source snapshot, not merged into this PR.

## Review fixes

1. **Preflight and service configuration:** replace the removed 05 `ENV_FILES` import
   with 02's `FullSettings` contract. Resolve the selected file once, validate service
   settings and compare actual runtime/maintenance SQLite, Chroma and embedding
   fingerprint values. For new 05 use `load_team_configuration`; for develop's legacy
   loader export every resolved field before checking its dotenv-based constructors.
   Initialize through `initialize_pair`, and verify/export the same snapshot for API and
   worker. No old constant is reintroduced and no module outside 07 is patched.
2. **Real regression assertions:** stop mocking removed `cli.Settings`/`RagSettings`.
   Use 04's parser with a selected env file, require `index_store_mismatch` for wrong-store
   reindex AND GC, and check active/runs/chunks metadata is unchanged and the wrong
   directory is not created. Keep the real 20 MiB caption cleanup/reap gate.
3. **Complete image inputs:** include 02 full tests, the allowlisted 06 directory
   (supporting fixtures plus its current packaged `youtube_agent/data/acceptance.json`),
   and 03's new acceptance script read by its tests. Non-editable Linux installations
   exercise the actual packaged 06 dataset, without adding a placeholder fixture.
4. **Runner coverage and paths:** add `02_api_backend/full/tests` as a separate suite.
   Keep reports under 07/runtime but put pytest state in short, unique OS temp paths.
   `--temp-root` / `YK07_TEMP_ROOT` are configurable, and reports retain the state path.
   No automatic recursive deletion of an operator's selected temp root is performed.
5. **Dependency and documentation accuracy:** rerun `uv lock`, locked sync and lock
   validation against both source compositions. Both currently resolve 116 packages;
   the lockfile already matches, so no artificial lock diff or unrelated upgrade is made.
   Preserve TEST_REPORT.md as historical evidence and document the now-repaired gates.

## Source compositions

| Composition | Immutable refs |
|---|---|
| Current base | develop `6520b4cd2361ce1acd4121a6ea4dd1663c73da10` plus this 07 working tree |
| Pending-PR compatibility | Same base, overlay 05/PR13 `74d1737e8651725eaa66ab9121df06bd8839a730`, 06/PR11 `576575fa9eae3cb320f06c40d3a9c3bc7e4be7e3`, 02/PR16 `8780a5ebd163349d4b6bef1b18ee8498dbcd0f18`, plus this 07 working tree |

The snapshot lives under `runtime/compat-20261020/MiniProject`; `source-refs.json` records
the refs. Native compatibility runs prepend its 02–06 src directories to PYTHONPATH;
Docker builds install that snapshot's packages non-editably using the 07 lockfile.
PR16 is necessary for 02's own full-flow test setup to match PR13's removed constant;
07 does not modify or silently skip those tests. PR15/frontend is not part of this matrix.

## Results

| Suite | Base Windows | Compatibility Windows | Base Linux | Compatibility Linux |
|---|---:|---:|---:|---:|
| 02 | 68 | 68 | 68 | 68 |
| 03 | 78 | 78 | 78 | 78 |
| 04 | 97 | 97 | 97 | 97 |
| 05 | 66 | 90 | 66 | 90 |
| 06 | 55 | 75 | 55 | 75 |
| 02 integration | 9 | 9 | 9 | 9 |
| 02 full | 26 | 26 | 26 | 26 |
| 07 acceptance/tooling/recovery | 13 | 13 | 13 | 13 |
| 07 regressions | 4 | 4 | 4 | 4 |
| **Passed total** | **416** | **460** | **416** | **460** |

All four results have zero failures/errors/skips; the live embedding test is deselected.
Base Windows totals combine baseline, acceptance and regression group commands; the
compatibility Windows and BOTH final Linux results are complete runner executions with
exit 0. Ruff lint/format, Compose validation, locked install and Git whitespace checks
passed. Counts are
suite results, not distinct production behaviors or model-quality measurements.

Both runtime/test image builds and both Compose startup drills passed. Drills created
fresh guarded pairs, started the full factory/API/worker, checked internal HTTP health
and `full_pair_preflight=true`, then removed their own containers/network/volume.
They used synthetic keys with outbound access blocked, and made no provider calls.
Base startup: `yk07-startup-e67782bbfb91`, 56.297 s including cleanup. Compatibility:
`yk07-startup-4c94b0771d66`, 46.484 s including cleanup.

Initial exploratory images exposed a missing 03 acceptance-script input; this was fixed
in 07 and the final images were rebuilt. Only final standard-runner results are the
Linux acceptance evidence; exploratory/cancelled runs are not presented as green builds.

## Local artifacts and reproduction

- Base Windows baseline: `runtime/20261020T143518589837Z/`.
- Base Windows acceptance: `runtime/20261020T143315874395Z/`.
- Base Windows regressions: `runtime/20261020T143438470857Z/`.
- Compatibility Windows: `runtime/compat-20261020/MiniProject/07_testing_deployment/runtime/20261020T143514072773Z/`.
- Final Linux JUnit/log/JSON: `runtime/review-base-linux/` and `runtime/review-compat-linux/`.
- Packaged 06 dataset check: `runtime/review-packaged-dataset.log` validates the installed
  site-packages resource, not just a copied source fixture.
- Final Linux command logs: `runtime/review-base-linux-final.log` and `runtime/review-compat-linux-final.log`.
- Build logs: `runtime/review-{base,compat}-build-final.log` and runtime build logs.
- Startup reports are in their project-named runtime directories (compatibility under
  the snapshot's 07/runtime). Raw logs/reports and synthetic state are ignored by Git.

Run `uv sync --project 07_testing_deployment --locked`, then `check.py` as described in
README.md. Build/run the standard 07 Compose tests profile for Linux. Select a shorter
`--temp-root` if the OS temporary directory itself is too deep on Windows.

## Remaining scope

All test containers were removed after report capture; startup helpers removed their
own isolated volumes/networks. Images/build cache and short OS temporary state remain
for diagnosis/reuse.

The CI file remains a **template** inside 07; no GitHub workflow was installed outside
07. Frontend build/unit/browser checks await integration of 01 (separate PR15). No live
YouTube/Gemini semantic evaluation, paid generation, public deployment, host-port browser
acceptance or operational production-volume rollback was performed. Offline regression
success and guarded startup do not establish model access or educational quality.
