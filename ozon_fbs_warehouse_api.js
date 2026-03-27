/**
 * 📦 Ozon API: Работа со складами FBS
 * Локальный скрипт для взаимодействия с Ozon Warehouse FBS API
 *
 * Реализует основные методы из документации:
 * - /v1/warehouse/list - Получение списка складов
 * - /v1/warehouse/fbs/create/drop-off/list - Список складов FBS для отгрузки
 * - /v1/warehouse/fbs/pickup/planning/list - Список складов для планирования курьеру
 * - /v1/warehouse/fbo/list - Список складов FBO
 * - /v1/product/info/stocks-by-warehouse/fbs - Получение остатков по FBS складам
 */

const https = require("https");
require("dotenv").config();

class OzonWarehouseAPI {
  constructor(clientId, apiKey) {
    this.clientId = clientId || process.env.OZON_CLIENT_ID;
    this.apiKey = apiKey || process.env.OZON_API_KEY;

    if (!this.clientId || !this.apiKey) {
      throw new Error("Необходимы OZON_CLIENT_ID и OZON_API_KEY");
    }
  }

  /**
   * Создание HTTPS запроса к API Ozon
   * @param {string} path - путь API
   * @param {string} method - HTTP метод (POST, GET)
   * @param {Object} body - тело запроса
   * @returns {Promise<any>} - ответ API
   */
  async makeRequest(path, method = "POST", body = null) {
    return new Promise((resolve, reject) => {
      const options = {
        hostname: "api-seller.ozon.ru",
        path: path,
        method: method,
        headers: {
          "Client-Id": this.clientId,
          "Api-Key": this.apiKey,
          "Content-Type": "application/json",
        },
      };

      const req = https.request(options, (res) => {
        let data = "";

        res.on("data", (chunk) => {
          data += chunk;
        });

        res.on("end", () => {
          try {
            const response = JSON.parse(data);
            resolve(response);
          } catch (e) {
            console.error("Ошибка парсинга ответа:", e.message);
            console.error("Ответ:", data);
            resolve(data); // возвращаем неструктурированный ответ
          }
        });
      });

      req.on("error", (error) => {
        reject(error);
      });

      if (body) {
        req.write(JSON.stringify(body));
      }

      req.end();
    });
  }

  /**
   * 1️⃣ Получение списка складов
   * Метод: POST /v1/warehouse/list
   * Возвращает список всех складов продавца (FBS, rFBS)
   *
   * @param {Object} params - параметры запроса
   * @param {number} params.limit - ограничение количества результатов (макс. 200)
   * @param {number} params.offset - смещение
   * @param {string} params.status - статус склада (ACTIVE, INACTIVE)
   * @returns {Promise<Object>} - результат API
   */
  async getWarehouseList(params = {}) {
    console.log("📦 Запрос списка складов...");

    const payload = {
      limit: params.limit || 200, // макс. 200 по документации
      offset: params.offset || 0,
      status: params.status || "ACTIVE",
    };

    try {
      const response = await this.makeRequest(
        "/v1/warehouse/list",
        "POST",
        payload,
      );

      if (response && response.result && Array.isArray(response.result)) {
        console.log(`✅ Успешно получено ${response.result.length} складов`);

        // Выводим информацию о каждом складе
        response.result.forEach((warehouse, index) => {
          console.log(
            `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.warehouse_id}, Тип: ${warehouse.type || "N/A"}, Статус: ${warehouse.status})`,
          );
        });
      } else {
        console.warn("⚠️ Неожиданный формат ответа:", response);
      }

      return response;
    } catch (error) {
      console.error("❌ Ошибка при получении списка складов:", error.message);
      throw error;
    }
  }

  /**
   * 2️⃣ Список складов FBS для отгрузки
   * Метод: POST /v1/warehouse/fbs/create/drop-off/list
   * Получение списка FBS-складов для создания отгрузок
   *
   * @param {Object} params - параметры запроса
   * @returns {Promise<Object>} - результат API
   */
  async getFBSWarehouseDropOffList(params = {}) {
    console.log("🚚 Запрос списка FBS складов для отгрузки...");

    const payload = {
      limit: params.limit || 200,
      offset: params.offset || 0,
    };

    try {
      const response = await this.makeRequest(
        "/v1/warehouse/fbs/create/drop-off/list",
        "POST",
        payload,
      );

      if (response && response.result && Array.isArray(response.result)) {
        console.log(
          `✅ Успешно получено ${response.result.length} складов для отгрузки`,
        );

        response.result.forEach((warehouse, index) => {
          console.log(
            `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.warehouse_id})`,
          );
        });
      }

      return response;
    } catch (error) {
      console.error(
        "❌ Ошибка при получении списка FBS складов для отгрузки:",
        error.message,
      );
      throw error;
    }
  }

