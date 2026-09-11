import os
import pytest
import fitz
from rt.core.image_extract import (
    ExtractedImage,
    extract_images_from_pdf,
    extract_images_from_folder,
    extract_images,
)


def test_extract_images_from_pdf_success(tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.new_page(width=100, height=100)
    doc.save(str(pdf_file))
    doc.close()

    images = extract_images_from_pdf(str(pdf_file))
    assert len(images) == 2
    assert images[0].source_label == "pdf:sample.pdf#1"
    assert images[1].source_label == "pdf:sample.pdf#2"
    assert isinstance(images[0].image_bytes, bytes)
    assert len(images[0].image_bytes) > 0


def test_extract_images_from_pdf_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_images_from_pdf(str(tmp_path / "non_existent.pdf"))

    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_text("not a pdf content")
    with pytest.raises(ValueError):
        extract_images_from_pdf(str(invalid_pdf))


def test_extract_images_from_folder_success(tmp_path):
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    (img_dir / "b.png").write_bytes(b"png data")
    (img_dir / "a.JPG").write_bytes(b"jpg data")
    (img_dir / ".hidden.png").write_bytes(b"hidden")
    (img_dir / "text.txt").write_text("ignore me")

    images = extract_images_from_folder(str(img_dir))
    assert len(images) == 2
    assert images[0].source_label == "folder:a.JPG"
    assert images[0].image_bytes == b"jpg data"
    assert images[1].source_label == "folder:b.png"
    assert images[1].image_bytes == b"png data"


def test_extract_images_from_folder_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_images_from_folder(str(tmp_path / "non_existent_folder"))


def test_extract_images_dispatcher(tmp_path):
    # PDF dispatch
    pdf_file = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_file))
    doc.close()

    res_pdf = extract_images(str(pdf_file))
    assert len(res_pdf) == 1

    # Folder dispatch
    folder = tmp_path / "img_folder"
    folder.mkdir()
    (folder / "pic.png").write_bytes(b"pic")
    res_folder = extract_images(str(folder))
    assert len(res_folder) == 1

    # Unsupported single file
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello")
    with pytest.raises(ValueError):
        extract_images(str(txt_file))
