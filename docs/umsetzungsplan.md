# Umsetzungsplan: weclapp-Client für die Mitarbeiter-Stammdaten-Sync

Stand: 30.09.2026 · Branch: `feature/weclapp-employee-sync` · Grundlage: [API-Analyse](weclapp_api_analyse.md)

> Dieses Repo liefert den **API-Client** als Python-Paket. Die **Sync-Logik** liegt in einem
> **eigenen Sync-Repo**, das dieses Paket als Abhängigkeit einbindet. Dazu gehören der
> Abgleich, der Diff, der Report und die Anbindung des Quellsystems.
>
> Der Plan deckt **Phase 1** ab: alles, was das Sync-Repo braucht, um Vorname, Nachname,
> Geburtsdatum und Personalnummer (= Mitarbeiternummer) nach weclapp zu schreiben.

**Stand der Umsetzung (30.09.2026):**

| AP | Status |
|---|---|
| AP 0–5 | ✅ umgesetzt (PR #3), M1 und M2 erreicht |
| AP 6 | 🟡 vorbereitet: Integrationstests in zwei Stufen ([integrationstests.md](integrationstests.md)), der Lauf wartet auf den Tenant (K1: [#8](https://github.com/Hochfrequenz/weclapp_client.py/issues/8), Lauf: [#9](https://github.com/Hochfrequenz/weclapp_client.py/issues/9)) |
| AP 7 | 🟡 README und Publish-Workflow fertig. Offen: PyPI-Setup und erstes Release ([#10](https://github.com/Hochfrequenz/weclapp_client.py/issues/10)), Einrichtungsdoku ([#11](https://github.com/Hochfrequenz/weclapp_client.py/issues/11)) |

Abweichungen vom ursprünglichen Plan:

- Die Version liest das Paket über `importlib.metadata`, eine generierte Versionsdatei gibt es nicht.
- Datumsfelder werden beim Lesen auf die nächste Mitternacht gerundet (siehe AP 2). Damit ist das Risiko aus P5
  weitgehend entschärft, P5 bleibt trotzdem ein Prüfpunkt.
- `get_by_key()` prüft den Typ des Custom Attributes nur, wenn `expected_type` übergeben wird.
- `Employee` enthält zusätzlich `employment_status` (nur lesend), als Vorbereitung für das Offboarding.
- **Vorabversion auf PyPI vor der Verifikation** (Entscheidung vom 07.10.2026): Mit dem Stand von AP 0–5 erscheint
  `v0.1.0a1` auf PyPI statt nur als Git-Tag ([#10](https://github.com/Hochfrequenz/weclapp_client.py/issues/10)). `v0.1.0` bleibt dem Stand nach den
  Integrationstests ([#9](https://github.com/Hochfrequenz/weclapp_client.py/issues/9)) vorbehalten. Die zweite Vorabversion `v0.1.0a2` entfällt, weil `a1` den Fake
  schon enthält.
- Offene Fragen und To-dos stehen als Issues im Repo ([#8](https://github.com/Hochfrequenz/weclapp_client.py/issues/8)–[#19](https://github.com/Hochfrequenz/weclapp_client.py/issues/19)), siehe Abschnitt 7.

---

## 1. Ziel und Abgrenzung

Ergebnis ist die Bibliothek `weclapp-client` (Import: `weclapp_client`) für die weclapp REST
API v2. Sie ist beschränkt auf die Endpunkte `/user`, `/employee`,
`/customAttributeDefinition` und `/user/currentUser`.

| Dieses Repo (Client) | Sync-Repo |
|---|---|
| HTTP-Anbindung: Auth, Timeouts, Retry, Fehler als Exceptions | Anbindung des Quellsystems |
| Typisierte Modelle für User, Employee und Custom Attributes | Eingabemodell für die Mitarbeiter-Datensätze |
| Lesen (mit Paging, Filtern, Feldauswahl), Anlegen, partielles Aktualisieren, Dry-Run | Abgleich über Personalnummer bzw. E-Mail, Diff, Entscheidung über Anlegen oder Aktualisieren |
| Hilfsfunktionen für die Personalnummer als Custom Attribute | Konfliktbehandlung, Report, Dry-Run-Modus des Syncs |
| In-Memory-Fake der Endpunkte, damit sich ohne Tenant testen lässt (auch im Sync-Repo) | Tests der Sync-Logik gegen den Fake |
| Prüfung des API-Verhaltens am Test-Tenant, dokumentiert in der Analyse | Betrieb: Zeitplan, Hosting, Secrets, Monitoring |
| Versionierte Releases | Einbindung einer festen Client-Version |

**Nicht im Client (Phase 1):** Löschen bzw. `softDelete`, Einladungen (`invite`), Rollen,
Lizenzen, Webhooks, weitere Felder. Braucht das Sync-Repo davon etwas, lässt es sich
nachrüsten (siehe Abschnitt 10).

---

## 2. Schnittstelle zum Sync-Repo

### 2.1 Einbindung

- Das Paket wird auf **PyPI** veröffentlicht (entschieden, K2), per Trusted Publishing. Der
  Workflow liegt im Template schon bereit, und das Repo ist ohnehin öffentlich. Das Sync-Repo
  bindet dann eine Version ein:

  ```toml
  # pyproject.toml im Sync-Repo
  dependencies = ["weclapp-client>=0.1,<0.2"]
  ```

- Vorabversionen liegen ebenfalls auf PyPI. pip und uv installieren sie nur, wenn die Versionsangabe selbst eine
  Vorabversion nennt. Dieselbe Angabe greift später automatisch die finale Version:

  ```toml
  dependencies = ["weclapp-client>=0.1.0a1,<0.2"]
  ```

- Alternativ geht eine Git-Abhängigkeit auf ein Tag, ohne Zugangsdaten, weil das Repo öffentlich ist:
  `weclapp-client @ git+https://github.com/Hochfrequenz/weclapp_client.py@v0.1.0a1`.

- **Versionierung:** SemVer über Git-Tags (hatch-vcs). Solange die Version bei `0.x` steht,
  darf auch eine Minor-Version Breaking Changes enthalten. Das Sync-Repo pinnt deshalb auf
  eine Minor-Version (`<0.2`). Was sich geändert hat, steht in den Release-Notes der
  GitHub-Releases.
- **Öffentliche API:** alles, was `weclapp_client`, `weclapp_client.models` und
  `weclapp_client.testing` über `__all__` exportieren. Module mit `_` sind intern.
  `py.typed` liegt bei, damit mypy im Sync-Repo die Typen sieht.
- **Abhängigkeiten:** zur Laufzeit nur `httpx` und `pydantic`, jeweils mit Untergrenze statt
  festem Pin, damit es im Sync-Repo keine Versionskonflikte gibt. Mindestversion ist
  Python 3.11.

### 2.2 Was das Sync-Repo vom Client bekommt

Das Sync-Repo gibt es noch nicht. Die Tabelle ist deshalb ein Vorschlag. Abgestimmt wird sie,
sobald das Sync-Repo angelegt ist (K3, [#12](https://github.com/Hochfrequenz/weclapp_client.py/issues/12)).

| Bedarf im Sync-Repo | Client-Funktion |
|---|---|
| Verbindung und Token prüfen | `client.users.current()` |
| Custom Attribute „Personalnummer“ auflösen | `client.custom_attribute_definitions.get_by_key("personalnummer")` |
| Bestand laden (alle User bzw. Employees, nur benötigte Felder) | `client.users.iterate(properties=[...])`, `client.employees.iterate(...)` |
| User über Personalnummer oder E-Mail finden | `client.users.find_one(Filter.custom_attribute_eq(definition.id, "00042"))` bzw. `Filter.eq("email", ...)` |
| Personalnummer am User lesen und setzen | `user.custom_attribute(definition.id)`, `CustomAttribute.of_string(definition.id, "00042")` |
| Personalakte zum User finden | `client.employees.for_user(user.id)` |
| Anlegen | `client.users.create(UserCreate(...))`, `client.employees.create(EmployeeCreate(...))` |
| Ändern mit Optimistic Locking | `client.users.update(user, UserUpdate(...))`, `client.employees.update(employee, EmployeeUpdate(...))` |
| Probelauf | `dry_run=True` bei `create` und `update` |
| Einzelfehler von systemischen Fehlern unterscheiden | Exception-Hierarchie (AP 1) |
| Tests ohne Tenant | `weclapp_client.testing.FakeWeclapp` (AP 5) |

### 2.3 Verhaltensgarantien (werden im README dokumentiert)

- **Ein `POST` wird bei unklarem Ausgang nicht wiederholt**, z. B. nach einem Lese-Timeout
  oder bei 502–504. Das Sync-Repo muss deshalb vor jedem Anlegen suchen. Dann erzeugt auch
  ein erneuter Lauf keine Duplikate.
- **Updates sind immer partiell** und nutzen die `version` des übergebenen Datensatzes. Bei
  einem Konflikt kommt ein `OptimisticLockError`, und das Sync-Repo liest neu und
  vergleicht erneut.
- **Custom Attributes:** Ein Update sendet nur die übergebenen Attribute. weclapp führt sie
  pro Attribut zusammen, andere Attribute des Users bleiben also erhalten (Prüfpunkt P7).
- **Filter werden vor dem Request geprüft**, und `find_one` wirft bei mehr als einem Treffer
  einen `AmbiguousResultError`. So führt ein Tippfehler nie dazu, dass stillschweigend der
  falsche Datensatz geändert wird.
- **Keine personenbezogenen Daten in den Logs** des Clients, nur IDs. Der Token erscheint
  weder in Logs noch in Exceptions.
- **Unbekannte Felder** in API-Antworten werden ignoriert. Erweiterungen der weclapp-API
  brechen den Client also nicht.

---

## 3. Technische Leitentscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| API-Version | v2 | aktuelle Version, v1 läuft aus |
| Python | ≥ 3.11, getestet mit 3.11–3.14 (CI-Matrix des Templates). Neue Versionen kommen nach ihrem Release in die Matrix, als Nächstes 3.15 (voraussichtlich Oktober 2026) | Das Sync-Repo läuft mit der jeweils neuesten Version (K3), das deckt die Matrix ab. Die Untergrenze 3.11 kostet im Code kaum etwas: Es fällt nur die Syntax ab 3.12 weg, also PEP-695-Generics und das `type`-Statement |
| HTTP | `httpx` mit synchronem Client | Timeouts und gzip eingebaut, Mocks über `httpx.MockTransport`. Ein Sync-Job braucht keine Parallelität, und weclapp rät ohnehin von Lastspitzen ab |
| Modelle | `pydantic` v2 mit mypy-Plugin, **getrennte Lese- und Schreibmodelle** | Lesemodelle garantieren `id` und `version`. Schreibmodelle enthalten nur beschreibbare Felder, read-only-Felder lassen sich damit gar nicht erst senden. Das Sync-Repo braucht so unter `mypy --strict` keine `None`-Prüfungen für IDs |
| Retry | eigene kleine Implementierung | nur wenige Zeilen, volle Kontrolle über die Idempotenz-Regeln (AP 1) |
| Tests | `pytest` mit `httpx.MockTransport` und dem eigenen Fake (AP 5) | keine zusätzliche Testbibliothek nötig |
| Typisierung | `mypy --strict` für `src` **und** `unittests` | so im Template vorgegeben |
| Sprache | Code, Docstrings und README auf Englisch, Fachdoku in `docs/` auf Deutsch | übliche Konvention im Python-Umfeld. codespell prüft `src` und `README.md` |
| Paketname | Distribution `weclapp-client`, Import `weclapp_client` | passt zum Repo, der Name ist auf PyPI frei (Stand 30.09.2026) |
| Veröffentlichung | PyPI, vorab Git-Tags | das Repo ist öffentlich, so ist die Einbindung ins Sync-Repo am einfachsten |
| Secrets | Token nur über die Konfiguration bzw. eine Umgebungsvariable, als `SecretStr` | erscheint nie in `repr`, Logs oder Exceptions |
| Logging | Standard-`logging`, Logger `weclapp_client` | keine Namen, Geburtsdaten oder E-Mails in Logs |
| Testdaten | nur synthetische Daten in Fixtures | das Repo ist öffentlich, also keine echten Namen, Tenant-Namen oder IDs |

---

## 4. Zielbild

### 4.1 Schichten

```text
Sync-Repo (eigenes Repo)       Quellsystem, Abgleich, Diff, Report
      |   nutzt nur die öffentliche API von weclapp_client
      v
weclapp_client.WeclappClient   Fassade: users, employees, custom_attribute_definitions
      v
Ressourcen + Modelle           generische Operationen, Lese- und Schreibmodelle, Filter
      v
HTTP-Transport                 Auth, Header, Timeouts, Retry, Fehler -> Exceptions
      v
weclapp REST API v2            in Tests ersetzt durch weclapp_client.testing.FakeWeclapp
```

### 4.2 Paketstruktur

```text
src/weclapp_client/
├── __init__.py                 # öffentliche API: WeclappClient, WeclappConfig, Filter, Exceptions
├── py.typed
├── config.py                   # WeclappConfig (inkl. from_env)
├── exceptions.py               # Exception-Hierarchie
├── _http.py                    # Transport: Header, Auth, Timeouts, Retry, Fehler-Mapping
├── _converters.py              # ms-Timestamps <-> date/datetime
├── query.py                    # Filter, Sortierung, Feldauswahl
├── client.py                   # WeclappClient (Kontextmanager)
├── testing.py                  # FakeWeclapp: In-Memory-Fake für eigene Tests und das Sync-Repo
├── models/
│   ├── base.py                 # Basisklassen: Aliase, Payload-Serialisierung
│   ├── user.py                 # User, UserCreate, UserUpdate, UserStatus
│   ├── employee.py             # Employee, EmployeeCreate, EmployeeUpdate, EmploymentStatus
│   └── custom_attribute.py     # CustomAttribute, CustomAttributeDefinition
└── resources/
    ├── base.py                 # Resource: iterate, list, count, get, find_one, create, update
    ├── users.py
    ├── employees.py
    └── custom_attribute_definitions.py
unittests/
├── conftest.py                 # Client mit MockTransport bzw. FakeWeclapp
├── fixtures/                   # Beispiel-Responses mit synthetischen Daten
├── test_http.py, test_query.py, test_models.py, test_resources.py, test_testing.py
└── integration/                # Marker "integration" bzw. "integration_write", nur mit WECLAPP_*-Variablen
```

### 4.3 Nutzung im Sync-Repo (Beispiel)

```python
from datetime import date

from weclapp_client import Filter, WeclappClient, WeclappConfig
from weclapp_client.models import CustomAttribute, EmployeeCreate, UserCreate, UserStatus

with WeclappClient(WeclappConfig.from_env()) as client:  # WECLAPP_BASE_URL, WECLAPP_API_TOKEN
    definition = client.custom_attribute_definitions.get_by_key("personalnummer")
    user = client.users.find_one(Filter.custom_attribute_eq(definition.id, "00042"))
    if user is None:
        user = client.users.create(
            UserCreate(
                email="erika.musterfrau@example.com",
                first_name="Erika",
                last_name="Musterfrau",
                status=UserStatus.NOT_ACTIVE,
                can_edit_dashboard=False,
                custom_attributes=[CustomAttribute.of_string(definition.id, "00042")],
            )
        )
    if client.employees.for_user(user.id) is None:
        client.employees.create(EmployeeCreate(user_id=user.id, birth_date=date(1985, 4, 12)))
```

Die eigentliche Logik setzt das Sync-Repo um: Bestand vorab laden, Diff bilden, Konflikte
erkennen, Report erstellen. Einen Vorschlag für den Ablauf enthält die
[Analyse](weclapp_api_analyse.md) in Abschnitt 5.

Tests im Sync-Repo laufen gegen den Fake:

```python
from weclapp_client.testing import FakeWeclapp


def test_new_employee_is_created() -> None:
    fake = FakeWeclapp()
    fake.add_custom_attribute_definition(attribute_key="personalnummer", attribute_type="STRING")
    with fake.client() as client:
        run_sync(client, records)  # Logik aus dem Sync-Repo
    assert [user.last_name for user in fake.users] == ["Musterfrau"]
```

---

## 5. Arbeitspakete

| AP | Inhalt | Ergebnis | Abhängig von | Test-Tenant nötig | Aufwand (Richtwert, PT = Personentage) |
|---|---|---|---|---|---|
| 0 | Projekt-Setup | Template zu `weclapp_client` umgebaut, CI grün | – | nein | S · 0,5 PT |
| 1 | HTTP-Transport, Konfiguration, Fehler | `_http.py`, `config.py`, `exceptions.py` | AP 0 | nein | M · 1–1,5 PT |
| 2 | Modelle und Konvertierung | `models/`, `_converters.py` | AP 0 | nein | M · 1 PT |
| 3 | Abfragen und generische Ressource | `query.py`, `resources/base.py` | AP 1, AP 2 | nein | M · 1 PT |
| 4 | Konkrete Ressourcen und Client-Fassade | `resources/*`, `client.py` → **M1** | AP 3 | nein | S · 0,5–1 PT |
| 5 | Test-Unterstützung `weclapp_client.testing` | `FakeWeclapp` → **M2** | AP 4 | nein | M · 1–1,5 PT |
| 6 | Verifikation mit dem Test-Tenant | Prüfpunkte erledigt, Integrationstests, Fake angeglichen → **M3** | AP 4 (für den Fake: AP 5) | **ja** | M · 1 PT plus Wartezeit |
| 7 | Dokumentation und Release | README mit Verhaltensgarantien, `v0.1.0a1` und später `v0.1.0` auf PyPI → **M4** | AP 5, für `v0.1.0` AP 6 | nein | S · 0,5–1 PT |

Summe: ca. 6,5–8,5 PT, Wartezeiten nicht eingerechnet.

### AP 0 – Projekt-Setup

- Paket umbenennen: `src/mypackage` → `src/weclapp_client`, Beispielklasse und Beispieltest
  entfernen. Ein Smoke-Test (Import und Version) sorgt dafür, dass Unittests und Coverage
  weiterhin etwas messen.
- `pyproject.toml`:
  - `name = "weclapp-client"`, Beschreibung, Autoren und Keywords setzen, URLs auf
    `Hochfrequenz/weclapp_client.py` umstellen.
  - Laufzeit-Abhängigkeiten `httpx` und `pydantic` mit Untergrenze (siehe 2.1).
  - Die Version kommt weiter aus den Git-Tags (hatch-vcs), zur Laufzeit liest das Paket sie
    über `importlib.metadata`. Die generierte Versionsdatei des Templates entfällt samt
    `.gitignore`-Eintrag.
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
  | 502 / 503 / 504 oder Lese-Timeout | wiederholen | **nicht wiederholen**, weil der Datensatz schon angelegt sein könnte. Der Aufrufer sucht vor dem Anlegen (Garantie aus 2.3) |

  PUT ist idempotent. War der erste Versuch schon erfolgreich, scheitert die Wiederholung
  höchstens am Optimistic Locking (409). Der Aufrufer liest dann neu.
- Die Response-Header `X-Weclapp-Wait-Ms` und `X-Weclapp-Wait-Reason` loggen: auf DEBUG, ab
  einer Schwelle auf WARNING.
- Fehler-Mapping: weclapp liefert JSON nach RFC 7807 (`type`, `title`, `status`, `detail`,
  `instance` sowie `validationErrors[]` mit `location`, `errorCode` und `allowed`), teils aber
  auch `text/plain`. Der Fehlertyp ist der Teil von `type` nach dem letzten `/`. Die Spalte
  „Art“ ist eine Empfehlung an das Sync-Repo, welche Fehler den ganzen Lauf abbrechen sollten
  und welche nur einen Datensatz betreffen.

  | Exception | Auslöser | Art |
  |---|---|---|
  | `WeclappError` | Basisklasse aller Fehler | – |
  | `WeclappConnectionError` | Netzwerkfehler oder Timeout nach allen Retries | systemisch |
  | `WeclappApiError` | Basis für HTTP-Fehler, enthält Status, Fehlertyp, `detail` und die Validierungsfehler | – |
  | ├ `AuthenticationError` | 401 | systemisch |
  | ├ `PermissionDeniedError` | 403 | systemisch |
  | ├ `NotFoundError` | 404 | datensatzbezogen |
  | ├ `WeclappValidationError` | 400 `validation` (der Name vermeidet eine Verwechslung mit `pydantic.ValidationError`) | datensatzbezogen |
  | ├ `OptimisticLockError` | 409 `optimistic_lock` | datensatzbezogen |
  | ├ `ConflictError` | andere 409er (`context`, `persistence`) | datensatzbezogen |
  | ├ `RateLimitError` | 429 nach allen Retries | systemisch |
  | └ `ServerError` | 5xx | systemisch |

- **Tests:**
  - Header und URL-Aufbau
  - jedes Fehler-Mapping (mit Beispiel-JSON aus der Doku) und `text/plain`-Fehler
  - 429 mit anschließendem Erfolg, 429 bis zum Retry-Limit
  - POST ohne Retry bei Lese-Timeout, GET mit Retry
  - Token taucht weder in `repr` noch in Exceptions auf

### AP 2 – Modelle und Konvertierung

- Basisklassen: camelCase-Aliase (`first_name` ↔ `firstName`). Unbekannte Felder in Antworten
  werden ignoriert.
- **Lesemodelle** (`User`, `Employee`, `CustomAttributeDefinition`): `id` und `version` sind
  garantiert. Alle übrigen Felder sind optional, weil weclapp `null`-Felder weglässt.
- **Schreibmodelle:**
  - `…Create`: Die Pflichtfelder laut Spec sind auch im Modell Pflicht (P1 bestätigt sie).
    Read-only-Felder gibt es dort nicht.
  - `…Update`: Alle Felder sind optional. Gesendet werden nur explizit gesetzte Felder, ein
    explizites `None` leert das Feld.
  - Außer `customAttributes` enthalten Update-Modelle keine Listen, denn fehlende
    Listeneinträge würde weclapp löschen.

  | Modell | Felder |
  |---|---|
  | `User` | `id`, `version`, `created_date`, `last_modified_date`, `username`, `email`, `first_name`, `last_name`, `status`, `can_edit_dashboard`, `custom_attributes`, dazu die Hilfsmethode `custom_attribute(definition_id)` |
  | `UserCreate` | `email`, `status`, `can_edit_dashboard` (alle drei Pflicht laut Spec), `first_name`, `last_name`, `custom_attributes` |
  | `UserUpdate` | `email`, `first_name`, `last_name`, `status`, `custom_attributes` |
  | `Employee` | `id`, `version`, `created_date`, `last_modified_date`, `employee_number`, `user_id`, `birth_date` |
  | `EmployeeCreate` | `user_id` (Pflicht laut Spec), `birth_date` |
  | `EmployeeUpdate` | `birth_date` |
  | `CustomAttribute` | `attribute_definition_id`, `string_value`, dazu die Fabrikmethode `of_string(definition_id, value)` |
  | `CustomAttributeDefinition` | `id`, `version`, `attribute_key`, `attribute_type`, `label`, `active`, `attribute_entity_type`, `entities` |

- Enums: `UserStatus` (`ACTIVE`, `DEPARTURE`, `NOT_ACTIVE`) und, als Vorbereitung für später,
  `EmploymentStatus` (`ACTIVE`, `INACTIVE`, `LEAVE_OF_ABSENCE`, `ONBOARDING`). Unbekannte
  Werte führen beim Lesen nicht zum Absturz.
- `_converters.py` rechnet zwischen ms seit Epoch und `datetime` bzw. `date` um:
  - Die Umrechnung läuft über `epoch + timedelta(milliseconds=…)` statt über
    `datetime.fromtimestamp()`. **Geburtsdaten vor 1970 ergeben negative Timestamps**, und die
    kann `fromtimestamp()` unter Windows nicht verarbeiten.
  - Die Zeitzonen-Konvention für reine Datumsfelder wie `birth_date` steht an genau einer
    Stelle. Geschrieben wird Mitternacht UTC. Beim Lesen wird auf die nächste Mitternacht
    gerundet, damit auch Werte richtig gelesen werden, die weclapp als Mitternacht deutscher
    Zeit speichert (22:00 bzw. 23:00 UTC am Vortag). Prüfpunkt P5 bestätigt das.
- **Tests:**
  - Parsen von Beispiel-JSON, abgeleitet aus der Spec
  - Create-Modelle ohne Pflichtfelder schlagen fehl
  - Update-Modelle senden nur die gesetzten Felder
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
  - `properties` (Feldauswahl) und `sort` werden ebenso geprüft. Bei einer Feldauswahl werden
    `id` und `version` automatisch mitgeladen, weil die Lesemodelle sie brauchen.
    Standard-Sortierung ist `id`, damit das Paging stabil bleibt.
- `Resource` ist generisch über Lese-, Create- und Update-Modell (per `typing.Generic`, wegen
  Python 3.11):

  | Methode | Verhalten |
  |---|---|
  | `iterate(*filters, properties=None, sort="id", page_size=1000)` | Iterator über alle Seiten, endet bei einer Seite mit weniger als `page_size` Einträgen |
  | `list(...)` | wie `iterate`, aber als Liste |
  | `count(*filters)` | `GET /<ressource>/count` |
  | `get(id)` | Einzelabruf, `NotFoundError`, wenn der Datensatz fehlt |
  | `find_one(*filters)` | `None` bei 0 Treffern, **`AmbiguousResultError` bei mehr als einem Treffer** |
  | `create(data, *, dry_run=False)` | `POST`, liefert den gespeicherten Datensatz. Mit `dry_run=True` kommt `None` zurück, weil weclapp dann keine IDs liefert (per `typing.overload` typisiert) |
  | `update(current, changes, *, dry_run=False)` | partielles `PUT` mit `ignoreMissingProperties=true`. `id` und `version` stammen aus `current`, damit Optimistic Locking der Normalfall ist |

  Ein `delete` gibt es in Phase 1 nicht.
- **Tests:**
  - Paging mit 0, 1, genau 1000 und 2500 Datensätzen
  - Filter-Serialisierung, ungültige Filter- und Feldnamen
  - `find_one` mit 0, 1 und 2 Treffern
  - `update` sendet `ignoreMissingProperties` und `version`
  - `create` mit Antwort 201, Dry-Run

### AP 4 – Konkrete Ressourcen und Client-Fassade

- `client.users` (`/user`): die Operationen aus AP 3 plus `current()` (`/user/currentUser`).
- `client.employees` (`/employee`): die Operationen aus AP 3 plus `for_user(user_id)`.
- `client.custom_attribute_definitions` (`/customAttributeDefinition`): `get_by_key(key)`
  lädt die Definitionen einmal (mit Cache) und sucht lokal nach dem Key. Fehlt das Attribut
  oder ist es nicht vom Typ `STRING`, gibt es einen Fehler.
- `WeclappClient(config, *, http_client=None)`: Kontextmanager. Für Tests lässt sich ein
  eigener `httpx.Client` übergeben.
- **Tests:** Pfade und Parameter jeder Ressource, Smoke-Test der öffentlichen API (die
  Importe aus Abschnitt 2.2).
- Vorabversion `v0.1.0a1` veröffentlichen, auf PyPI statt nur als Git-Tag ([#10](https://github.com/Hochfrequenz/weclapp_client.py/issues/10)), zusammen mit AP 5.

**Meilenstein M1:** Der Client-Kern ist fertig, gegen Mocks getestet und für das Sync-Repo
einbindbar.

### AP 5 – Test-Unterstützung `weclapp_client.testing`

Warum im Paket und nicht nur in `unittests/`? So kann das Sync-Repo seine Logik ohne Tenant
testen, ohne das Verhalten der API selbst nachbauen zu müssen. Der Fake braucht nur `httpx`,
das ohnehin eine Abhängigkeit ist.

- `FakeWeclapp` ist ein In-Memory-weclapp für `/user`, `/employee`,
  `/customAttributeDefinition` und `/user/currentUser`, umgesetzt als `httpx.MockTransport`.
  `fake.client()` liefert einen fertig konfigurierten `WeclappClient`.
- Das Verhalten folgt der echten API, so wie Analyse und AP 6 sie beschreiben:
  - Er vergibt IDs, `version` (steigt mit jeder Änderung), `createdDate` und
    `lastModifiedDate`, außerdem `username` und `employeeNumber`, wie das System es tut.
  - Er versteht die Filter, die der Client nutzt (`eq`, `in`, `customAttribute<id>-eq`, …),
    sowie `properties`, `sort` und Paging.
  - Partielle Updates führen `customAttributes` pro Attribut zusammen. Stimmt die `version`
    nicht, antwortet er mit 409 `optimistic_lock`.
  - Er validiert: fehlende Pflichtfelder (P1) und mitgeschickte read-only-Felder führen zu
    400, doppelte E-Mail-Adressen werden abgewiesen (P4).
  - Mit `dryRun` validiert er, ohne zu speichern. Die Antwort enthält dann keine
    Meta-Felder.
- Testhilfen:
  - Daten vorbelegen: `add_user`, `add_employee`, `add_custom_attribute_definition`
  - Bestand einsehen: `fake.users`, `fake.employees`
  - Request-Protokoll, z. B. um zu prüfen, dass ein Lauf keine Schreibzugriffe erzeugt hat
  - Fehler einspielen, z. B. „der nächste Request antwortet mit 429, 503 oder läuft in einen
    Timeout“
- **Tests:** Die Ressourcen-Tests des Clients laufen zusätzlich gegen den Fake. Der Fake
  bekommt außerdem eigene Tests.
- ~~Vorabversion `v0.1.0a2` taggen~~: entfällt, `v0.1.0a1` enthält den Fake bereits.

**Meilenstein M2:** Das Sync-Repo kann seine Logik ohne Tenant testen.

### AP 6 – Verifikation mit dem Test-Tenant

Voraussetzung ist der Zugang zum Test-Tenant (K1). Dort wird eingerichtet:

- ein technischer API-User mit Token
- ein Custom Attribute „Personalnummer“ (Typ `STRING`, Entität `user`, Key z. B.
  `personalnummer`)

Welche Art von Tenant es wird, ist noch offen (K1). Die Integrationstests sind deshalb in zwei Stufen aufgeteilt
und funktionieren für beide Varianten (Anleitung: [integrationstests.md](integrationstests.md)):

| Stufe | Marker | Inhalt | Test-Tenant | Produktiv-Tenant |
|---|---|---|---|---|
| 1 | `integration` | nur Lesezugriffe und Dry-Runs | ✅ | ✅ |
| 2 | `integration_write` | legt markierte Testdatensätze an, ändert sie und räumt auf, nur mit `WECLAPP_ALLOW_WRITES=1` | ✅ | nur nach Absprache: verbraucht Mitarbeiternummern, User bleiben nach `softDelete` als Rest, eventuell gehen Mails raus (P2) |

Mit dem Produktiv-Tenant allein bleiben P2, P3 und die `username`-Vergabe (P4) offen, bis ein abgestimmter
Schreibtest läuft. Die übrigen Prüfpunkte deckt Stufe 1 ab.

Prüfpunkte (die ⚠-Punkte aus der Analyse):

| # | Prüfung | Vorgehen | Wirkt auf |
|---|---|---|---|
| P1 | Pflichtfelder bei `POST /user` und `POST /employee` | minimale Payloads mit `dryRun=true` | Create-Modelle, Fake |
| P2 | User mit `NOT_ACTIVE` anlegbar, keine automatische Mail bei `POST /user` | Test-User mit eigener Test-Postfach-Adresse | Doku für das Sync-Repo (S3) |
| P3 | Personalakte für einen `NOT_ACTIVE`-User anlegbar und nutzbar | `POST /employee`, danach Ansicht in der Oberfläche | Doku für das Sync-Repo |
| P4 | Vergabe von `username`, Eindeutigkeit von `email` (auch bei Groß-/Kleinschreibung) | zweiten User mit derselben E-Mail anlegen | Fake, Doku für das Sync-Repo |
| P5 | Zeitzone von `birthDate` | Datum in der Oberfläche erfassen und per API lesen, und umgekehrt | `_converters.py` |
| P6 | Filter `customAttribute<id>-eq` am User, `properties=customAttributes` | `GET /user` | Filter, Feldauswahl |
| P7 | `ignoreMissingProperties` bei `PUT /user` und `PUT /employee`, dazu das Zusammenführen der `customAttributes`. Der Parameter ist nur allgemein dokumentiert und an diesen beiden Endpunkten in der Spec nicht deklariert | partielle Updates | `update()`, Fake |
| P8 | `sort=id` und `pageSize=1000` bei `/user` und `/employee` | `GET` | Paging |
| P9 | minimale Rechte des API-Users | Rolle schrittweise einschränken | Einrichtungsdoku |
| P10 | Format echter Fehlerantworten (400, 403, 404, 409) | Fehler gezielt provozieren | Fehler-Mapping, Fake |
| P11 | Kann ein User mehrere Personalakten haben? (Der Fake nimmt an: nein) | zweiten `POST /employee` für denselben User | Fake, Doku für das Sync-Repo |

- Die Integrationstests liegen in `unittests/integration/`. Sie laufen nur, wenn
  `WECLAPP_API_TOKEN` und `WECLAPP_BASE_URL` bzw. `WECLAPP_TENANT` gesetzt sind, also nicht in der CI.
- Stufe 2 legt nur markierte Testdatensätze an (Nachname `ZZ-Test weclapp-client`) und räumt sie
  danach auf: `DELETE /employee/id/{id}` und `POST /user/id/{id}/softDelete`. Beides läuft über
  Test-Helfer, nicht über die öffentliche API.
- Am Ende gibt pytest eine Zusammenfassung aus: Befunde je Prüfpunkt, noch manuell zu Prüfendes
  (z. B. Mails, Anzeige in der Oberfläche) und den Stand des Aufräumens. Personenbezogene Daten
  enthält sie nicht.
- **Keine echten Daten ins Repo**, denn es ist öffentlich. Antworten aus dem Tenant werden
  nicht als Fixtures übernommen, auch nicht anonymisiert. Die Fixtures bleiben synthetisch.
- Die Ergebnisse werden in der Analyse nachgetragen und sind damit auch die Grundlage für das
  Sync-Repo. Der Fake wird an das echte Verhalten angeglichen.

**Meilenstein M3:** Das API-Verhalten ist verifiziert und dokumentiert, und der Fake
entspricht ihm.

### AP 7 – Dokumentation und Release

- README auf Englisch:
  - Zweck, Installation (PyPI bzw. Git-Tag), Konfiguration, Beispiele
  - **Verhaltensgarantien** (Abschnitt 2.3) und die Exceptions mit ihrer Art
  - Testen mit `FakeWeclapp`
  - Hinweise zu Logging und Datenschutz
- `docs/einrichtung_weclapp.md` auf Deutsch: API-User und minimale Rechte (P9), Token,
  Custom Attribute anlegen. Das Sync-Repo verweist darauf.
- Release-Prozess:
  - Workflow `python-publish.yml` aktivieren (erledigt)
  - Trusted Publishing auf PyPI und das GitHub-Environment `release` einrichten (K2, [#10](https://github.com/Hochfrequenz/weclapp_client.py/issues/10))
  - prüfen, ob die neueste Python-Version in der CI-Matrix ist ([#13](https://github.com/Hochfrequenz/weclapp_client.py/issues/13))
  - Vorabversion `v0.1.0a1` mit dem Stand von AP 0–5 veröffentlichen (GitHub-Release als „pre-release“)
  - nach den Integrationstests: Tag `v0.1.0` setzen, GitHub-Release erstellen, das Paket landet auf PyPI
- Das Sync-Repo bindet danach die PyPI-Version ein.

**Meilenstein M4:** `v0.1.0` liegt auf PyPI.

---

## 6. Reihenfolge und Meilensteine

```text
AP 0 --> AP 1 --+
                +--> AP 3 --> AP 4 (M1) --> AP 5 (M2) --+--> AP 7 (M4)
AP 0 --> AP 2 --+                 |                     |
                                  +--> AP 6 (M3) -------+
                                       startet, sobald der Test-Tenant verfügbar ist
```

| Meilenstein | Inhalt | Nutzen für das Sync-Repo |
|---|---|---|
| M1 | Client-Kern (AP 0–4) | kann mit der Integration beginnen |
| M2 | Fake (AP 5) | kann seine Logik ohne Tenant testen |
| M3 | Verifikation am Test-Tenant (AP 6) | kann sich auf dokumentiertes API-Verhalten verlassen |
| M4 | Release `v0.1.0` auf PyPI (AP 7), vorab schon `v0.1.0a1` | hat mit `a1` sofort eine installierbare Version, mit `v0.1.0` eine verifizierte für den Produktivbetrieb |

- Bis M2 ist kein Test-Tenant nötig.
- AP 6 kann parallel zu AP 5 beginnen, sobald der Zugang da ist.
- Nach jedem AP ist die CI grün. Die Umsetzung läuft auf diesem Branch, mit mindestens einem
  Commit je AP.

---

## 7. Klärungen

### 7.1 Klärungen für dieses Repo (Stand 07.10.2026)

| # | Thema | Stand | Noch zu tun | Blockiert | Issue |
|---|---|---|---|---|---|
| K1 | Test-Tenant | Der Zugang wird organisiert. Ob es ein eigener Test-Tenant oder der Produktiv-Tenant wird, ist noch unklar | Art des Tenants festlegen. Die Einschränkungen für den Produktiv-Tenant stehen in AP 6 | AP 6 | [#8](https://github.com/Hochfrequenz/weclapp_client.py/issues/8) |
| K2 | Bereitstellung des Pakets | **entschieden: PyPI.** Zuerst erscheint die Vorabversion `v0.1.0a1` mit dem aktuellen Stand, `v0.1.0` nach den Integrationstests. Der Publish-Workflow ist aktiviert | Jemand mit Admin-Rechten richtet Trusted Publishing auf PyPI und das GitHub-Environment `release` ein | AP 7 | [#10](https://github.com/Hochfrequenz/weclapp_client.py/issues/10) |
| K3 | Sync-Repo | **geklärt:** Das Sync-Repo wird neu angelegt und läuft mit der neuesten Python-Version. Die Untergrenze 3.11 bleibt, neue Versionen kommen in die CI-Matrix | Schnittstelle (Abschnitt 2.2) abstimmen, sobald das Sync-Repo startet | nichts | [#12](https://github.com/Hochfrequenz/weclapp_client.py/issues/12) |

### 7.2 Übergabe an das Sync-Repo

Diese Punkte stammen aus der Analyse. Sie betreffen die Sync-Logik oder den Betrieb, **nicht
den Client**, denn der Client unterstützt jedes mögliche Ergebnis. Sie stehen nur hier, damit
sie beim Start des Sync-Repos nicht verloren gehen.

| # | Frage | Hinweis | Issue |
|---|---|---|---|
| S1 | Kosten User mit `NOT_ACTIVE` und ohne Lizenz etwas? | Vor dem Go-live klären. Kostet jedes Konto etwas, ist das Vorgehen „ein User pro Mitarbeiter“ zu überdenken | [#14](https://github.com/Hochfrequenz/weclapp_client.py/issues/14) |
| S2 | Haben alle Mitarbeiter eine E-Mail-Adresse? Wenn nicht: Regel für Platzhalter festlegen | `email` ist beim Anlegen eines Users Pflicht | [#15](https://github.com/Hochfrequenz/weclapp_client.py/issues/15) |
| S3 | Verschickt `POST /user` automatisch Mails? | Das API-Verhalten prüft der Client in AP 6 (P2), die Konsequenz zieht das Sync-Repo | [#16](https://github.com/Hochfrequenz/weclapp_client.py/issues/16) |
| S4 | Gibt es in weclapp schon User oder Mitarbeiter, die beim Erstabgleich zugeordnet werden müssen? | betrifft den ersten Produktivlauf | [#17](https://github.com/Hochfrequenz/weclapp_client.py/issues/17) |
| S5 | Lässt sich der Nummernkreis für Mitarbeiter manuell befüllen? (weclapp-Support) | Einzige Stelle, die den Client berühren könnte: Wird `employeeNumber` per API beschreibbar, bekommt `EmployeeCreate` das Feld. Bis dahin trägt das Custom Attribute die Personalnummer | [#18](https://github.com/Hochfrequenz/weclapp_client.py/issues/18) |
| S6 | Betrieb des Sync-Jobs: Zeitplan, Hosting, Secrets | – | [#19](https://github.com/Hochfrequenz/weclapp_client.py/issues/19) |

---

## 8. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Breaking Changes im Client brechen das Sync-Repo | SemVer, klar definierte öffentliche API, Release-Notes. Das Sync-Repo pinnt auf eine Minor-Version |
| Versionskonflikte der Abhängigkeiten im Sync-Repo | nur zwei Laufzeit-Abhängigkeiten, Untergrenzen statt Pins, CI-Matrix 3.11–3.14 |
| Der Fake weicht vom echten API-Verhalten ab, die Tests im Sync-Repo wiegen dann in falscher Sicherheit | Fake nach AP 6 angleichen. Dieselben Szenarien laufen gegen den Fake und als Integrationstest gegen den Tenant |
| weclapp ignoriert unbekannte Filter stillschweigend | Feldnamen vor dem Request prüfen, `find_one` mit Mehrdeutigkeits-Check |
| Doppelte Anlage nach einem Timeout bei `POST` | kein Retry bei unklarem Ausgang. Dokumentierte Garantie: Das Sync-Repo sucht vor dem Anlegen |
| Geburtsdatum um einen Tag verschoben (Zeitzone) | Umrechnung an einer Stelle, Prüfpunkt P5 |
| Geburtsdaten vor 1970 scheitern unter Windows | Umrechnung per `timedelta`, eigener Testfall |
| weclapp ändert die API | tolerante Lesemodelle, nur partielle Updates. Später optional ein automatischer Abgleich mit der aktuellen Spec |
| Echte Daten gelangen ins öffentliche Repo | nur synthetische Fixtures. Tenant-URL und Token nur über Umgebungsvariablen |
| Es steht nur der Produktiv-Tenant zur Verfügung (K1) | dort nur lesende Tests und Dry-Runs. Schreibtests nur nach Absprache (AP 6) |
| Personenbezogene Daten in Logs oder Fehlermeldungen | Logging-Regel, `SecretStr` für den Token, Test mit `caplog` |

---

## 9. Definition of Done (Phase 1)

- AP 0–7 abgeschlossen, CI grün, Coverage ≥ 80 % (Ziel: ≥ 90 %).
- `mypy --strict` ohne Ausnahmen für `src` und `unittests`.
- Prüfpunkte P1–P11 erledigt, die Ergebnisse in der Analyse nachgetragen, der Fake
  angeglichen.
- Öffentliche API und Verhaltensgarantien sind im README dokumentiert.
- `v0.1.0` liegt auf PyPI. Das Sync-Repo kann das Paket installieren und seine Logik gegen den
  Fake testen.

---

## 10. Ausblick nach Phase 1

- Weitere Felder in den Modellen, sobald das Sync-Repo sie braucht, z. B. Eintritt und
  Austritt, Beschäftigungsstatus, geschäftliche Kontaktdaten.
- Weitere Operationen bei Bedarf: `softDelete` für User und `DELETE` für Employees (für das
  Offboarding), `invite`.
- Eine async-Variante des Clients.
- Ein automatischer Abgleich der Modelle mit der aktuellen weclapp-Spec als geplanter Workflow.
