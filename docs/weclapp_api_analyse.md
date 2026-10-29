# Analyse der weclapp REST API für die Synchronisation von Mitarbeiter-Stammdaten

Stand: 30.09.2026 · Grundlage: offizielle OpenAPI-Specs
[`openapi_v1.yaml`](https://www.weclapp.com/api/openapi_v1.yaml) und
[`openapi_v2.yaml`](https://www.weclapp.com/api/openapi_v2.yaml)
(v1: 732 Pfade, v2: 712 Pfade), Doku unter <https://www.weclapp.com/api/>.

> Diese Analyse stützt sich zunächst allein auf die öffentliche Spezifikation, inklusive der
> weclapp-eigenen Metadaten `x-weclapp` (z. B. `required`, `entity`). Punkte, die wir erst
> an einem Tenant prüfen können, sind mit **⚠ verifizieren** markiert.
>
> **Nachtrag 29.10.2026:** Stufe 1 der Integrationstests (nur Lesezugriffe und Dry-Runs) ist
> gegen den Produktiv-Tenant gelaufen. Die Befunde stehen in [Abschnitt 10](#10-befunde-aus-dem-tenant-ap-6),
> die geklärten ⚠-Punkte sind mit ✅ markiert.

---

## 1. Anforderungen (Stand der Abstimmung)

| # | Thema | Entscheidung |
|---|---|---|
| A1 | Richtung | **Nur schreibend nach weclapp.** Das Quellsystem führt, weclapp ist das Ziel. |
| A2 | Feldumfang (Phase 1) | **Name, Geburtsdatum, Mitarbeiternummer.** Weitere Felder ggf. später. |
| A3 | Neue Mitarbeiter | Werden in weclapp **angelegt**. Sie arbeiten **nicht selbst** mit weclapp, sondern werden dort nur verwaltet. **Klärungsbedarf, siehe Abschnitt 3.** |
| A4 | Test-Tenant | Es gibt nur den Produktiv-Tenant. Lesen und Dry-Runs sind frei, Anlegen nur abgestimmt (Abschnitt 10). |
| A5 | Aufteilung | Die Sync-Logik liegt in einem **eigenen Sync-Repo**. Dieses Repo liefert nur den API-Client als Paket, das dort als Abhängigkeit eingebunden wird. |

---

## 2. Zusammenfassung

- In weclapp sind Mitarbeiterdaten auf **zwei Ressourcen** verteilt:
  - **`user`** ist das Konto mit Vor- und Nachname, E-Mail und Status.
  - **`employee`** ist die HR-Personalakte mit Geburtsdatum, Personalnummer und weiteren
    Personaldaten.
- Für unsere drei Felder bedeutet das:

  | Fachliches Feld | weclapp-Feld | Beschreibbar? |
  |---|---|---|
  | Vorname / Nachname | `user.firstName` / `user.lastName` (max. 50 Zeichen) | ✅ ja |
  | Geburtsdatum | `employee.birthDate` (ms seit Epoch) | ✅ ja |
  | Mitarbeiternummer | `employee.employeeNumber` | ❌ **read-only**, weclapp vergibt sie selbst |

- **Jeder `employee` braucht einen `user`.** `employee.userId` ist laut Spec Pflicht. Auch
  Mitarbeiter, die nicht mit weclapp arbeiten, brauchen daher ein User-Konto (siehe 3.1).
- **Die Mitarbeiternummer lässt sich nicht per API setzen.** Laut Doku führt das Senden
  read-only-Felder sogar zu HTTP 400. Lösungsweg siehe 3.2.
- Wir verwenden **API v2**. Die Schemas von `employee` und `user` sind in v1 und v2 gleich,
  aber v1 läuft aus.

---

## 3. Kritische Punkte und Klärungsbedarf

### 3.1 Mitarbeiter ohne weclapp-Nutzung brauchen trotzdem ein User-Konto (zu A3)

Laut Spec (`x-weclapp.required`):

| Ressource | Pflichtfelder beim Anlegen |
|---|---|
| `employee` | `userId` (die `employeeNumber` ist ebenfalls Pflicht, wird aber vom System vergeben) |
| `user` | `email`, `status`, `canEditDashboard` (`username` ist Pflicht, aber read-only, also vom System vergeben) |

Für „nur verwaltete“ Mitarbeiter heißt das:

- Wir legen einen `user` mit **`status = NOT_ACTIVE`** an, ohne `licenses`, ohne
  `userRoles` und mit `canEditDashboard = false`. Danach legen wir den `employee` mit
  diesem `userId` an.
- Den Endpunkt **`/user/id/{id}/invite` rufen wir nicht auf**, damit keine Einladungs-Mail
  rausgeht.
- **`email` ist Pflicht, muss aber nicht eindeutig sein** (✅ P4, Abschnitt 10). Jeder
  Mitarbeiter braucht also eine E-Mail-Adresse, und wer anlegt, prüft Dubletten selbst.

**Offene Fragen an weclapp bzw. den Tenant-Admin:**

1. **Kosten:** Zählen User mit `NOT_ACTIVE` und ohne Lizenz für die Abrechnung? Ist genau
   dafür eine Lizenz- oder Benutzerart vorgesehen?
2. **E-Mail:** Haben alle Mitarbeiter eine E-Mail-Adresse im Quellsystem? Wenn nicht,
   brauchen wir eine Regel für Platzhalter, z. B. `personalnummer@noreply.<firma>`.
   ✅ geprüft: weclapp prüft die E-Mail nicht auf Eindeutigkeit (P4).
3. **Automatische Mails:** Verschickt `POST /user` automatisch eine Mail, oder passiert das
   nur über `invite`? ⚠ verifizieren (P2, braucht einen echten Anlegetest)
4. **Status:** Darf ein neuer User direkt mit `NOT_ACTIVE` angelegt werden, und
   funktioniert die Personalakte dann trotzdem vollständig? Ein Dry-Run mit `NOT_ACTIVE`
   wird akzeptiert. Das Sync-Repo legt neue User inzwischen aber mit `ACTIVE` an, und dafür
   gibt es im Tenant viele Personalakten (P3).
5. **Bestand:** Gibt es in weclapp schon User oder Mitarbeiter, die wir beim ersten Lauf
   zuordnen müssen, statt sie doppelt anzulegen?

### 3.2 Die Mitarbeiternummer ist read-only (zu A2)

Wir können `employee.employeeNumber` beim Anlegen und beim Ändern nicht setzen, weil
weclapp sie aus dem eigenen Nummernkreis vergibt. Optionen:

| Option | Beschreibung | Bewertung |
|---|---|---|
| **a) Custom Attribute am `user`** | Eigenes Feld „Personalnummer“ (Typ String) am User anlegen und bei jeder Sync befüllen. Filterbar per `customAttribute<id>-eq=<nr>`. | ✅ **Empfehlung.** Funktioniert allein über die API und dient zugleich als Schlüssel für den Abgleich. Nachteil: Das Feld hängt am User, nicht an der Personalakte (`employee` unterstützt keine Custom Attributes). |
| b) Nummernkreis in weclapp manuell setzen | Prüfen, ob sich der Nummernkreis für Mitarbeiter so einstellen lässt, dass Nummern manuell vergeben werden. | ⚠ verifizieren mit weclapp-Support. Über die API bliebe das Feld trotzdem read-only. |
| c) Die weclapp-Nummer akzeptieren | weclapp vergibt die Nummer, wir speichern nur die Zuordnung. | ❌ Das erfüllt die Anforderung „Mitarbeiternummer übernehmen“ nicht. |

