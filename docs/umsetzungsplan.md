# Umsetzungsplan: weclapp-Client für die Mitarbeiter-Stammdaten-Sync

Stand: 30.09.2026 · Branch: `feature/weclapp-employee-sync` · Grundlage: [API-Analyse](weclapp_api_analyse.md)

> Der Plan deckt **Phase 1** ab: Vorname, Nachname, Geburtsdatum und Personalnummer
> (= Mitarbeiternummer) aus dem führenden System nach weclapp schreiben. Alles, was sich
> erst mit dem Test-Tenant klären lässt, ist in AP 6 gesammelt. Die Entwicklung bis
> Meilenstein M2 hängt nicht davon ab.

---

## 1. Ziel und Abgrenzung

Ergebnis von Phase 1 ist die Python-Bibliothek `weclapp-client` (Import: `weclapp_client`)
mit zwei Teilen:

1. **API-Client** für die weclapp REST API v2, beschränkt auf die benötigten Endpunkte
   `/user`, `/employee`, `/customAttributeDefinition` und `/user/currentUser`.
2. **Sync-Baustein** `weclapp_client.employee_sync`. Er nimmt Mitarbeiter-Datensätze in
   einem neutralen Format entgegen und legt sie idempotent als User plus Personalakte
   (`employee`) an bzw. aktualisiert sie.

| Im Scope | Nicht im Scope (Phase 1) |
|---|---|
| Anlegen und Aktualisieren von User und Employee | Anbindung des Quellsystems (es liefert die Datensätze im neutralen Format) |
| Felder: Vorname, Nachname, Geburtsdatum, Personalnummer (als Custom Attribute am User) | weitere Felder (folgen ggf. später) |
| Abgleich über die Personalnummer, beim Erstabgleich über die E-Mail | Offboarding und Löschen (Phase 1 meldet nur, wer in weclapp, aber nicht mehr in der Quelle ist) |
| Dry-Run und Ergebnis-Report | Betrieb des Sync-Jobs (Zeitplan, Hosting, Secret-Verwaltung) |
| Unit-Tests gegen eine gemockte API, Integrationstests gegen den Test-Tenant | Webhooks, Einladungs-Mails, Rollen, Lizenzen |

**Entscheidung:** Der Sync-Baustein liegt als eigenes Unterpaket im Client-Repo. Seine Regeln
(User und Employee als Paar, Custom Attribute als Schlüssel, Status `NOT_ACTIVE`) sind
weclapp-spezifisch. Er nutzt nur die öffentliche Client-API und lässt sich daher bei Bedarf
in den aufrufenden Service verschieben.

---

## 2. Technische Leitentscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| API-Version | v2 | aktuelle Version, v1 läuft aus |
| Python | ≥ 3.11, getestet mit 3.11–3.14 (CI-Matrix des Templates) | deshalb keine Syntax ab 3.12, z. B. keine PEP-695-Generics und kein `type`-Statement |
| HTTP | `httpx` mit synchronem Client | Timeouts und gzip eingebaut, Mocks über `httpx.MockTransport`. Ein Sync-Job braucht keine Parallelität, und weclapp rät ohnehin von Lastspitzen ab |
| Modelle | `pydantic` v2 mit mypy-Plugin | Validierung, camelCase-Aliase, typsichere Serialisierung |
| Retry | eigene kleine Implementierung | nur wenige Zeilen, volle Kontrolle über die Idempotenz-Regeln (siehe AP 1) |
| Tests | `pytest` mit `httpx.MockTransport`, keine Zusatzbibliothek | Mocks und ein In-Memory-Fake der Endpunkte, ganz ohne echten Tenant |
| Typisierung | `mypy --strict` für `src` **und** `unittests` | so im Template vorgegeben |
| Sprache | Code, Docstrings und README auf Englisch, Fachdoku in `docs/` auf Deutsch | übliche Konvention im Python-Umfeld. codespell prüft `src` und `README.md` |
| Paketname | Distribution `weclapp-client`, Import `weclapp_client` | passt zum Repo, der Name ist auf PyPI frei (Stand 30.09.2026) |
| Secrets | Token nur über die Konfiguration bzw. eine Umgebungsvariable, als `SecretStr` | erscheint nie in `repr`, Logs oder Exceptions |
| Logging | Standard-`logging`, Logger `weclapp_client` | **keine Namen, Geburtsdaten oder E-Mails in Logs**, nur weclapp-IDs und Personalnummern |

