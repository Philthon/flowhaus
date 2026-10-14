"""Regenerate the demo CSVs: `uv run python data/make_data.py`."""

import csv
from pathlib import Path

HERE = Path(__file__).parent
ZWSP = "​"

ROWS = [
    ("Anna Schmidt", "anna.schmidt@example.com", "Nordwind GmbH"),
    ("  ben carter", "Ben.Carter@Example.com  ", "Carter & Sons"),
    ("Chloe Dubois", "chloe.dubois@example.fr", "Maison Bleu"),
    ("david kim ", "  DAVID.KIM@EXAMPLE.COM", "Kim Logistics"),
    ("Elena Rossi", "mailto:elena.rossi@example.it", "Rossi Design"),
    ("Farid Haddad", "farid.haddad@example.com,", "Haddad Trading"),
    ("Grace Lee", "grace.lee@example.com.", "Lee Analytics"),
    ("Hannah Müller", "hannah.mueller" + ZWSP + "@example.de", "Müller AG"),
    ("Ivan Petrov", "ivan.petrov.example.com", "Petrov Labs"),
    ("Jane Doe", "jane+news@example.com", "Doe Media"),
    ("Kofi Mensah", "kofi.mensah@example.com", "Mensah Foods"),
    ("Laura Gómez", "laura.gomez@example.es", "Gómez Arquitectos"),
    ("Mark Taylor", "mark.taylor@example.co.uk", "Taylor Consulting"),
    ("nina patel", "Nina.Patel@example.com", "Patel Health"),
    ("Oscar Nilsson", "oscar.nilsson@example.se", "Nordic Boats"),
    ("Priya Singh", "priya.singh+work@example.in", "Singh Software"),
    ("Quentin Blake", "", "Blake Studio"),
    ("Rosa Martins", "rosa.martins@example.pt", "Martins Wines"),
    ("Sam O'Brien", "sam.obrien@example.ie", "O'Brien Pubs"),
    ("Tariq Aziz", "tariq.aziz@@example.com", "Aziz Imports"),
    ("Uma Rao", "uma.rao@example.com", "Rao Textiles"),
    ("Victor Hugo", "VICTOR.HUGO@example.com", "Hugo Books"),
    ("Wendy Zhang", "wendy.zhang@example.cn", "Zhang Electronics"),
    ("Xavier Ruiz", "mailto:Xavier.Ruiz@Example.com", "Ruiz Solar"),
    ("Yuki Tanaka", "yuki.tanaka@example.jp", "Tanaka Robotics"),
    ("Zoe Adams", "zoe.adams@example", "Adams Bakery"),
    ("anna schmidt", "ANNA.SCHMIDT@example.com", "Nordwind GmbH"),
    ("Ben Carter", "ben.carter@example.com", "Carter & Sons"),
    ("Carlos Mendes", "carlos.mendes@example.br", "Mendes Coffee"),
    ("Dana White", " dana.white@example.com ", "White Legal"),
    ("Emil Novak", "emil.novak@example.cz", "Novak Glass"),
    (ZWSP + "Fatima Zahra", "fatima.zahra@example.ma", "Zahra Rugs"),
    ("George Brown", "george.brown@example.com;", "Brown Builders"),
    ("Helen Clark", "helen.clark at example.com", "Clark Events"),
    ("Isaac Newton", "isaac.newton@example.com", "Gravity Inc"),
    ("Jane Doe", "Jane+News@Example.com", "Doe Media"),
    ("Karl Weber", "karl.weber@example.de", "Weber Tools"),
    ("Lina Haddad", "lina.haddad@example.lb", "Haddad Trading"),
    ("Mia Wong", "mia.wong+crm@example.hk", "Wong Finance"),
    ("Noah Fischer", "noah.fischer@example.at", "Fischer Ski"),
    ("Olivia Brown ", "olivia.brown@example.com", "Brown Builders"),
    ("Pavel Horák", "pavel.horak@example.cz" + ZWSP, "Horák Beer"),
    ("Quinn Murphy", "quinn.murphy@example.ie", "Murphy Law"),
    ("Ravi Kumar", "ravi.kumar@example.in", "Kumar Pharma"),
    ("Sofia Rossi", "sofia.rossi@example.it", "Rossi Design"),
    ("tom hardy", "TOM.HARDY@EXAMPLE.COM.", "Hardy Films"),
    ("Ulla Berg", "ulla.berg@example.no", "Berg Fishing"),
    ("Vera Ivanova", "vera ivanova@example.ru", "Ivanova Art"),
    ("Will Smith", "will.smith@example.com", "Smith Media"),
    ("Kofi Mensah", "  kofi.mensah@example.com", "Mensah Foods"),
]


def write(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


if __name__ == "__main__":
    write(HERE / "contacts.csv", ["name", "email", "company"], ROWS)
    # Same people, but the email column is missing: the run should fail in "Clean contacts".
    write(HERE / "contacts_broken.csv", ["name", "company"], [(n, c) for n, _, c in ROWS])
    print(f"wrote {len(ROWS)} rows to contacts.csv and contacts_broken.csv")
