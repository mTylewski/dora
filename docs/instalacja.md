# Instalacja i utrzymanie (dla administratora IT kancelarii)

Cel: instalacja w mniej niż 1 godzinę. Serwer, konto u dostawcy VPS i konto Claude API należą do kancelarii.

## Wymagania

- VPS w UE z Debianem 12, 4 vCPU, 8 GB RAM. OCR jest wymagający; przy dużej liczbie skanów lepiej więcej.
- Osobny dysk na dane (szyfrowany LUKS), np. 50 GB.
- Nazwa domenowa wskazująca na serwer (np. `claims.kancelaria.pl`) albo nazwa tylko wewnętrzna (wtedy `caddy_tls_internal: true`).
- Klucz API z konta Claude API kancelarii.
- Komputer z Ansible (≥ 2.15) i dostępem SSH do serwera.

## Instalacja

```bash
cd deploy/ansible
cp inventory.example.ini inventory.ini              # adres serwera, użytkownik
cp group_vars/all.example.yml group_vars/all.yml    # konfiguracja
ansible-vault encrypt_string --name vault_anthropic_api_key 'sk-ant-...' >> group_vars/all.yml
ansible-galaxy collection install ansible.posix
ansible-playbook -i inventory.ini site.yml --ask-vault-pass
```

W trakcie instalacji playbook poprosi o sformatowanie dysku danych jako LUKS. Hasło LUKS ustala kancelaria i przechowuje je w swoim menedżerze haseł.

Po instalacji utwórz pierwszego administratora:

```bash
docker compose -f /etc/claims/docker-compose.yml --env-file /srv/claims/config/.env \
  exec web python -m app.cli create-user admin@kancelaria.pl --role admin
```

Wyświetlony adres `otpauth://` dodaj do aplikacji uwierzytelniającej. Kolejnych użytkowników administrator zakłada w aplikacji: **Użytkownicy**.

Następnie administrator uzupełnia w aplikacji:
- **Kancelaria**: dane do pism, domyślny rachunek, wzór sygnatury spraw (np. `KAN/{rok}/{nr}`), lista prawników powiązanych z kontami;
- **Szablony**: szablony pism kancelarii (.docx z polami `{{...}}`), każdy jako osobny rodzaj pisma w kreatorze.

## Klucze — kopia zapasowa

`/srv/claims/config/.env.secrets` zawiera `CLAIMS_MAPPING_KEY`. Bez tego klucza zapisane sprawy są nieczytelne. Skopiuj go do menedżera haseł kancelarii.

## Zakończenie dostępu instalacyjnego

Jeśli instalację wykonuje dostawca:
1. Ustaw `installer_ssh_pubkey` w `group_vars/all.yml`. Ostatni krok playbooka usuwa ten klucz z serwera.
2. Kancelaria zmienia hasła do konta VPS i do konta Claude API.

Dostawca nie loguje się na serwer po wdrożeniu.

## Aktualizacje

Aktualizacje działają w modelu pull: serwer sam pobiera nowe wydanie i uruchamia je dopiero po weryfikacji podpisu kluczem publicznym dostawcy (`/etc/claims/cosign.pub`).

- **Tryb ręczny** (domyślny): administrator wpisuje nowe wydanie (obraz z `@sha256:…` z informacji o wydaniu) do `/etc/claims/release` i uruchamia `sudo claims-update`.
- **Tryb automatyczny**: `auto_update: true`. Timer `claims-update.timer` codziennie o 4:00 pobiera, weryfikuje i wdraża wydanie z `/etc/claims/release`.

Aktualizacje systemu operacyjnego robi `unattended-upgrades`, o ile serwery Debiana są na liście dozwolonych hostów.

## Restart serwera

Przy `luks_unlock: manual` po restarcie trzeba odblokować dysk danych i uruchomić usługi:

```bash
sudo cryptsetup open /dev/sdb claims_data
sudo mount /srv/claims
sudo systemctl start docker
```

Docker nie wystartuje, dopóki dysk danych nie jest zamontowany (`RequiresMountsFor`). Dzięki temu kontenery nie uruchomią się na pustym katalogu.

## Kontrole

- `systemctl status claims-firewall claims-egress-refresh.timer claims-purge.timer`
- `journalctl -k | grep claims-egress-drop` pokazuje zablokowany ruch wychodzący.
- `docker compose -f /etc/claims/docker-compose.yml --env-file /srv/claims/config/.env ps`
- Dziennik dostępu: w aplikacji, **Dziennik**.

## Konfiguracja merytoryczna

Pliki w `/srv/claims/config/app/` (po zmianie: `docker compose … restart web worker`):

- `calculator.yaml`: sposób liczenia dni, zatwierdzany przez prawnika.
- `statutory_interest.yaml`: tabele odsetek ustawowych, uzupełniane z obwieszczeń wraz ze źródłem.
- `letter.yaml`: dane kancelarii w piśmie, termin zapłaty, podstawa prawna.

Szablon pisma (.docx na papierze firmowym kancelarii) wgrywa administrator w aplikacji: **Szablony**. Ta sama strona opisuje dostępne pola `{{...}}` i pozwala pobrać szablon domyślny jako punkt wyjścia. Wgrany szablon leży na zaszyfrowanym wolumenie (`/srv/claims/files/templates/`).
- `models.yaml`: modele dla kroków analizy.
