"""
scripts/adversarial_check.py

Milestone 4 adversarial review. Behaves like a hostile client: sends invalid types, injection strings, path tricks,
fake and oversized files and password-bypass attempts to EVERY route of the unified app, against a throw-away
database in a real MongoDB (dropped at the end; the team's database is never touched).

A finding is: a status outside the expected set (any 500), an internal detail in a response (traceback, driver name,
connection string, file path), a payload reflected unescaped into HTML, an admin route answering without the password
when one is set, or the dashboard broken after the attack. Exit code 1 if there is any finding.

    MONGODB_TEST_URI=mongodb://localhost:27018 python scripts/adversarial_check.py

Results, and the defects it found, are in docs/evidence/security/README.md.
"""

import io
import os
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MONGODB_URI"] = ""      # never the developer's database: the app is given the throw-away one below
os.environ["ADMIN_PASSWORD"] = ""

from openpyxl import Workbook  # noqa: E402
from pymongo import MongoClient  # noqa: E402

import main_api  # noqa: E402
from data_access.mongo_repository import MongoAcademicRepository  # noqa: E402
from data_pipeline.etl_processor import ETLProcessor  # noqa: E402
from webapp import create_app  # noqa: E402

# 308 = Werkzeug normalising "..%2f" in a path (it redirects to a route that then validates); 414 = URI too long.
EXPECTED = {200, 201, 308, 400, 401, 404, 405, 409, 413, 414, 422}
LEAKS = ("Traceback", 'File "', "pymongo", "mongodb://", "werkzeug", "site-packages", "Exception")
HEADER = ("matricula", "nombre", "parcial1", "parcial2", "parcial3", "asistencia_pct", "participacion")

WEIRD_IDS = ["", " ", "..", "../../etc/passwd", "%2e%2e%2f", "<script>alert(1)</script>", "' OR 1=1 --",
             '{"$gt":""}', "$where", "a" * 5000, "ñandú", "😀", "%00", "G1%00", "G1;DROP", "null", "NaN", "-1",
             "‮", "CON", "%0d%0aSet-Cookie:x=1"]
HOSTILE_BODIES = [None, "", "null", "[]", "123", '"str"', "{", '{"group_id": null}', '{"group_id": ["a"]}',
                  '{"group_id": {"$ne": null}}', '{"group_id": "' + "a" * 100_000 + '"}', '{"teacher": {"$gt": 1}}',
                  '{"count": "abc"}', '{"count": 1e400}', '{"count": -1}', '{"count": 501}', '{"count": true}',
                  '{"count": [1]}', '{"reset": "false", "count": 1}']
HOSTILE_STUDENTS = [{"grades": ["90"]}, {"grades": [None]}, {"grades": [150]}, {"grades": [-1]}, {"grades": ["NaN"]},
                    {"grades": [1e308]}, {"grades": [True]}, {"grades": [[1]]}, {"grades": [{"$gt": 1}]},
                    {"grades": [80] * 10_000}, {"grades": "80"}, {"attendance_pct": "abc"}, {"attendance_pct": 101},
                    {"attendance_pct": True}, {"participation_score": {"$ne": 0}}, {"student_id": ""},
                    {"name": ""}, {"student_id": "x" * 10_000}, {"name": "<img src=x onerror=alert(1)>"},
                    {"student_id": "$where"}, {"name": "B" * 100_000}, {"student_id": None}]


