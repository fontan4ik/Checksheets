Feron клиентский API
 1.0.0 
OAS3
REST API комании Feron предназначен для получения списка товаров, описания, свойств и остатков товаров в базе Feron, посредством HTTPS-запросов.

Authorize
Товары


POST
/v1/products/list
Получает данные списка товаров, с опциональным фильтром по артикулам

Parameters
Cancel
No parameters

Request body

application/json
{
  "filter": [
    "48546",
    "38269"
  ]
}
Execute
Clear
Responses
Curl

curl -X 'POST' \
  'https://clientapi.shop.feron.ru/v1/products/list' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx' \
  -H 'Content-Type: application/json' \
  -d '{
  "filter": [
    "48546",
    "38269"
  ]
}'
Request URL
https://clientapi.shop.feron.ru/v1/products/list
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:12:20 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
[
  {
    "code": "38269",
    "brand": "FERON",
    "model": "AL164",
    "name": "LB-474 (25W) 230V GX70 4000K, для натяжных потолков",
    "printName": "Лампа cветодиодная, (25W) 230V GX70 4000K, LB-474",
    "description": "Светильники трековые на шинопровод GX53, однофазный (ИВО) FERON AL164, 15W, 230V, цвет белый, корпус алюминий, вращение →350°/↓90°, 92*92*55 мм",
    "packing_ratio": 1,
    "packing_unit": "шт",
    "properties": [
      {
        "name": "Мощность, Вт",
        "value": "15"
      },
      {
        "name": "Тип лампы",
        "value": "GX53"
      },
      {
        "name": "Напряжение, Вольт",
        "value": "230"
      },
      {
        "name": "Материал корпуса",
        "value": "алюминий"
      }
    ],
    "images": [
      "https://shop.feron.ru/upload/iblock/6da/8flk2etl4useyou64y6v5n8silb9w2r0.jpg",
      "https://shop.feron.ru/upload/iblock/470/470a8c82a254a8d51c27d2893ecf26b8.jpg",
      "https://shop.feron.ru/upload/iblock/8ad/rlry8bhgxqt708d40qcddm6xcijiaukt.jpg"
    ],
    "files": [
      {
        "type": "certificate",
        "value": "https://feron.ru/postup/certificate/01381 Лампы светодиодные тм Feron, серия  LB. Сертификат по 004 и 020_1.pdf"
      },
      {
        "type": "declaration",
        "value": "https://feron.ru/postup/certificate/87137 Лампы светодиодные  тм Feron серия  LB Декларация по 037_1.jpg"
      },
      {
        "type": "manual",
        "value": "https://feron.ru/instructions/инструкция филаментные лампы.docx"
      }
    ]
  }
]
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links

GET
/v1/products/{code}
Получает данные существующего товара по его артикулу

Parameters
Cancel
Name	Description
code *
string
(path)
Артикул товара

38269
Execute
Clear
Responses
Curl

curl -X 'GET' \
  'https://clientapi.shop.feron.ru/v1/products/38269' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx'
Request URL
https://clientapi.shop.feron.ru/v1/products/38269
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:12:06 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
{
  "code": "38269",
  "brand": "FERON",
  "model": "AL164",
  "name": "LB-474 (25W) 230V GX70 4000K, для натяжных потолков",
  "printName": "Лампа cветодиодная, (25W) 230V GX70 4000K, LB-474",
  "description": "Светильники трековые на шинопровод GX53, однофазный (ИВО) FERON AL164, 15W, 230V, цвет белый, корпус алюминий, вращение →350°/↓90°, 92*92*55 мм",
  "packing_ratio": 1,
  "packing_unit": "шт",
  "properties": [
    {
      "name": "Мощность, Вт",
      "value": "15"
    },
    {
      "name": "Тип лампы",
      "value": "GX53"
    },
    {
      "name": "Напряжение, Вольт",
      "value": "230"
    },
    {
      "name": "Материал корпуса",
      "value": "алюминий"
    }
  ],
  "images": [
    "https://shop.feron.ru/upload/iblock/6da/8flk2etl4useyou64y6v5n8silb9w2r0.jpg",
    "https://shop.feron.ru/upload/iblock/470/470a8c82a254a8d51c27d2893ecf26b8.jpg",
    "https://shop.feron.ru/upload/iblock/8ad/rlry8bhgxqt708d40qcddm6xcijiaukt.jpg"
  ],
  "files": [
    {
      "type": "certificate",
      "value": "https://feron.ru/postup/certificate/01381 Лампы светодиодные тм Feron, серия  LB. Сертификат по 004 и 020_1.pdf"
    },
    {
      "type": "declaration",
      "value": "https://feron.ru/postup/certificate/87137 Лампы светодиодные  тм Feron серия  LB Декларация по 037_1.jpg"
    },
    {
      "type": "manual",
      "value": "https://feron.ru/instructions/инструкция филаментные лампы.docx"
    }
  ]
}
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
404	
Not found

Media type

