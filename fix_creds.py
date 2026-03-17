import json

creds = {
  "type": "service_account",
  "project_id": "seo-pipline",
  "private_key_id": "f87f76243a9a9d363e5a064bb54c3674744b3553",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEugIBADANBgkqhkiG9w0BAQEFAASCBKQwggSgAgEAAoIBAQDGpqDomm7pkaI8\nxdB7mQVAgDAxhIE7T0AjWRQ0lWjWL1F4f1CTTbaJW8tQLqipmzO6CXIBmNFu3/n3\niKzI+TBHh/s71OqojZG3sxTmJI9n+4sPbn5Si4BwJV3+afDrxREyBuwSKaRqBFEb\n5yKRhw9mhjuKg5N67ppuGgNyfPAmNBvGr9UGsPtF+yhzK6rvBKU8LGNa7fOutOSx\nkSL03tuDVLb3cwCzifBH2s/NRnR+I8SfqyYPOu/k7fGjemX6TTZWBwf6yvi91nMS\nAYGPm/KwXkdHoWVU7d3+3Jb666MvG8b4PfBocWZ84nmqmU548I08bgoLdB58y1Oy\nFUOq7fAvAgMBAAECggEAD7xwX6yoH5F9SBIldz0CaP8ekjWcZR3ch1BNpPK2+MyL\nyB9RuzF7RbtDSkk/7BuSx+hqowy/fmh4rS6i/VKcC/aOJMmzgwGf6uzhOW/o+kQ3\nWlQW5qQNWxTisr4iqxKTz6IzviaVUx6fbDXti5im1CjK+6h7nM/c5N7jqgSSo3v2\nSEqkOX6av5IX3PJWClQJTGqoTiVZB9k2QlYKam/amIuIzu1CZMJtbgFvhmk5Aw/n\nLcsHyuATBBDc3s9/IRDRnWjZxpGagGVQqSE52ixRZZTrvepB4cwUEaMSYH5TcF9m\nnjsaNQdIs4Ka7DpjwSG93v/HAhPH7PSLy+Z5XVS+nQKBgQD8iisCQw6vtI8eSOcd\nSyIjqKYP+H40dbIQBRqRvC4EDs6hz+9lyZG0cuVnXzIGvl5Z5InrI7KsicfImJev\ly9FmYaYA25qQFw+TL4vnSU9xQrU17AH8oUJsIKdpK72K5pYZZRipjQtniy0GH1p\nZ1rLXuPIiN3aQY6mN6VspMrswwKBgQDJX29fPt8b2cUGfUxeqblyvGGgirdjP0+a\nb0DBkoXXKg6iEEKrwLrB/JySbRsji80Y/Nn+41porYeaTV0n0y37eZZ+vS4aEOcb\nhp5TO/QzYhn1apezudcrjUpdwZo/XCzjVfL7P4ovlb0fWa5spjWshr6mHMtGr3DP\n4CckVEPoJQKBgGQKsCMDQYwlcRTEOJoIK4wIwVBOVmCdx15FR1M4Qtpkq0K6xtGB\n2nCrm2kp8v1s6J+fw2sdBykGo9g5as2qjJV7zi/mHBWHTYN4j1b5X8lqh3Htx9Q+\nJKnD/NpKZO0sNMaT5wZ1ZPI1WOw3T2c0BGnQO1gzr/9IPSRnoua5GZJVAoGAUMFu\n/nlOK/MXKlURTV0vO64EUMeQZ8K5/6riAz7pYbJCEAgJVKuDucu+VpJesdCcvYqZ\nObifRx9gJCcmVpQ/+nt2OPlRBa8Fn2pLEAIZGooa8up+T9sVSSfuTM8ZNpOWhMyx\nFsUSe6bHI01pv7SgDcIzrpYZhw1QZmz0BYOtf+kCfx+REWetNjJ4Z/gl8rzPncqd\haLhEwqY58hKXd1Gs5WoDyU74EBDkMi91mCOEJrQQs/m+U6KRKvZZBoHEoBuY+UO\noylChbe3Iw/f2sdml7z1xXQZtJdOUCdRniHt6NW/sCV1OIcf5PYL4JAl1RhrWLX1\nIT0GYEzFsw9+26mxlR8=\n-----END PRIVATE KEY-----\n",
  "client_email": "seo-pipline@seo-pipline.iam.gserviceaccount.com",
  "client_id": "116216456011406269643",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/seo-pipline%40seo-pipline.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

with open(r"c:\AI\Работа Voltmir\Проверка таблицы\gsheets_creds.json", "w", encoding="utf-8") as f:
    json.dump(creds, f, indent=2)

print("File gsheets_creds.json rewritten successfully.")
