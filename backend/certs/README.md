# CA Минцифры для MAX Bot API

`platform-api2.max.ru` использует цепочку **Russian Trusted CA**.  
Стандартный `certifi` её не содержит → `CERTIFICATE_VERIFY_FAILED`.

Файлы скачаны с https://gu-st.ru (портал Госуслуг / НУЦ):

- `russian_trusted_root_ca.crt`
- `russian_trusted_sub_ca.crt`
- `russian_trusted_ca_bundle.pem` — оба в одном PEM

При `MAX_API_VERIFY_SSL=true` приложение само собирает бандл
`data/cacert_with_russian_trusted.pem` (certifi + эти CA).

На Ubuntu дополнительно: `sudo bash scripts/install-russian-ca.sh`
