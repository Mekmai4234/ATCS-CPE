# RAG Buddy assets

## Current mint / articulated Buddy — 24 October 2026

The current UI uses a CSS mint canvas and three independently generated transparent rig layers. See [sources, optimized paths, fallback and final prompts](design/buddy-rig/README.md). The original PNG outputs live in `design/buddy-rig/source/`; runtime WebPs live in `public/assets/buddy-rig/`. Built-in ImageGen was used, followed only by resize/format optimization. No new fonts or WebGL runtime were added.

References supplied by the user: `D:\Web\New folder\exec-81439149-86c4-431e-bd57-72b88060b752.png` (home), `exec-2fd33f63-a760-49bc-b608-39340799a49b.png` (floating chat), `exec-384baf3d-0cf3-482c-883d-5f72f45c9cc4.png` (login). These are visual guidance, not real member profiles, metrics, lessons or model responses. Controls and cards are actual HTML. The forest assets described below are historical and no longer requested by the current backdrop component.

## Historical forest UI — 21 October 2026

Prepared 2026-10-21 for the module-01 forest UI. User references: `D:\Web\image.png` (login concept), `D:\Web\image2.png` (home/admin concept), and the existing RAG Buddy character sheet under `output/mascot/rag-buddy-model-sheet-v1/`. The screenshots informed composition and palette; neither screenshot is used as a page background or replacement for HTML controls. Password fields in the reference were intentionally omitted to follow the Google-only requirement.

ImageGen produced a transparent 3D-style mascot and a dark teal/mint forest. Prompt direction: preserve the existing friendly round RAG Buddy character, backpack/headphones and books; isolate the mascot on transparency; create a separate soft forest with layered trees, teal shadows and mint light, with no UI or text. An initial light-forest variant was not used. Generated imagery was resized/encoded with Sharp; no WebGL model is required.

| Public asset        |  Bytes | Purpose                    |
| ------------------- | -----: | -------------------------- |
| forest-desktop.webp | 302724 | Desktop forest, 1672 × 941 |
| forest-mobile.webp  | 173632 | Mobile forest, 960 × 1280  |
| rag-buddy-1200.webp | 174080 | Large mascot, alpha        |
| rag-buddy-640.webp  |  73458 | Medium mascot, alpha       |
| rag-buddy-320.webp  |  29560 | Small mascot, alpha        |

Total: 753454 bytes. `Forest.tsx` selects forest sizes with picture/media and mascot sizes with srcset. The forest is decorative and hidden from assistive technology; the mascot has descriptive alt text. Headings, navigation, forms and Google controls are actual HTML. Font files are bundled from the existing font packages. Reference ownership/licensing was not independently established; this document records provenance, not a claim of exclusive rights.
