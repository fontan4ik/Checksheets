const https = require("https");
require("dotenv").config();

// Получаем credentials
const clientId = process.env.OZON_CLIENT_ID || "142355";
const apiKey = process.env.OZON_API_KEY || "fe539630-170b-4b48-b222-8ba092907a63";

console.log("Using Client-ID:", clientId);
console.log("Using Api-Key:", apiKey.substring(0, 10) + "...");

// Функция для выполнения запроса с детальным логированием
function makeRequest(path, method = "POST", body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: "api-seller.ozon.ru",
      path: path,
      method: method,
      headers: {
        "Client-Id": clientId,
        "Api-Key": apiKey,
        "Content-Type": "application/json",
      },
    };

    console.log(`\nMaking ${method} request to ${options.hostname}${path}`);
    console.log("Headers:", JSON.stringify(options.headers, null, 2));
    if (body) {
      console.log("Body:", JSON.stringify(body, null, 2));
    }

    const req = https.request(options, (res) => {
      console.log(`\nResponse status: ${res.statusCode}`);
      console.log("Response headers:", JSON.stringify(res.headers, null, 2));
      
      let data = "";

      res.on("data", (chunk) => {
        data += chunk;
      });

      res.on("end", () => {
        console.log(`\nResponse body (${data.length} chars):`);
        console.log(data.substring(0, 500) + (data.length > 500 ? "..." : ""));
        
        try {
          const response = JSON.parse(data);
          resolve(response);
        } catch (e) {
          console.error("Error parsing JSON:", e.message);
          resolve(data); // возвращаем неструктурированный ответ
        }
      });
    });

    req.on("error", (error) => {
      console.error("Request error:", error.message);
      reject(error);
    });

    if (body) {
      req.write(JSON.stringify(body));
    }

    req.end();
  });
}

// Тестируем разные endpoints
async function testEndpoints() {
  console.log("=" .repeat(60));
  console.log("Testing Ozon API endpoints");
  console.log("=" .repeat(60));

  // Тест 1: Проверяем доступность API с простым запросом
  try {
    console.log("\n1. Testing basic connectivity...");
    await makeRequest("/v1/warehouse/list", "POST", {
      limit: 1,
      offset: 0,
      status: "ACTIVE"
    });
  } catch (error) {
    console.error("Test 1 failed:", error.message);
  }

  // Тест 2: Пробуем другие версии API
  try {
    console.log("\n2. Testing v2 warehouse endpoint...");
    await makeRequest("/v2/warehouse/list", "POST", {
      limit: 1,
      offset: 0
    });
  } catch (error) {
    console.error("Test 2 failed:", error.message);
  }

  // Тест 3: Пробуем другой endpoint для проверки работы API
  try {
    console.log("\n3. Testing product info endpoint (should fail with auth error if working)...");
    await makeRequest("/v1/product/info/list", "POST", {
      offer_id: ["test"]
    });
  } catch (error) {
    console.error("Test 3 failed:", error.message);
  }
}

testEndpoints().catch(console.error);