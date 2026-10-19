# RAG Buddy model sheet

Created: 2026-10-19 (Asia/Bangkok)
Generation method: built-in ImageGen, followed by two targeted ImageGen edits. No fallback CLI was used.

## Deliverables

- `rag-buddy-base-2d.png`: the selected transparent 2D mascot with headphones and a video-learning tablet.
- `rag-buddy-model-sheet.png`: final raster presentation board, 1024 × 1536 px.
- `user-brief.txt`: the user's supplied specification, preserved verbatim.
- This file records the actual generation and editing prompts.

## Contents

The board presents a coral 3D hero banner, a central 2D turnaround and component reference, six UI states, and a glossy 3D front/side/back toy reference. Character identity follows the user's selected reference and the previously approved headphones/tablet illustration.

## Use as a design reference

This PNG is a visual reference, not an editable vector asset, a rig, or a 3D mesh. Component boundaries and pivot marks are illustrative. It does not establish closed SVG paths, true separated layers, exact orthographic measurements, usable animation pivots, or exact geometric agreement between views. Some highlights remain in the technical illustrations. The arm alternatives and screen details require completion during source-asset construction. Do not treat the supplied character reference as proof of a newly original character identity.

For implementation, redraw clean flat vector parts into individual named layers; separate eyes, eyelids and pupils; define closed/open snout, shoulder/fin/head pivots and arm pose alternatives; separate the tablet frame and content; then build and test the six interaction states in the chosen animation runtime. Validate at both 64px and hero sizes, on light/dark backgrounds, and with reduced motion. A GLB version requires actual 3D modeling and rigging against approved proportions.

## Initial generation prompt

Use case: identity-preserve.
Input image 1: the approved finished 2D mascot reference. Preserve this character's identity, exact mint/teal/pink palette, very large round white eyes and small teal pupils, broad pink snout, blue fins, chubby seated proportions, coral headphones, and coral tablet. Extend that exact design into a cohesive model sheet.
Output: ONE large premium portrait art-director presentation board, ideally 2048 x 3072 or higher resolution with a 2:3 aspect ratio. The following is the user's complete design brief. Follow it carefully:

[USER_INPUT]
MASCOT_NAME: RAG Buddy (YouTube Video Q&A Mascot)
CHARACTER_MAIN_FEATURES: A chubby, round, jelly-like mint-aqua creature with huge round white eyes with thick teal outlines and small glossy teal pupils, a wide flat pink duck-bill-style snout, soft pink blush cheeks, translucent sky-blue fin-like frills on both sides of the head and one on the back, short stubby arms and legs, and a seated baby-like pose. Thick deep-teal rounded outlines in a cute sticker style.
ACCESSORY_DETAILS: Glossy coral-pink over-ear headphones with rounded ear cups, plus a coral-pink rounded tablet showing a video player UI (a play button, a progress bar with a slider dot, two text lines, and a small timestamp badge)
TOP_BANNER_BG_COLOR: Vibrant coral-red gradient
MIDDLE_BG_COLOR: Clean off-white
BOTTOM_BG_COLOR: Soft slate gray studio gradient
PRIMARY_BODY_COLOR: Glossy mint-aqua body with sky-blue fins and pastel pink snout
ACCENT_ACCESSORY_COLOR: Coral-pink headphones and tablet with deep teal outlines

[ROLE & TASK]
Act as a master character designer, 3D toy modeler, and web mascot rigging artist. Create a professional IP mascot design model sheet and turnaround guide for a "YouTube RAG" web app (chat with and search inside videos), presented across three stacked horizontal panels. The design must be built as a production-ready base asset that will be further developed into an interactive animated mascot on a website.