---

## 3. Zielbild

### 3.1 Schichten

```text
Aufrufer (Sync-Job)  --- liefert EmployeeMasterData ---+
                                                       v
weclapp_client.employee_sync    Abgleich, Diff, Anlegen/Aktualisieren, Report
                                                       v
weclapp_client.WeclappClient    Fassade: users, employees, custom_attribute_definitions
                                                       v
Ressourcen + Modelle            generische Operationen, pydantic-Modelle, Filter
                                                       v
HTTP-Transport                  Auth, Header, Timeouts, Retry, Fehler -> Exceptions
                                                       v
weclapp REST API v2
```

### 3.2 Paketstruktur

```text
src/weclapp_client/
├── __init__.py                 # öffentliche API: WeclappClient, WeclappConfig, Filter, Exceptions
├── py.typed
├── _version.py                 # von hatch-vcs erzeugt, nicht eingecheckt
├── config.py                   # WeclappConfig (inkl. from_env)
├── exceptions.py               # Exception-Hierarchie
├── _http.py                    # Transport: Header, Auth, Timeouts, Retry, Fehler-Mapping
├── _converters.py              # ms-Timestamps <-> date/datetime
├── query.py                    # Filter, Sortierung, Feldauswahl
├── client.py                   # WeclappClient (Kontextmanager)
├── models/
│   ├── base.py                 # WeclappModel: Aliase, read-only-Felder, Payload-Serialisierung
│   ├── user.py                 # User, UserStatus
│   ├── employee.py             # Employee, EmploymentStatus
│   └── custom_attribute.py     # CustomAttribute, CustomAttributeDefinition
├── resources/
│   ├── base.py                 # Resource[ModelT]: iterate, list, count, get, find_one, create, update
│   ├── users.py
│   ├── employees.py
│   └── custom_attribute_definitions.py
└── employee_sync/
    ├── models.py               # EmployeeMasterData, SyncOutcome, SyncReport
    └── synchronizer.py         # EmployeeSynchronizer
unittests/
├── conftest.py                 # Client mit MockTransport, Laden der Fixtures
├── fixtures/                   # Beispiel-Responses: zuerst aus der Spec, später anonymisiert aus dem Test-Tenant
├── fake_weclapp.py             # In-Memory-Fake für /user, /employee, /customAttributeDefinition
├── test_http.py, test_query.py, test_models.py, test_resources.py, test_employee_sync.py
└── integration/                # Marker "integration", läuft nur mit gesetzten WECLAPP_*-Variablen
```

### 3.3 Geplante Nutzung

```python
from datetime import date

from weclapp_client import WeclappClient, WeclappConfig
from weclapp_client.employee_sync import EmployeeMasterData, EmployeeSynchronizer

records = [
    EmployeeMasterData(
        personnel_number="00042",
        first_name="Erika",
        last_name="Musterfrau",
        birth_date=date(1985, 4, 12),
        email="erika.musterfrau@example.com",
    ),
]

with WeclappClient(WeclappConfig.from_env()) as client:  # WECLAPP_BASE_URL, WECLAPP_API_TOKEN
    synchronizer = EmployeeSynchronizer(client, personnel_number_attribute_key="personalnummer")
    report = synchronizer.sync(records, dry_run=True)
    print(report.summary())
```

Den Client kann man auch direkt nutzen. Änderungen übergibt man dabei als Modell, gesendet
werden nur die explizit gesetzten Felder, und mypy prüft die Feldnamen:

```python
from weclapp_client import Filter
from weclapp_client.models import Employee

with WeclappClient(WeclappConfig.from_env()) as client:
    employee = client.employees.find_one(Filter.eq("userId", "4711"))
    if employee is not None:
        client.employees.update(employee, Employee(birth_date=date(1985, 4, 12)))
```

---

## 4. Arbeitspakete