→ **Vorschlag:** Option a) umsetzen und parallel b) beim weclapp-Support anfragen. Klappt
b), können wir später zusätzlich oder stattdessen die echte `employeeNumber` nutzen.

### 3.3 Weitere Punkte

- **Geburtsdatum:** Die API erwartet Millisekunden seit Epoch (UTC). Wir liefern das Datum
  als Mitternacht UTC. ⚠ verifizieren, dass die weclapp-Oberfläche nicht den Vortag
  anzeigt, weil sie in eine andere Zeitzone umrechnet. Teilweise geprüft (P5): Die
  Oberfläche selbst speichert reine Datumsfelder als Mitternacht deutscher Zeit, und solche
  Werte liest der Client am selben Tag, den die Oberfläche zeigt (✅ am Eintrittsdatum
  verglichen). Wie die Oberfläche einen vom Client geschriebenen Wert anzeigt, klärt
  der Anlegetest.
- **Namenslänge:** `firstName` und `lastName` dürfen höchstens 50 Zeichen lang sein. Längere
  Namen führen zu einem Validierungsfehler, den wir sauber melden müssen.
- **Datenschutz:** Das Geburtsdatum ist personenbezogen, gehört aber nicht zu den besonders
  sensiblen Daten nach Art. 9 DSGVO. Trotzdem: nicht loggen, Token als Secret führen.

