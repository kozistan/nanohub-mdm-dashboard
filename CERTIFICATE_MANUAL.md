# Manual k certifikátům - MDM/DEP/SCEP Infrastructure

## Přehled certifikátů

### 1. SCEP Certifikáty
**Lokace**: `/home/microm/nanohub/scep-docker/depot/`
- `ca.pem` - SCEP CA certifikát (TOLAR COMPANY s.r.o.)
- `ca.key` - SCEP CA private key

**Použití**: Vydávání certifikátů pro MDM enrollment
**Platnost**: 100 let (do 2125)
**Kombinovaný CA**: `/home/microm/nanohub/certs/combined_scep_ca.pem` (obsahuje TOLAR + MicroMDM CA)

### 2. DEP Certifikáty
**Lokace**: `/home/microm/nanohub/dep/`
- `micromdm_dep_cert.pem` - DEP public key certifikát (CN: micromdm-dep-token)
- `PushCertificatePrivateKey_decrypted.key` - DEP private key
- `MDM_ Martin Kubovciak_Certificate.pem` - Apple MDM certifikát

**Použití**: Dekryptování DEP tokenů z Apple Business Manager
**Platnost**: Podle Apple Business Manager (obvykle 1 rok)

### 3. Push Certifikáty
**Lokace**: `/home/microm/nanohub/certs/`
- `MDM_ Martin Kubovciak_Certificate.pem` - Apple MDM push certifikát
- `PushCertificatePrivateKey.key` - Push private key (encrypted)
- `push_key_decrypted.pem` - Push private key (decrypted)

**Použití**: Push notifikace pro MDM
**Platnost**: 1 rok (nutné obnovit každý rok)

### 4. Vendor Certifikáty
**Lokace**: `/home/microm/nanohub/certs/`
- `VendorPrivateKey.key` - Vendor private key (encrypted)
- `mdm_cert_clean.pem` - Vendor certifikát (CN: MDM Vendor: Martin Kubovciak)

**Použití**: MDM vendor identifikace
**Platnost**: Podle Apple Developer Program

## Proces obnovy certifikátů

### 1. Obnova Push Certifikátů (každý rok)
```bash
# 1. Přihlásit se do Apple Identity Portal
# https://identity.apple.com/pushcert

# 2. Obnovit push certifikát pomocí CSR
# 3. Stáhnout nový push certifikát

# 4. Nahrát do systému
cp novy_push_cert.pem /home/microm/nanohub/certs/
cp novy_push_key.pem /home/microm/nanohub/certs/

# 5. Dekryptovat private key
openssl rsa -in novy_push_key.pem -out push_key_decrypted.pem

# 6. Aktualizovat NanoHUB konfiguraci
sudo nano /etc/systemd/system/nanohub.service
# Změnit cesty k certifikátům

# 7. Restart služby
sudo systemctl restart nanohub
```

### 2. Obnova DEP Tokenů (každý rok)
```bash
# 1. Vygenerovat nový DEP keypair (pouze pokud je potřeba)
curl -u depserver:$APIKEY "$BASE_URL/v1/tokenpki/$DEP_NAME/certificate" > new_dep_cert.pem

# 2. Nahrát certifikát do Apple Business Manager
# https://business.apple.com

# 3. Stáhnout nový DEP token (.p7m soubor)

# 4. Dekryptovat token pomocí deptokens nebo mdmctl
# Na starém serveru:
mdmctl get dep-tokens -export-token /tmp/DEPOAuthToken.json

# 5. Nahrát dekryptovaný token do NanoDEP
mysql -h 127.0.0.1 -P 3306 -u nanohub -p"$DB_PASSWORD" dep -e "
UPDATE dep_names SET 
    consumer_key = 'NOVY_CONSUMER_KEY',
    consumer_secret = 'NOVY_CONSUMER_SECRET',
    access_token = 'NOVY_ACCESS_TOKEN',
    access_secret = 'NOVY_ACCESS_SECRET',
    access_token_expiry = 'NOVY_EXPIRY_DATE'
WHERE name = 'mdm.sloto.space';"

# 6. Test DEP komunikace
./dep-account-detail.sh
```

### 3. Obnova SCEP CA (100 let - až v roce 2125)
```bash
# 1. Generovat nový SCEP CA
cd /home/microm/nanohub/scep-docker
./scepserver-linux-amd64 ca -init -depot new_depot \
  -organization "TOLAR COMPANY s.r.o." \
  -organizational_unit "Slotegrator" \
  -country "CZ" \
  -common_name "TOLAR SCEP CA" \
  -years 100

# 2. Vytvořit kombinovaný CA (starý + nový)
cat new_depot/ca.pem > /home/microm/nanohub/certs/combined_scep_ca.pem
echo "" >> /home/microm/nanohub/certs/combined_scep_ca.pem
cat depot/ca.pem >> /home/microm/nanohub/certs/combined_scep_ca.pem

# 3. Aktualizovat NanoHUB
sudo nano /etc/systemd/system/nanohub.service
# Změnit -ca na nový combined_scep_ca.pem

# 4. Postupně nahradit SCEP server
mv depot depot_old
mv new_depot depot
sudo systemctl restart scep-docker

# 5. Restart NanoHUB
sudo systemctl restart nanohub
```

## Troubleshooting

### Problém: DEP token nelze dekryptovat
**Řešení**: Ověřit správný keypair
```bash
# Zkontrolovat MD5 hash certifikátu a klíče
openssl x509 -in cert.pem -pubkey -noout | openssl md5
openssl rsa -in key.pem -pubout | openssl md5
# Musí být stejný hash
```

### Problém: Push notifikace nefungují
**Řešení**: Zkontrolovat push certifikát
```bash
# Zkontrolovat platnost push certifikátu
openssl x509 -in push_cert.pem -text -noout | grep -A 2 "Not After"

# Zkontrolovat topic ID
openssl x509 -in push_cert.pem -text -noout | grep -A 5 "Subject Alternative Name"
```

### Problém: SCEP enrollment selhává
**Řešení**: Zkontrolovat SCEP CA
```bash
# Test SCEP GetCACert
curl "http://localhost:8080/scep?operation=GetCACert" -o test_ca.der
openssl x509 -inform DER -in test_ca.der -text -noout | grep "Subject:"
```

## Lokace důležitých souborů

### Certifikáty
- `/home/microm/nanohub/certs/` - Všechny certifikáty
- `/home/microm/nanohub/scep-docker/depot/` - SCEP CA
- `/home/microm/nanohub/dep/` - DEP certifikáty

### Konfigurace
- `/etc/systemd/system/nanohub.service` - NanoHUB service
- `/etc/systemd/system/nanodep.service` - NanoDEP service
- `/etc/systemd/system/scep-docker.service` - SCEP service
- `/etc/systemd/system/nanocmd.service` - NanoCMD service

### Logy
- `/var/log/nanohub/nanohub.log` - NanoHUB logy
- `/var/log/nanohub/nanodep.log` - NanoDEP logy
- `/var/log/nanohub/scep-docker.log` - SCEP logy
- `/var/log/nanohub/nanocmd.log` - NanoCMD logy

## Důležité poznámky

1. **Backup certifikátů**: Vždy zálohovat certifikáty před obnovou
2. **Testování**: Vždy testovat na staging prostředí
3. **Monitoring**: Sledovat expiraci certifikátů
4. **Dokumentace**: Aktualizovat tento manual po změnách
5. **Časování**: Obnovovat certifikáty minimálně 30 dní před expirací
