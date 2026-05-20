import os
import requests
import base64
import sys
import time
import json
import urllib.parse
from threading import Thread

# --- ANSI цвета ---
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
MAGENTA= "\033[95m"
BLUE   = "\033[94m"

# ─────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────
OUTPUT_DIR      = "configs"       # Папка для сохранения результатов
CUSTOM_REMARK   = "V Team"        # Ваше кастомное название
REQUEST_TIMEOUT = 12              # секунды
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ConfigCollector/1.0)"
}

# Динамическое чтение URL-адресов из GitHub Secrets
ENV_URLS = os.getenv("CONFIG_URLS", "")
URLS = [line.strip() for line in ENV_URLS.splitlines() if line.strip()]

# ─────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────

def is_ci() -> bool:
    return os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"

def animate_loading(stop_event: dict):
    chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event["done"]:
        sys.stdout.write(f"\r{CYAN}[ {chars[i % len(chars)]} Сбор... ]{RESET} ")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1

def shorten_url(url: str) -> str:
    parts = url.split("/")
    if len(parts) > 4:
        return f"{parts[3]}/.../{parts[-1]}"
    return url[-40:]

def get_config_fingerprint(config_str: str) -> str:
    """Создает уникальный отпечаток конфига без названия (remark)."""
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
    """Заменяет оригинальное название на кастомное."""
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

def parse_configs(url: str) -> tuple[list[str], str]:
    in_ci = is_ci()
    stop_event = {"done": False}
    if not in_ci:
        spinner = Thread(target=animate_loading, args=(stop_event,), daemon=True)
        spinner.start()
    try:
        raw = fetch_url(url)
        stop_event["done"] = True
        if not in_ci: sys.stdout.write("\r" + " " * 40 + "\r")
        if raw is None: return [], "Net_Err"
        return decode_content(raw)
    except Exception:
        stop_event["done"] = True
        return [], "Error"

# ─────────────────────────────────────────────
# Главная логика
# ─────────────────────────────────────────────

def main():
    in_ci = is_ci()
    
    # Проверка: если список URL пуст, значит секрет не задан или пустой
    if not URLS:
        print(f"\n{RED}{BOLD}[ОШИБКА] Список URL пуст!{RESET}")
        print(f"{YELLOW}Убедитесь, что вы создали секрет CONFIG_URLS в настройках репозитория.{RESET}\n")
        sys.exit(1)

    if not in_ci:
        os.system("cls" if os.name == "nt" else "clear")
        print(f"\n{BOLD}{MAGENTA}{'ТИП':<9} | {'КОЛ-ВО':<8} | ИСТОЧНИК{RESET}")
        print(f"{BLUE}" + "-" * 65 + RESET)
    else:
        print("=== Config Collector starting ===")
        print(f"Loaded {len(URLS)} sources from GitHub Secrets.")

    unique_configs_dict = {} # {fingerprint: modified_config}
    total_raw = 0

    try:
        for link in URLS:
            configs, data_type = parse_configs(link)
            total_raw += len(configs)
            for cfg in configs:
                fp = get_config_fingerprint(cfg)
                if fp not in unique_configs_dict:
                    unique_configs_dict[fp] = set_custom_remark(cfg, CUSTOM_REMARK)

            if not in_ci:
                type_colors = {"Plain": GREEN, "Base64": GREEN, "Empty": YELLOW}
                type_col = f"{type_colors.get(data_type, RED)}{data_type:<9}{RESET}"
                print(f"{type_col} | {len(configs):>4} шт.   | {shorten_url(link)}")
            else:
                print(f"[{data_type}] {len(configs):>4} configs  {shorten_url(link)}")

    except KeyboardInterrupt:
        print(f"\n{YELLOW}⚠ Прервано пользователем{RESET}")

    finally:
        unique_configs = list(unique_configs_dict.values())
        total_unique = len(unique_configs)
        
        # Гарантируем наличие папки под файлы
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Алгоритм равномерного распределения на 10 файлов
        num_files = 10
        avg = total_unique // num_files
        remain = total_unique % num_files
        
        idx = 0
        saved_info = []
        
        for i in range(num_files):
            # Распределяем остаток по первым файлам
            chunk_size = avg + (1 if i < remain else 0)
            chunk = unique_configs[idx:idx + chunk_size]
            idx += chunk_size
            
            file_name = f"sub_{i+1}.txt"
            file_path = os.path.join(OUTPUT_DIR, file_name)
            
            with open(file_path, "w", encoding="utf-8") as f:
                if chunk:
                    f.write("\n".join(chunk) + "\n")
                else:
                    f.write("") # Защита на случай, если уникальных конфигов меньше 10
            
            saved_info.append(f"{file_name}: {len(chunk)} шт.")

        # Красивый вывод результатов
        if not in_ci:
            print(f"\n{CYAN}╔{'═'*58}╗{RESET}")
            print(f"{CYAN}║{RESET}{BOLD}  ВСЕГО НАЙДЕНО:   {total_raw:<39}{RESET}{CYAN}║{RESET}")
            print(f"{CYAN}║{RESET}{BOLD}  УНИКАЛЬНЫХ:      {total_unique:<39}{RESET}{CYAN}║{RESET}")
            print(f"{CYAN}║{RESET}{BOLD}  МАРКИРОВКА:      {CUSTOM_REMARK:<39}{RESET}{CYAN}║{RESET}")
            print(f"{CYAN}╠{'═'*58}╣{RESET}")
            for info in saved_info:
                print(f"{CYAN}║{RESET}  • {info:<45} {RESET}{CYAN}║{RESET}")
            print(f"{CYAN}╚{'═'*58}╝{RESET}\n")
        else:
            print(f"\nTotal: {total_raw} | Unique: {total_unique} | Split into {num_files} files in '{OUTPUT_DIR}/'")
            for info in saved_info:
                print(f"  - {info}")

if __name__ == "__main__":
    main()
