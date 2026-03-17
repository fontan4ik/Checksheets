import requests
import json

client_id = '142355'
api_key = 'fe539630-170b-4b48-b222-8ba092907a63'
wb_token = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA'

def list_ozon():
    url = 'https://api-seller.ozon.ru/v1/warehouse/list'
    headers = {
        'Client-Id': client_id,
        'Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    response = requests.post(url, headers=headers, json={})
    print('OzonWarehouses:', json.dumps(response.json().get('result', []), indent=2))

def list_wb():
    url = 'https://marketplace-api.wildberries.ru/api/v3/warehouses'
    headers = {
        'Authorization': 'Bearer ' + wb_token
    }
    response = requests.get(url, headers=headers)
    print('WBWarehouses:', json.dumps(response.json(), indent=2))

if __name__ == '__main__':
    list_ozon()
    list_wb()
