#!/usr/bin/env python3
"""Воспроизводимо извлечь исходный PDF, не изменяя его и реестр требований."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только сравнить, без записи")
    args = parser.parse_args()
    try:
        registry = json.loads((ROOT / "docs/product/requirements.json").read_text(encoding="utf-8"))
        source = registry["source"]
        pdf = (ROOT / source["path"]).resolve()
        target = (ROOT / source["extracted_text"]).resolve()
        if not pdf.is_relative_to(ROOT) or not target.is_relative_to(ROOT):
            raise ValueError("Пути источника должны оставаться в проекте")
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("SHA-256 PDF изменился. Нужен анализ изменения исходника и требований")
        executable = shutil.which("pdftotext")
        if not executable:
            raise ValueError("Не найден pdftotext (Poppler); сохранённый текст не изменён")
        result = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", str(pdf), "-"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        pages = result.stdout.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if len(pages) != source["page_count"]:
            raise ValueError(f"Ожидалось {source['page_count']} страниц, получено {len(pages)}")
        text = f"Источник: {source['id']} — {source['path']}\nSHA-256: {source['sha256']}\n"
        for number, page in enumerate(pages, 1):
            text += f"\n=== Страница {number} ===\n\n{page.rstrip()}\n"
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != text:
                raise ValueError("Извлечённый текст отличается. Проверьте исходник и версию Poppler")
            print(f"OK: PDF и сохранённый текст совпадают, страниц: {len(pages)}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"Записан {source['extracted_text']}; страниц: {len(pages)}; SHA-256 PDF совпадает")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Ошибка извлечения: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