| AP | Inhalt | Ergebnis | Abhängig von | Test-Tenant nötig | Aufwand (Richtwert, PT = Personentage) |
|---|---|---|---|---|---|
| 0 | Projekt-Setup | Template zu `weclapp_client` umgebaut, CI grün | – | nein | S · 0,5 PT |
| 1 | HTTP-Transport, Konfiguration, Fehler | `_http.py`, `config.py`, `exceptions.py` | AP 0 | nein | M · 1–1,5 PT |
| 2 | Modelle und Konvertierung | `models/`, `_converters.py` | AP 0 | nein | M · 1 PT |
| 3 | Abfragen und generische Ressource | `query.py`, `resources/base.py` | AP 1, AP 2 | nein | M · 1 PT |
| 4 | Konkrete Ressourcen und Client-Fassade | `resources/*`, `client.py` → **M1** | AP 3 | nein | S · 0,5–1 PT |
| 5 | Sync-Baustein | `employee_sync/` → **M2** | AP 4 | nein | L · 1,5–2 PT |
| 6 | Verifikation mit dem Test-Tenant | Prüfpunkte erledigt, Integrationstests → **M3** | AP 4 (für Sync-Tests AP 5) | **ja** | M · 1 PT plus Wartezeit |
| 7 | Dokumentation und Release | README, Betriebsdoku, `v0.1.0` → **M4** | AP 5, AP 6 | nein | S · 0,5 PT |

Summe: ca. 7–8,5 PT, Wartezeiten nicht eingerechnet.

### AP 0 – Projekt-Setup

- Paket umbenennen: `src/mypackage` → `src/weclapp_client`, Beispielklasse und Beispieltest
  entfernen. Ein Smoke-Test (Import und Version) sorgt dafür, dass Unittests und Coverage
  weiterhin etwas messen.
- `pyproject.toml`:
  - `name = "weclapp-client"`, Beschreibung, Autoren und Keywords setzen, URLs auf
    `Hochfrequenz/weclapp_client.py` umstellen.
  - Laufzeit-Abhängigkeiten `httpx` und `pydantic` mit Untergrenze statt festem Pin, weil es
    sich um eine Bibliothek handelt.
  - `version-file` auf `src/weclapp_client/_version.py` umstellen, `.gitignore` entsprechend
    anpassen.
  - mypy: `plugins = ["pydantic.mypy"]`. pytest: Marker `integration` registrieren.
- CI und Pre-commit: den Pfad `src/mypackage` in `pythonlint.yml` und
  `.pre-commit-config.yaml` ersetzen. **Die Job-Namen bleiben unverändert**, weil sie als
  Required Checks dienen.
- README: den Template-Text durch eine kurze Projektbeschreibung ersetzen (Ausbau in AP 7).
- `uv lock` neu erzeugen.

**Fertig, wenn** alle CI-Checks grün sind: Unittests 3.11–3.14, Coverage ≥ 80 %, ruff, mypy
strict, codespell, Packaging, Dev-Umgebung, BOM-Check.

### AP 1 – HTTP-Transport, Konfiguration, Fehler

- `WeclappConfig`:
  - `base_url`, alternativ `tenant` (daraus wird `https://<tenant>.weclapp.com/webapp/api/v2/`)
  - `api_token` als `SecretStr`
  - Timeouts (Standard 60 s, Verbindungsaufbau 10 s)
  - `max_retries` (Standard 5) und `user_agent`
  - `from_env()` liest `WECLAPP_BASE_URL` bzw. `WECLAPP_TENANT` sowie `WECLAPP_API_TOKEN`.
- Feste Header: `AuthenticationToken`, `Accept: application/json`, `Accept-Encoding: gzip`,
  `User-Agent: weclapp-client-py/<version>`.
- Retry-Regeln: exponentieller Backoff mit Jitter von 1 s bis höchstens 30 s. Die
  `sleep`-Funktion ist injizierbar, damit Tests nicht wirklich warten.

  | Situation | GET / PUT | POST |
  |---|---|---|
  | 429 Too Many Requests | wiederholen | wiederholen (der Request wurde nicht verarbeitet) |
  | Verbindungsaufbau fehlgeschlagen | wiederholen | wiederholen (der Request hat den Server nicht erreicht) |
  | 502 / 503 / 504 oder Lese-Timeout | wiederholen | **nicht wiederholen**, weil der Datensatz schon angelegt sein könnte. Der Sync-Ablauf sucht vor jeder Anlage und holt Fehlendes im nächsten Lauf nach |

  PUT ist idempotent. War der erste Versuch schon erfolgreich, scheitert die Wiederholung
  höchstens am Optimistic Locking (409). Der Sync fängt das ab, indem er neu liest und neu
  vergleicht.
