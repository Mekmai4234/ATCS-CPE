# Evidence library time and relevance contract

`EvidenceLibrary.search` is lexical retrieval without model/embedding calls. It must
receive the latest question, not an unconditional concatenation of unrelated history.
It does not detect conversational intent or parse time expressions on the caller's behalf.
The module 05 caller must resolve genuine follow-ups and pass explicit start/end seconds.
Passing an unrelated historic topic or omitting the requested interval remains a caller
defect; module 04 regressions alone do not close BUG-01/BUG-02 from the 2026-11-02 audit.

Time windows use positive overlap with `[start_seconds, end_seconds)`: a transcript or
video observation ending exactly at the requested start, or starting exactly at the
requested end, is excluded. OCR/visual point observations include the start and exclude
the end. The same rule applies to ranked hits and neighbors. SQL filters transcript
hits before applying collection limits; every returned evidence kind is filtered again.
Original citation intervals remain intact when a chunk crosses the requested boundary.
Clients must show those actual intervals and cannot claim every word lies in the window.

`inspected_records` counts collected records, not every SQL row considered or all video
content. `complete` describes bounded catalogue collection, not semantic completeness
or whole-clip model coverage. `ranking_score` is lexical overlap, not confidence. Research
context selection separately reports indexed/inspected/retrieved counts; only actual
successful model input may count as sent/processed coverage. No semantic recall metric
or Thai paraphrase quality is claimed by fixture regression.

Gold evaluation remains pending human intervals/review. The existing 36-case review
fixture and human gate in 07 must not be relabeled reviewed. Paired real embedding
model/dimension/fingerprint and backup/restore acceptance remain separate live gates.