[VISUAL HIERARCHY]
Primary focal point: Top hero teaser banner featuring a dynamic 3D close-up render of the mascot wearing its headphones and waving cheerfully with one hand, the tablet tucked under the other arm.
Secondary focal point: Bottom section presenting a complete 3D glossy vinyl toy turnaround in front, side, and back views, seated pose, with the headphones and tablet shown.
Tertiary focal point: Middle section showing clean 2D vector orthographic turnaround views, an exploded parts breakdown, a UI state and expression row, and callout illustrations of ACCESSORY_DETAILS.
Supporting visual elements: Subtle blue-grey horizontal dotted measurement alignment lines indicating height proportions across the turnaround sections.

[COMPOSITION]
Arrangement: Vertically stacked three-tier brand identity presentation layout.
Top Tier: Dynamic hero banner over TOP_BANNER_BG_COLOR with a bold tilted orange circular speech bubble containing a white play-button icon and a small question-mark icon (icons only, no text), with motion lines anchoring the close-up mascot render.
Middle Tier: 2D vector technical orthographic model sheet over MIDDLE_BG_COLOR, split into three rows:
  Row 1: front, side profile, and back views aligned precisely with dotted measurement guide lines.
  Row 2: exploded parts breakdown with each part drawn separately and cleanly, with thin leader lines: head, eyes (open and blink), pupils, snout/mouth, blush cheeks, left and right fins, back fin, body, left arm, right arm (waving and holding poses), legs, headphones, and tablet with screen.
  Row 3: UI state and expression strip showing the same character in six small poses: Idle (calm blink), Listening (hand on headphone), Thinking (eyes looking up, tablet loading), Searching (pointing at the tablet screen), Answering (happy open snout, waving), and Error/Confused (tilted head, question mark).
Bottom Tier: Full 3D rendered toy turnaround over BOTTOM_BG_COLOR showcasing front, side, and rear views of the vinyl figurine with natural grounding contact shadows.

[WEB & INTERACTIVE USE]
Design the mascot so it can be split into layers and animated on a website (SVG, Lottie, Rive, CSS, or Three.js/GLB):
- Clean, closed, flat-color vector shapes with consistent thick teal outlines, easy to separate into layers.
- Every moving part is a separate, non-overlapping-ambiguity piece with a clear pivot point (eyelids, pupils, snout, arms, fins, headphones, tablet screen).
- Strong, readable silhouette that stays recognizable at small sizes (64px chat avatar up to a large hero image).
- A limited, consistent palette that works on both light and dark website themes.
- Simple expression set designed for UI states: idle, listening, thinking, searching, answering, error.
- Interactive-ready behaviors: eyes that can follow the cursor, blinking, fins that gently wiggle, arm that waves on hover, tablet screen that can swap content (play, loading, timestamp).
- Provide the mascot with a transparent-background-friendly design (no background elements touching or baked into the character) and consistent proportions across all views and poses.
- The 3D vinyl turnaround must match the 2D proportions exactly so it can be used as a modeling reference for a GLB/Three.js version.

[STYLE & REALISM]
Style: Hybrid 2D vector art guide and smooth 3D designer vinyl toy rendering, kawaii sticker-style thick rounded outlines in deep teal.
Lighting: Clean commercial studio lighting with soft specular highlights on glossy jelly-vinyl surfaces and balanced warm ambient fill.
Surfaces & Textures: Smooth injection-molded glossy vinyl with a slightly translucent jelly finish on the fins, glossy plastic headphones and tablet, and flat clean 2D vector linework.

[COLOR & MOOD]
Color Palette: TOP_BANNER_BG_COLOR, MIDDLE_BG_COLOR, and BOTTOM_BG_COLOR background hierarchy, paired with PRIMARY_BODY_COLOR and ACCENT_ACCESSORY_COLOR.
Mood: Cheerful, playful, curious, techy-friendly, and professional industrial IP design presentation.

[NEGATIVE PROMPT]
Perspective distortion on turnaround figures, inconsistent character proportions between tiers or between poses, inconsistent snout/fin/eye shapes between views, overlapping parts that cannot be separated into layers, gradients or shadows baked into the 2D parts, photorealistic furry textures, rough painterly textures, grunge, messy sketching lines, dark dramatic shadows, crowded busy backgrounds, readable brand logos, text watermarks, logo signatures, garbled text, low resolution.