---

## 4. Benötigte Endpunkte (Phase 1)

### 4.1 Im Scope

| Endpunkt | Methode | Zweck |
|---|---|---|
| `/user/currentUser` | `GET` | Verbindungs- und Rechtetest beim Start |
| `/customAttributeDefinition` | `GET` | ID des Custom Attributes „Personalnummer“ einmalig ermitteln (Filter über `attributeKey`) und cachen |
| `/user` | `GET` | Bestehende User suchen: per `customAttribute<id>-eq=<nr>`, Fallback per `email-eq=` |
| `/user` | `POST` | Neuen User anlegen (`email`, `firstName`, `lastName`, `status=NOT_ACTIVE`, `canEditDashboard=false`, `customAttributes`) |
| `/user/id/{id}` | `GET`, `PUT` | User lesen (für `version`) und Namen oder Personalnummer aktualisieren |
| `/employee` | `GET` | Personalakte zum User finden: `userId-eq=<id>` |
| `/employee` | `POST` | Personalakte anlegen (`userId`, `birthDate`) |
| `/employee/id/{id}` | `GET`, `PUT` | Geburtsdatum aktualisieren |

Bei allen `GET`-Listen nutzen wir `pageSize` bis 1000. Beim Anlegen und Ändern ist
`dryRun=true` für einen Probelauf möglich.

### 4.2 Später bzw. bei Bedarf

| Endpunkt | Wann |
|---|---|
| `/user/id/{id}/softDelete` | Offboarding, wenn ein Mitarbeiter im Quellsystem wegfällt (Alternative: nur `status` bzw. `employee.exitDate` und `employmentStatus = INACTIVE` setzen) |
| `/user/count`, `/employee/count` | Plausibilitätschecks und Monitoring |
| `/workingTimeRule`, `/workScheduleProfile`, `/businessHolidays` | Erst, wenn Arbeitszeitmodelle oder Feiertagskalender synchronisiert werden |
| `/userRole` | Erst, wenn Rollen vergeben werden sollen (für „nur verwaltete“ Mitarbeiter nicht nötig) |

### 4.3 Nicht benötigt

| Endpunkt | Grund |
|---|---|
| `/webhook` | Wir schieben nach weclapp und müssen nicht auf Änderungen in weclapp reagieren |
| `/user/id/{id}/invite` | Soll bewusst **nicht** genutzt werden (A3) |
| `/personDepartment`, `/personRole`, `/salesTeam`, `/costCenter` | Betreffen CRM-Kontakte, Vertrieb bzw. Controlling, nicht HR-Stammdaten |
| `/absenceType`, `/timeRecord`, `/calendarEvent` | Bewegungsdaten, keine Stammdaten |
| MFA-Endpunkte, `userImage` | Nicht relevant |

---

## 5. Sync-Ablauf pro Mitarbeiter (Phase 1)

> Diesen Ablauf setzt das Sync-Repo um (A5). Hier ist er ein Vorschlag und beschreibt,
> welche Operationen der Client dafür bereitstellen muss.