def workbook(rows, header=HEADER) -> bytes:
    wb = Workbook()
    ws = wb.active
    if header:
        ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def zip_bytes(name: str, text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return out.getvalue()


def hostile_files() -> dict[str, tuple[bytes, str]]:
    good = ("S8", "A", 80, 80, 80, 90, 80)
    return {
        "text renamed .xlsx": (b"hello", "a.xlsx"),
        "empty file": (b"", "a.xlsx"),
        "csv": (b"matricula,nombre\n1,a", "a.csv"),
        "executable renamed .xlsx": (b"MZ\x90\x00" * 100, "virus.xlsx"),
        "zip that is not a workbook": (zip_bytes("x.txt", "hi"), "z.xlsx"),
        "zip bomb (200 MB inflated)": (zip_bytes("xl/worksheets/sheet1.xml", "0" * 200_000_000), "b.xlsx"),
        "no header": (workbook([good], header=None), "a.xlsx"),
        "wrong headers": (workbook([(1, 2, 3)], header=("x", "y", "z")), "a.xlsx"),
        "only header": (workbook([]), "a.xlsx"),
        "hostile rows": (workbook([("S1", "A", "ochenta", "x", None, "abc", "zz"), ("S2", "A", 500, -3, 1e309, 200, -1),
                                   ("S3", "=1+1", "=A1*2", '=HYPERLINK("http://x")', 80, 90, 80),
                                   ("S4", "<script>alert(1)</script>", True, None, 80, 90, 80),
                                   ("S1", "dup", 80, 80, 80, 90, 80), (None, "no id", 80, 80, 80, 90, 80)]), "a.xlsx"),
        "1,001 rows": (workbook([(f"T{i}", "A", 80, 80, 80, 90, 80) for i in range(1001)]), "a.xlsx"),
        "upper-case extension": (workbook([good]), "A.XLSX"),
        "path in the file name": (workbook([good]), "../../evil.xlsx"),
    }


class Attack:
    def __init__(self, client):
        self.client = client
        self.findings: list[tuple] = []
        self.requests = 0

    def check(self, label: str, response):
        self.requests += 1
        body = "" if response.mimetype == "application/pdf" else response.get_data(as_text=True)
        problems = [f"status {response.status_code}"] if response.status_code not in EXPECTED else []
        problems += [f"leak {leak!r}" for leak in LEAKS if leak in body]
        if "<script>alert" in body and response.mimetype == "text/html":
            problems.append("payload reflected into HTML")
        if problems:
            self.findings.append((label, response.status_code, problems, body[:160]))
        return response

    def run(self):
        c = self.client
        c.post("/admin/api/groups", json={"group_id": "G1"})
        for gid in WEIRD_IDS:
            for url in (f"/api/groups/{gid}", f"/reports/groups/{gid}.pdf", f"/api/v1/groups/{gid}/risk-report",
                        f"/?group={gid}", f"/reports/groups/G1/students/{gid}.pdf", f"/admin/api/groups/{gid}/students",
                        f"/admin/api/groups/G1/students/{gid}/history", f"/admin/api/collections/{gid}"):
                self.check(f"GET {url[:70]}", c.get(url))
            for url in (f"/admin/api/groups/NOPE{gid}", f"/admin/api/groups/G1/students/{gid}"):
                self.check(f"DELETE {url[:70]}", c.delete(url))
        for method in ("put", "patch", "delete", "post"):
            for url in ("/", "/api/groups", "/health", "/reports/groups/G1.pdf", "/admin/", "/admin/api/stats"):
                self.check(f"{method.upper()} {url}", getattr(c, method)(url))
        for url in ("/.env", "/.git/config", "/static/../.env", "/static/..%2f.env", "/static/%2e%2e/core/config.py",
                    "/templates/admin.html", "/admin/../.env", "//etc/passwd", "/console", "/debug"):
            if self.check(f"GET {url}", c.get(url)).status_code == 200:
                self.findings.append((f"GET {url}", 200, ["a hidden file or path answered"], ""))
        for query in ("limit=-5", "limit=999999999999", "limit=abc", "skip=-1", "skip=99999999999999999999"):
            self.check(f"GET collections?{query}", c.get(f"/admin/api/collections/students?{query}"))
        for query in ("q=.*", "q=(a+)+$", "q=%5B", "q=$where", "q=" + "x" * 5000, "level=<script>", "kind=../../",
                      "from=2026-02-30", "from=abc", "to=99999-01-01", "limit=-1", "limit=99999999999999999999",
                      "skip=-5", "skip=99999999999999999999"):
            for url in ("/admin/api/error-log", "/admin/api/error-log/export.pdf"):
                self.check(f"GET {url}?{query[:40]}", c.get(f"{url}?{query}"))
        for raw in HOSTILE_BODIES:
            for url in ("/admin/api/groups", "/admin/api/groups/G1/students", "/admin/api/seed"):
                kwargs = {} if raw is None else {"data": raw, "content_type": "application/json"}
                self.check(f"POST {url} {str(raw)[:30]}", c.post(url, **kwargs))
        for fields in HOSTILE_STUDENTS:
            body = {"student_id": "S2", "name": "B", "grades": [80], "attendance_pct": 90, "participation_score": 80,
                    **fields}
            self.check(f"POST student {str(fields)[:50]}", c.post("/admin/api/groups/G1/students", json=body))
        for name, (content, filename) in hostile_files().items():
            for gid, form in (("G1", {}), ("NEW1", {"create_group": "true"}), ("bad id!", {"create_group": "true"}),
                              ("G1", {"mode": "strict"}), ("G1", {"mode": "evil"})):
                data = {"file": (io.BytesIO(content), filename), **form}
                self.check(f"IMPORT {name} -> {gid}", c.post(f"/admin/api/groups/{gid}/import", data=data,
                                                             content_type="multipart/form-data"))
        too_big = {"file": (io.BytesIO(b"x" * (5 * 1024 * 1024)), "a.xlsx")}
        self.check("IMPORT 5 MB", c.post("/admin/api/groups/G1/import", data=too_big, content_type="multipart/form-data"))
        self.check("huge header", c.get("/api/groups", headers={"X-Admin-Password": "x" * 100_000}))
        # After all of that the application must still work.
        c.post("/admin/api/groups/G1/students", json={"student_id": "S1", "name": "Ana", "grades": [80, 70],
                                                      "attendance_pct": 90, "participation_score": 80})
        for url in ("/", "/admin/", "/health", "/ready", "/api/groups", "/api/groups/G1", "/reports/groups/G1.pdf"):
            response = c.get(url)
            if response.status_code != 200:
                self.findings.append((f"AFTER {url}", response.status_code, ["broken after the attack"], ""))

    def try_bypass_password(self):
        c = self.client
        for method, url in (("get", "/admin/api/stats"), ("delete", "/admin/api/groups/G1"), ("post", "/admin/api/seed"),
                            ("delete", "/admin/api/seed"), ("get", "/admin/api/collections/students"),
                            ("get", "/admin/api//stats"), ("get", "/admin//api/stats"), ("get", "/admin/api/stats/"),
                            ("get", "/ADMIN/api/stats"), ("get", "/admin/api/./stats"), ("get", "/admin/api/health/../stats"),
                            ("get", "/admin/api/groups/G1/students"), ("get", "/admin/api/error-log"),
                            ("get", "/admin/api/error-log/export.pdf")):
            self.requests += 1
            response = getattr(c, method)(url)
            if response.status_code not in (401, 404, 405, 308):
                self.findings.append((f"PASSWORD BYPASS {method.upper()} {url}", response.status_code, ["not 401"], ""))


def main() -> int:
    uri = os.environ.get("MONGODB_TEST_URI")
    if not uri:
        print("set MONGODB_TEST_URI (e.g. mongodb://localhost:27018): the check needs a throw-away MongoDB")
        return 2
    mongo = MongoClient(uri)
    db = mongo[f"spp_adversarial_{uuid.uuid4().hex[:8]}"]
    repo = MongoAcademicRepository(db=db)
    try:
        with patch.object(main_api, "_repository", repo), patch.object(main_api, "_etl", ETLProcessor(repo)):
            attack = Attack(create_app().test_client())
            attack.run()
            with patch.dict(os.environ, {"ADMIN_PASSWORD": "adversarial-check"}):
                attack.client = create_app().test_client()
                attack.try_bypass_password()
    finally:
        mongo.drop_database(db.name)
        mongo.close()
    print(f"{attack.requests} hostile requests, {len(attack.findings)} findings")
    for finding in attack.findings:
        print(" ", finding)
    return 1 if attack.findings else 0


if __name__ == "__main__":
    sys.exit(main())