Execution guidance:
- Exactly THREE stacked horizontal background panels. Top coral hero banner approximately 23% of the canvas height; middle off-white technical sheet approximately 55%; bottom slate-gray studio turnaround approximately 22%. Thin understated divisions, generous margins, no heavy decorative borders.
- Top: one impressive close-up 3D toy render of the same character, cheerful wave and tablet tucked under the other arm, glossy mint vinyl and translucent blue fins. Orange tilted circular speech bubble with a white play triangle and a small question mark, icons only. Keep the character large and preserve the broad pink snout. Small clear heading "RAG BUDDY" is permitted elsewhere in the banner, but no additional advertising text.
- Middle: exactly three subrows, with precise neat alignment. First subrow: 3 flat 2D orthographic neutral seated views, labeled only "FRONT", "SIDE", "BACK", matching height, with blue-gray dotted alignment guides at crest, eye, snout and ground levels. Front is exactly face-on; side is a true 90-degree profile; back is exactly rear-facing, with no face on the back of the head. Same tablet and headphones positioned physically consistently. In rear view, the tablet naturally occludes behind the body; do not draw the screen on the mascot's back.
- Middle second subrow: a spacious organized exploded COMPONENT ATLAS, as two compact aligned rows of isolated flat-color pieces with small readable labels and thin leader lines to tiny pivot-cross markers. Include each of the user-listed groups as visually separate pieces: HEAD, EYES (open pair and blink pair), PUPILS, SNOUT (closed and open), BLUSH pair, FIN L, FIN R, BACK FIN, BODY, ARM L, ARM R (wave and hold alternatives), LEGS pair, HEADPHONES, TABLET FRAME and SCREEN. Every piece has its complete closed contour, spacing around it, consistent thick teal outlines. Separate pieces must not overlap. The isolated headphones and tablet components also serve as the accessory callout drawings, with a tiny screen variant row of play, loading dots, timestamp. NO gradients, specular shine or painted shadows in this 2D component row.
- Middle third subrow: exactly six distinct consistent small full-character 2D poses in a single horizontal strip, labeled "IDLE", "LISTENING", "THINKING", "SEARCHING", "ANSWERING", "ERROR". Make the poses distinguishable exactly as requested. Use a small question mark only above ERROR. The thinking tablet has loading dots; the searching character points at its tablet; listening touches one headphone; answering waves and opens the pink snout slightly. Reuse the same character anatomy, no extra limbs.
- Bottom: exactly 3 full 3D toy renders of the SAME neutral seated character in front, true side, and rear views, identical scale and baseline. Match the first 2D subrow's proportions and accessory geometry. Soft contact shadows on the slate gray studio ground. Restrained glossy vinyl highlights, blue fins subtly translucent. Precise visual continuity with top hero and flat 2D views.
- Clear uncluttered high-resolution information design: focus on full anatomy, accurate rotations, separate parts, readable state silhouettes. Minimal labeling only as specified. No lengthy paragraphs, garbled technical text, logos, watermark, unrelated icons or extra panels.
- The image is a modeling and animation reference sheet. It must look rigorously designed; do not add unsupported claims like "rigged", "SVG", "GLB" or "production-ready file" to the artwork.

## Technical-panel refinement prompt