```text
Eingabe: personalnummer, vorname, nachname, geburtsdatum, email

1. user  = GET /user?customAttribute<CA_ID>-eq=<personalnummer>
           (Fallback beim ersten Lauf: GET /user?email-eq=<email>)
2. wenn kein user:
       user = POST /user { email, firstName, lastName, status: NOT_ACTIVE,
                           canEditDashboard: false,
                           customAttributes: [{ attributeDefinitionId: CA_ID,
                                                stringValue: personalnummer }] }
   sonst wenn Name/Personalnummer abweichen:
       PUT /user/id/{user.id}?ignoreMissingProperties=true
           { version, firstName, lastName, customAttributes }
3. emp   = GET /employee?userId-eq=<user.id>
4. wenn kein emp:
       POST /employee { userId: user.id, birthDate }
   sonst wenn birthDate abweicht:
       PUT /employee/id/{emp.id}?ignoreMissingProperties=true { version, birthDate }
```

- **Idempotent:** Die Schritte 1 und 3 suchen immer zuerst nach vorhandenen Datensätzen.
  Bricht ein Lauf zwischen `POST /user` und `POST /employee` ab, holt der nächste Lauf die
  fehlende Personalakte nach.
- **Nur Änderungen schreiben:** Ein `PUT` geht nur raus, wenn sich ein Feld tatsächlich
  unterscheidet. Das spart Last und hält die Änderungshistorie in weclapp sauber.
- **Effizienz bei vielen Mitarbeitern:** Statt einzelner Suchanfragen einmal alle User
  (`properties=id,version,firstName,lastName,email,customAttributes`) und alle Employees
  (`properties=id,version,userId,birthDate,employeeNumber`) laden und lokal abgleichen.
  Das sind wenige große Requests statt vieler kleiner, wie weclapp es empfiehlt.
- ✅ geprüft (P6): `customAttributes` lässt sich in `properties=` anfragen, und der Filter
  `customAttribute<id>-eq` findet User über ein String-Attribut.

---

## 6. Datenmodell (Referenz)

### 6.1 `user` (v2, identisch zu v1)

| Feld | Typ | Pflicht | Bemerkung |
|---|---|---|---|
| `id`, `version`, `createdDate`, `lastModifiedDate` | | | read-only, `version` für Optimistic Locking |
| `username` | string (256) | (✓) | **read-only** (✅ per Dry-Run bestätigt), vom System vergeben, bei fast allen Usern gleich der E-Mail-Adresse (P4) |
| `email` | string (256, email) | ✓ | nicht eindeutig (P4) |
| `status` | `ACTIVE`, `DEPARTURE`, `NOT_ACTIVE` | ✓ | für „nur verwaltete“ Mitarbeiter `NOT_ACTIVE`, das Sync-Repo nutzt `ACTIVE` |
| `canEditDashboard` | boolean | ✓ | `false`; ein Dry-Run ohne das Feld wird trotzdem akzeptiert (P1) |
| `firstName`, `lastName` | string (50) | | **Name** |
| `title`, `phoneNumber`, `mobilePhoneNumber`, `faxNumber` | string | | später ggf. |
| `userRoles` | `[{id}]` | | → `/userRole` |
| `licenses` | `[string]` | | leer lassen |
| `customAttributes` | `[customAttribute]` | | **Personalnummer** (Option a) |
| `superUser`, `imageId` | | | read-only |

Zusätzliche Filter am User: `hasEmployee` (boolean).

### 6.2 `employee` (v2, identisch zu v1)