  /**
   * 3️⃣ Список складов для планирования курьеру
   * Метод: POST /v1/warehouse/fbs/pickup/planning/list
   * Бета-метод для получения списка складов для планирования отгрузок курьеру
   *
   * @param {Object} params - параметры запроса
   * @returns {Promise<Object>} - результат API
   */
  async getFBSPickupPlanningList(params = {}) {
    console.log("📍 Запрос списка FBS складов для планирования курьеру...");

    const payload = {
      limit: params.limit || 200,
      offset: params.offset || 0,
    };

    try {
      const response = await this.makeRequest(
        "/v1/warehouse/fbs/pickup/planning/list",
        "POST",
        payload,
      );

      if (response && response.result && Array.isArray(response.result)) {
        console.log(
          `✅ Успешно получено ${response.result.length} складов для планирования`,
        );

        response.result.forEach((warehouse, index) => {
          console.log(
            `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.warehouse_id})`,
          );
        });
      }

      return response;
    } catch (error) {
      console.error(
        "❌ Ошибка при получении списка складов для планирования курьеру:",
        error.message,
      );
      throw error;
    }
  }

  /**
   * 4️⃣ Список складов FBO
   * Метод: POST /v1/warehouse/fbo/list
   * Для получения списка складов FBO (отдельно от FBS)
   *
   * @param {Object} params - параметры запроса
   * @returns {Promise<Object>} - результат API
   */
  async getFBOList(params = {}) {
    console.log("🏪 Запрос списка FBO складов...");

    const payload = {
      limit: params.limit || 200,
      offset: params.offset || 0,
    };

    try {
      const response = await this.makeRequest(
        "/v1/warehouse/fbo/list",
        "POST",
        payload,
      );

      if (response && response.result && Array.isArray(response.result)) {
        console.log(
          `✅ Успешно получено ${response.result.length} FBO складов`,
        );

        response.result.forEach((warehouse, index) => {
          console.log(
            `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.warehouse_id})`,
          );
        });
      }

      return response;
    } catch (error) {
      console.error(
        "❌ Ошибка при получении списка FBO складов:",
        error.message,
      );
      throw error;
    }
  }

  /**
   * 5️⃣ Получение остатков по FBS складам
   * Метод: POST /v1/product/info/stocks-by-warehouse/fbs
   *
   * @param {number[]} skuList - массив SKU
   * @param {number} warehouseId - ID склада
   * @param {number} limit - лимит результатов (макс. 1000)
   * @returns {Promise<Object>} - результат API
   */
  async getFBSStocks(skuList, warehouseId, limit = 1000) {
    console.log(
      `📊 Запрос остатков для склада ID: ${warehouseId}, SKU: ${skuList.length} шт.`,
    );

    // Проверяем, что warehouseId передан
    if (!warehouseId) {
      throw new Error("Необходимо указать warehouseId");
    }

    const payload = {
      sku: skuList.slice(0, 500), // максимум 500 SKU за раз
      warehouse_id: warehouseId,
      limit: Math.min(limit, 1000), // максимум 1000
    };

    try {
      const response = await this.makeRequest(
        "/v1/product/info/stocks-by-warehouse/fbs",
        "POST",
        payload,
      );

      if (response && response.result && Array.isArray(response.result)) {
        console.log(
          `✅ Успешно получено ${response.result.length} записей остатков`,
        );

        // Подсчет товаров с остатками
        const withStock = response.result.filter(
          (item) => (item.present || 0) + (item.reserved || 0) > 0,
        );

        console.log(`📦 Товаров с остатками: ${withStock.length}`);

        // Пример данных
        if (response.result.length > 0) {
          console.log("📝 Пример данных:");
          const sample = response.result[0];
          console.log(
            `   SKU: ${sample.sku}, Present: ${sample.present || 0}, Reserved: ${sample.reserved || 0}`,
          );
        }
      }

      return response;
    } catch (error) {
      console.error("❌ Ошибка при получении FBS остатков:", error.message);
      throw error;
    }
  }

