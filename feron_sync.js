var FERON_API_KEY = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx";
var FERON_BASE_URL = "https://api.feron.ru";
var FERON_SHEET_NAME = "тест";

var WAREHOUSES = {
  "Самара": "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7",
  "Внуково": "de099cee-372a-11ef-96b6-a4bf0186f0c7",
  "Новосибирск": "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7",
};

var SHEET_COLUMNS = {
  "Самара": "Ферон Самара",
  "Внуково": "Ферон Внуково",
  "Новосибирск": "Ферон Новосибирск",
};

function getFeronApiKey() {
  if (!FERON_API_KEY) {
    var userProps = PropertiesService.getUserProperties();
    FERON_API_KEY = userProps.getProperty("FERON_API_KEY");
  }
  return FERON_API_KEY;
}

function setFeronApiKey(apiKey) {
  FERON_API_KEY = apiKey;
  var userProps = PropertiesService.getUserProperties();
  userProps.setProperty("FERON_API_KEY", apiKey);
}

function fetchAllFeronData(apiKey) {
  var headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer " + apiKey,
  };

  var productsMap = {};
  var searchToken = "";

  Logger.log("--- Fetching all products from Feron catalog ---");
  Logger.log("API Key prefix check: " + apiKey.substring(0, 10));

  for (var i = 0; i < 100; i++) {
    var url = FERON_BASE_URL + "/offers/products/search";
    var payload;
    if (searchToken) {
      payload = { "search_token": searchToken };
    } else {
      payload = { "size": 3000 };
    }

    var options = {
      "method": "post",
      "headers": headers,
      "payload": JSON.stringify(payload),
      "muteHttpExceptions": true,
    };

    var response = UrlFetchApp.fetch(url, options);

    if (response.getResponseCode() === 429) {
      Logger.log("Rate limit hit during search, waiting 10s...");
      Utilities.sleep(10000);
      response = UrlFetchApp.fetch(url, options);
    }

    if (response.getResponseCode() !== 200) {
      Logger.log("Error fetching products: " + response.getResponseCode() + " " + response.getContentText());
      break;
    }

    var data = JSON.parse(response.getContentText());
    var items = data.items || [];
    for (var j = 0; j < items.length; j++) {
      var item = items[j];
      var pId = item.product_id;
      var vCode = item.vendor_code;
      if (pId && vCode) {
        productsMap[pId] = String(vCode).trim();
      }
    }

    var newToken = data.search_token;
    if (!newToken || newToken === searchToken) {
      break;
    }
    searchToken = newToken;

    if (items.length === 0) {
      break;
    }
  }

  Logger.log("Found " + Object.keys(productsMap).length + " unique products in Feron catalog.");

  var allStocks = {};
  var productIds = Object.keys(productsMap);

  Logger.log("--- Fetching quantities for all products in bulk ---");
  var chunkSize = 500;

  for (var i = 0; i < productIds.length; i += chunkSize) {
    var chunk = productIds.slice(i, i + chunkSize);
    var url = FERON_BASE_URL + "/quantities/search";
    var payload = { "products_id": chunk };

    var options = {
      "method": "post",
      "headers": headers,
      "payload": JSON.stringify(payload),
      "muteHttpExceptions": true,
    };

    var response = UrlFetchApp.fetch(url, options);

    if (response.getResponseCode() === 429) {
      Logger.log("Rate limit hit during quantity fetch (index " + i + "), waiting 10s...");
      Utilities.sleep(10000);
      response = UrlFetchApp.fetch(url, options);
    }

    if (response.getResponseCode() !== 200) {
      Logger.log("Error fetching quantities: " + response.getResponseCode());
      continue;
    }

    var data = JSON.parse(response.getContentText());
    var items = data.items || [];
    for (var j = 0; j < items.length; j++) {
      var item = items[j];
      var pId = item.product_id;
      var wId = item.warehouse_id;
      var qtyData = item.value || {};
      var qty = qtyData.quantity || 0;

      var vCode = productsMap[pId];
      if (vCode) {
        if (!allStocks[vCode]) {
          allStocks[vCode] = {};
        }
        try {
          var val = parseInt(qty, 10);
          if (isNaN(val)) val = 0;
          allStocks[vCode][wId] = Math.max(0, val);
        } catch (e) {
          allStocks[vCode][wId] = 0;
        }
      }
    }

    var progress = Math.min(i + chunkSize, productIds.length);
    Logger.log("  Progress: " + progress + "/" + productIds.length + " articles processed");
  }

  return allStocks;
}

