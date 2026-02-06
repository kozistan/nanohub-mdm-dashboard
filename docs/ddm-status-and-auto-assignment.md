# DDM Status Display & Auto-Assignment

**Datum:** 2026-02-06  
**Verze:** 1.0

## Přehled změn

Tato aktualizace přidává:
1. Automatické přiřazení DDM setů při New Device Installation a Device Manager
2. Zobrazení DDM status dat v Device Detail
3. Vylepšení DDM editoru a UI

---

## 1. DDM Set Auto-Assignment

### Popis
DDM sety se nyní automaticky přiřazují zařízením na základě jejich manifestu a OS typu podle tabulky `ddm_required_sets`.

### Kdy se přiřazuje
- **New Device Installation** - Phase 5 na konci provisioningu
- **Device Manager Update** - při změně manifestu (odebere staré sety, přiřadí nové)

### Soubory
- `/opt/nanohub/backend_api/nanohub_admin/commands.py`
  - `_assign_ddm_sets_for_device(uuid, manifest, os_type, run_command_fn)`
  - `_remove_ddm_sets_for_device(uuid, manifest, os_type, run_command_fn)`

### Mapování (ddm_required_sets)
| Manifest | OS | DDM Set |
|----------|-----|---------|
| default | macos | sloto-macos-karlin-default |
| default | ios | sloto-ios-karlin-default |
| tech | macos | sloto-macos-karlin-tech |
| tech | ios | sloto-ios-karlin-tech |
| default-bel | macos | sloto-macos-bel-default |
| ... | ... | ... |

### Poznámky
- Zařízení enrollovaná před touto změnou nemají DDM sety - nutno přiřadit ručně nebo přes Device Manager
- DDM set se přiřazuje voláním `/opt/nanohub/ddm/scripts/ddm-assign-device.sh`

---

## 2. DDM Status Display

### Popis
Device Detail → DDM tab nyní zobrazuje StatusItems data z DDM subscription reportů.

### Architektura

```
Device DDM Sync → KMFDDM → Webhook → status_values table → API → UI
```

### Webhook Processing
`/opt/nanohub/webhook/webhook.py` - funkce `save_ddm_status_values()`:
- Parsuje nested StatusItems JSON do flat key-value párů
- Ukládá do tabulky `status_values` (enrollment_id, path, value, container_type, value_type)
- **Filtruje:**
  - `declarations` - ukládá se zvlášť do `status_declarations`
  - `client-capabilities` - příliš verbose, zobrazuje se zvlášť

### API Endpoint
`GET /admin/api/device/<uuid>/ddm-status`

Response:
```json
{
  success: true,
  data: {
    categories: {
      device: [
        {key: serial-number, value: C02K62T5Q6LR, type: string, path: ...}
      ],
      softwareupdate: [...],
      management: [...]
    },
    updated_at: 2026-02-06 04:08:39
  }
}
```

### UI Display
- **Hlavní sekce:** Terminal boxy pro device, passcode, softwareupdate, security
- **Collapsible sekce:** Supported Capabilities - client-capabilities (co zařízení umí reportovat)

### Status Items
Subscribed v `com.sloto.ddm.status-subscriptions`:
- `device.*` - serial, udid, model, OS verze
- `passcode.is-compliant`, `passcode.is-present`
- `softwareupdate.install-state`, `pending-version`, `install-reason`, `failure-reason`
- `security.fde.*`, `security.certificate.list`
- `management.declarations`, `management.client-capabilities`

**Poznámka:** Některé status items vrací `UnsupportedStatusValue` na macOS (passcode, security.fde).

---

## 3. UI Změny

### DDM Editor Popup
- Širší modal (700px) pro lepší editaci JSON
- CSS třída `.modal-box.wide`

### Device Manager
- Odstraněno pole DEP (není potřeba při manuální správě)
- Přidáno info o DDM setech při výběru manifestu

### Device Detail Info Tab
- Odstraněny duplicitní údaje (Serial, Hostname, OS, DEP)

---

## 4. Databázové tabulky

### status_values
```sql
CREATE TABLE status_values (
  enrollment_id VARCHAR(128) NOT NULL,
  path VARCHAR(255) NOT NULL,
  container_type VARCHAR(6) NOT NULL,
  value_type VARCHAR(7) NOT NULL,
  value VARCHAR(255) NOT NULL,
  status_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (enrollment_id, path, container_type, value_type, value)
);
```

### ddm_required_sets
```sql
CREATE TABLE ddm_required_sets (
  id INT PRIMARY KEY AUTO_INCREMENT,
  manifest VARCHAR(127) NOT NULL,
  os VARCHAR(10) NOT NULL,
  set_id INT NOT NULL,
  FOREIGN KEY (set_id) REFERENCES ddm_sets(id),
  UNIQUE KEY (manifest, os)
);
```

---

## 5. Soubory změněné v této aktualizaci

| Soubor | Změna |
|--------|-------|
| `commands.py` | DDM auto-assign helper funkce + Phase 5 |
| `webhook.py` | `save_ddm_status_values()` pro parsing StatusItems |
| `devices.py` | API endpoint + loadDdmStatus() JS |
| `dashboard.py` | Odstranění DEP, DDM set info |
| `command_registry.py` | Odstranění DEP pole |
| `admin.css` | `.modal-box.wide` třída |
| `ddm.py` | Wide class na modaly |