  /**
   * Комплексная функция для диагностики FBS складов
   * Получает информацию о всех FBS складах и примеры остатков
   *
   * @param {number[]} testSKUs - тестовые SKU для проверки остатков
   */
  async diagnoseFBSWarehouses(testSKUs = []) {
    console.log("🔍 Диагностика FBS складов...\n");

    try {
      // 1. Получаем общий список складов
      const allWarehouses = await this.getWarehouseList();

      if (!allWarehouses || !allWarehouses.result) {
        console.error("❌ Не удалось получить список складов");
        return;
      }

      // Фильтруем FBS склады
      const fbsWarehouses = allWarehouses.result.filter(
        (wh) =>
          wh.type &&
          (wh.type.toUpperCase() === "FBS" || wh.type.toUpperCase() === "RFBS"),
      );

      console.log(`\n🏭 Найдено FBS складов: ${fbsWarehouses.length}`);

      fbsWarehouses.forEach((warehouse, index) => {
        console.log(
          `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.warehouse_id})`,
        );

        // Выводим дополнительную информацию если доступна
        if (warehouse.address) {
          console.log(
            `      Адрес: ${warehouse.address.full_address || "N/A"}`,
          );
        }
        console.log(`      Активен: ${warehouse.is_active ? "Да" : "Нет"}`);
        console.log(`      Тип: ${warehouse.type}`);
      });

      // 2. Если есть тестовые SKU, проверяем остатки на первых 3 FBS складах
      if (testSKUs && testSKUs.length > 0 && fbsWarehouses.length > 0) {
        console.log(
          `\n📈 Проверка остатков по тестовым SKU: [${testSKUs.join(", ")}]`,
        );

        const warehousesToCheck = fbsWarehouses.slice(0, 3); // Проверяем на первых 3 складах

        for (const warehouse of warehousesToCheck) {
          console.log(
            `\n   --- Проверка на складе: ${warehouse.name} (ID: ${warehouse.warehouse_id}) ---`,
          );

          try {
            const stocks = await this.getFBSStocks(
              testSKUs,
              warehouse.warehouse_id,
            );

            if (stocks && stocks.result && Array.isArray(stocks.result)) {
              stocks.result.forEach((item) => {
                const total = (item.present || 0) + (item.reserved || 0);
                console.log(
                  `      SKU ${item.sku}: Present=${item.present || 0}, Reserved=${item.reserved || 0}, Total=${total}`,
                );
              });
            }
          } catch (stockError) {
            console.error(
              `      ❌ Ошибка при запросе остатков:`,
              stockError.message,
            );
          }
        }
      }

      console.log("\n✅ Диагностика FBS складов завершена");
    } catch (error) {
      console.error("❌ Ошибка при диагностике FBS складов:", error.message);
      throw error;
    }
  }

  /**
   * Получение деталей склада по ID
   *
   * @param {number} warehouseId - ID склада
   * @returns {Object|undefined} - информация о складе
   */
  getWarehouseById(warehouseId) {
    // Предполагается, что список складов уже получен
    // На практике нужно реализовать отдельный метод для поиска в сохраненном списке
    console.log(`🔍 Поиск склада с ID: ${warehouseId}`);
    return undefined;
  }
}

/**
 * Пример использования скрипта
 */
async function main() {
  console.log("📦 Запуск скрипта работы с Ozon FBS складами\n");

  // Получаем credentials из environment variables или используем дефолтные
  const clientId = process.env.OZON_CLIENT_ID || "142355";
  const apiKey =
    process.env.OZON_API_KEY || "fe539630-170b-4b48-b222-8ba092907a63";

  const ozonAPI = new OzonWarehouseAPI(clientId, apiKey);

  try {
    // Пример 1: Получить список всех складов
    console.log("=== Пример 1: Получение списка всех складов ===");
    await ozonAPI.getWarehouseList();

    // Пример 2: Получить список FBS складов для отгрузки
    console.log(
      "\n=== Пример 2: Получение списка FBS складов для отгрузки ===",
    );
    await ozonAPI.getFBSWarehouseDropOffList();

    // Пример 3: Диагностика FBS складов с тестовыми SKU
    console.log("\n=== Пример 3: Диагностика FBS складов ===");
    const testSKUs = [301916350, 986326117]; // Пример тестовых SKU
    await ozonAPI.diagnoseFBSWarehouses(testSKUs);

    // Пример 4: Проверка остатков по конкретному складу
    console.log("\n=== Пример 4: Проверка остатков по FBS складу ===");
    // В реальности здесь должен быть актуальный ID FBS склада
    // await ozonAPI.getFBSStocks(testSKUs, YOUR_WAREHOUSE_ID_HERE);
  } catch (error) {
    console.error("\n❌ Произошла ошибка в главной функции:", error.message);
  }

  console.log("\n🏁 Скрипт завершен");
}

// Экспорт класса для использования в других модулях
module.exports = OzonWarehouseAPI;

// Запуск скрипта если файл выполняется напрямую
if (require.main === module) {
  main().catch(console.error);
}