application/json
Example Value
Schema
{
  "statusCode": 404,
  "message": "Not found error message",
  "error": "Not found"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links
Остатки


POST
/v1/stocks/list
Получает остатки списка товаров, с опциональным фильтром по артикулам

Parameters
Cancel
No parameters

Request body

application/json
{
  "filter": [
    "48546",
    "38269"
  ]
}
Execute
Clear
Responses
Curl

curl -X 'POST' \
  'https://clientapi.shop.feron.ru/v1/stocks/list' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx' \
  -H 'Content-Type: application/json' \
  -d '{
  "filter": [
    "48546",
    "38269"
  ]
}'
Request URL
https://clientapi.shop.feron.ru/v1/stocks/list
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:11:59 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
[
  {
    "code": "38269",
    "stocks": [
      {
        "warehouse": "moscow",
        "stock": 2500,
        "overLimit": true
      },
      {
        "warehouse": "novosibirsk",
        "stock": 1200,
        "overLimit": false
      }
    ]
  }
]
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links

GET
/v1/stocks/{code}
Получает остатки существующего товара по его артикулу

Parameters
Cancel
Name	Description
code *
string
(path)
Артикул товара

38269
Execute
Clear
Responses
Curl

curl -X 'GET' \
  'https://clientapi.shop.feron.ru/v1/stocks/38269' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx'
Request URL
https://clientapi.shop.feron.ru/v1/stocks/38269
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:11:50 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
{
  "code": "38269",
  "stocks": [
    {
      "warehouse": "moscow",
      "stock": 2500,
      "overLimit": true
    },
    {
      "warehouse": "novosibirsk",
      "stock": 1200,
      "overLimit": false
    }
  ]
}
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
404	
Not found

Media type

application/json
Example Value
Schema
{
  "statusCode": 404,
  "message": "Not found error message",
  "error": "Not found"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links
Цены


POST
/v1/prices/list
Получает цены списка товаров, с опциональным фильтром по артикулам

Parameters
Cancel
No parameters

Request body

application/json
{
  "filter": [
    "48546",
    "38269"
  ]
}
Execute
Clear
Responses
Curl

curl -X 'POST' \
  'https://clientapi.shop.feron.ru/v1/prices/list' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx' \
  -H 'Content-Type: application/json' \
  -d '{
  "filter": [
    "48546",
    "38269"
  ]
}'
Request URL
https://clientapi.shop.feron.ru/v1/prices/list
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:11:39 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
[
  {
    "code": "38269",
    "prices": [
      {
        "type": "rrc",
        "price": 1250.42
      },
      {
        "type": "mic",
        "price": 665.4
      }
    ]
  }
]
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links

GET
/v1/prices/{code}
Получает цены существующего товара по его артикулу

Исходящие отчеты


POST
/v1/reports/sellout
Предназначен для пересылки в компанию Ферон отчетных данных по продажам за указанные периоды

Parameters
Cancel
No parameters

Request body

application/json
{
  "salesData": [
    {
      "regionCode": 77,
      "regionString": "Москва",
      "federalDistrict": "ЦФО",
      "year": 2023,
      "month": 2,
      "productCode": "abc_12345",
      "feronProductCode": "48546",
      "productName": "FERON AL164 светильник трековый под лампу GX53, белый",
      "feronProductName": "AL164 светильник трековый под лампу GX53, белый",
      "revenue": 123456.78,
      "value": 43456.78,
      "quantity": 255
    }
  ]
}
Execute
Clear
Responses
Curl

curl -X 'POST' \
  'https://clientapi.shop.feron.ru/v1/reports/sellout' \
  -H 'accept: application/json' \
  -H 'API-KEY: MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx' \
  -H 'Content-Type: application/json' \
  -d '{
  "salesData": [
    {
      "regionCode": 77,
      "regionString": "Москва",
      "federalDistrict": "ЦФО",
      "year": 2023,
      "month": 2,
      "productCode": "abc_12345",
      "feronProductCode": "48546",
      "productName": "FERON AL164 светильник трековый под лампу GX53, белый",
      "feronProductName": "AL164 светильник трековый под лампу GX53, белый",
      "revenue": 123456.78,
      "value": 43456.78,
      "quantity": 255
    }
  ]
}'
Request URL
https://clientapi.shop.feron.ru/v1/reports/sellout
Server response
Code	Details
401	
Error: Unauthorized

Response body
Download
{
  "statusCode": 401,
  "message": "Unauthorized"
}
Response headers
 connection: keep-alive 
 content-length: 43 
 content-type: application/json; charset=utf-8 
 date: Fri,06 Feb 2026 16:11:22 GMT 
 etag: W/"2b-hGShxOkieaAVDloBubJVM+h58D8" 
 server: nginx/1.18.0 (Ubuntu) 
 x-powered-by: Express 
Responses
Code	Description	Links
200	
Success

Media type

application/json
Controls Accept header.
Example Value
Schema
{}
No links
400	
Bad Request

Media type

application/json
Example Value
Schema
{
  "statusCode": 400,
  "message": [
    "Bad Request error message"
  ],
  "error": "Bad Request"
}
No links
401	
Unauthorized

Media type

application/json
Example Value
Schema
{
  "statusCode": 401,
  "message": "Unauthorized"
}
No links
500	
Internal server error

Media type

application/json
Example Value
Schema
{
  "statusCode": 500,
  "message": "Internal server error"
}
No links