- Die Response-Header `X-Weclapp-Wait-Ms` und `X-Weclapp-Wait-Reason` loggen: auf DEBUG, ab
  einer Schwelle auf WARNING.
- Fehler-Mapping: weclapp liefert JSON nach RFC 7807 (`type`, `title`, `status`, `detail`,
  `instance` sowie `validationErrors[]` mit `location`, `errorCode` und `allowed`), teils aber
  auch `text/plain`. Der Fehlertyp ist der Teil von `type` nach dem letzten `/`.

  | Exception | Auslöser |
  |---|---|
  | `WeclappError` | Basisklasse aller Fehler |
  | `WeclappConnectionError` | Netzwerkfehler oder Timeout nach allen Retries |
  | `WeclappApiError` | Basis für HTTP-Fehler, enthält Status, Fehlertyp, `detail` und die Validierungsfehler |
  | ├ `AuthenticationError` | 401 |
  | ├ `PermissionDeniedError` | 403 |
  | ├ `NotFoundError` | 404 |
  | ├ `WeclappValidationError` | 400 `validation` (der Name vermeidet eine Verwechslung mit `pydantic.ValidationError`) |
  | ├ `OptimisticLockError` | 409 `optimistic_lock` |
  | ├ `ConflictError` | andere 409er (`context`, `persistence`) |
  | ├ `RateLimitError` | 429 nach allen Retries |
  | └ `ServerError` | 5xx |

- `dry_run` ist ein Parameter an allen schreibenden Aufrufen.
- **Tests:**
  - Header und URL-Aufbau
  - jedes Fehler-Mapping (mit Beispiel-JSON aus der Doku) und `text/plain`-Fehler
  - 429 mit anschließendem Erfolg, 429 bis zum Retry-Limit
  - POST ohne Retry bei Lese-Timeout, GET mit Retry
  - Token taucht weder in `repr` noch in Exceptions auf

### AP 2 – Modelle und Konvertierung

- Basisklasse `WeclappModel`:
  - camelCase-Aliase (`first_name` ↔ `firstName`)
  - unbekannte Felder werden beim Lesen ignoriert, damit Erweiterungen der API nichts kaputt
    machen
  - alle Felder optional, weil weclapp `null`-Felder weglässt
- Serialisierung für Schreibzugriffe (`to_payload`): Es gehen nur explizit gesetzte Felder
  raus, **nie** read-only-Felder und nie unbekannte Felder (beides beantwortet weclapp mit 400).
  Listen außer `customAttributes` werden in partiellen Updates nicht gesendet, denn fehlende
  Listeneinträge würde weclapp löschen.
- Modelle für Phase 1:

  | Modell | Felder |
  |---|---|
  | `User` | `id`, `version`, `created_date`, `last_modified_date`, `username` (read-only), `email`, `first_name`, `last_name`, `status`, `can_edit_dashboard`, `custom_attributes` |
  | `Employee` | `id`, `version`, `created_date`, `last_modified_date`, `employee_number` (read-only), `user_id`, `birth_date` |
  | `CustomAttribute` | `attribute_definition_id`, `string_value` |
  | `CustomAttributeDefinition` | `id`, `attribute_key`, `attribute_type`, `label`, `active`, `attribute_entity_type`, `entities` |

- Enums: `UserStatus` (`ACTIVE`, `DEPARTURE`, `NOT_ACTIVE`) und, als Vorbereitung für später,
  `EmploymentStatus` (`ACTIVE`, `INACTIVE`, `LEAVE_OF_ABSENCE`, `ONBOARDING`). Unbekannte
  Werte führen beim Lesen nicht zum Absturz.
- `_converters.py` rechnet zwischen ms seit Epoch und `datetime` bzw. `date` um:
  - Die Umrechnung läuft über `epoch + timedelta(milliseconds=…)` statt über
    `datetime.fromtimestamp()`. **Geburtsdaten vor 1970 ergeben negative Timestamps**, und die
    kann `fromtimestamp()` unter Windows nicht verarbeiten.
  - Die Zeitzonen-Konvention für reine Datumsfelder wie `birth_date` steht an genau einer
    Stelle: vorläufig Mitternacht UTC, endgültig nach Prüfpunkt P5 in AP 6.
