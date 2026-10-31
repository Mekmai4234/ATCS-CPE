# P1 shared evidence library

`rag.evidence_library().search(question, sources, backend_context, ...)` exposes a
bounded local catalogue for 05/06. No embedding or vision request is made. Records
keep distinct `transcript`, `ocr`, `visual`, and native `video` kinds; text, source
generation/version, exact interval, original citation and provenance remain intact.
The catalogue reuses the existing immutable transcript chunks, current media revision
index and private native observation store instead of manufacturing speech chunks.

Arguments: `kinds`, `limit` (1–100), `max_records` (1–5000, at least one per source),
`start_seconds`, `end_seconds`, and `neighbors` (0–2). Time intervals intersect the
requested interval; returned timestamps are not clipped or invented. Adjacent evidence
keeps its original kind/version and obeys the time filter. Sources are ranked separately
and selected round-robin so one clip cannot occupy every result slot when the limit
can cover all matching clips. English words and Thai character bigrams supply lexical
topic lookup. Scores measure text overlap, not confidence or semantic correctness.

Collection is bounded equally per clip. Transcript lookup filters the existing SQLite
chunk catalogue by topic terms and interval BEFORE limiting results, so relevant late
content is not hidden by an unrelated prefix. Up to 24 lexical terms are used; a larger
query discloses incomplete collection. Native revision scans inspect at most 64 recent revisions and no more than the
record budget. `complete=false` discloses a collection bound or incomplete inventory;
`complete=true` only means that collection was complete, never that every frame or
claim was checked. Consumers must escalate an unsuccessful bounded lookup rather than
treat it as proof that no relevant evidence exists. OCR/visual records retain their v2
snapshot and asset citation; they cannot be passed as transcript-v1 citations.

Every call requires a real authenticated backend execution. Current job/lease, account,
selected sources, library grant and source generation/version are checked before and
after collection. Native observations are private to their owner, current configured
effective vision model (`vision_model or llm_model`), supported prompt version and one-hour reuse lifetime. Expiry only removes reuse
eligibility; immutable referenced observations remain in 02 for historical citation
verification. OCR/visual data uses only the current revision pointer for that generation.
Revocation, cancellation and changed versions fail closed; no browser-supplied owner is
accepted. There is no mutable global result cache or new migration.

05 integration is outside this module's PR. It can use these candidates before deciding
to inspect video again, and must judge whether they actually support the new question.
06's separate P1 PR uses native-video candidates for learning and revalidates their
canonical IDs against 02 before publication. OCR/visual learning still needs its distinct
v2 public artifact contract; this library does not disguise it as native video.
