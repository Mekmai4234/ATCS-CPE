# Original clip / local OCR tool QA

This optional **QA image** is separate from the application worker. It works from
Windows Docker Desktop/Linux containers and a Linux server without a Gemini key.
It does not install software on the host or change providers. Native Windows tool
bundling and module 03's Windows Job Object integration remain separately unverified.

From MiniProject (PowerShell):

```powershell
New-Item -ItemType Directory -Force 07_testing_deployment/runtime | Out-Null
docker build -f 07_testing_deployment/Dockerfile.media -t ragbuddy-07-media:qa .
$mediaEvidence = (Resolve-Path 07_testing_deployment/runtime).Path
docker run --rm --network none --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,noexec,nosuid,size=128m --mount "type=bind,source=$mediaEvidence,target=/evidence" ragbuddy-07-media:qa
```

Use a new output directory for another run, e.g. append
`python /qa/media_probe.py --output /evidence/local-media-2` after the image name.
Existing output is rejected. On Linux use the same command with an absolute bind
path and `--user "$(id -u):$(id -g)"` so the non-root process owns its output.
Default PR CI builds/runs this exact image on its actual checkout, with networking
disabled during QA. Package installation requires network only during image build.

## Packaging and measured evidence

Digest-pinned Python base; exact Debian packages: FFmpeg 5.1.9, Tesseract 5.3.0,
English/Thai traineddata 4.1.0 and Noto core fonts 20201225. If a pinned package is
removed, build fails rather than silently selecting a new version. Transitive OS
packages are recorded in `packages.txt`; this is **not** a complete snapshot-pinned
Debian repository or a bit-for-bit reproducible image claim.

The report retains actual tool versions, traineddata SHA-256, full package inventory,
copyright notice hashes/copies, seven clips, fourteen sampled PNGs and OCR text.
Measurements include serial wall time, child CPU seconds, cumulative child RSS
high-water (Linux KiB), clip bytes and total artifact bytes. These tiny two-second,
640x360 fixtures do not establish the owner's server capacity for ten-minute uploads.
OCR can emit spurious text on geometry; originals remain the review source.

The seven fixtures exercise clear Thai/English signs, no text, mixed visual/synthetic
audio, a brief event outside the sampled points, injection text as inert input,
an unnamed geometric avatar and faint text. There are no downloaded media, real
people or unheard words. They do **not** prove injection resistance, person attribution,
real speech semantics, model quality or a successful visual-only API conversation.
Coverage always records sampled points, never whole-video review.

## License and distribution record

The image retains Debian copyright notices and copies them to QA artifacts. The
packaged FFmpeg notice reports GPL components; do not label this Debian build purely
LGPL. Preserve package versions/configuration and corresponding source/license
requirements when distributing a derived image. Tesseract and language data notices
are retained with the font notice. This change does not publish an image.

Primary references: [FFmpeg license/build conditions](https://ffmpeg.org/legal.html),
[Tesseract engine and traineddata installation](https://tesseract-ocr.github.io/tessdoc/Installation.html),
[Tesseract license](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE),
[language-data license](https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE).
Actual package copyright files, rather than a generic upstream label alone, describe
the distributed Debian binaries and dependencies.
