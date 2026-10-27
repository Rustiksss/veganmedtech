"""Проверки процесса задач и регрессий SDD на временных синтетических копиях."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
module_spec = importlib.util.spec_from_file_location("check_sdd", ROOT / "scripts/check_sdd.py")
check_sdd = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(check_sdd)

BODY = """
# Синтетическая рабочая задача

## Запрос и цель
Проверить формат процесса на вымышленных данных.
## План выполнения
Создать тестовую запись и проверить её.
## Затрагиваемые файлы
Только временная копия проекта.
## Критерии готовности
| ID | Критерий | Способ проверки |
| --- | --- | --- |
| CHECK-01 | Основной результат | Синтетическая проверка |
| CHECK-02 | Безопасный отказ | Негативная проверка |
## Ревью разработчика
Только синтетическое свидетельство для тестов, не реальный аппрув.
## Выполнение и самопроверка
Результаты соответствуют тестовым метаданным.
## Технический долг
Новый технический долг не обнаружен на тестовых данных.
"""


def task_fixture(status="awaiting_approval"):
    metadata = {
        "schema_version": 1, "id": "WORK-9001", "revision": 1,
        "status": status, "created_on": "2026-10-18",
        "approval": {"status": "pending", "reviewer": None, "approved_revision": None,
                     "evidence": None, "approved_on": None},
        "checks": [{"id": f"CHECK-{number:02}", "status": "planned", "result": "", "evidence": []}
                   for number in (1, 2)],
        "completion": {"project_status_updated": False, "technical_debt_reviewed": False,
                       "technical_debt_result": ""},
        "completed_on": None,
    }
    if status in {"approved", "in_progress", "verifying", "completed"}:
        metadata["approval"] = {
            "status": "approved", "reviewer": "Синтетический разработчик",
            "approved_revision": 1, "evidence": "Тестовое согласование; только fixture",
            "approved_on": "2026-10-18",
        }
    if status == "completed":
        metadata["completed_on"] = "2026-10-18"
        metadata["completion"] = {
            "project_status_updated": True, "technical_debt_reviewed": True,
            "technical_debt_result": "Новый технический долг не обнаружен на тестовых данных",
        }
        for check in metadata["checks"]:
            check.update(status="passed", result="Синтетическая проверка выполнена", evidence=["README.md"])
    return metadata


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compass-sdd-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            *check_sdd.SKIP_DIRS, ".env*", ".idea", ".vscode",
        ))
        self.current = self.root / "CURRENT_TASK.md"

    def write_task(self, metadata, path=None, body=BODY):
        target = path or self.current
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("```json\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n```\n" + body, encoding="utf-8")

    def errors(self):
        checker = check_sdd.Checker(self.root)
        checker.workflow()
        return "\n".join(checker.errors)

    def assertInvalid(self, text):
        self.assertIn(text, self.errors())

    def archive(self, metadata=None):
        path = self.root / "tasks/completed/WORK-9001.md"
        self.write_task(metadata or task_fixture("completed"), path)
        return path.relative_to(self.root).as_posix()

    def idle(self, last=None):
        self.write_task({"schema_version": 1, "status": "idle", "last_completed_task": last}, body="# Активной задачи нет\n")

    def test_repository_and_cli_validate(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_sdd.py"), "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_unapproved_states(self):
        for status in ("draft", "awaiting_approval"):
            with self.subTest(status=status):
                self.write_task(task_fixture(status))
                self.assertEqual(self.errors(), "")

    def test_valid_approved_states(self):
        for status in ("approved", "in_progress", "verifying"):
            with self.subTest(status=status):
                self.write_task(task_fixture(status))
                self.assertEqual(self.errors(), "")

    def test_start_without_approval_rejected(self):
        metadata = task_fixture()
        metadata["status"] = "in_progress"
        self.write_task(metadata)
        self.assertInvalid("выполнение требует аппрува")

    def test_stale_approval_rejected(self):
        metadata = task_fixture("in_progress")
        metadata["revision"] = 2
        self.write_task(metadata)
        self.assertInvalid("аппрув относится к другой редакции")

    def test_new_revision_resets_approval(self):
        metadata = task_fixture()
        metadata["revision"] = 2
        self.write_task(metadata)
        self.assertEqual(self.errors(), "")

    def test_approval_requires_actual_record_fields(self):
        for field in ("reviewer", "evidence", "approved_on"):
            with self.subTest(field=field):
                metadata = task_fixture("approved")
                metadata["approval"][field] = None
                self.write_task(metadata)
                self.assertNotEqual(self.errors(), "")

    def test_pending_with_stale_record_rejected(self):
        metadata = task_fixture()
        metadata["approval"]["reviewer"] = "Старая запись"
        self.write_task(metadata)
        self.assertInvalid("pending-аппрув должен иметь пустые поля")

    def test_waiting_with_approval_rejected(self):
        metadata = task_fixture("approved")
        metadata["status"] = "awaiting_approval"
        self.write_task(metadata)
        self.assertInvalid("ожидающая ревью задача")

    def test_blocked_requires_reason(self):
        metadata = task_fixture("blocked")
        self.write_task(metadata)
        self.assertInvalid("blocked требует blocked_reason")
        metadata["blocked_reason"] = "Тестовая внешняя зависимость"
        self.write_task(metadata)
        self.assertEqual(self.errors(), "")

    def test_valid_archive_and_idle(self):
        self.idle(self.archive())
        self.assertEqual(self.errors(), "")

    def test_idle_before_first_archive(self):
        for path in (self.root / "tasks/completed").glob("WORK-*.md"):
            path.unlink()
        self.idle()
        self.assertEqual(self.errors(), "")

    def test_idle_requires_existing_archive_reference(self):
        self.idle("tasks/completed/WORK-9999.md")
        self.assertInvalid("last_completed_task должен указывать")

    def test_idle_cannot_keep_active_metadata(self):
        self.write_task({"schema_version": 1, "status": "idle", "id": "WORK-9001", "last_completed_task": self.archive()}, body="# Нет задачи\n")
        self.assertInvalid("idle не должен содержать")

    def test_current_cannot_duplicate_archived_id(self):
        self.archive()
        self.write_task(task_fixture())
        self.assertInvalid("уже существует в архиве")

    def test_incomplete_task_cannot_be_archived(self):
        self.idle(self.archive(task_fixture("in_progress")))
        self.assertInvalid("в архиве допустимы только completed")

    def test_completed_task_must_leave_current_file(self):
        self.write_task(task_fixture("completed"))
        self.assertInvalid("завершённую задачу перенесите")

    def test_archive_name_matches_id(self):
        metadata = task_fixture("completed")
        metadata["id"] = "WORK-9002"
        self.idle(self.archive(metadata))
        self.assertInvalid("имя архивного файла не совпадает")

    def test_every_check_must_pass_before_completion(self):
        for status in ("planned", "failed", "blocked"):
            with self.subTest(status=status):
                metadata = task_fixture("completed")
                metadata["checks"][0]["status"] = status
                self.idle(self.archive(metadata))
                self.assertInvalid("завершение требует успешной самопроверки")

    def test_success_requires_result_and_evidence(self):
        for field, value in (("result", ""), ("evidence", []), ("evidence", ["missing-report.txt"])):
            with self.subTest(field=field, value=value):
                metadata = task_fixture("completed")
                metadata["checks"][0][field] = value
                self.idle(self.archive(metadata))
                self.assertNotEqual(self.errors(), "")

    def test_missing_criterion_rejected(self):
        metadata = task_fixture()
        metadata["checks"].pop()
        self.write_task(metadata)
        self.assertInvalid("checks не совпадают")

    def test_duplicate_criterion_rejected(self):
        metadata = task_fixture()
        metadata["checks"].append(deepcopy(metadata["checks"][0]))
        self.write_task(metadata)
        self.assertInvalid("повтор критерия")

    def test_missing_plan_section_rejected(self):
        self.write_task(task_fixture(), body=BODY.replace("## План выполнения", "## Другой раздел"))
        self.assertInvalid("отсутствует раздел «План выполнения»")

    def test_completion_requires_status_and_debt_review(self):
        for field, value in (("project_status_updated", False), ("technical_debt_reviewed", False), ("technical_debt_result", "")):
            with self.subTest(field=field):
                metadata = task_fixture("completed")
                metadata["completion"][field] = value
                self.idle(self.archive(metadata))
                self.assertNotEqual(self.errors(), "")

    def test_dates_are_valid_and_ordered(self):
        for field, value in (("created_on", "2026-02-30"), ("completed_on", "2026-10-17")):
            with self.subTest(field=field):
                metadata = task_fixture("completed")
                metadata[field] = value
                self.idle(self.archive(metadata))
                self.assertNotEqual(self.errors(), "")

    def test_malformed_metadata_reports_errors(self):
        for field, value in (("status", []), ("approval", []), ("checks", {}), ("revision", True)):
            with self.subTest(field=field):
                metadata = task_fixture()
                metadata[field] = value
                self.write_task(metadata)
                self.assertNotEqual(self.errors(), "")
        self.current.write_text('```json\n{bad json}\n```\n', encoding="utf-8")
        self.assertInvalid("CURRENT_TASK.md")

    def test_filled_current_task_template_validates(self):
        body = (self.root / "templates/current-task.md").read_text(encoding="utf-8")
        body = body.replace("{{NNNN}}", "9001").replace("{{YYYY-MM-DD}}", "2026-10-18")
        self.current.write_text(re.sub(r"\{\{[^{}]+\}\}", "Тестовое описание", body), encoding="utf-8")
        self.assertEqual(self.errors(), "")

    def test_regressions_requirements_links_pdf_and_feature_template(self):
        registry_path = self.root / "docs/product/requirements.json"
        original = registry_path.read_text(encoding="utf-8")
        registry = json.loads(original)
        registry["requirements"].append(deepcopy(registry["requirements"][0]))
        registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
        checker = check_sdd.Checker(self.root)
        checker.registry()
        self.assertIn("Повтор ID", "\n".join(checker.errors))
        registry_path.write_text(original, encoding="utf-8")
        pdf = self.root / registry["source"]["path"]
        pdf.write_bytes(pdf.read_bytes() + b"\n")
        checker = check_sdd.Checker(self.root)
        checker.registry()
        self.assertIn("SHA-256", "\n".join(checker.errors))
        (self.root / "broken.md").write_text("[missing](missing.md)\n", encoding="utf-8")
        checker = check_sdd.Checker(self.root)
        checker.registry()
        checker.markdown()
        self.assertIn("битая локальная ссылка", "\n".join(checker.errors))
        target = self.root / "specs/002-example"
        target.mkdir()
        for name in check_sdd.FEATURE_FILES:
            body = (self.root / "templates" / name).read_text(encoding="utf-8")
            for key, value in {"{{NNN}}": "002", "{{slug}}": "example", "{{REQ-ID}}": "CON-001"}.items():
                body = body.replace(key, value)
            (target / name).write_text(re.sub(r"\{\{[^{}]+\}\}", "Тестовое описание", body), encoding="utf-8")
        checker = check_sdd.Checker(self.root)
        checker.registry()
        checker.errors.clear()  # Ошибка изменённого PDF уже проверена выше.
        checker.feature(target)
        self.assertEqual(checker.errors, [])


if __name__ == "__main__":
    unittest.main()
