# Local Free Tier preparation evidence

`report.json`, seven MKV clips and fourteen PNGs were generated locally by
`scripts/media_probe.py` under a non-root, network-disabled Docker container limited
to 1 CPU / 512 MiB / 128 PIDs. No Gemini or paid provider request was made.
`whole_video_reviewed=false` and semantic/model acceptance remain false.

The mixed clip is a tone with a fixture sidecar caption, not real recorded speech.
The anonymous scene is geometry, not a photograph of a real person. The injection
text was OCR input only: this does not prove model prompt-injection resistance.
The brief event lies outside the sampled points. Retain the original clips to review it.

Engine/model/font copyright notices and actual package inventory are retained.
Font binaries are omitted from this committed evidence subset; they are in the QA
image and full runtime/CI artifacts. `artifact_bytes` describes the complete generated
directory before report.json, including those fonts, not this smaller committed subset.

`candidate-diagnostic.json` pins unmerged PR source and distinguishes the original
stale lock from the explicitly refreshed isolated diagnostic lock. Its pre-refresh
tooling hash is historical, not a final PR checkout fingerprint. Use current-head CI
artifacts for the final code's source proof. The comparison found 24 candidate backend
tests passing and 5 strict schema tests passing, with 1 real 02/05 interface failure.
None of these results certifies integrated develop or a deployment.
