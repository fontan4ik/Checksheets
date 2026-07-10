Товары и каталоги (1.0.0)
Элемент каталога
Метод предназначен для получения элемента иерархии каталогов товаров.

Authorizations:
Authorization
path Parameters
catalog_id
required
string <uuid> (Идентификатор каталога)
Responses
200
Запрос успешно выполнен

Response Schema: application/json
catalog_id
required
string <uuid> (Идентификатор элемента каталога)
name
required
string (Наименование элемента каталога)
parent_catalog_id
required
Идентификатор родительского элемента (string) or Идентификатор родительского элемента (null) (Идентификатор родительского элемента)
order
required
Порядок сортировки (integer) or Порядок сортировки (null) (Порядок сортировки)
401
Запрос не авторизован

404
Элемент каталога не существует

422
Ошибка валидации


get
/offers/catalogs/{catalog_id}

Примеры ответа
200422
Content type
application/json

Copy
{
"catalog_id": "de71ec92-2e85-49a4-a1c0-bcbd8d385f9e",
"name": "string",
"parent_catalog_id": "6af9e40a-e9d1-489c-a461-d2968926dbb3",
"order": 0
}
Иерархия каталога
Метод предназначен для получения иерархии каталогов товаров.

Authorizations:
Authorization
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Массив элементов каталога)
401
Запрос не авторизован

422
Ошибка валидации


get
/offers/catalogs

Примеры ответа
200422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{
"catalog_id": "de71ec92-2e85-49a4-a1c0-bcbd8d385f9e",
"name": "string",
"parent_catalog_id": "6af9e40a-e9d1-489c-a461-d2968926dbb3",
"order": 0
}
]
}
Фильтры каталога
Метод предназначен для получения доступных фильтров в каталоге.

Authorizations:
Authorization
Request Body schema: application/json
required
catalog_id	
Фильтр по идентификатору каталога (string) or Фильтр по идентификатору каталога (null) (Фильтр по идентификатору каталога)
catalog_deep_search	
boolean (В случае применения фильтра по идентификатору каталога искать в том числе в подкаталогах)
Default: true
filter_token	
Токен поиска (string) or Токен поиска (null) (Токен поиска)
size_name	
integer (Количество наименований элементов на странице) [ 10 .. 3000 ]
Default: 10
size_value	
integer (Количество значений элементов на странице) [ 10 .. 100 ]
Default: 10
statuses	
Array of strings (Статус товаров)
Default: ["regular","new"]
Items Enum: "undefined" "new" "regular" "archive"
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Массив фильтров)
filter_token
required
Токен для получения следующих результатов запроса по данному поиску (string) or Токен для получения следующих результатов запроса по данному поиску (null) (Токен для получения следующих результатов запроса по данному поиску)
401
Запрос не авторизован

422
Ошибка валидации


post
/offers/catalogs/filters

Примеры запроса
Payload
Content type
application/json

Copy
Expand allCollapse all
{
"catalog_id": "de71ec92-2e85-49a4-a1c0-bcbd8d385f9e",
"catalog_deep_search": true,
"filter_token": "string",
"size_name": 10,
"size_value": 10,
"statuses": [
"regular",
"new"
]
}
Примеры ответа
200422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{
"name": "string",
"doc_count_error_upper_bound": 0,
"sum_other_doc_count": 0,
"top_values": [],
"min_value": 0,
"max_value": 0,
"filter_value_token": "string"
}
],
"filter_token": "string"
}
Значения фильтра каталога
Метод предназначен для получения доступных значений для фильтра в каталоге.

Authorizations:
Authorization
Request Body schema: application/json
required
filter_value_token
required
string (Токен для получения следующих результатов запроса по данному поиску)
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Значения фильтра, сортированные по частоте)
filter_value_token
required
Токен для получения следующих результатов запроса по данному поиску (string) or Токен для получения следующих результатов запроса по данному поиску (null) (Токен для получения следующих результатов запроса по данному поиску)
401
Запрос не авторизован

422
Ошибка валидации


post
/offers/catalogs/filters/values

Примеры запроса
Payload
Content type
application/json

Copy
{
"filter_value_token": "string"
}
Примеры ответа
200422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{}
],
"filter_value_token": "string"
}
Поиск товаров
Метод предназначен для поиска товаров.

При первоначальном запросе требуется указать количество возвращаемых результатов в поле тела запроса size и при необходимости поля фильтров. Для осуществления пагинации необходимо передавать только поле search_token до тех пор, пока массив результатов не будет пуст.