---

## 6. Troubleshooting

### Zařízení nemá DDM status data
1. Zkontrolovat přiřazení DDM setu: `curl -u nanohub: http://localhost:9004/api/v1/ddm/enrollment-sets/<UUID>`
2. Pokud `null` - přiřadit set přes DDM sekci nebo Device Manager
3. Triggerovat sync: `/opt/nanohub/ddm/scripts/ddm-force-sync.sh <UUID>`

### Status items vrací UnsupportedStatusValue
- Normální pro některé items na macOS (passcode, security.fde)
- Errors jsou logovány v `status_reports.status_report` JSON

### Data se nezobrazují po změně
- Webhook musí přijmout nový DDM status report
- Zařízení syncuje při wake/unlock po push notifikaci

---

## 7. DDM Cache Sync (2026-02-06 update)

### Problém
Reports stránka používala `device_details.ddm_data` cache, která se aktualizovala jen při ručním "Refresh Declarations". 
Webhook ukládal data do `status_declarations`, ale neaktualizoval cache → reports ukazovaly zastaralá data.

### Řešení
Přidána funkce `update_device_ddm_cache()` do `webhook.py`:
- Volá se automaticky po `save_ddm_declaration_status()`
- Čte `status_declarations` a aktualizuje `device_details.ddm_data`
- Reports nyní zobrazují aktuální DDM stav

### Data flow (updated)
```
Device DDM Sync → KMFDDM → Webhook
                              ↓
                    status_declarations
                              ↓
                    update_device_ddm_cache()  ← NEW
                              ↓
                    device_details.ddm_data
                              ↓
                    Reports page (check_device_ddm)
```

### Manuální refresh cache
```sql
-- Pro všechna zařízení
UPDATE device_details dd
SET ddm_data = (
    SELECT JSON_ARRAYAGG(
        JSON_OBJECT(
            'identifier', sd.declaration_identifier,
            'active', IF(sd.active = 1, TRUE, FALSE),
            'valid', IF(sd.valid = 'valid', TRUE, FALSE)
        )
    )
    FROM status_declarations sd
    WHERE sd.enrollment_id = dd.uuid
),
ddm_updated_at = NOW()
WHERE EXISTS (SELECT 1 FROM status_declarations sd WHERE sd.enrollment_id = dd.uuid);
```

---

## 8. DDM Compliance Logic (2026-02-06 update)

### Problém
Reports ukazovaly všechna zařízení jako "incomplete" protože set obsahoval deklaraci
`softwareupdate.enforcement.macos`, která nebyla v aktivaci (StandardConfigurations).

### Jak DDM funguje

```
DDM Set (sloto-macos-karlin-tech)
├── com.sloto.ddm.activation.macos-karlin     ← Activation (vždy applied)
├── com.sloto.ddm.passcode                    ← V StandardConfigurations → applied
├── com.sloto.ddm.softwareupdate.macos        ← V StandardConfigurations → applied  
├── com.sloto.ddm.status-subscriptions        ← V StandardConfigurations → applied
├── com.sloto.ddm.org-info.tolar              ← Management type → auto-applied
└── com.sloto.ddm.softwareupdate.enforcement  ← NENÍ v StandardConfigurations → NOT applied!
```

**Typy deklarací:**
| Typ | Prefix | Chování |
|-----|--------|---------|
| Activation | `com.apple.activation.*` | Vždy applied, definuje co se aplikuje |
| Configuration | `com.apple.configuration.*` | Applied jen pokud v StandardConfigurations |
| Management | `com.apple.management.*` | Auto-applied přes set assignment |

### Nová logika check_device_ddm()

1. **Přeskočit** deklarace kde `valid=unknown` (nejsou v aktivaci)
2. **Management typy**: kontrolovat jen `valid`, ne `active`
3. **Configuration typy**: kontrolovat `active` AND `valid`
4. **Počítat jako required** jen deklarace co jsou skutečně applied

### Výsledek
- Před: 5/6 (softwareupdate.enforcement počítán jako missing)
- Teď: 5/5 (softwareupdate.enforcement přeskočen - není v aktivaci)

## Force Sync and Upload Functions

### Declaration Upload Button (DDM Page)

The DDM page (`/admin/ddm`) includes an **Upload** button for each declaration:
- Shows status badge: ✓ (green) if uploaded, "pending" (orange) if not
- Clicking **Upload** sends the declaration to KMFDDM API
- Useful for force-updating a declaration after editing its payload

### Force DDM Sync Button (Device Detail)

The Device Detail DDM tab includes a **Force Sync** button:
- Sends APNs push notification to the device
- Device will sync DDM declarations on next wake/unlock
- Uses NanoMDM API: `PUT /api/v1/nanomdm/push/{uuid}`

### When to Use

- **Upload button**: After editing a declaration payload in the DB
- **Force Sync button**: When device seems out of sync or after assigning new DDM sets
