from pathlib import Path


FILES = [
    Path("configuracoes/models.py"),
    Path("ordens/models.py"),
]

REPLACEMENTS = [
    ("Ã§", "ç"),
    ("Ã£", "ã"),
    ("Ã¡", "á"),
    ("Ã©", "é"),
    ("Ãª", "ê"),
    ("Ã³", "ó"),
    ("Ãº", "ú"),
    ("Ã­", "í"),
    ("Ã‡", "Ç"),
    ("Ã‰", "É"),
    ("Ã“", "Ó"),
    ("Ãš", "Ú"),
    ("Ã€", "À"),
    ("Ã¢", "â"),
    ("Ã´", "ô"),
    ("Ãµ", "õ"),
    ("Ã‰", "É"),
    ("Ã‚", "Â"),
    ("NÂº", "Nº"),
    ("Âº", "º"),
    ("Âª", "ª"),
    ("â€˜", "'"),
    ("â€™", "'"),
    ("â€œ", '"'),
    ("â€\x9d", '"'),
    ("â€“", "-"),
    ("â€”", "-"),
    ("â€¦", "..."),
    ("ðŸ”’", ""),
    ("âž•", ""),
]


def main() -> None:
    for file_path in FILES:
        original = file_path.read_text(encoding="utf-8")
        fixed = original
        total_changes = 0
        for old, new in REPLACEMENTS:
            count = fixed.count(old)
            if count:
                fixed = fixed.replace(old, new)
                total_changes += count
        if fixed != original:
            file_path.write_text(fixed, encoding="utf-8")
            print(f"{file_path}: {total_changes} substituicoes")
        else:
            print(f"{file_path}: sem alteracoes")


if __name__ == "__main__":
    main()
