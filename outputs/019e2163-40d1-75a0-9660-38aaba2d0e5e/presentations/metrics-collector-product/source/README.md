# Source presentation produit Metrics Collector

Cette source genere le PowerPoint livre ici :

`../output/metrics-collector-presentation-produit.pptx`

Les slides sont des modules ESM utilises par le runtime `@oai/artifact-tool`.
Les visuels generes specialement pour cette presentation sont dans
`source/assets/`. Ils remplacent les anciens badges Swagger dans le deck.

## Regenerer le PPTX

Depuis la racine du repo :

```bash
PYTHON=/Users/thomas-illiet/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
/Users/thomas-illiet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
/Users/thomas-illiet/.codex/plugins/cache/openai-primary-runtime/presentations/26.506.11943/skills/presentations/scripts/build_artifact_deck.mjs \
  --workspace "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/source-build" \
  --slides-dir "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/source/slides" \
  --out "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/output/metrics-collector-presentation-produit.pptx" \
  --preview-dir "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/source-build/preview" \
  --layout-dir "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/source-build/layout" \
  --contact-sheet "/Users/thomas-illiet/Documents/New project 2/outputs/019e2163-40d1-75a0-9660-38aaba2d0e5e/presentations/metrics-collector-product/source-build/contact-sheet.png" \
  --slide-count 9 \
  --slide-size 1280x720 \
  --scale 1
```

Le dossier `source-build/` est un dossier de build temporaire.
