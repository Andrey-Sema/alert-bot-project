import os
import time  # Импортируем тайм для нормального получения системного времени

# Имя итогового файла для скармливания нейронкам
OUTPUT_FILE = "project_context_dump.md"
# Ставим точку, чтобы парсить ВСЕ файлы в текущем корне проекта (Bot_for_threats)
TARGET_DIR = "."

# Что мы наглухо игнорируем при сборке
IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
IGNORE_FILES = {".env", "project_context_dump.md", ".DS_Store", "dump_project.py"}
IGNORE_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".session", ".session-journal", ".db"}


def should_ignore(path: str, is_dir: bool = False) -> bool:
    name = os.path.basename(path)
    if is_dir:
        return name in IGNORE_DIRS
    if name in IGNORE_FILES:
        return True
    _, ext = os.path.splitext(name)
    if ext.lower() in IGNORE_EXTENSIONS:
        return True
    return False


def generate_dump():
    if not os.path.exists(TARGET_DIR):
        print(f"❌ Ошибка: Папка {TARGET_DIR} не найдена! Запусти скрипт из корня.")
        return

    print(f"🚀 Начинаю сборку контекста из папки '{TARGET_DIR}'...")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write(f"# PROJECT CONTEXT DUMP: {TARGET_DIR}\n")
        out.write(f"Generated on: {time.ctime()}\n\n")  # Исправлено на time.ctime()
        out.write("Это единый файл контекста проекта для анализа LLM.\n")
        out.write("---\n\n")

        for root, dirs, files in os.walk(TARGET_DIR):
            dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), is_dir=True)]

            for file in files:
                file_path = os.path.join(root, file)
                if should_ignore(file_path, is_dir=False):
                    continue

                rel_path = os.path.relpath(file_path, os.path.dirname(TARGET_DIR))
                print(f"➕ Добавляю: {rel_path}")

                out.write(f"## FILE: {rel_path}\n")
                out.write(
                    "```python\n" if file.endswith(".py") else "```yaml\n" if file.endswith(".yml") else "```text\n")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        out.write(f.read())
                except Exception as e:
                    out.write(f"[Ошибка чтения файла: {str(e)}]\n")

                out.write("\n```\n\n---\n\n")

    print(f"🔥 Дамп успешно создан! Файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_dump()