- **Tests:**
  - Parsen von Beispiel-JSON, abgeleitet aus der Spec
  - Payload ohne read-only-Felder, nur mit den gesetzten Feldern
  - Datumsgrenzen: vor 1970, Schaltjahr, Zeitzonen
  - unbekannte Felder und Enum-Werte

### AP 3 – Abfragen und generische Ressource

- `query.py`:
  - `Filter.eq/ne/lt/le/gt/ge/like/ilike/in_/null/not_null(feld, wert)` erzeugt
    Query-Parameter wie `email-eq=…`. `in_` wird als JSON-Array serialisiert.
  - `Filter.custom_attribute_eq(definition_id, wert)` erzeugt `customAttribute<id>-eq=…`.
  - Filter verwenden die API-Feldnamen aus der weclapp-Doku (camelCase). **Die Feldnamen
    werden vor dem Request geprüft**, und zwar gegen die erlaubten Filterfelder der
    jeweiligen Ressource aus der Spec. Dazu gehören auch Zusatzfilter wie `hasEmployee` am
    User oder `firstName`, `lastName` und `email` am Employee. Die Prüfung ist nötig, weil
    weclapp unbekannte Filter sonst stillschweigend ignoriert.
  - `properties` (Feldauswahl) und `sort` werden ebenso geprüft. Standard-Sortierung ist `id`,
    damit das Paging stabil bleibt.
- `Resource[ModelT]`, generisch über `typing.Generic` (wegen Python 3.11):

  | Methode | Verhalten |
  |---|---|
  | `iterate(*filters, properties=None, sort="id", page_size=1000)` | Iterator über alle Seiten, endet bei einer Seite mit weniger als `page_size` Einträgen |
  | `list(...)` | wie `iterate`, aber als Liste |
  | `count(*filters)` | `GET /<ressource>/count` |
  | `get(id)` | Einzelabruf, `NotFoundError`, wenn der Datensatz fehlt |
  | `find_one(*filters)` | `None` bei 0 Treffern, **`AmbiguousResultError` bei mehr als einem Treffer** (zweites Sicherheitsnetz gegen ignorierte Filter) |
  | `create(entity, *, dry_run=False)` | `POST`, liefert den angelegten Datensatz zurück |
  | `update(current, changes, *, dry_run=False)` | partielles `PUT` mit `ignoreMissingProperties=true`. `id` und `version` stammen aus `current`, damit Optimistic Locking der Normalfall ist |

  Ein `delete` gibt es in Phase 1 nicht.
- **Tests:**
  - Paging mit 0, 1, genau 1000 und 2500 Datensätzen
  - Filter-Serialisierung, ungültige Filter- und Feldnamen
  - `find_one` mit 0, 1 und 2 Treffern
  - `update` sendet `ignoreMissingProperties` und `version`
  - `create` mit Antwort 201, Dry-Run-Parameter

### AP 4 – Konkrete Ressourcen und Client-Fassade

- `client.users` (`/user`): die Operationen aus AP 3 plus `current()` (`/user/currentUser`).
  `invite` und `softDelete` gibt es in Phase 1 bewusst **nicht**.
- `client.employees` (`/employee`): die Operationen aus AP 3 plus `for_user(user_id)`.
- `client.custom_attribute_definitions` (`/customAttributeDefinition`): `get_by_key(key)` mit
  Cache. Fehlt das Attribut oder ist es nicht vom Typ `STRING`, gibt es einen Fehler.
- `WeclappClient(config, *, http_client=None)`: Kontextmanager. Für Tests lässt sich ein
  eigener `httpx.Client` übergeben.
- **Tests:** Pfade und Parameter jeder Ressource, Smoke-Test der öffentlichen API.

**Meilenstein M1:** Der Client-Kern ist fertig und gegen Mocks getestet.

### AP 5 – Sync-Baustein `employee_sync`