function syncFeron() {
  Logger.log("============================================================");
  Logger.log("STARTING FERON STOCK SYNCHRONIZATION (BULK MODE)");
  Logger.log("============================================================");

  var apiKey = getFeronApiKey();
  if (!apiKey) {
    Logger.log("ERROR: Feron API key not found. Please run setFeronApiKey('your_key') first.");
    return;
  }

  var allFeronStocks = fetchAllFeronData(apiKey);

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheetName = FERON_SHEET_NAME;
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    Logger.log("ERROR: Sheet '" + sheetName + "' not found.");
    return;
  }

  var lastRow = sheet.getLastRow();
  var vendorCodes = [];
  if (lastRow > 1) {
    var range = sheet.getRange(2, 2, lastRow - 1, 1);
    var values = range.getValues();
    for (var i = 0; i < values.length; i++) {
      vendorCodes.push(values[i][0]);
    }
  }
  Logger.log("Successfully loaded " + vendorCodes.length + " articles from column B");

  for (var whName in WAREHOUSES) {
    var whId = WAREHOUSES[whName];
    var colName = SHEET_COLUMNS[whName];
    if (!colName) continue;

    Logger.log("Processing warehouse: " + whName + " (ID: " + whId + ")");

    var stats = { "matched": 0, "not_found": 0, "non_zero": 0 };
    var formattedResults = [];

    for (var i = 0; i < vendorCodes.length; i++) {
      var codeStr = String(vendorCodes[i]).trim();
      if (!codeStr) {
        formattedResults.push([0]);
        continue;
      }

      var stocksForCode = allFeronStocks[codeStr];
      if (stocksForCode !== undefined) {
        stats.matched++;
        var qty = stocksForCode[whId] || 0;
        formattedResults.push([qty]);
        if (qty > 0) stats.non_zero++;
      } else {
        stats.not_found++;
        formattedResults.push([0]);
      }
    }

    Logger.log("  - Match Rate: " + stats.matched + "/" + vendorCodes.length + " articles found in API");
    Logger.log("  - Inventory: " + stats.non_zero + " articles have stock > 0");

    try {
      var colIndex = getColumnByHeader(sheet, colName);
      if (colIndex === -1) {
        Logger.log("  - ERROR: Column '" + colName + "' not found.");
        continue;
      }

      Logger.log("  - Updating Google Sheet column '" + colName + "'...");
      var updateRange = sheet.getRange(2, colIndex, formattedResults.length, 1);
      updateRange.setValues(formattedResults);
      Logger.log("  - OK: Warehouse " + whName + " updated successfully.");
    } catch (e) {
      Logger.log("  - ERROR: Failed to update " + whName + ": " + e);
    }
  }

  Logger.log("============================================================");
  Logger.log("FERON STOCK SYNCHRONIZATION COMPLETED");
  Logger.log("============================================================");
}

function getColumnByHeader(sheet, headerName) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  for (var i = 0; i < headers.length; i++) {
    if (String(headers[i]).trim() === headerName) {
      return i + 1;
    }
  }
  return -1;
}

function testFeronConnection() {
  var apiKey = getFeronApiKey();
  if (!apiKey) {
    Logger.log("ERROR: Feron API key not set. Run setFeronApiKey('your_key') first.");
    return;
  }

  var headers = {
    "Accept": "application/json",
    "Authorization": "Bearer " + apiKey,
  };

  var url = FERON_BASE_URL + "/offers/products/search";
  var payload = { "size": 10 };

  var options = {
    "method": "post",
    "headers": headers,
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true,
  };

  var response = UrlFetchApp.fetch(url, options);
  var code = response.getResponseCode();

  Logger.log("API Test Result:");
  Logger.log("  Status Code: " + code);
  Logger.log("  Response: " + response.getContentText().substring(0, 500));

  if (code === 200) {
    Logger.log("  Status: SUCCESS - API key is valid");
  } else if (code === 401) {
    Logger.log("  Status: FAILED - Invalid API key");
  } else {
    Logger.log("  Status: ERROR - Check API key and try again");
  }
}