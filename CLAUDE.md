# CLAUDE.md

## Project Overview

Docker-based tool for converting directories of JPG images into CBZ (Comic Book Archive) files for manga/comic collections.

## Development Environment

```bash
# Build dev image
docker compose build dev

# Interactive shell
docker compose run --rm dev /bin/bash

# Run converter
docker compose run --rm dev python main.py

# Build and push production images (requires .env)
task build
```

## Important Implementation Notes

- **System zip**: Uses system `zip` command (not Python's zipfile) for CBZ creation
- **Pillow error suppression**: `'NoneType' object has no attribute 'close'` from Pillow is intentionally caught and ignored in `verify_image_integrity()`
- **Corruption halts processing**: Any validation failure aborts CBZ creation for the entire directory
- **ImageMagick toggle**: `use_imagemagick` flag in `main()` controls whether images are reprocessed (strip metadata, compress, auto-orient)
