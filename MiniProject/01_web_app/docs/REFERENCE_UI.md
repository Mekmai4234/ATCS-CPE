# Reference artwork and interface update — 2026-10-25

Module: **01_web_app**. The login, home, library, learning pages and Buddy chat share the mint visual system. Authentication, private data scope and AI APIs remain the existing implementations.

## What changed

- Replaced the assembled body/head/hand mascot in hero areas with a cohesive 3D scene based on the three user-approved references.
- Replaced the floating launcher, navigation logo, chat header and assistant avatar with the matching transparent Buddy head.
- Kept bounded pointer-responsive parallax on the hero, tap greeting, reduced-motion support, image-failure fallback, draggable chat, keyboard movement with arrow keys/Home and persistent launcher coordinates.
- Added locally bundled Kanit 700/800 Thai display typography; body text retains IBM Plex Sans Thai and Manrope.
- Reworked mint surfaces, headline scale, import card, video cards, login benefits and chat proportions. Thumbnail images are no longer dimmed by the previous treatment.
- Preserved the official Google Identity Services control. Its exact internal appearance belongs to Google; no imitation login button or credential flow was added.
- The desktop floating panel is wider (460px on large displays). Mobile keeps the existing modal focus behavior and bounded viewport sizing.
- Preview data remains explicitly identified as synthetic. The real library continues to use each imported video's metadata and thumbnail. No invented views, dates, durations, account profiles or AI answers were added to production.

## Assets

All new images are generated with the built-in **imagegen** tool. No application Gemini quota or API key was used. The downloaded WebP files are bundled static assets; displaying them does not make a generation API call.

| File under public/assets/buddy-reference | Dimensions       | Purpose                        |
| ---------------------------------------- | ---------------- | ------------------------------ |
| scene-1536.webp                          | 1536 × 1024      | Desktop hero/login scene       |
| scene-768.webp                           | 768 × 512        | Responsive smaller scene       |
| avatar-256.webp                          | 256 × 256, alpha | Logo, launcher and chat avatar |

Total new image weight is approximately **154 KiB**. The PNG masters are retained in the user's Codex generated-images folder. Export only resized/re-encoded these masters; no visual content was manually composited into screenshots.

## Prompts and provenance

Reference supplied by the user: `exec-81439149-86c4-431e-bd57-72b88060b752.png` (approved RAG Buddy home mockup). Related approved login/chat references: `exec-384baf3d-0cf3-482c-883d-5f72f45c9cc4.png` and `exec-051b3d9a-e304-49c0-add3-1985b0ddec18.png`.

Scene master: `exec-34f3cf8e-ce98-4f47-8739-1143404eed1e.png`.

> Create a production website illustration asset, NOT a screenshot or UI mockup. The attached image is ONLY the visual reference. Extract/recreate its mint 3D learning scene as a clean landscape 3:2 illustration. Preserve the EXACT adorable turquoise RAG Buddy character design from the reference: glossy round mint creature, enormous friendly white eyes with navy pupils, blue fins, coral-red headphones, big happy pink smile, seated little legs, holding a cream video player tablet with coral rim, waving its hand at viewer's RIGHT. Mascot centered slightly right, complete full body sitting on a broad two-tier mint circular pedestal near the bottom. Background: pastel mint sculptural plants, softly blurred arches, books and pencil cup to right, floating rounded white video play tile top left, chart tile left, blue-line note tile upper right, tiny yellow sparkles. Bright airy high-key studio lighting, beautiful polished 3D collectible toy rendering, exactly the reference's soft glossy materials and proportions. Full scene has very pale mint-white #f3fffb edges so it blends with a webpage. No text of any kind, no headers, no buttons, no logos, no speech bubble, no UI, no watermark. Do not invent a different mascot. High resolution asset for a hero on a Thai educational app.

Avatar master: `exec-1f7cc2da-c3a0-41e8-8ea5-c5e07c32b5ba.png`, using the new scene as the reference and requesting transparent output.

> Create a square transparent-background mascot avatar asset for a website chat launcher from this reference scene. Keep the EXACT same mint glossy RAG Buddy character identity, face proportions and coral-red headphones, blue fins, big white expressive eyes with navy pupils, pink cheeks and huge happy pink smile. Show only the complete head and headphones, front-facing with slight friendly tilt; no body, no hands, no tablet, no pedestal, no scenery, no background, no enclosing circle, no badge, no text. Entire head including blue crest fits inside canvas with only 5% transparent padding, no cut-off headphones. Beautiful polished 3D toy render matching the reference. True alpha transparency.

## Verification

Run from this module:

```powershell
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm test
pnpm run test:browser
pnpm run format:check
pnpm run build
pnpm run test:production
```

Browser tests cover login/session boundaries, citation interactions, chat scope, pointer and touch dragging, keyboard alternatives, reduced motion, missing artwork, accessibility contrast, and layouts at 375 / 768 / 1024 / 1440px. Test-only entry points cannot create a deployment build. Screenshots are actual browser renders with test data, not image-generated website screenshots.

This visual update does not deploy, migrate the live database, verify a real Google account, or attest Gemini Free Tier billing status.

### Verified result for this change

- TypeScript, formatting, production build and the production login-gate smoke test passed.
- Unit tests: **104 passed**.
- Browser suite: **75 passed, 8 skipped** (the skipped cases require the optional real backend/identity harness).
- The launcher-position regression was also exercised three consecutive times after fixing temporary viewport changes. Keyboard focus no longer relocates Buddy over the header/logout control.
- Five final screenshots were captured from the actual React pages at 1586 × 992 using a test session and API fixtures. The login screenshot renders the official Google button; no real account login or AI request was performed.

## Navigation regression follow-up — 2026-10-25

The oversized home illustration could extend over the header at desktop widths and receive clicks meant for navigation. Earlier layout tests used a demo banner, which moved the illustration down and concealed the production-layout overlap. The new no-banner regression reproduced the failure at 1536, 1920 and 2560 pixels before the fix.

The header now has an explicit stacking layer and an opaque surface. Decorative scene layers no longer receive pointer events; mascot greeting events are attached to the bounded scene container, retaining pointer-responsive movement. The demo banner also has its own layer so the artwork cannot wash out its text.

New regression coverage checks real pointer hit targets, all four navigation destinations, the logout control and horizontal overflow at 375, 768, 1024, 1280, 1440, 1536, 1920 and 2560 pixels. A keyboard/history test checks that switching pages and using Back/Forward preserves the chat draft and learning task type. Responses are isolated fixtures shaped like the live backend with no demo banner; no model requests are made.

The running authenticated localhost application was also checked by clicking Home, Library, Chat and Learning. All destinations rendered and the browser reported no console errors during those checks. API health reported schema 0003 and non-synthetic custom mode; this does not attest a live Gemini response.

Final navigation verification (26 October 2026): **104 unit tests and 84 browser tests passed**; 8 optional backend/identity cases were skipped in the browser run. Formatting, TypeScript/production build and production login-gate smoke also passed. No outbound Gemini request was used for this fix.


## Launcher simplification — 26 October 2026

Removed the separate three-dot position button and its menu at the user's request. Only the Buddy chat face remains. Pointer/touch dragging still works; keyboard users can move the focused launcher with arrow keys and reset it with Home. The Buddy browser suite passed all 17 cases; formatting and production build passed.
