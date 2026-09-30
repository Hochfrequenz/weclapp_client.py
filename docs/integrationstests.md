# Integrationstests gegen einen weclapp-Tenant (AP 6)

Die Integrationstests prüfen die Punkte P1–P11 aus dem [Umsetzungsplan](umsetzungsplan.md), also das Verhalten
der echten weclapp-API, auf das sich Client und `FakeWeclapp` verlassen. Sie liegen in `unittests/integration/` und
werden ohne Zugangsdaten automatisch übersprungen, auch in der CI.

## Zwei Stufen

| Stufe | Marker | Was passiert | Geeignet für |
|---|---|---|---|
| 1 | `integration` | nur Lesezugriffe und Dry-Runs (`dryRun=true`), keine Änderungen | Test-Tenant **und** Produktiv-Tenant |
| 2 | `integration_write` | legt eigene Testdatensätze an, ändert sie und räumt sie am Ende auf | Test-Tenant, im Produktiv-Tenant nur nach Absprache |

Stufe 2 läuft nur, wenn zusätzlich `WECLAPP_ALLOW_WRITES=1` gesetzt ist.

Warum Stufe 2 im Produktiv-Tenant heikel ist:

- Jede angelegte Personalakte verbraucht eine Mitarbeiternummer aus dem Nummernkreis.
- User lassen sich in API v2 nur per `softDelete` entfernen, Reste bleiben im System (Lizenzfrage S1).
- Beim Anlegen eines Users gehen eventuell Mails raus (P2).
- Integrationen oder Webhooks, die an eurem weclapp hängen, könnten auf neue User reagieren.

## Vorbereitung im Tenant

1. **Technischen API-User anlegen** und dessen API-Token erzeugen (Mein weclapp → API).
2. **Custom Attribute für die Personalnummer anlegen:** Typ `STRING`, Entität `user`, Key z. B.
   `personalnummer`. Ohne das Attribut werden die Tests zu P6 und die ganze Stufe 2 übersprungen.
3. Für P2 ein **Test-Postfach** bereithalten, das Mails an eine Adressvorlage wie
   `weclapp-it+{id}@eure-domain.de` empfängt. Ohne eigene Vorlage verwenden die Tests
   `weclapp-client-it+{id}@example.com`: Das ist unkritisch, zeigt aber nicht, ob Mails verschickt werden.

## Umgebungsvariablen

| Variable | Pflicht | Bedeutung |
|---|---|---|
| `WECLAPP_API_TOKEN` | ja | Token des technischen API-Users |
| `WECLAPP_BASE_URL` oder `WECLAPP_TENANT` | ja | z. B. `https://<tenant>.weclapp.com/webapp/api/v2/` bzw. nur `<tenant>` |
| `WECLAPP_ALLOW_WRITES` | nur für Stufe 2 | `1` erlaubt das Anlegen von Testdatensätzen |
| `WECLAPP_IT_PERSONNEL_NUMBER_KEY` | nein | Key des Custom Attributes, Standard `personalnummer` |
| `WECLAPP_IT_EMAIL_TEMPLATE` | nein | Vorlage für Test-E-Mail-Adressen mit dem Platzhalter `{id}` |

Token und Tenant-URL gehören **nicht ins Repo**, das Repo ist öffentlich. Setze sie nur in der eigenen Shell oder
in einer lokalen, nicht eingecheckten Datei.

## Ausführen

Stufe 1 (auch im Produktiv-Tenant unbedenklich), PowerShell:

```powershell
$env:WECLAPP_TENANT = "<tenant>"; $env:WECLAPP_API_TOKEN = "<token>"; uv run pytest unittests/integration -m integration -rs
```

Stufe 1 und 2 (Test-Tenant oder nach Absprache), PowerShell:

```powershell
$env:WECLAPP_TENANT = "<tenant>"; $env:WECLAPP_API_TOKEN = "<token>"; $env:WECLAPP_ALLOW_WRITES = "1"; uv run pytest unittests/integration -rs
```

In einer POSIX-Shell (Git Bash, Linux, macOS):

```bash
WECLAPP_TENANT="<tenant>" WECLAPP_API_TOKEN="<token>" uv run pytest unittests/integration -m integration -rs
```

## Ergebnis lesen

Am Ende gibt pytest den Abschnitt **„weclapp: Ergebnisse der Prüfpunkte (AP 6)“** aus. Er hat drei Teile:

- **Befunde je Prüfpunkt,** z. B. `P5: gespeicherte Geburtsdaten (37 geprüft): Mitternacht MEZ (UTC+1): 20, ...`.
  Befunde mit `ACHTUNG` bedeuten, dass eine Annahme des Fakes nicht stimmt.
- **Manuell zu prüfen:** was sich nicht automatisch feststellen lässt, z. B. ob eine Mail angekommen ist (P2) oder
  wie die Oberfläche das Geburtsdatum anzeigt (P5), jeweils mit den IDs der Testdatensätze.
- **Aufräumen:** welche Testdatensätze entfernt wurden und welche nicht. Nicht entfernte Datensätze haben den
  Nachnamen `ZZ-Test weclapp-client` und lassen sich darüber in weclapp finden.

Die Proben in Stufe 1 halten ihr Ergebnis meist nur fest und schlagen nicht fehl, weil ein Dry-Run nicht zwingend alle
Prüfungen eines echten Requests durchläuft. Stufe 2 prüft das echte Verhalten mit Assertions.

## Datenschutz

- Die Tests geben keine personenbezogenen Daten aus. Assertions vergleichen nur IDs, Anzahlen und Ja/Nein-Werte,
  und die Befunde enthalten nur strukturelle Angaben (z. B. wie viele Geburtsdaten um Mitternacht UTC liegen).
- Stufe 1 liest im Produktiv-Tenant echte Daten, hält sie aber nur im Speicher.
- Antworten aus einem echten Tenant dürfen **nicht** als Fixtures ins Repo, auch nicht anonymisiert.
- Dry-Runs mit echten Daten (P4: vorhandene E-Mail-Adresse, P11: vorhandener User) laufen erst, nachdem ein Test
  bestätigt hat, dass ein Dry-Run nichts speichert.

## Nach dem Lauf

1. Befunde und manuelle Prüfungen in der [Analyse](weclapp_api_analyse.md) nachtragen (die ⚠-Punkte).
2. Weicht weclapp von einer Annahme des Fakes ab (`ACHTUNG`), `FakeWeclapp` und dessen Tests anpassen.
3. Weicht weclapp von einer Annahme des Clients ab, z. B. bei der Zeitzone (P5) oder bei den Pflichtfeldern (P1),
   Modelle bzw. Umrechnung anpassen.
4. Nicht aufgeräumte Testdatensätze in weclapp entfernen.