Use case: precise-object-edit.
Input image: current RAG BUDDY three-panel model sheet.
Edit only the MIDDLE OFF-WHITE TECHNICAL PANEL, from just below the top coral hero banner to just above the bottom gray studio renders. Preserve the top coral hero banner and all three bottom 3D toy renders, typography, colors, character identities and existing overall layout. Keep the same image aspect ratio. The middle section needs a final production-reference cleanup:
1) Convert EVERY middle-panel 2D character, UI state and component to genuine solid FLAT COLORS. Remove all gradients, soft shadows, white shine streaks and specular gloss from this middle technical section. Keep crisp consistent deep-teal outlines, solid mint body, solid sky-blue fins, solid pink snout, solid coral headphones/tablet, white eyes, tiny flat eye catchlights. Keep all outlines closed.
2) In the isolated component atlas: make the component labeled BODY a torso-only mint oval/blob with NO arms, feet or legs attached, because the arms and legs already exist as separate parts. Make the EYES (OPEN) components two empty white eye shapes with teal outlines and NO pupils embedded; keep the separate PUPILS components. EYES (BLINK) should be closed eye lid shapes. Keep all parts completely separated by empty space. Close the bottom contour of the BACK FIN component. Keep a separate left arm and clearly show two right-arm alternatives (a waving fin-hand and a holding fin-hand) in the arm region without overlapping adjacent parts; use tiny labels only if needed. Show small teal pivot-cross markers at arm shoulders, fin roots, head/body connection and headphone anchor; these are actual cross-shaped marks, not just annotation dots.
3) Keep the 3 orthographic views at identical heights and baselines, true front, side and back, matching the bottom 3D model anatomy. Keep thin blue-gray dotted guide lines.
4) Correct the six-state strip while retaining exactly six characters and the existing labels: IDLE calm and neutral, LISTENING with ONE hand visibly lifted to touch its headphone ear cup and the other holding the tablet, THINKING eyes looking upward with three loading dots on tablet, SEARCHING pointing at tablet, ANSWERING waving happily with slightly open pink snout, ERROR head tilted with small question mark. No extra arms.
5) Tablet screen detail should include a play panel, a progress line with slider, two tiny summary strokes, and a timestamp chip in the neutral front view; the three separate screen alternatives should respectively show play, loading and timestamp. Keep text "02:14" where appropriate.
Preserve all other features and exact labels. This is still a single beautiful poster with hybrid 3D top and bottom and STRICTLY FLAT 2D in the middle. No new panels, no watermarks, no new long text, no geometry or expression changes outside the specified technical middle section. Keep all small labels readable at the highest available output resolution.

## Final composition prompt

Create the final RAG BUDDY model sheet by combining these two supplied versions.
IMAGE 1 IS THE MASTER for layout and 3D rendering. Its TOP CORAL PANEL and BOTTOM SLATE-GRAY PANEL must remain fully glossy 3D vinyl toy renders with volumetric studio lighting and soft dimensional shading. Preserve those two panels from IMAGE 1. Do not flatten, repaint as vector, or reduce their 3D appearance.
IMAGE 2 is the reference only for the improved middle off-white technical panel: use its isolated empty white eye parts, separate pupils, detached torso-only BODY, complete closed fin outlines and pivot cross markers. The middle panel alone uses clean flat 2D vector-like shapes.
The output is one coherent portrait three-panel sheet with EXACTLY the same dimensions, layout, character identity, typography and color scheme as IMAGE 1.
Make one precise pose correction in the middle's six-state strip: the SECOND character from the left, labeled LISTENING, must have its viewer-left hand raised up to physically touch the viewer-left coral headphone ear cup. Its other hand holds the tablet. Its eyes may remain peacefully closed. Draw a visibly bent arm going from the torso to the headphone, not to the tablet. Only two hands on this character.
Preserve all six labels IDLE, LISTENING, THINKING, SEARCHING, ANSWERING, ERROR. Keep every other state intact.
Strict invariants: original 3D top hero from image1; original 3D bottom front-side-rear toys from image1; flat 2D technical middle based on image2. No other redesign or text changes. Preserve image1's reflective highlights, volumetric body, realistic vinyl earcups, soft contact shadows and translucent fins in both 3D panels. The result should demonstrate a clear and intentional contrast between 3D rendered toys in the top and bottom panels and a flat 2D design guide in the center.