| Gruppe | Felder |
|---|---|
| Meta (read-only) | `id`, `version`, `createdDate`, `lastModifiedDate`, **`employeeNumber`** (Pflicht, aber read-only und vom System vergeben) |
| Verknüpfungen | **`userId`** (Pflicht) → `user`, `supervisorId` → `employee`, `businessHolidaysId` → `businessHolidays` |
| **Phase 1** | **`birthDate`** |
| Beschäftigung | `employmentStatus` (`ACTIVE`, `INACTIVE`, `LEAVE_OF_ABSENCE`, `ONBOARDING`), `employmentType` (`INTERNAL`, `EXTERNAL`), `occupationType`, `salaryType`, `entryDate`, `exitDate`, `endOfProbationPeriodDate`, `department`, `office` |
| Kontakt | `businessPhoneNumber`, `businessMobileNumber`, `businessFaxNumber`, `privateAddress` (`address`), `privateEmailAddress`, `privatePhoneNumber`, `emergencyContact` |
| Persönliches | `salutation`, `gender`, `placeOfBirth`, `nationalityCountryCode`, `marriageStatus`, `religion`, `childAllowance` |
| Steuer/SV (Art. 9 DSGVO) | `socialSecurityNumber`, `taxNumber`, `incomeTaxClass`, `healthInsuranceName`, `healthInsuranceType` |
| Bildung | `highestEducationLevel`, `highestProfessionalEducation`, `enrollmentCertValidUntilDate` |
| Zeitabhängig | `workingTimeRuleAssignments[]`, `workScheduleProfileAssignments[]` (jeweils `startDate`, `endDate`, Referenz-ID) |

Zusätzliche Filter am Employee über den verknüpften User: `firstName`, `lastName`,
`email`, `fullUserName`, `title`. `employee` hat **keine** `customAttributes`. Custom
Attributes gibt es nur für den Entitätstyp `user`.

---

## 7. Technische Grundlagen der API

| Thema | Verhalten laut Doku | Konsequenz für den Client |
|---|---|---|
| Base-URL | `https://<TENANT>.weclapp.com/webapp/api/v2/` | Tenant konfigurierbar |
| Auth | Header `AuthenticationToken: <token>` (alternativ Basic Auth mit User `*` und Token als Passwort). Der Token gehört zu einem User und erbt dessen Rechte. | Eigenen technischen API-User mit Rechten auf User- und Personalverwaltung anlegen |
| Header | `Accept: application/json`, `Content-Type: application/json`, `Accept-Encoding: gzip`, sprechender `User-Agent` | im Client fest setzen |
| Paging | `page` (beginnt bei 1), `pageSize` (Standard 100, max. 1000), `offset` | Iterator, `pageSize=1000`, immer mit `sort` |
| Filter | `<feld>-<op>=<wert>` (`eq, ne, lt, gt, le, ge, null, notnull, like, ilike, in, notin`, …), `or-`-Präfix, `filter=`-Ausdrücke (Beta). **Unbekannte Filter werden stillschweigend ignoriert!** | Filterfelder prüfen. Sonst liefert eine Suche nach einem User mit einem Tippfehler im Filter **alle** User, und der Code nimmt womöglich den ersten |
| Feldauswahl | `properties=…`, `includeReferencedEntities=userId` | schlanke Abfragen |
| Nulls | Null-Felder werden weggelassen, `serializeNulls=true` liefert sie mit. **Leere Strings gelten als `null`.** | beim Diffen `""` und `None` gleich behandeln |
| Datum | ms seit Epoch (UTC) | `date` ↔ ms-Konverter |
| Update | `PUT` ersetzt standardmäßig das ganze Objekt. Mit `?ignoreMissingProperties=true` ändert es nur die gesendeten Felder. Listen werden dabei ersetzt (fehlende Einträge werden gelöscht), **`customAttributes` dagegen pro Attribut zusammengeführt** (nicht gesendete Attribute bleiben erhalten). Der Parameter ist allgemein dokumentiert, bei `PUT /user` und `PUT /employee` aber nicht in der Spec deklariert (✅ bei `PUT /user` geprüft, P7; `PUT /employee` folgt mit dem Anlegetest) | **immer** partielles Update plus `version`. Außer `customAttributes` keine Listen senden |
| Read-only- und unbekannte Felder | Werden sie beim POST/PUT mitgeschickt, gibt es **HTTP 400**, bei Feldern ohne Berechtigung **403** | Serializer sendet nur bekannte, beschreibbare Felder |
| Optimistic Locking | Stimmt die `version` nicht, kommt `409 optimistic_lock` | neu lesen, erneut versuchen |
| Dry-Run | `?dryRun=true` bei POST/PUT/DELETE | Probelauf der Sync ohne Änderungen |
| Fehler | RFC 7807 Problem-JSON (`validation`, `forbidden`, `not_found`, `optimistic_lock`, …), teils `text/plain` | eigene Exception-Hierarchie, Validierungsfehler pro Feld |
| Last | Kein festes Rate-Limit. Requests über dem Parallel-Limit warten bis zu 30 s in der Queue, danach `429` | Retry mit exponentiellem Backoff, Timeout ≥ 60 s, sequentiell oder mit wenig Parallelität |