- Eingabemodell `EmployeeMasterData`:

  | Feld | Regel |
  |---|---|
  | `personnel_number` | Pflicht. String, damit führende Nullen erhalten bleiben. Muss in der Eingabe eindeutig sein |
  | `first_name`, `last_name` | Pflicht, nicht leer, höchstens 50 Zeichen (Limit von weclapp) |
  | `birth_date` | optional, `date` |
  | `email` | Pflicht, weil `user.email` in weclapp Pflicht ist. Die Regel für Platzhalter ist noch offen, siehe K2 |

- `EmployeeSynchronizer(client, *, personnel_number_attribute_key, new_user_status=UserStatus.NOT_ACTIVE)`
  mit der Methode `sync(records, *, dry_run=False) -> SyncReport`.
- Ablauf eines Laufs:
  1. **Eingabe prüfen:** doppelte Personalnummern oder E-Mails, Feldlängen. Ungültige
     Datensätze werden als `invalid` gemeldet, der Lauf geht weiter.
  2. **Custom Attribute auflösen:** Die Definition wird über ihren Key geladen. Fehlt sie,
     bricht der Lauf ab, denn dann ist das Setup unvollständig.
  3. **Bestand laden:** alle User und Employees mit Feldauswahl, also wenige große Requests
     statt vieler kleiner. Daraus entstehen drei Indizes: Personalnummer → User, E-Mail
     (kleingeschrieben) → User und `userId` → Employee. Haben mehrere User dieselbe
     Personalnummer, ist das ein `conflict`.
  4. **Je Datensatz:**
     - User finden: zuerst über die Personalnummer, dann über die E-Mail (Erstabgleich).
       Gibt es keinen, wird er neu angelegt: mit `status=NOT_ACTIVE`,
       `canEditDashboard=false`, ohne Rollen und Lizenzen und mit der Personalnummer als
       Custom Attribute. **`invite` wird nicht aufgerufen.**
     - Trifft die E-Mail einen User mit einer **anderen** Personalnummer, ist das ein
       `conflict`. Dann wird nichts geändert.
     - Weichen Vorname, Nachname oder Personalnummer ab, folgt ein partielles `PUT`. Dabei
       geht nur das eigene Custom Attribute raus. weclapp führt `customAttributes` bei
       partiellen Updates pro Attribut zusammen, andere Attribute bleiben also erhalten.
       E-Mail und Status bestehender User ändert Phase 1 nicht.
     - Employee über `userId` finden, sonst `POST {userId, birthDate}`. Weicht das
       Geburtsdatum ab, folgt ein partielles `PUT`. Verglichen wird als `date`, nicht als ms.
     - Bei `OptimisticLockError` wird einmal neu gelesen, neu verglichen und erneut
       geschrieben. Scheitert auch das, wird der Datensatz als `error` gemeldet.
  5. **Fehlerbehandlung:** Fehler bei einzelnen Datensätzen landen im Report. Systemische
     Fehler brechen den Lauf ab: 401, 403, eine fehlende Attribut-Definition oder ein
     Verbindungsabbruch nach allen Retries.
  6. **Report** (`SyncReport`):
     - je Datensatz ein `SyncOutcome` mit einem der Werte `created`, `updated`, `unchanged`,
       `conflict`, `invalid` oder `error`
     - dazu die weclapp-IDs und die Namen der geänderten Felder (ohne deren Werte)
     - Summen über alle Datensätze
     - zusätzlich die User mit Personalnummer, die in der Quelle fehlen. Das dient nur zur
       Info, ein Offboarding gibt es in Phase 1 nicht.
- **Dry-Run:** Schreibzugriffe laufen mit `dryRun=true`. weclapp validiert dann, ohne zu
  speichern. Im Report bedeuten `created` und `updated` in diesem Fall „würde angelegt“ bzw.
  „würde geändert“. Einschränkung: Dry-Run-Antworten enthalten keine IDs. Bei neuen Usern
  lässt sich der Employee-Schritt deshalb nicht vorab prüfen.
- **Tests** gegen den In-Memory-Fake (`unittests/fake_weclapp.py`):
  - Neuanlage
  - ein zweiter Lauf ohne Änderungen erzeugt **keinen** Schreibzugriff
  - Änderung von Name und Geburtsdatum
  - Erstabgleich über die E-Mail, Konflikt bei abweichender Personalnummer
  - doppelte Eingaben
  - Optimistic Lock mit erfolgreicher Wiederholung
  - ein Einzelfehler bricht den Lauf nicht ab, ein 403 schon
  - Dry-Run
  - bricht ein Lauf zwischen User- und Employee-Anlage ab, holt der nächste Lauf die
    Personalakte nach
  - keine Namen, Geburtsdaten oder E-Mails in den Logs (geprüft mit `caplog`)

