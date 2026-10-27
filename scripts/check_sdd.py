#!/usr/bin/env python3
"""Проверить документационный каркас SDD стандартной библиотекой Python."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


REQUIREMENT = re.compile(r"(?:FR|CON|NFR|QA)-\d{3}")
FEATURE_FILES = ("spec.md", "plan.md", "tasks.md", "acceptance.md", "traceability.json")
REQUIRED_FILES = (
    "AGENTS.md", "README.md", ".gitignore", ".editorconfig",
    "docs/sources/README.md", "docs/sources/case-brief.txt",
    "docs/product/brief.md", "docs/product/requirements.json",
    "docs/product/backlog.md", "docs/product/open-questions.md",
    "docs/workflow/sdd.md", "docs/architecture/overview.md",
    "docs/architecture/decisions/0001-documentation-first.md",
    "docs/clinical/content-policy.md", "docs/quality/verification.md",
    "templates/README.md", "templates/adr.md",
    "scripts/check_sdd.py", "scripts/extract_source.py",
    "CURRENT_TASK.md", "PROJECT_STATUS.md", "TECH_DEBT.md",
    "tasks/completed/README.md", "templates/current-task.md", "tests/test_check_sdd.py",
) + tuple(f"templates/{name}" for name in FEATURE_FILES)
SKIP_DIRS = {
    ".git", ".aws", ".codex", ".agents", ".venv", "__pycache__", "node_modules",
    ".next", ".nuxt", "dist", "build", "coverage", ".cache", ".turbo",
    "data", "uploads", "backups", "playwright-report", "test-results",
}


class Checker:
    def __init__(self, root):
        self.root = root.resolve()
        self.errors = []
        self.requirements = {}
        self.feature_count = 0
        self.link_count = 0
        self.archived_count = 0

    def error(self, message):
        self.errors.append(message)

    @staticmethod
    def choice(value, allowed):
        return isinstance(value, str) and value in allowed

    @staticmethod
    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def valid_date(value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return False
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False

    def read(self, path):
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self.error(f"{path.relative_to(self.root)}: {error}")
            return ""

    def read_json(self, path):
        try:
            value = json.loads(self.read(path))
            if not isinstance(value, dict):
                raise ValueError("ожидался JSON-объект")
            return value
        except ValueError as error:
            self.error(f"{path.relative_to(self.root)}: {error}")
            return {}

    def local_file(self, value, context):
        if not isinstance(value, str) or not value.strip():
            self.error(f"{context}: ожидался непустой локальный путь")
            return None
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            self.error(f"{context}: файл не найден внутри проекта: {value}")
            return None
        return path

    def evidence(self, value, context, required=False):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            self.error(f"{context}: evidence должен быть списком путей")
            return
        if required and not value:
            self.error(f"{context}: для успешного статуса нужны свидетельства")
        for item in value:
            self.local_file(item, context)

    def registry(self):
        data = self.read_json(self.root / "docs/product/requirements.json")
        if data.get("schema_version") != 1:
            self.error("Реестр: неизвестная schema_version")
        source = data.get("source", {})
        if not isinstance(source, dict):
            self.error("Реестр: source должен быть объектом")
            source = {}
        if not isinstance(source.get("id"), str) or not source["id"].strip():
            self.error("Реестр: не заполнен ID источника")
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            self.error("Реестр: неверный формат SHA-256")
        pdf = self.local_file(source.get("path"), "Исходный PDF")
        if pdf and hashlib.sha256(pdf.read_bytes()).hexdigest() != source.get("sha256"):
            self.error("SHA-256 исходного PDF не совпадает с реестром")
        self.local_file(source.get("extracted_text"), "Текст исходника")
        count = source.get("page_count")
        if type(count) is not int or count < 1:
            self.error("Реестр: неверное количество страниц")
            count = 0
        items = data.get("requirements")
        if not isinstance(items, list) or not items:
            self.error("Реестр: requirements должен быть непустым списком")
            return
        for item in items:
            if not isinstance(item, dict):
                self.error("Реестр: требование должно быть объектом")
                continue
            key = item.get("id")
            if not isinstance(key, str) or not REQUIREMENT.fullmatch(key):
                self.error(f"Неверный ID требования: {key}")
                continue
            if key in self.requirements:
                self.error(f"Повтор ID требования: {key}")
            self.requirements[key] = item
            for field in ("title", "statement", "verification", "category", "primary_slice"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    self.error(f"{key}: не заполнено поле {field}")
            if not self.choice(item.get("status"), {"specified", "implemented", "verified"}):
                self.error(f"{key}: неизвестный статус")
            self.evidence(item.get("evidence"), key, required=item.get("status") == "verified")
            origin = item.get("origin")
            if not isinstance(origin, dict):
                self.error(f"{key}: не указан origin")
                continue
            if origin.get("type") == "pdf":
                pages = origin.get("pages")
                if origin.get("source") != source.get("id"):
                    self.error(f"{key}: неизвестный источник")
                if not isinstance(pages, list) or not pages or any(
                    type(page) is not int or page < 1 or page > count for page in pages
                ):
                    self.error(f"{key}: неверные страницы источника")
            elif origin.get("type") == "derived":
                if not isinstance(origin.get("rationale"), str) or not origin["rationale"].strip():
                    self.error(f"{key}: производное требование требует rationale")
            else:
                self.error(f"{key}: origin.type должен быть pdf или derived")

    def markdown_files(self):
        for directory, names, files in os.walk(self.root):
            names[:] = sorted(name for name in names if name not in SKIP_DIRS)
            for filename in sorted(files):
                if filename.endswith(".md"):
                    yield Path(directory) / filename

    def markdown(self):
        for path in self.markdown_files():
            body = self.read(path)
            relative = path.relative_to(self.root)
            is_template = relative.parts[0] == "templates"
            if not is_template and re.search(r"\{\{[^{}]+\}\}", body):
                self.error(f"{relative}: остался заполнитель шаблона")
            for key in set(REQUIREMENT.findall(body)):
                if key not in self.requirements:
                    self.error(f"{relative}: неизвестное требование {key}")
            for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", body):
                raw = target.strip()
                if not raw:
                    self.error(f"{relative}: пустая локальная ссылка")
                    continue
                raw = raw[1:raw.index(">")] if raw.startswith("<") and ">" in raw else raw.split()[0]
                parsed = urlsplit(raw)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                if "{{" in raw and is_template:
                    continue
                linked = (path.parent / unquote(parsed.path)).resolve()
                self.link_count += 1
                if not linked.is_relative_to(self.root) or not linked.exists():
                    self.error(f"{relative}: битая локальная ссылка {raw}")

    def definitions(self, body, prefix, number, context):
        ids = re.findall(rf"^### ({prefix}-\d{{3}}-\d{{2}})\b", body, flags=re.MULTILINE)
        if not ids:
            self.error(f"{context}: нет определений {prefix}")
        for key, amount in Counter(ids).items():
            if amount > 1 or not key.startswith(f"{prefix}-{number}-"):
                self.error(f"{context}: повтор или неверный номер {key}")
        return set(ids)

    def feature(self, directory):
        self.feature_count += 1
        context = directory.relative_to(self.root)
        if not re.fullmatch(r"\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*", directory.name):
            self.error(f"{context}: неверное имя функции")
        for name in FEATURE_FILES:
            if not (directory / name).is_file():
                self.error(f"{context}: отсутствует {name}")
        if any(not (directory / name).is_file() for name in FEATURE_FILES):
            return
        number = directory.name[:3]
        spec = self.read(directory / "spec.md")
        acceptance = self.definitions(spec, "AC", number, context)
        tests = self.definitions(self.read(directory / "acceptance.md"), "TEST", number, context)
        tasks = self.read(directory / "tasks.md")
        task_ids = re.findall(r"^- \[[ x]\] (TASK-\d{3}-\d{2}):", tasks, re.MULTILINE)
        if not task_ids or len(task_ids) != len(set(task_ids)):
            self.error(f"{context}: отсутствуют задачи или повторены их ID")
        if any(not key.startswith(f"TASK-{number}-") for key in task_ids):
            self.error(f"{context}: неверный номер задачи")
        trace = self.read_json(directory / "traceability.json")
        if trace.get("schema_version") != 1 or trace.get("feature") != directory.name:
            self.error(f"{context}: неверная версия или feature в трассировке")
        status = trace.get("status")
        if not self.choice(status, {"draft", "ready", "in-progress", "verified", "blocked"}):
            self.error(f"{context}: неизвестный статус спецификации")
        if f"Статус: `{status}`" not in spec:
            self.error(f"{context}: статус spec.md не совпадает с трассировкой")
        mappings = trace.get("mappings")
        if not isinstance(mappings, list) or not mappings:
            self.error(f"{context}: mappings должен быть непустым списком")
            return
        covered_ac, covered_tests, mapped_requirements = set(), set(), set()
        for mapping in mappings:
            if not isinstance(mapping, dict):
                self.error(f"{context}: mapping должен быть объектом")
                continue
            key = mapping.get("requirement")
            if not isinstance(key, str) or key not in self.requirements:
                self.error(f"{context}: неизвестное требование в трассировке: {key}")
            elif key in mapped_requirements:
                self.error(f"{context}: повтор требования в трассировке: {key}")
            else:
                mapped_requirements.add(key)
            if not self.choice(mapping.get("coverage"), {"full", "partial"}):
                self.error(f"{context}: coverage должен быть full или partial")
            for field, known, used in (
                ("acceptance", acceptance, covered_ac), ("tests", tests, covered_tests)
            ):
                ids = mapping.get(field)
                if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
                    self.error(f"{context}: {field} должен быть непустым списком ID")
                    continue
                for key in ids:
                    if key not in known:
                        self.error(f"{context}: неизвестный ID {key}")
                    used.add(key)
        for label, defined, covered in (
            ("AC", acceptance, covered_ac), ("TEST", tests, covered_tests)
        ):
            if defined - covered:
                self.error(f"{context}: {label} без трассировки: {', '.join(sorted(defined - covered))}")
            if covered - defined:
                self.error(f"{context}: лишние {label} в трассировке: {', '.join(sorted(covered - defined))}")
        verification = trace.get("verification")
        if not isinstance(verification, list):
            self.error(f"{context}: verification должен быть списком")
            return
        recorded = set()
        for record in verification:
            if not isinstance(record, dict):
                self.error(f"{context}: запись verification должна быть объектом")
                continue
            key = record.get("test")
            if not isinstance(key, str):
                self.error(f"{context}: неверный ID теста")
                continue
            if key not in tests or key in recorded:
                self.error(f"{context}: неизвестный/повторный тест в verification: {key}")
            recorded.add(key)
            state = record.get("status")
            if not self.choice(state, {"planned", "passed", "failed", "blocked"}):
                self.error(f"{context}: неизвестный статус теста {key}")
            if status == "verified" and state != "passed":
                self.error(f"{context}: verified требует прохождения всех тестов")
            self.evidence(record.get("evidence"), f"{context}/{key}", required=state == "passed")
        if recorded != tests:
            self.error(f"{context}: не для всех тестов есть статус")
        if status == "verified" and re.search(r"^- \[ \]", tasks, re.MULTILINE):
            self.error(f"{context}: verified при незавершённых задачах")

    def task_metadata(self, path):
        body = self.read(path)
        blocks = re.findall(r"^```json[ \t]*\n(.*?)^```[ \t]*$", body, re.MULTILINE | re.DOTALL)
        if len(blocks) != 1:
            self.error(f"{path.relative_to(self.root)}: нужен единственный JSON-блок метаданных")
            return {}, body
        try:
            metadata = json.loads(blocks[0])
            if not isinstance(metadata, dict):
                raise ValueError("метаданные задачи должны быть объектом")
            if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
                self.error(f"{path.relative_to(self.root)}: неверная schema_version задачи")
            return metadata, body
        except ValueError as error:
            self.error(f"{path.relative_to(self.root)}: {error}")
            return {}, body

    def task(self, path, metadata, body, archived=False):
        context = str(path.relative_to(self.root))
        key = metadata.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"WORK-\d{4}", key):
            self.error(f"{context}: неверный ID рабочей задачи")
        if archived and path.stem != key:
            self.error(f"{context}: имя архивного файла не совпадает с ID задачи")
        revision = metadata.get("revision")
        if type(revision) is not int or revision < 1:
            self.error(f"{context}: revision должна быть положительным целым числом")
        state = metadata.get("status")
        if not self.choice(state, {"draft", "awaiting_approval", "approved", "in_progress", "verifying", "completed", "blocked"}):
            self.error(f"{context}: неизвестный статус рабочей задачи")
        if archived and state != "completed":
            self.error(f"{context}: в архиве допустимы только completed-задачи")
        if not archived and state == "completed":
            self.error(f"{context}: завершённую задачу перенесите в tasks/completed/, текущий файл верните в idle")
        if state == "blocked" and not self.nonempty(metadata.get("blocked_reason")):
            self.error(f"{context}: blocked требует blocked_reason")
        created = metadata.get("created_on")
        if not self.valid_date(created):
            self.error(f"{context}: неверная дата created_on")
        for heading in (
            "Запрос и цель", "План выполнения", "Затрагиваемые файлы", "Критерии готовности",
            "Ревью разработчика", "Выполнение и самопроверка", "Технический долг",
        ):
            if not re.search(rf"^## {re.escape(heading)}(?:\s.*)?$", body, re.MULTILINE):
                self.error(f"{context}: отсутствует раздел «{heading}»")
        approval = metadata.get("approval")
        if not isinstance(approval, dict):
            self.error(f"{context}: approval должен быть объектом")
            approval = {}
        decision = approval.get("status")
        if not self.choice(decision, {"pending", "approved"}):
            self.error(f"{context}: неизвестное состояние аппрува")
        if self.choice(state, {"approved", "in_progress", "verifying", "completed"}) and decision != "approved":
            self.error(f"{context}: выполнение требует аппрува разработчика")
        if decision == "approved":
            if state in ("draft", "awaiting_approval"):
                self.error(f"{context}: ожидающая ревью задача не может иметь действующий аппрув")
            if type(approval.get("approved_revision")) is not int or approval["approved_revision"] != revision:
                self.error(f"{context}: аппрув относится к другой редакции")
            for field in ("reviewer", "evidence"):
                if not self.nonempty(approval.get(field)):
                    self.error(f"{context}: аппрув требует {field}")
            approved = approval.get("approved_on")
            if not self.valid_date(approved):
                self.error(f"{context}: неверная дата approved_on")
            elif self.valid_date(created) and approved < created:
                self.error(f"{context}: аппрув датирован раньше создания задачи")
        elif decision == "pending":
            if any(approval.get(field) is not None for field in ("reviewer", "approved_revision", "evidence", "approved_on")):
                self.error(f"{context}: pending-аппрув должен иметь пустые поля согласования")
        defined = set(re.findall(r"^\| (CHECK-\d{2}) \|", body, re.MULTILINE))
        if not defined:
            self.error(f"{context}: нет определений критериев CHECK-NN в таблице")
        checks = metadata.get("checks")
        if not isinstance(checks, list) or not checks:
            self.error(f"{context}: checks должен быть непустым списком")
            checks = []
        recorded = set()
        for check in checks:
            if not isinstance(check, dict):
                self.error(f"{context}: запись checks должна быть объектом")
                continue
            check_id = check.get("id")
            if not isinstance(check_id, str) or not re.fullmatch(r"CHECK-\d{2}", check_id):
                self.error(f"{context}: неверный ID критерия")
                continue
            if check_id in recorded:
                self.error(f"{context}: повтор критерия {check_id}")
            recorded.add(check_id)
            result = check.get("status")
            if not self.choice(result, {"planned", "passed", "failed", "blocked"}):
                self.error(f"{context}/{check_id}: неизвестный статус самопроверки")
            if state == "completed" and result != "passed":
                self.error(f"{context}/{check_id}: завершение требует успешной самопроверки")
            if not isinstance(check.get("result"), str) or (result == "passed" and not self.nonempty(check.get("result"))):
                self.error(f"{context}/{check_id}: требуется фактический result самопроверки")
            self.evidence(check.get("evidence"), f"{context}/{check_id}", required=result == "passed")
        if recorded != defined:
            self.error(f"{context}: checks не совпадают с определёнными критериями")
        completion = metadata.get("completion")
        if not isinstance(completion, dict):
            self.error(f"{context}: completion должен быть объектом")
            completion = {}
        for field in ("project_status_updated", "technical_debt_reviewed"):
            if type(completion.get(field)) is not bool:
                self.error(f"{context}: {field} должен быть boolean")
            if state == "completed" and completion.get(field) is not True:
                self.error(f"{context}: перед завершением требуется {field}")
        debt_result = completion.get("technical_debt_result")
        if not isinstance(debt_result, str) or (state == "completed" and not self.nonempty(debt_result)):
            self.error(f"{context}: требуется результат проверки технического долга")
        completed = metadata.get("completed_on")
        if state == "completed":
            if not self.valid_date(completed):
                self.error(f"{context}: completed требует дату завершения")
            else:
                for start in (created, approval.get("approved_on")):
                    if self.valid_date(start) and completed < start:
                        self.error(f"{context}: дата завершения раньше создания/аппрува")
        elif completed is not None:
            self.error(f"{context}: дата завершения допустима только для completed")

    def workflow(self):
        current = self.root / "CURRENT_TASK.md"
        metadata, body = self.task_metadata(current)
        archives, ids = {}, set()
        folder = self.root / "tasks/completed"
        for path in sorted(folder.glob("*.md")):
            if path.name == "README.md":
                continue
            record, content = self.task_metadata(path)
            self.task(path, record, content, archived=True)
            archives[path.relative_to(self.root).as_posix()] = record
            key = record.get("id")
            if isinstance(key, str):
                if key in ids:
                    self.error(f"Архив: повтор ID рабочей задачи {key}")
                ids.add(key)
        self.archived_count = len(archives)
        if metadata.get("status") == "idle":
            if any(field in metadata for field in ("id", "revision", "approval", "checks", "completion")):
                self.error("CURRENT_TASK.md: idle не должен содержать метаданные активной задачи")
            last = metadata.get("last_completed_task")
            if last is None:
                if archives:
                    self.error("CURRENT_TASK.md: при наличии архива нужна ссылка last_completed_task")
            elif not isinstance(last, str) or last not in archives:
                self.error("CURRENT_TASK.md: last_completed_task должен указывать на задачу из архива")
            return
        self.task(current, metadata, body)
        key = metadata.get("id")
        if isinstance(key, str) and key in ids:
            self.error(f"CURRENT_TASK.md: ID {key} уже существует в архиве")

    def run(self):
        for name in REQUIRED_FILES:
            self.local_file(name, "Обязательный файл")
        self.registry()
        self.markdown()
        self.workflow()
        specs = self.root / "specs"
        if specs.is_dir():
            for directory in sorted(specs.iterdir()):
                if directory.is_dir() and not directory.name.startswith("."):
                    self.feature(directory)
        if not self.feature_count:
            self.error("Нет ни одной спецификации функции в specs/")
        if self.errors:
            print(f"Ошибок SDD: {len(self.errors)}", file=sys.stderr)
            for message in self.errors:
                print(f"- {message}", file=sys.stderr)
            return 1
        print(
            f"OK: требований — {len(self.requirements)}, спецификаций — {self.feature_count}, "
            f"локальных ссылок — {self.link_count}; структура и SHA-256 PDF проверены."
        )
        print(f"Процесс рабочей задачи проверен; завершённых задач в архиве — {self.archived_count}.")
        print("Проверено устройство документации; приложение и клинические правила не проверялись.")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1],
        help="корень проекта (по умолчанию определяется по расположению скрипта)",
    )
    args = parser.parse_args()
    try:
        return Checker(args.root).run()
    except (OSError, ValueError) as error:
        print(f"Ошибка проверки SDD: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
