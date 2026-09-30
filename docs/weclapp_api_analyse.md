# Analyse der weclapp REST API für die Synchronisation von Mitarbeiter-Stammdaten

Stand: 30.09.2026 · Grundlage: offizielle OpenAPI-Specs
[`openapi_v1.yaml`](https://www.weclapp.com/api/openapi_v1.yaml) und
[`openapi_v2.yaml`](https://www.weclapp.com/api/openapi_v2.yaml)
(v1: 732 Pfade, v2: 712 Pfade), Doku unter <https://www.weclapp.com/api/>.

> Diese Analyse stützt sich allein auf die öffentliche Spezifikation, inklusive der
> weclapp-eigenen Metadaten `x-weclapp` (z. B. `required`, `entity`). Einen Test-Tenant gibt
> es noch nicht. Punkte, die wir erst dort prüfen können, sind mit **⚠ verifizieren**
> markiert.

---

## 1. Anforderungen (Stand der Abstimmung)

| # | Thema | Entscheidung |
|---|---|---|
| A1 | Richtung | **Nur schreibend nach weclapp.** Das Quellsystem führt, weclapp ist das Ziel. |
| A2 | Feldumfang (Phase 1) | **Name, Geburtsdatum, Mitarbeiternummer.** Weitere Felder ggf. später. |
| A3 | Neue Mitarbeiter | Werden in weclapp **angelegt**. Sie arbeiten **nicht selbst** mit weclapp, sondern werden dort nur verwaltet. **Klärungsbedarf, siehe Abschnitt 3.** |
| A4 | Test-Tenant | Kommt noch, Zugriff wird organisiert. |

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
- **`email` ist Pflicht und muss vermutlich eindeutig sein.** Jeder Mitarbeiter braucht
  also eine E-Mail-Adresse.

**Offene Fragen an weclapp bzw. den Tenant-Admin:**

1. **Kosten:** Zählen User mit `NOT_ACTIVE` und ohne Lizenz für die Abrechnung? Ist genau
   dafür eine Lizenz- oder Benutzerart vorgesehen?
2. **E-Mail:** Haben alle Mitarbeiter eine E-Mail-Adresse im Quellsystem? Wenn nicht,
   brauchen wir eine Regel für Platzhalter, z. B. `personalnummer@noreply.<firma>`.
   ⚠ verifizieren, ob weclapp die E-Mail auf Eindeutigkeit prüft.
3. **Automatische Mails:** Verschickt `POST /user` automatisch eine Mail, oder passiert das
   nur über `invite`? ⚠ verifizieren
4. **Status:** Darf ein neuer User direkt mit `NOT_ACTIVE` angelegt werden, und
   funktioniert die Personalakte dann trotzdem vollständig? ⚠ verifizieren
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
  anzeigt, weil sie in eine andere Zeitzone umrechnet.
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
- ⚠ verifizieren: ob `customAttributes` in `properties=` angefragt werden kann, und ob der
  Filter `customAttribute<id>-eq` für String-Attribute am User funktioniert.

---

## 6. Datenmodell (Referenz)

### 6.1 `user` (v2, identisch zu v1)

| Feld | Typ | Pflicht | Bemerkung |
|---|---|---|---|
| `id`, `version`, `createdDate`, `lastModifiedDate` | | | read-only, `version` für Optimistic Locking |
| `username` | string (256) | (✓) | **read-only**, vom System vergeben (⚠ verifizieren wie, vermutlich aus der E-Mail) |
| `email` | string (256, email) | ✓ | |
| `status` | `ACTIVE`, `DEPARTURE`, `NOT_ACTIVE` | ✓ | für „nur verwaltete“ Mitarbeiter `NOT_ACTIVE` |
| `canEditDashboard` | boolean | ✓ | `false` |
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
| Update | `PUT` ersetzt standardmäßig das ganze Objekt. Mit `?ignoreMissingProperties=true` ändert es nur die gesendeten Felder. Listen werden dabei ersetzt (fehlende Einträge werden gelöscht), **`customAttributes` dagegen pro Attribut zusammengeführt** (nicht gesendete Attribute bleiben erhalten). Der Parameter ist allgemein dokumentiert, bei `PUT /user` und `PUT /employee` aber nicht in der Spec deklariert (⚠ verifizieren) | **immer** partielles Update plus `version`. Außer `customAttributes` keine Listen senden |
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
- **Nicht im Client, sondern in der Sync-Logik darüber:** Abgleich, Diff und die Regeln aus
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
5. Parallel dazu den Client-Kern (Abschnitt 8) umsetzen und mit gemockten HTTP-Antworten
   testen. Dafür brauchen wir den Tenant noch nicht.

Den ausgearbeiteten Plan mit Arbeitspaketen, Meilensteinen und Prüfpunkten enthält
[umsetzungsplan.md](umsetzungsplan.md).
