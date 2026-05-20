import os
import requests
import base64
import sys
import time
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- ANSI цвета для красивого лога в GitHub Actions ---
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"

# ─────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────
OUTPUT_FILE = "configs/all_configs.txt"
CUSTOM_REMARK = "V Team"        # Ваше кастомное название
REQUEST_TIMEOUT = 12             # секунды
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ConfigCollector/1.0)"
}

# Извлекаем ссылки из GitHub Secrets (переменной окружения)
raw_urls = os.getenv("CONFIG_URLS", "")

# Разбиваем строку по переносим строк или запятым, убирая пустые элементы
if "," in raw_urls:
    URLS = [u.strip() for u in raw_urls.split(",") if u.strip()]
else:
    URLS = [u.strip() for u in raw_urls.splitlines() if u.strip()]

# ─────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────

def shorten_url(url: str) -> str:
    parts = url.split("/")
    if len(parts) > 4:
        return f"{parts[3]}/.../{parts[-1]}"
    return url[-40:]

def get_config_fingerprint(config_str: str) -> str:
    config_str = config_str.strip()
    if config_str.startswith("vmess://"):
        try:
            b64_data = config_str[8:]
            padding = len(b64_data) % 4
            if padding: b64_data += "=" * (4 - padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8', errors='ignore'))
            if 'ps' in data: del data['ps']
            return "vmess://" + json.dumps(data, sort_keys=True)
        except: return config_str
    elif "://" in config_str:
        return config_str.split("#")[0]
    return config_str

def set_custom_remark(config_str: str, remark: str) -> str:
    config_str = config_str.strip()
    if config_str.startswith("vmess://"):
        try:
            b64_data = config_str[8:]
            padding = len(b64_data) % 4
            if padding: b64_data += "=" * (4 - padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8', errors='ignore'))
            data['ps'] = remark
            new_json = json.dumps(data, separators=(',', ':'))
            return "vmess://" + base64.b64encode(new_json.encode('utf-8')).decode('utf-8')
        except: return config_str
    elif "://" in config_str:
        base = config_str.split("#")[0]
        return f"{base}#{urllib.parse.quote(remark)}"
    return config_str

def get_mirror_urls(original_url: str) -> list[str]:
    urls = [original_url]
    if "raw.githubusercontent.com" in original_url:
        p = original_url.split("/")
        if len(p) >= 7:
            user, repo, branch, path = p[3], p[4], p[5], "/".join(p[6:])
            urls.append(f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}")
            urls.append(f"https://fastly.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}")
    return urls

def decode_content(raw: str) -> tuple[list[str], str]:
    content = raw.strip()
    if not content: return [], "Empty"
    if "://" in content:
        lines = [l.strip() for l in content.splitlines() if l.strip() and "://" in l]
        return lines, "Plain"
    try:
        padding = len(content) % 4
        if padding: content += "=" * (4 - padding)
        decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        lines = [l.strip() for l in decoded.splitlines() if l.strip() and "://" in l]
        return lines, "Base64"
    except: return [], "B64_Err"

def fetch_url(url: str) -> str | None:
    for mirror in get_mirror_urls(url):
        try:
            r = requests.get(mirror, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            return r.text
        except: continue
    return None

def process_single_url(url: str) -> tuple[str, list[str], str]:
    try:
        raw = fetch_url(url)
        if raw is None:
            return url, [], "Net_Err"
        configs, data_type = decode_content(raw)
        return url, configs, data_type
    except Exception:
        return url, [], "Error"

# ─────────────────────────────────────────────
# Главная логика
# ─────────────────────────────────────────────

def main():
    if not URLS:
        print(f"{RED}[Критическая ошибка] Список CONFIG_URLS пуст! Проверьте GitHub Secrets.{RESET}")
        sys.exit(1)

    print(f"{CYAN}=== Начинаем параллельный сбор конфигураций ({len(URLS)} источников) ==={RESET}")

    unique_configs_dict = {}
    total_raw = 0
    results = []

    # Скачиваем параллельно в 15 потоков для экономии минут GitHub Actions
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_url = {executor.submit(process_single_url, url): url for url in URLS}
        for future in as_completed(future_to_url):
            results.append(future.result())

    # Логируем результаты обработки в консоль GitHub
    print(f"\n{BOLD}{MAGENTA}{'ТИП':<9} | {'КОЛ-ВО':<8} | ИСТОЧНИК{RESET}")
    print(f"{BLUE}" + "-" * 65 + RESET)

    url_to_res = {res[0]: (res[1], res[2]) for res in results}

    for link in URLS:
        if link in url_to_res:
            configs, data_type = url_to_res[link]
        else:
            configs, data_type = [], "Skipped"

        total_raw += len(configs)
        for cfg in configs:
            fp = get_config_fingerprint(cfg)
            if fp not in unique_configs_dict:
                unique_configs_dict[fp] = set_custom_remark(cfg, CUSTOM_REMARK)

        type_colors = {"Plain": GREEN, "Base64": GREEN, "Empty": YELLOW, "Net_Err": RED, "Error": RED}
        type_col = f"{type_colors.get(data_type, RED)}{data_type:<9}{RESET}"
        print(f"{type_col} | {len(configs):>4} шт.   | {shorten_url(link)}")

    # Сохраняем результат в файл
    unique_configs = list(unique_configs_dict.values())
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_configs) + "\n")

    # Выводим финальную статистику
    print(f"\n{CYAN}╔{'═'*58}╗{RESET}")
    print(f"{CYAN}║{RESET}{BOLD}  ВСЕГО НАЙДЕНО:   {total_raw:<39}{RESET}{CYAN}║{RESET}")
    print(f"{CYAN}║{RESET}{BOLD}  УНИКАЛЬНЫХ:      {len(unique_configs):<39}{RESET}{CYAN}║{RESET}")
    print(f"{CYAN}║{RESET}{BOLD}  МАРКИРОВКА:      {CUSTOM_REMARK:<39}{RESET}{CYAN}║{RESET}")
    print(f"{CYAN}║{RESET}{BOLD}  СОХРАНЕНО В:     {OUTPUT_FILE:<39}{RESET}{CYAN}║{RESET}")
    print(f"{CYAN}╚{'═'*58}╝{RESET}\n")

if __name__ == "__main__":
    main()