---

## 8. Scope des Python-Clients (Phase 1)

- **Transport:** Token-Auth, gzip, Timeout ≥ 60 s, Retry/Backoff bei 429 und 5xx,
  Problem-JSON → Exceptions, `dryRun`-Schalter.
- **Generische Resource-Basis:** `list()` als Iterator mit Paging, `get(id)`, `create()`,
  `update(id, …)` (immer partiell, mit `version`), dazu Filter- und `properties`-Builder.
  Weitere Ressourcen lassen sich damit später leicht ergänzen.
- **Ressourcen:** `users`, `employees`, `custom_attribute_definitions`, `current_user()`.
- **Modelle (Pydantic):** `User`, `Employee`, `CustomAttribute`,
  `CustomAttributeDefinition` mit den Feldern aus Abschnitt 6. Read-only-Felder werden
  gelesen, aber nie gesendet. Unbekannte Felder werden toleriert, damit spätere
  API-Erweiterungen den Client nicht brechen.
- **Nicht im Client, sondern im Sync-Repo (A5):** Abgleich, Diff und die Regeln aus
  Abschnitt 5.

---

## 9. Nächste Schritte

1. Die Fragen aus **3.1** (Kosten, E-Mail, automatische Mails, Status, Bestand) mit dem
   weclapp-Admin bzw. dem weclapp-Support klären.
2. Beim weclapp-Support anfragen, ob der **Nummernkreis für Mitarbeiter** manuell vergeben
   werden kann (Option 3.2 b).
3. Im Tenant das **Custom Attribute „Personalnummer“** für die Entität `user` anlegen
   (Option 3.2 a).
4. Sobald der Test-Tenant da ist: alle ⚠-Punkte per `dryRun` bzw. gegen Testdaten prüfen.
   Lesen und Dry-Runs sind erledigt (Abschnitt 10), der Anlegetest steht noch aus.
5. Parallel dazu den Client-Kern (Abschnitt 8) umsetzen und mit gemockten HTTP-Antworten
   testen. Dafür brauchen wir den Tenant noch nicht.

Den ausgearbeiteten Plan mit Arbeitspaketen, Meilensteinen und Prüfpunkten enthält
[umsetzungsplan.md](umsetzungsplan.md).

---

## 10. Befunde aus dem Tenant (AP 6)

Stand 29.10.2026. Es gibt nur den Produktiv-Tenant (K1). Gelaufen ist Stufe 1 der
Integrationstests: nur Lesezugriffe und Dry-Runs. Ein erster Dry-Run hat bestätigt, dass
`dryRun=true` nichts speichert. Die Befunde enthalten nur strukturelle Angaben, keine Daten aus
dem Tenant.

