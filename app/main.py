#!/usr/bin/env python3

import os
import sys
import shutil
import subprocess
import tempfile
import argparse
from pathlib import Path
from PIL import Image

INPUT_DIR = '/data/input'
OUTPUT_DIR = '/data/output'
JPEG_QUALITY = 75

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.JPG', '.JPEG', '.png', '.PNG'}
PDF_EXTENSIONS = {'.pdf', '.PDF'}

type Result = tuple[bool, str | None]


def get_image_files(directory: Path) -> list[Path]:
    return sorted(f for f in directory.rglob('*') if f.is_file() and f.suffix in IMAGE_EXTENSIONS)


def get_pdf_files(directory: Path) -> list[Path]:
    return sorted(f for f in directory.rglob('*') if f.is_file() and f.suffix in PDF_EXTENSIONS)


def convert_pdf_to_images(pdf_path: Path, output_dir: Path) -> Result:
    try:
        subprocess.run(
            ['pdftoppm', '-jpeg', '-r', '150', str(pdf_path), str(output_dir / pdf_path.stem)],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, None
    except subprocess.CalledProcessError as e:
        return False, f"pdftoppm command error: {e.stderr}"
    except Exception as e:
        return False, f"Error converting PDF to images: {e}"


def is_landscape_image(image_path: Path) -> tuple[bool, int, int]:
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            return width > height, width, height
    except Exception:
        return False, 0, 0


def split_landscape_image(
    image_path: Path,
    output_right: Path,
    output_left: Path,
    crop_left: int = 0,
    crop_right: int = 0,
) -> Result:
    # crop is applied before splitting when specified
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            if crop_left > 0 or crop_right > 0:
                right_bound = width - crop_right
                if crop_left >= right_bound:
                    return False, f"Crop values ({crop_left}+{crop_right}px) exceed image width ({width}px)"
                img = img.crop((crop_left, 0, right_bound, height))
                width = img.size[0]

            mid = width // 2
            img.crop((mid, 0, width, height)).save(output_right, 'JPEG', quality=JPEG_QUALITY)
            img.crop((0, 0, mid, height)).save(output_left, 'JPEG', quality=JPEG_QUALITY)

        return True, None
    except Exception as e:
        return False, f"Error splitting image: {e}"


def is_valid_jpg_header(file_path: Path) -> Result:
    try:
        with open(file_path, 'rb') as f:
            if f.read(2) != b'\xff\xd8':
                return False, "Invalid JPEG header (missing SOI marker)"
            f.seek(-2, os.SEEK_END)
            if f.read(2) != b'\xff\xd9':
                return False, "Invalid JPEG footer (missing EOI marker)"
        return True, None
    except Exception as e:
        return False, f"Error reading file: {e}"


def verify_image_integrity(file_path: Path) -> Result:
    try:
        # verify() must be called before any load()
        with Image.open(file_path) as img:
            img.verify()
        # re-open required because verify() exhausts the file pointer
        with Image.open(file_path) as img:
            img.load()
            img.convert('RGB')
        return True, None
    except AttributeError as e:
        if "'NoneType' object has no attribute 'close'" in str(e):
            return True, None
        return False, f"Image integrity check failed: {e}"
    except Exception as e:
        return False, f"Image integrity check failed: {e}"


def check_file_size(file_path: Path) -> Result:
    try:
        size = file_path.stat().st_size
        if size == 0:
            return False, "File is empty (0 bytes)"
        if size < 100:
            return False, f"File is suspiciously small ({size} bytes)"
        return True, None
    except Exception as e:
        return False, f"Error checking file size: {e}"


def repair_jpeg_eoi(file_path: Path) -> Result:
    try:
        with open(file_path, 'rb') as f:
            f.seek(-2, os.SEEK_END)
            footer = f.read(2)
        if footer != b'\xff\xd9':
            with open(file_path, 'ab') as f:
                f.write(b'\xff\xd9')
            return True, None
        return False, None
    except Exception as e:
        return False, f"Error repairing file: {e}"


def check_jpg_corruption(file_path: Path) -> Result:
    for check in (check_file_size, is_valid_jpg_header, verify_image_integrity):
        valid, error = check(file_path)
        if not valid:
            return False, error
    return True, None


def create_cbz(
    source_dir: Path,
    output_cbz: Path,
    split_landscape: bool = False,
    crop_left: int = 0,
    crop_right: int = 0,
) -> Result:
    print(f"\nProcessing: {source_dir.name}")
    print("-" * 60)

    image_source_dir = source_dir
    pdf_conversion_dir: tempfile.TemporaryDirectory | None = None

    pdf_files = get_pdf_files(source_dir)
    if not get_image_files(source_dir) and len(pdf_files) == 1:
        pdf_file = pdf_files[0]
        print(f"  Found single PDF file: {pdf_file.name}, converting to images...")
        pdf_conversion_dir = tempfile.TemporaryDirectory()
        image_source_dir = Path(pdf_conversion_dir.name)

        success, error = convert_pdf_to_images(pdf_file, image_source_dir)
        if not success:
            pdf_conversion_dir.cleanup()
            print(f"  ERROR: {error}")
            return False, error

    try:
        img_files = get_image_files(image_source_dir)
        if not img_files:
            print(f"  No image files found in {source_dir.name}")
            return False, "No image files found"

        print(f"  Found {len(img_files)} image file(s)")
        return _create_cbz_from_images(img_files, output_cbz, split_landscape, crop_left, crop_right)
    finally:
        if pdf_conversion_dir is not None:
            pdf_conversion_dir.cleanup()


def _create_cbz_from_images(
    img_files: list[Path],
    output_cbz: Path,
    split_landscape: bool,
    crop_left: int,
    crop_right: int,
) -> Result:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        output_idx = 1

        for file_idx, img_file in enumerate(img_files, 1):
            print(f"  [{file_idx}/{len(img_files)}] {img_file.name}")

            is_landscape, width, height = is_landscape_image(img_file)

            if split_landscape and is_landscape:
                crop_note = f", cropping {crop_left}+{crop_right}px" if (crop_left or crop_right) else ""
                print(f"    Landscape ({width}x{height}), splitting into 2 pages{crop_note}...")

                right_path = temp_path / f"{output_idx:03d}.jpg"
                left_path = temp_path / f"{output_idx + 1:03d}.jpg"

                success, error = split_landscape_image(img_file, right_path, left_path, crop_left, crop_right)
                if not success:
                    print(f"    ERROR: {error}")
                    return False, error

                print(f"    OK -> {right_path.name}, {left_path.name} (split)")
                output_idx += 2

            else:
                suffix = '.jpg' if img_file.suffix.lower() == '.jpeg' else img_file.suffix.lower()
                out_path = temp_path / f"{output_idx:03d}{suffix}"
                try:
                    shutil.copy2(img_file, out_path)
                    print(f"    OK -> {out_path.name} (renamed)")
                except Exception as e:
                    print(f"    ERROR: Error copying file: {e}")
                    return False, f"Error copying file: {e}"
                output_idx += 1

        # Validate all processed images
        print(f"\n  Checking processed images for corruption...")
        all_processed = sorted(
            [*temp_path.glob('*.jpg'), *temp_path.glob('*.png')],
            key=lambda f: f.name,
        )

        corrupted: list[tuple[str, str | None]] = []
        for img_file in all_processed:
            if img_file.suffix.lower() == '.jpg':
                repaired, repair_error = repair_jpeg_eoi(img_file)
                if repaired:
                    print(f"    [REPAIRED] {img_file.name}: appended missing EOI marker")
                elif repair_error:
                    print(f"    [REPAIR FAILED] {img_file.name}: {repair_error}")
                is_valid, error = check_jpg_corruption(img_file)
            else:
                is_valid, error = verify_image_integrity(img_file)

            if not is_valid:
                corrupted.append((img_file.name, error))
                print(f"    [CORRUPTED] {img_file.name}: {error}")
            else:
                print(f"    [OK] {img_file.name}")

        if corrupted:
            error_msg = f"Found {len(corrupted)} corrupted image(s) after processing"
            print(f"\n  ERROR: {error_msg}")
            return False, error_msg

        print(f"  All {len(all_processed)} images are valid")

        # Package into CBZ (ZIP archive)
        print(f"\n  Creating CBZ archive: {output_cbz.name}")
        file_list = sorted(f.name for f in [*temp_path.glob('*.jpg'), *temp_path.glob('*.png')])
        if not file_list:
            return False, "No processed images found"

        try:
            subprocess.run(
                ['zip', '-9', '-q', str(output_cbz.absolute()), *file_list],
                cwd=temp_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return False, f"zip command error: {e.stderr}"
        except Exception as e:
            return False, f"Error creating CBZ: {e}"

        file_size = output_cbz.stat().st_size / (1024 * 1024)
        print(f"  CBZ created successfully ({file_size:.2f} MB)")
        return True, None


def convert_directories_to_cbz(
    split_landscape: bool = False,
    crop_left: int = 0,
    crop_right: int = 0,
) -> tuple[int, int, int]:
    input_path = Path(INPUT_DIR)
    output_path = Path(OUTPUT_DIR)

    if not input_path.exists():
        print(f"Error: Input directory '{INPUT_DIR}' does not exist")
        sys.exit(1)

    output_path.mkdir(parents=True, exist_ok=True)

    subdirs = [d for d in sorted(input_path.iterdir()) if d.is_dir() and not d.name.startswith('.')]
    if not subdirs:
        print(f"No subdirectories found in '{INPUT_DIR}'")
        return 0, 0, 0

    print(f"Found {len(subdirs)} director(ies) to convert")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 60)

    success_count = skipped_count = failed_count = 0
    failed_dirs: list[tuple[str, str | None]] = []

    for subdir in subdirs:
        cbz_path = output_path / f"{subdir.name}.cbz"

        if cbz_path.exists():
            print(f"\nSkipping: {subdir.name} (already exists)")
            skipped_count += 1
            continue

        success, error = create_cbz(subdir, cbz_path, split_landscape, crop_left, crop_right)
        if success:
            success_count += 1
        else:
            failed_count += 1
            failed_dirs.append((subdir.name, error))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total directories processed: {len(subdirs)}")
    print(f"Successfully converted: {success_count}")
    print(f"Skipped (already exists): {skipped_count}")
    print(f"Failed: {failed_count}")

    if failed_dirs:
        print("\n" + "=" * 60)
        print("FAILED CONVERSIONS")
        print("=" * 60)
        for dir_name, error in failed_dirs:
            print(f"\n{dir_name}:")
            print(f"  {error}")

    return success_count, skipped_count, failed_count


def main() -> None:
    parser = argparse.ArgumentParser(description='Convert directories of JPG images to CBZ format')
    parser.add_argument('--split-landscape', action='store_true', default=False,
                        help='Split landscape images into two pages (default: False)')
    parser.add_argument('--crop-lr', type=int, default=0, metavar='PIXELS',
                        help='Crop PIXELS from both left and right sides before splitting (default: 0)')

    args = parser.parse_args()
    crop = args.crop_lr

    print("CBZ Converter")
    print("=" * 60)
    print(f"Split landscape images: {args.split_landscape}")
    if crop > 0:
        print(f"Crop left/right: {crop}px")
    print("=" * 60)

    _, _, failed = convert_directories_to_cbz(args.split_landscape, crop, crop)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