**Meilenstein M2:** Der Sync-Baustein ist fertig und gegen den Fake getestet.

### AP 6 – Verifikation mit dem Test-Tenant

Voraussetzung ist der Zugang zum Test-Tenant (K6). Dort wird eingerichtet:

- ein technischer API-User mit Token
- ein Custom Attribute „Personalnummer“ (Typ `STRING`, Entität `user`, Key z. B.
  `personalnummer`)

Prüfpunkte (die ⚠-Punkte aus der Analyse):

| # | Prüfung | Vorgehen | Wirkt auf |
|---|---|---|---|
| P1 | Pflichtfelder bei `POST /user` und `POST /employee` | minimale Payloads mit `dryRun=true` | Modelle, Defaults im Sync |
| P2 | User mit `NOT_ACTIVE` anlegbar, keine automatische Mail bei `POST /user` | Test-User mit eigener Test-Postfach-Adresse | Default im Sync, K3 |
| P3 | Personalakte für einen `NOT_ACTIVE`-User anlegbar und nutzbar | `POST /employee`, danach Ansicht in der Oberfläche | Sync-Ablauf |
| P4 | Vergabe von `username`, Eindeutigkeit von `email` (auch bei Groß-/Kleinschreibung) | zweiten User mit derselben E-Mail anlegen | Prüfung der Eingabe |
| P5 | Zeitzone von `birthDate` | Datum in der Oberfläche erfassen und per API lesen, und umgekehrt | `_converters.py` |
| P6 | Filter `customAttribute<id>-eq` am User, `properties=customAttributes` | `GET /user` | Laden des Bestands |
| P7 | `ignoreMissingProperties` bei `PUT /user` und `PUT /employee`, dazu das Zusammenführen der `customAttributes`. Der Parameter ist nur allgemein dokumentiert und an diesen beiden Endpunkten in der Spec nicht deklariert | partielle Updates | `update()` |
| P8 | `sort=id` und `pageSize=1000` bei `/user` und `/employee` | `GET` | Paging |
| P9 | minimale Rechte des API-Users | Rolle schrittweise einschränken | Betriebsdoku |
| P10 | Format echter Fehlerantworten (400, 403, 404, 409) | Fehler gezielt provozieren | Fehler-Mapping |

- Integrationstests liegen in `unittests/integration/` (Marker `integration`). Sie laufen nur,
  wenn `WECLAPP_BASE_URL` und `WECLAPP_API_TOKEN` gesetzt sind, also nicht in der CI.
- Testdaten werden danach aufgeräumt: `DELETE /employee/id/{id}` und
  `POST /user/id/{id}/softDelete`. Beides läuft über Test-Helfer, nicht über die öffentliche
  API.
- Echte Responses anonymisiert als Fixtures übernehmen. Abweichungen im Code und in der
  Analyse nachziehen.

**Meilenstein M3:** Client und Sync sind gegen den Test-Tenant verifiziert.

### AP 7 – Dokumentation und Release

- README auf Englisch: Zweck, Installation, Konfiguration, Beispiele für Client und Sync,
  Hinweise zu Logging und Datenschutz.
- `docs/betrieb.md` auf Deutsch:
  - API-User, Rechte und Token
  - Custom Attribute anlegen
  - Umgebungsvariablen
  - der erste Lauf als Dry-Run
  - den Report lesen
- Version über ein Git-Tag (hatch-vcs), die erste Version ist `v0.1.0`.
- Veröffentlichung auf PyPI (der Workflow liegt im Template, ist aber auskommentiert) oder nur
  intern, siehe K7.

**Meilenstein M4:** Release `v0.1.0`. Für den Produktivbetrieb müssen außerdem K1, K3 und K4
geklärt sein.

---

## 5. Reihenfolge und Meilensteine

```text
AP 0 --> AP 1 --+
                +--> AP 3 --> AP 4 (M1) --> AP 5 (M2) --+--> AP 7 (M4)
AP 0 --> AP 2 --+                |                      |
                                 +--> AP 6 (M3) --------+
                                      startet, sobald der Test-Tenant verfügbar ist
```

