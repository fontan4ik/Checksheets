import requests
import json

token = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA'

headers = {
    'Authorization': token,
    'Content-Type': 'application/json'
}

url = 'https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products'

payload = {
    "currentPeriod": {
        "start": "2026-02-02",
        "end": "2026-03-02"
    },
    "stockType": "wb",
    "skipDeletedNm": False,
    "orderBy": {
        "field": "ordersCount",
        "mode": "desc"
    },
    "limit": 2,
    "offset": 0
}

res = requests.post(url, headers=headers, json=payload)
print(res.status_code)
print(res.text[:500])