Authorizations:
Authorization
Request Body schema: application/json
required
search_token	
Токен поиска (string) or Токен поиска (null) (Токен поиска)
size	
integer (Количество элементов на странице) [ 10 .. 3000 ]
Default: 10
order_by	
string (Order)
Default: "relevance"
Enum: "relevance" "vendor_code"
statuses	
Array of strings (Статус товаров)
Default: ["regular","new"]
Items Enum: "undefined" "new" "regular" "archive"
catalog_id	
Фильтр по идентификатору каталога (string) or Фильтр по идентификатору каталога (null) (Фильтр по идентификатору каталога)
catalog_deep_search	
boolean (В случае применения фильтра по идентификатору каталога искать в том числе в подкаталогах)
Default: true
multi_match	
Поисковый запрос использующий полнотекстовый поиск по всем полям (string) or Поисковый запрос использующий полнотекстовый поиск по всем полям (null) (Поисковый запрос использующий полнотекстовый поиск по всем полям)
vendor_code	
Поиск по артикулу товара (string) or Поиск по артикулу товара (null) (Поиск по артикулу товара)
name	
Поиск по наименованию товара (string) or Поиск по наименованию товара (null) (Поиск по наименованию товара)
brand	
Поиск по бренду (string) or Поиск по бренду (null) (Поиск по бренду)
model	
Поиск по наименованию модели (string) or Поиск по наименованию модели (null) (Поиск по наименованию модели)
description	
Поиск по описанию товара (string) or Поиск по описанию товара (null) (Поиск по описанию товара)
name_in_doc	
Поиск запрос по полному наименованию товара (string) or Поиск запрос по полному наименованию товара (null) (Поиск запрос по полному наименованию товара)
product_category	
Поиск по категории товара (string) or Поиск по категории товара (null) (Поиск по категории товара)
manufacturer_country	
Поиск по стране производителю (string) or Поиск по стране производителю (null) (Поиск по стране производителю)
package_multiplier	
Поиск по кратности упаковки (string) or Поиск по кратности упаковки (null) (Поиск по кратности упаковки)
properties	
Array of objects (Фильтрация по свойствам)
Default: []
product_id	
Array of Фильтрация по идентификаторам продуктов (strings) or Фильтрация по идентификаторам продуктов (null) (Фильтрация по идентификаторам продуктов)
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Массив результатов поиска товаров)
search_token
required
Токен для получения следующих результатов запроса по данному поиску (string) or Токен для получения следующих результатов запроса по данному поиску (null) (Токен для получения следующих результатов запроса по данному поиску)
401
Запрос не авторизован

422
Ошибка валидации


post
/offers/products/search

Примеры запроса
Payload
Content type
application/json

Copy
Expand allCollapse all
{
"search_token": "string",
"size": 10,
"order_by": "relevance",
"statuses": [
"regular",
"new"
],
"catalog_id": "de71ec92-2e85-49a4-a1c0-bcbd8d385f9e",
"catalog_deep_search": true,
"multi_match": "string",
"vendor_code": "string",
"name": "string",
"brand": "string",
"model": "string",
"description": "string",
"name_in_doc": "string",
"product_category": "string",
"manufacturer_country": "string",
"package_multiplier": "string",
"properties": [ ],
"product_id": [
"497f6eca-6276-4993-bfeb-53cbbbba6f08"
]
}
Примеры ответа
200422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{}
],
"search_token": "string"
}
Поиск связанных товаров
Метод предназначен для поиска сопутствующих товаров.

При первоначальном запросе требуется указать количество возвращаемых результатов в поле тела запроса size и при необходимости поля фильтров. Для осуществления пагинации необходимо передавать только поле search_token до тех пор, пока массив результатов не будет пуст.

Authorizations:
Authorization
Request Body schema: application/json
required
search_token	
Токен поиска (string) or Токен поиска (null) (Токен поиска)
size	
integer (Количество элементов на странице) [ 10 .. 3000 ]
Default: 10
order_by	
string (Order)
Default: "relevance"
Enum: "relevance" "vendor_code"
statuses	
Array of strings (Статус товаров)
Default: ["regular","new"]
Items Enum: "undefined" "new" "regular" "archive"
product_id	
Поиск связанных товаров (string) or Поиск связанных товаров (null) (Поиск связанных товаров)
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Массив результатов поиска товаров)
search_token
required
Токен для получения следующих результатов запроса по данному поиску (string) or Токен для получения следующих результатов запроса по данному поиску (null) (Токен для получения следующих результатов запроса по данному поиску)
401
Запрос не авторизован

404
Продукт не найден

422
Ошибка валидации


post
/offers/products/related/search

Примеры запроса
Payload
Content type
application/json

Copy
Expand allCollapse all
{
"search_token": "string",
"size": 10,
"order_by": "relevance",
"statuses": [
"regular",
"new"
],
"product_id": "0d012afa-f885-4e65-aeca-37e27701e2d1"
}
Примеры ответа
200404422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{
"product_id": "0d012afa-f885-4e65-aeca-37e27701e2d1",
"status": "undefined",
"vendor_code": "string",
"name": "string",
"brand": "string",
"model": "string",
"images": [],
"description": "string",
"guarantee": "string",
"name_in_doc": "string",
"product_category": "string",
"product_type": 0,
"manufacturer_country": "string",
"properties": [],
"files": [],
"package_multiplier": "string",
"offer_minimal_multiplier": 0,
"similar_product_id": [],
"related_product_id": [],
"bar_code": "string"
}
],
"search_token": "string"
}
Поиск аналогов
Метод предназначен для поиска товаров.