- Bis M2 ist kein Test-Tenant nötig.
- AP 6 kann parallel zu AP 5 beginnen, sobald der Zugang da ist. Die Prüfpunkte brauchen nur
  den Client aus AP 4.
- Nach jedem AP ist die CI grün. Die Umsetzung läuft auf diesem Branch, mit mindestens einem
  Commit je AP.

---

## 6. Offene Klärungen

| # | Frage | Klärung durch | Blockiert |
|---|---|---|---|
| K1 | Kosten User mit `NOT_ACTIVE` und ohne Lizenz etwas? | weclapp / Tenant-Admin | Produktivbetrieb, nicht die Entwicklung |
| K2 | Haben alle Mitarbeiter eine E-Mail-Adresse? Wenn nicht: Regel für Platzhalter festlegen | Fachbereich / HR | AP 5 nur teilweise, die Regel lässt sich später als Option nachrüsten |
| K3 | Verschickt `POST /user` automatisch Mails? | Test-Tenant (P2) | Produktivbetrieb |
| K4 | Gibt es in weclapp schon User oder Mitarbeiter, die beim Erstabgleich zugeordnet werden müssen? | Tenant-Admin | ersten Produktivlauf |
| K5 | Lässt sich der Nummernkreis für Mitarbeiter manuell befüllen? | weclapp-Support | nichts, wäre eine spätere Erweiterung |
| K6 | Zugang zum Test-Tenant | intern | AP 6 |
| K7 | Veröffentlichung auf PyPI oder nur intern? | Team | AP 7 |
| K8 | Wo und wie läuft der Sync-Job (Aufrufer, Zeitplan, Secret-Verwaltung)? | Team | Betrieb, nicht dieses Repo |

---

## 7. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Die Personalnummer lässt sich nicht als `employeeNumber` setzen | Custom Attribute am User, parallel K5 klären |
| weclapp ignoriert unbekannte Filter stillschweigend, eine Suche trifft dann den falschen Datensatz | Feldnamen vor dem Request prüfen, `find_one` mit Mehrdeutigkeits-Check, Sync auf vorab geladenem Bestand |
| Doppelte Anlage nach einem Timeout bei `POST` | `POST` bei unklarem Ausgang nicht wiederholen. Der idempotente Ablauf holt Fehlendes im nächsten Lauf nach |
| Geburtsdatum um einen Tag verschoben (Zeitzone) | Umrechnung an einer Stelle, Vergleich als `date`, Prüfpunkt P5 |
| Geburtsdaten vor 1970 scheitern unter Windows | Umrechnung per `timedelta`, eigener Testfall |
| Lizenzkosten für verwaltete User | K1 vor dem Go-live klären |
| weclapp ändert die API | tolerante Modelle, nur partielle Updates. Später optional ein automatischer Abgleich mit der aktuellen Spec |
| Personenbezogene Daten in Logs oder Fehlermeldungen | Logging-Regel, `SecretStr` für den Token, Test mit `caplog` |

---

## 8. Definition of Done (Phase 1)

- AP 0–7 abgeschlossen, CI grün, Coverage ≥ 80 % (Ziel für den Client-Kern: ≥ 90 %).
- `mypy --strict` ohne Ausnahmen für `src` und `unittests`.
- Prüfpunkte P1–P10 erledigt, die Ergebnisse in der Analyse nachgetragen.
- Ein Dry-Run gegen den Test-Tenant mit realistischem Datenumfang war erfolgreich, danach ein
  echter Lauf mit Testdaten.
- README und Betriebsdoku sind vollständig.

---

## 9. Ausblick nach Phase 1

- Weitere Felder, z. B. Eintritt und Austritt, Beschäftigungsstatus, geschäftliche
  Kontaktdaten: Modelle und Diff erweitern.
- Offboarding über `exitDate`, `employmentStatus = INACTIVE` und den User-Status bzw.
  `softDelete`.
- Ein Upsert für einzelne Datensätze, für ereignisgesteuerte Syncs. Bei Bedarf eine
  async-Variante des Clients.
- Ein automatischer Abgleich der Modelle mit der aktuellen weclapp-Spec als geplanter Workflow.