| Punkt | Befund | Folge |
|---|---|---|
| P1 | `POST /user` ohne `email` wird mit 400 abgewiesen, betroffen ist das Feld `email`. Ohne `canEditDashboard` wird ein Dry-Run akzeptiert, obwohl die Spec das Feld als Pflicht führt. Alle Personalakten im Tenant haben eine `userId`. | keine, `UserCreate` sendet `canEditDashboard` weiterhin |
| P2 | Ein Dry-Run mit `status=NOT_ACTIVE` wird akzeptiert. Ob `POST /user` eine Mail verschickt, zeigt erst ein echter Anlegetest. | offen |
| P3 | Personalakten gibt es im Tenant nur für User mit `ACTIVE` oder `DEPARTURE`. Für `ACTIVE`, wie es das Sync-Repo nutzt, ist das der Normalfall. | für `NOT_ACTIVE` offen, für das Sync-Repo nicht mehr nötig |
| P4 | **`username` lässt sich nicht setzen:** Einen Dry-Run von `POST /user` mit `username` weist weclapp mit 400 ab („property username is read-only“, `platform.read_only_property`). `username` ist bei fast allen Usern gleich der E-Mail-Adresse. Bei einigen ist es eine andere E-Mail-Adresse (vermutlich wurde die E-Mail später geändert) oder ein Name ohne `@`. **weclapp prüft die E-Mail nicht auf Eindeutigkeit:** Im Tenant gibt es E-Mail-Adressen in gleicher Schreibweise bei mehreren Usern, auch bei aktiven. Dry-Runs mit einer vorhandenen E-Mail werden akzeptiert, in gleicher wie in anderer Groß-/Kleinschreibung. | `FakeWeclapp` akzeptiert jetzt doppelte E-Mail-Adressen. Eine Suche per E-Mail kann mehrere User liefern, `find_one()` meldet dann `AmbiguousResultError`. Das Sync-Repo prüft Dubletten selbst. Den `username` braucht das Sync-Repo nicht. Ob weclapp ihn bei per API angelegten Usern auf die E-Mail-Adresse setzt, zeigt der Anlegetest |
| P5 | Im Tenant haben die Personalakten kein Geburtsdatum und fast nie ein Eintrittsdatum. Das einzige vorhandene `entryDate` liegt auf Mitternacht deutscher Sommerzeit (22:00 UTC am Vortag). So speichert es die Oberfläche. Der Client liest es am selben Tag, den die Oberfläche zeigt (✅ manuell verglichen). Ohne das Runden käme der Vortag heraus. | Lesen ist geprüft. Offen ist, wie die Oberfläche einen vom Client geschriebenen Wert anzeigt (Anlegetest) |
| P6 | `properties=customAttributes` und der Filter `customAttribute<id>-eq` funktionieren. Den Key des Attributs „Personalnummer“ hat weclapp selbst vergeben, eine zufällige Zeichenfolge statt `personalnummer`. | Das Attribut über seine ID auflösen, wie im Sync-Repo. Die Integrationstests nehmen dafür `WECLAPP_IT_PERSONNEL_NUMBER_ATTRIBUTE_ID` |
| P7 | `PUT /user?ignoreMissingProperties=true` (Dry-Run) behält nicht gesendete Felder und führt `customAttributes` pro Attribut zusammen. | wie in Client und Fake umgesetzt. `PUT /employee` folgt mit dem Anlegetest |
| P8 | Paging mit `pageSize=1000` und `sort=id` liefert bei `/user` und `/employee` jede Entität genau einmal, passend zu `count`. | keine |
| P9 | Der Token funktioniert. Es ist ein persönlicher Token, noch kein technischer API-User. | Die minimalen Rechte sind offen, sie sind die Grundlage für die Einrichtungsdoku |
| P10 | 400: Problem-JSON vom Typ `validation` mit `validationErrors`. 401 bei ungültigem Token: `error` `unauthorized`, `detail` „no identity available“. 404: `not_found`. 409 bei veralteter `version`: `optimistic_lock`, auch im Dry-Run. | passt zum Fehler-Mapping des Clients |
| P11 | Kein User hat mehr als eine Personalakte. Ein Dry-Run für eine zweite Personalakte wird mit 400 abgewiesen, `validationErrors` vom Typ `consistency`. | `FakeWeclapp` meldet den Fall jetzt ebenfalls als `consistency` |

**Noch offen**, zu klären mit einem Anlegetest (ein User, eine Personalakte) und manuellen Prüfungen:

- P2: Geht beim Anlegen eines Users eine Mail raus?
- P4: Wie vergibt weclapp `username` bei einem per API angelegten User, z. B. in Kleinschreibung?
- P5: Zeigt die Oberfläche ein vom Client geschriebenes Datum (Mitternacht UTC) am richtigen Tag an?
- P7: `PUT /employee` mit `ignoreMissingProperties=true`, als Dry-Run am Testdatensatz
- P9: minimale Rechte eines technischen API-Users