При первоначальном запросе требуется указать количество возвращаемых результатов в поле тела запроса size и при необходимости поля фильтров. Для осуществления пагинации необходимо передавать только поле search_token до тех пор, пока массив результатов не будет пуст.

Authorizations:
Authorization
Request Body schema: application/json
required
search_token	
Токен поиска (string) or Токен поиска (null) (Токен поиска)
size	
integer (Количество элементов на странице) [ 10 .. 3000 ]
Default: 10
order_by	
string (Order)
Default: "relevance"
Enum: "relevance" "vendor_code"
statuses	
Array of strings (Статус товаров)
Default: ["regular","new"]
Items Enum: "undefined" "new" "regular" "archive"
similar	
Поисковый запрос по аналогам товаров (string) or Поисковый запрос по аналогам товаров (null) (Поисковый запрос по аналогам товаров)
Responses
200
Запрос успешно выполнен

Response Schema: application/json
items
required
Array of objects (Массив результатов поиска товаров)
search_token
required
Токен для получения следующих результатов запроса по данному поиску (string) or Токен для получения следующих результатов запроса по данному поиску (null) (Токен для получения следующих результатов запроса по данному поиску)
401
Запрос не авторизован

422
Ошибка валидации


post
/offers/products/similar/search

Примеры запроса
Payload
Content type
application/json

Copy
Expand allCollapse all
{
"search_token": "string",
"size": 10,
"order_by": "relevance",
"statuses": [
"regular",
"new"
],
"similar": "string"
}
Примеры ответа
200422
Content type
application/json

Copy
Expand allCollapse all
{
"items": [
{
"product_id": "0d012afa-f885-4e65-aeca-37e27701e2d1",
"status": "undefined",
"vendor_code": "string",
"name": "string",
"brand": "string",
"model": "string",
"images": [],
"description": "string",
"guarantee": "string",
"name_in_doc": "string",
"product_category": "string",
"product_type": 0,
"manufacturer_country": "string",
"properties": [],
"files": [],
"package_multiplier": "string",
"offer_minimal_multiplier": 0,
"similar_product_id": [],
"related_product_id": [],
"bar_code": "string"
}
],
"search_token": "string"
}
Получение товара
Метод предназначен для получения данных по товару по его идентификатору, содержащемуся в поле product_id.

Authorizations:
Authorization
path Parameters
product_id
required
string <uuid> (Product Id)
Идентификатор продукта

Responses
200
Запрос успешно выполнен

Response Schema: application/json
product_id
required
string <uuid> (Идентификатор товара)
status
required
string (Status)
Enum: "undefined" "new" "regular" "archive"
vendor_code
required
string (Артикул товара)
name
required
string (Наименование товара)
brand
required
string (Бренд товара)
model
required
string (Модель товара)
images
required
Array of strings (Массив ссылок на изображения товара)
description
required
string (Описание товара)
guarantee
required
string (Гарантия)
name_in_doc
required
string (Наименование товара для документов)
product_category
required
string (Категория товара)
product_type
required
integer (Тип товара)
manufacturer_country
required
string (Страна производства товара)
properties
required
Array of objects (Массив свойств товара)
files
required
Array of objects (Массив ссылок на файлы товара)
package_multiplier
required
string (Кратность упаковок товара)
offer_minimal_multiplier
required
integer (Кратность отгрузки товара)
similar_product_id
required
Array of strings <uuid> (Идентификаторы аналогичных товаров) [ items <uuid > ]
related_product_id
required
Array of strings <uuid> (Идентификаторы сопутствующих товаров) [ items <uuid > ]
bar_code
required
string (Бар-код)
401
Запрос не авторизован

404
Товар не найден

422
Ошибка валидации


get
/offers/products/{product_id}

Примеры ответа
200404422
Content type
application/json

Copy
Expand allCollapse all
{
"product_id": "0d012afa-f885-4e65-aeca-37e27701e2d1",
"status": "undefined",
"vendor_code": "string",
"name": "string",
"brand": "string",
"model": "string",
"images": [
"string"
],
"description": "string",
"guarantee": "string",
"name_in_doc": "string",
"product_category": "string",
"product_type": 0,
"manufacturer_country": "string",
"properties": [
{}
],
"files": [
{}
],
"package_multiplier": "string",
"offer_minimal_multiplier": 0,
"similar_product_id": [
"497f6eca-6276-4993-bfeb-53cbbbba6f08"
],
"related_product_id": [
"497f6eca-6276-4993-bfeb-53cbbbba6f08"
],
"bar_code": "string"
}
Архивы
Архивы

Authorizations:
Authorization
Responses
200
Successful Response

Response Schema: application/json
property name*
additional property
string

get
/offers/archives

Примеры ответа
200
Content type
application/json

Copy
{
"property1": "string",
"property2": "string"
}