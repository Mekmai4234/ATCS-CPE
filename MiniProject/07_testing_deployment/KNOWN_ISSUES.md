# Release blockers and ownership

These checks exercise current implementations without editing modules 02–06.

| ID | Owner | Gate and expected safe behavior |
|---|---|---|
| K03-PIPE | 03 | Reject oversized output (20 MiB, real ceiling 8 MiB) within a bounded cleanup time; reap the child. The probe has an emergency drain so verification can finish. |
| K04-ENV | 02/04/05 | Runtime and maintenance must resolve the same Chroma directory and embedding config. A 05-local override currently differs from the maintenance loader. |
| K04-STORE | 04 with 02/05 | Reindex against another empty Chroma store sharing SQLite must fail BEFORE changing the active manifest. Only disposable data is used. |

Run `check.py --group regressions`. No xfail/skip masks these defects. Future owner fixes
must also cover garbage collection, timeout/cancel with buffered output and concurrent
close. The store test detects unsafe reindexing, not every garbage-collection failure.

Other dependencies: 01 is absent, CI activation requires a change outside 07, live
end-to-end generation/semantic review and actual Docker build/run need execution. Root
README/architecture/task assignment and OpenAI defaults are stale. The 07 Compose
explicitly selects Gemini settings; this does not fix other entrypoints. Its preflight
compares effective configuration but does not add durable store-identity protection to 04.
