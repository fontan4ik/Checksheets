$headers = @{
    "Client-Id" = "142355"
    "Api-Key" = "fe539630-170b-4b48-b222-8ba092907a63"
    "Content-Type" = "application/json"
}
$body = @{ limit = 200 } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "https://api-seller.ozon.ru/v1/warehouse/list" -Method Post -Headers $headers -Body $body
$response.result | ForEach-Object { "$($_.name) | $($_.warehouse_id)" }
