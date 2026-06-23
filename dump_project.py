import os
import time
from pathlib import Path

# ✅ СЕНЬОР-ФИКС: Намертво отрезаем 'htmlcov', чтобы сгенерированные отчеты покрытия не лезли в дампы
IGNORE_DIRS = {'data', 'logs', 'reports', 'prometheus', 'grafana', '__pycache__', 'htmlcov'}

# ✅ СЕНЬОР-ФИКС: Добавили бинарные и XML артефакты покрытия в игнор-лист файлов
IGNORE_FILES = {
    'dump_project.py',
    'project_context_dump.txt',
    'tests_context_dump.txt',
    'README.md',
    '.DS_Store',
    'Thumbs.db',
    '.coverage',
    'coverage.xml'
}

# Секреты, которые жестко скипаем ради безопасности
SECRET_PATTERNS = ['.env', 'secret', 'token', 'key', 'password', 'private']

project_root = Path(__file__).resolve().parent
# НАСТРОЙКА ДВУХ РАЗДЕЛЬНЫХ ПУТЕЙ ДЛЯ ВЫВОДА
output_main = project_root / 'project_context_dump.txt'
output_tests = project_root / 'tests_context_dump.txt'

print(f"=== СТАРТ ОЧИЩЕННОГО УЛЬТРА-ДАМПЕРА (СЕПАРАЦИЯ ЯДРА И ТЕСТОВ) ===", flush=True)
print(f"Корень проекта: {project_root}", flush=True)
print(f"Файл ядра системы: {output_main}", flush=True)
print(f"Файл тестового слоя: {output_tests}\n", flush=True)

start_time = time.time()

main_project_core = []
test_suite_matrix = []

# Идем по проекту линейным обходом
for root, dirs, files in os.walk(project_root, topdown=True):

    # Фильтруем скрытые директории, виртуальные окружения и мусорные папки
    dirs[:] = [
        d for d in dirs
        if d not in IGNORE_DIRS
           and not d.startswith('.')
           and 'venv' not in d.lower()
    ]

    current_dir_rel = Path(root).relative_to(project_root)
    print(f"📁 Обход директории: {current_dir_rel if str(current_dir_rel) != '.' else 'КОРЕНЬ'}", flush=True)

    for file in files:
        file_path = Path(root) / file
        relative_path = file_path.relative_to(project_root)

        # Жесткий отсев игнорируемых файлов
        if file in IGNORE_FILES or file == output_main.name or file == output_tests.name:
            continue

        # Скипаем файлы, если они попадают под паттерны секретов
        if any(p in file.lower() for p in SECRET_PATTERNS):
            print(f"  [ПРОПУСК СЕКРЕТА] {file}", flush=True)
            continue

        size_kb = file_path.stat().st_size / 1024
        print(f"  📄 Читаю: {file} ({size_kb:.1f} KB) ... ", end='', flush=True)

        if size_kb > 2000:
            print("ПРОПУЩЕН (превышен лимит размера)", flush=True)
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            print("ОК ", end='', flush=True)
        except UnicodeDecodeError:
            print("ПРОПУЩЕН (бинарник/картинка/артефакт)", flush=True)
            continue
        except Exception as e:
            print(f"ОШИБКА ({e})", flush=True)
            continue

        file_entry = {
            "path": relative_path,
            "content": content
        }

        # Сепарация слоев кода на этапе обхода
        if "tests" in relative_path.parts:
            test_suite_matrix.append(file_entry)
            print("[-> ТЕСТЫ]", flush=True)
        else:
            main_project_core.append(file_entry)
            print("[-> ЯДРО СЕРВИСА]", flush=True)

# ЗАПИСЬ СЕКТОРОВ В РАЗНЫЕ ФАЙЛЫ НА ДИСК

# 1. Записываем файлы ядра приложения (Бизнес-логика, Докер, Конфиги)
with open(output_main, 'w', encoding='utf-8') as dump_main:
    dump_main.write("# SECTION I: MAIN OPERATIONAL CORE APPLICATION FILES\n")
    dump_main.write("# ============================================================\n\n")
    for entry in main_project_core:
        dump_main.write(f"## FILE: {entry['path']}\n")
        dump_main.write(f"```text\n{entry['content']}\n```\n\n---\n\n")

# 2. Записываем файлы тестов (Pytest, Hypothesis, Сценарии физзинга)
with open(output_tests, 'w', encoding='utf-8') as dump_tests:
    dump_tests.write("# SECTION II: TEST SUITE & AUTOMATION MATRICES\n")
    dump_tests.write("# ============================================================\n\n")
    for entry in test_suite_matrix:
        dump_tests.write(f"## FILE: {entry['path']}\n")
        dump_tests.write(f"```text\n{entry['content']}\n```\n\n---\n\n")

duration = time.time() - start_time
total_files = len(main_project_core) + len(test_suite_matrix)

print(f"\n{'=' * 50}", flush=True)
print(f"🏁 Раздельная генерация дампов завершена успешно!", flush=True)
print(f"  ├─ Создан: {output_main.name} ({len(main_project_core)} файлов чистого ядра)", flush=True)
print(f"  ├─ Создан: {output_tests.name} ({len(test_suite_matrix)} файлов чистых тестов)", flush=True)
print(f"  └─ Суммарно упаковано: {total_files} файлов за {duration:.2f} сек.", flush=True)
print(f"{'=' * 50}", flush=True)