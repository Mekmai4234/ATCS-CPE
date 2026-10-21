# RAG Buddy assets

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
