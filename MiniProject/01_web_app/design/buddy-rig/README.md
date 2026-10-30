# Buddy layered raster rig — 24 October 2026

Built-in ImageGen generated three separate transparent PNG layers from the existing `public/assets/rag-buddy-640.webp` reference. Sharp only resized/encoded the outputs to WebP, preserving alpha. This is an articulated 2D raster rig with a 3D rendered look, not a WebGL model or a screenshot pretending to be interactive UI.

| Layer                               | Editable/original output | Runtime optimized asset                 |
| ----------------------------------- | ------------------------ | --------------------------------------- |
| Head, blank eye sockets, headphones | source/head.png          | ../../public/assets/buddy-rig/head.webp |
| Torso, feet, fins and tablet        | source/body.png          | ../../public/assets/buddy-rig/body.webp |
| Waving arm/hand                     | source/hand.png          | ../../public/assets/buddy-rig/hand.webp |

The two pupils are code-native glossy shapes over the empty eye sockets: centres 34% / 65% horizontally and 55% vertically. Head, body and waving arm use independent transforms. The hand holding the tablet remains part of the torso pose. Calibration/transforms are in `src/mint.css`; interaction is in `src/InteractiveBuddy.tsx`. Existing `public/assets/rag-buddy-640.webp` is the still fallback if any layer fails to load.

Full-rig pointer input is limited to a nearby region. Pupils move at most 6 px horizontally / 5 px vertically, head at most 5 degrees. Movement uses a ref + one requestAnimationFrame, not application state per pointermove. Hidden tabs reset tracking; reduced motion disables tracking/transitions/animations. Greeting/wave and success nod are finite, with no sound. The launcher/head-only rig has no pointer-tracking listener.

## Final prompts (built-in ImageGen, no API CLI)

Head:

> Create ONE game-ready transparent raster layer for a 2D articulated rig, matching the reference RAG Buddy toy-render character exactly in glossy 3D material and colors. Deliver ONLY its isolated round turquoise HEAD, coral headphones, small blue fins, smiling mouth and cheek blush, front-facing symmetric, straight head (no tilt). Two large WHITE OVAL EYE SOCKETS WITH DARK TEAL OUTLINES, absolutely NO pupils or irises inside; these white eyes are blank for code-driven pupils. No neck/body/tablet/hands/feet. Head tightly and centrally framed in a square canvas with comfortable transparent margins. Eyes symmetric and level, centers at approximately 35% and 65% horizontal of head, 45% vertical; friendly smile below. Clean alpha, no ground, no shadow outside alpha, no text, no sheet or extra views. This asset will be an independently moving head layer on a matching torso.

Body:

> A square transparent game-ready single raster rig layer. Match this reference RAG Buddy's glossy rounded 3D toy materials: turquoise body, blue tail/fins, coral-trimmed video tablet in lap, two turquoise feet. Front-facing symmetric sitting TORSO ONLY, with NO head and NO headphones and NO eyes above torso. One small right hand holding the tablet is included; omit left arm entirely so a waving arm can be attached separately. Top edge is a short rounded neck socket. Keep body in lower central area with natural proportions like reference, isolated on true transparency. No scene, no ground, no labels, no additional parts, no guide marks.

Hand:

> One transparent game-ready rig asset, matching reference character's glossy turquoise 3D toy skin. ONLY one isolated left-side waving arm with a cute open three-finger hand and thumb, curved forearm ending in a rounded shoulder root. Hand points upward at a slight outward angle, palm facing camera. The arm goes from lower right shoulder to upper left hand. Absolutely NO head, body, tablet, text, background, ground or other parts. Square canvas, clean true alpha margins, coherent highlights matching front upper-left studio light. Designed to rotate at its lower-right shoulder pivot over a separate torso.

The generated eye placement is calibrated to the actual pixels rather than assumed from the prompt. User references under `D:\Web\New folder` guide the mint UI composition; they are not used as full-page assets or as real member/AI data. Earlier forest images remain historical assets and are not rendered in the current UI. Provenance records do not establish exclusive rights to supplied references.
