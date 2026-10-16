# Collage animation language

## Definition

Treat digital collage animation as cut-out animation made with scanned/generated paper, photographs, type, ink, and flat props. The physical precedent is frame-by-frame movement of flat paper/card/fabric pieces; the digital workflow preserves that layered, limited, slightly uneven character while gaining deterministic compositing.

## Visual grammar

- Build three depths: paper environment, story subjects, foreground scraps/ink.
- Keep torn/deckled edges visible. A perfectly masked silhouette reads like ordinary motion graphics.
- Use paper fibers, newsprint dots, ink bleed, fold shadows, and slight color misregistration.
- Keep one focal accent color. Let neutrals and archival color carry the rest.
- Prefer one dominant physical action per short shot: assembles, tears, slides, crashes, folds, scatters, or sinks.
- Keep micro-jitter restrained: usually 1–4 px and below 0.5 degrees at 1080p.
- Use a decisive pattern interrupt near the emotional peak: a color burst, hard tear, scale change, or field reversal.
- Preserve silhouette readability through the impact. Debris must support, not cover, the main action.

## Editorial explainer influence

Use the useful ideas associated with modern editorial explainers without copying a brand system: curiosity-led staging, archival texture, simple information hierarchy, maps/labels only when the story needs them, and rhythmic motion that makes a complex idea immediately legible. Never add a Vox logo or imitate one identifiable published frame.

## Frame-by-frame contract

- Output every source frame as an independent flattened PNG.
- Bake subject movement, paper jitter, debris, and camera changes into those PNGs.
- Do not use CSS or GSAP interpolation to create motion that is absent from the PNG sequence.
- At 30fps, 5 seconds means exactly 150 files named `frame_0001.png` through `frame_0150.png`.
- Adjacent frames must not be byte-identical. Use measurable motion, not a renamed duplicate.
- Generate a small number of consistent source cutouts with an image model; do not independently regenerate the whole scene 150 times because subject identity and spatial continuity will drift.

## Short-shot rhythm

For a 3–8 second narrative collage, use five phases:

1. Establish the paper world and primary motion.
2. Introduce the obstacle or new layer.
3. Peak with one dominant impact or transformation.
4. Resolve physical consequences.
5. Hold a readable final silhouette while ambient paper motion continues.

## Reject these shortcuts

- One still image with a camera zoom.
- A five-frame GIF repeated to reach 150 files.
- 150 model-regenerated full scenes with drifting characters.
- Smooth vector motion with paper texture pasted on top.
- Uninspected transparent images with black/white boxes.
- Render success claimed as visual success without a contact sheet and 1x playback.

## Research anchors

- Adobe, “Cut-out animation”: https://www.adobe.com/uk/creativecloud/animation/discover/cut-out-animation.html
- Vox Media, Explainer Studio announcement: https://www.voxmedia.com/about-vox-media/2017/10/13/16459628/vox-creative-expands-its-video-offering-for-advertisers-with-the-explainer-studio/
- Vox Media, Explainer Studio fifth anniversary: https://www.voxmedia.com/2022/10/19/23411609/vox-creatives-explainer-studio-celebrates-fifth-anniversary-expands-to-shorter-social-first-formats
