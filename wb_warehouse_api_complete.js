/**
 * 📦 Wildberries API: Работа со складами
 * Локальный скрипт для взаимодействия с Wildberries Warehouse API
 *
 * Реализует основные методы из документации:
 * - /api/v3/warehouses - Получение списка складов (через marketplace-api)
 * - /api/v1/supplies/warehouses - Список складов для поставки (FBW)
 * - /api/analytics/v1/stocks-report/wb-warehouses - Остатки товаров на складах
 * - /api/v3/stocks/{warehouseId} - Обновление остатков на складе
 */

const https = require("https");
require("dotenv").config();

class WildberriesWarehouseAPI {
  constructor(apiToken) {
    this.apiToken = apiToken || process.env.WB_API_TOKEN;

    if (!this.apiToken) {
      throw new Error("Необходим WB_API_TOKEN");
    }
  }

  /**
   * Создание HTTPS запроса к API Wildberries
   * @param {string} hostname - домен API
   * @param {string} path - путь API
   * @param {string} method - HTTP метод (GET, POST, PUT, etc.)
   * @param {Object} body - тело запроса (если применимо)
   * @param {Object} query - параметры запроса (если применимо)
   * @returns {Promise<any>} - ответ API
   */
  async makeRequest(hostname, path, method = "GET", body = null, query = null) {
    // Добавляем параметры запроса к пути если есть
    const queryString = query
      ? "?" + new URLSearchParams(query).toString()
      : "";
    const fullPath = path + queryString;

    return new Promise((resolve, reject) => {
      const options = {
        hostname: hostname,
        path: fullPath,
        method: method,
        headers: {
          Authorization: `Bearer ${this.apiToken}`,
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

      if (body && method !== "GET") {
        req.write(JSON.stringify(body));
      }

      req.end();
    });
  }

  /**
   * 1️⃣ Получение списка складов
   * Метод: GET /api/v3/warehouses (через marketplace-api)
   * Возвращает список всех доступных складов Wildberries
   *
   * @returns {Promise<Object>} - результат API
   */
  async getWarehouses() {
    console.log("📦 Запрос списка складов Wildberries...");

    try {
      const response = await this.makeRequest(
        "marketplace-api.wildberries.ru",
        "/api/v3/warehouses",
        "GET",
      );

      if (
        response &&
        response.warehouses &&
        Array.isArray(response.warehouses)
      ) {
        console.log(
          `✅ Успешно получено ${response.warehouses.length} складов`,
        );

        // Выводим информацию о каждом складе
        response.warehouses.forEach((warehouse, index) => {
          console.log(
            `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.id}, Код: ${warehouse.code || "N/A"}, Тип: ${warehouse.type || "N/A"})`,
          );

          if (warehouse.address) {
            console.log(`      Адрес: ${warehouse.address}`);
          }

          console.log(`      Активен: ${warehouse.is_active ? "Да" : "Нет"}`);
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
   * 2️⃣ Список складов для поставки (FBW)
   * Метод: GET /api/v1/supplies/warehouses
   * Возвращает информацию о доступных складах и типах упаковки для поставки
   *
   * @param {Object} params - параметры запроса
   * @param {string} params.barcode - артикул товара (штрихкод)
   * @param {number} params.quantity - количество товара для поставки
   * @returns {Promise<Object>} - результат API
   */
  async getSupplyWarehouses(params = {}) {
    console.log("🏭 Запрос списка складов для поставки (FBW)...");

    const queryParams = {
      barcode: params.barcode,
      quantity: params.quantity,
    };

    try {
      const response = await this.makeRequest(
        "suppliers-api.wildberries.ru",
        "/api/v1/supplies/warehouses",
        "GET",
        null,
        queryParams,
      );

      if (response && Array.isArray(response)) {
        console.log(
          `✅ Успешно получено ${response.length} вариантов поставки`,
        );

        response.forEach((supplyOption, index) => {
          console.log(
            `  ${index + 1}. Склад: ${supplyOption.name || "N/A"} (ID: ${supplyOption.id})`,
          );
          if (supplyOption.packaging_types) {
            console.log(
              `      Типы упаковки:`,
              supplyOption.packaging_types.join(", "),
            );
          }
        });
      } else {
        console.log("ℹ️ Формат ответа:", typeof response);
        if (typeof response === "object") {
          console.log("📦 Доступные поля:", Object.keys(response));
        }
      }

      return response;
    } catch (error) {
      console.error(
        "❌ Ошибка при получении списка складов для поставки:",
        error.message,
      );
      throw error;
    }
  }

  /**
   * 3️⃣ Остатки товаров на складах
   * Метод: POST /api/analytics/v1/stocks-report/wb-warehouses
   * Получение текущих остатков товаров на складах Wildberries
   *
   * @param {Object} params - параметры запроса
   * @param {string} params.dateFrom - начальная дата (YYYY-MM-DD)
   * @param {string} params.dateTo - конечная дата (YYYY-MM-DD)
   * @returns {Promise<Object>} - результат API
   */
  async getWarehouseStocks(params = {}) {
    console.log("📊 Запрос остатков товаров на складах...");

    const payload = {
      dateFrom:
        params.dateFrom ||
        new Date(new Date().setDate(new Date().getDate() - 30))
          .toISOString()
          .split("T")[0], // 30 дней назад по умолчанию
      dateTo: params.dateTo || new Date().toISOString().split("T")[0], // сегодня
    };

    try {
      const response = await this.makeRequest(
        "suppliers-api.wildberries.ru",
        "/api/analytics/v1/stocks-report/wb-warehouses",
        "POST",
        payload,
      );

      if (response && Array.isArray(response)) {
        console.log(`✅ Успешно получено ${response.length} записей остатков`);

        // Подсчет товаров с остатками
        const withStock = response.filter((item) => item.quantity > 0);
        console.log(`📦 Товаров с остатками: ${withStock.length}`);

        // Пример данных
        if (response.length > 0) {
          console.log("📝 Пример данных:");
          const sample = response[0];
          console.log(
            `   Артикул: ${sample.nmId || sample.barcode || "N/A"}, Количество: ${sample.quantity || 0}, Склад: ${sample.warehouseName || sample.whNmId || "N/A"}`,
          );
        }
      } else {
        console.warn("⚠️ Неожиданный формат ответа:", response);
      }

      return response;
    } catch (error) {
      console.error("❌ Ошибка при получении остатков:", error.message);
      throw error;
    }
  }

  /**
   * 4️⃣ Обновление остатков товаров на конкретном складе
   * Метод: PUT /api/v3/stocks/{warehouseId}
   * Обновление остатков товаров на конкретном складе
   *
   * @param {number} warehouseId - ID склада
   * @param {Array} stocks - массив остатков для обновления
   * @returns {Promise<Object>} - результат API
   */
  async updateWarehouseStocks(warehouseId, stocks) {
    console.log(
      `🔄 Обновление остатков на складе ID: ${warehouseId}, товаров: ${stocks.length} шт.`,
    );

    if (!warehouseId) {
      throw new Error("Необходимо указать warehouseId");
    }

    if (!stocks || !Array.isArray(stocks)) {
      throw new Error("Поле stocks должно быть массивом");
    }

    const payload = {
      stocks: stocks.map((stock) => ({
        barcode: stock.barcode,
        quantity: parseInt(stock.quantity) || 0,
      })),
    };

    try {
      const response = await this.makeRequest(
        "marketplace-api.wildberries.ru",
        `/api/v3/stocks/${warehouseId}`,
        "PUT",
        payload,
      );

      // Проверяем успешность обновления
      if (response) {
        if (typeof response === "object" && response.hasOwnProperty("errors")) {
          console.log(
            "⚠️ Некоторые элементы могли не обновиться:",
            response.errors,
          );
        } else {
          console.log("✅ Все остатки успешно обновлены");
        }
      }

      return response;
    } catch (error) {
      console.error("❌ Ошибка при обновлении остатков:", error.message);
      throw error;
    }
  }

  /**
   * Комплексная функция для диагностики складов Wildberries
   * Получает информацию о всех складах и образцы остатков
   *
   * @param {Object} dateParams - параметры даты для запроса остатков
   */
  async diagnoseWarehouses(dateParams = {}) {
    console.log("🔍 Диагностика складов Wildberries...\n");

    try {
      // 1. Получаем список складов
      const warehouses = await this.getWarehouses();

      if (!warehouses || !warehouses.warehouses) {
        console.error("❌ Не удалось получить список складов");
        return;
      }

      console.log(`\n🏭 Найдено складов: ${warehouses.warehouses.length}`);

      // Показываем основные склады
      const mainWarehouses = warehouses.warehouses.filter((wh) =>
        ["KLD", "EKB", "SPB", "KZN", "KRD"].includes(wh.code),
      );

      console.log("\n📌 Основные склады (по кодам):");
      mainWarehouses.forEach((warehouse, index) => {
        console.log(
          `  ${index + 1}. ${warehouse.name} (ID: ${warehouse.id}, Код: ${warehouse.code}, Тип: ${warehouse.type})`,
        );
      });

      // 2. Запрашиваем остатки (если возможно)
      console.log("\n📈 Проверка запроса остатков...");
      try {
        const stocks = await this.getWarehouseStocks(dateParams);
        if (stocks && Array.isArray(stocks)) {
          console.log(`✅ Получено ${stocks.length} записей остатков`);
        }
      } catch (stocksError) {
        console.warn(`⚠️ Ошибка при запросе остатков:`, stocksError.message);
      }

      console.log("\n✅ Диагностика складов Wildberries завершена");
    } catch (error) {
      console.error(
        "❌ Ошибка при диагностике складов Wildberries:",
        error.message,
      );
      throw error;
    }
  }

  /**
   * Поиск склада по ID
   *
   * @param {number} warehouseId - ID склада
   * @returns {Object|undefined} - информация о складе
   */
  findWarehouseById(warehouseId) {
    console.log(`🔍 Поиск склада с ID: ${warehouseId}`);
    // Этот метод будет работать с ранее полученным списком складов
    // Реализация зависит от хранения списка складов
    return undefined;
  }

  /**
   * Поиск склада по коду
   *
   * @param {string} code - код склада (например, 'KLD')
   * @returns {Object|undefined} - информация о складе
   */
  findWarehouseByCode(code) {
    console.log(`🔍 Поиск склада с кодом: ${code}`);
    return undefined;
  }
}

/**
 * Пример использования скрипта
 */
async function main() {
  console.log("📦 Запуск скрипта работы с Wildberries складами\n");

  // Получаем токен из environment variables или используем дефолтный
  const apiToken =
    process.env.WB_API_TOKEN ||
    "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA";

  const wbAPI = new WildberriesWarehouseAPI(apiToken);

  try {
    // Пример 1: Получить список всех складов
    console.log("=== Пример 1: Получение списка всех складов ===");
    await wbAPI.getWarehouses();

    // Пример 2: Диагностика складов
    console.log("\n=== Пример 2: Диагностика складов ===");
    await wbAPI.diagnoseWarehouses();

    // Пример 3: Попытка получить остатки (требуется специальные права)
    console.log("\n=== Пример 3: Запрос остатков ===");
    const today = new Date().toISOString().split("T")[0];
    const monthAgo = new Date(new Date().setDate(new Date().getDate() - 30))
      .toISOString()
      .split("T")[0];

    try {
      await wbAPI.getWarehouseStocks({
        dateFrom: monthAgo,
        dateTo: today,
      });
    } catch (error) {
      console.warn(
        "⚠️ Запрос остатков может требовать дополнительных прав:",
        error.message,
      );
    }

    console.log(
      "\nℹ️  Примечание: Обновление остатков (метод updateWarehouseStocks) требует специальных прав доступа и не будет продемонстрирован",
    );
  } catch (error) {
    console.error("\n❌ Произошла ошибка в главной функции:", error.message);
  }

  console.log("\n🏁 Скрипт завершен");
}

// Экспорт класса для использования в других модулях
module.exports = WildberriesWarehouseAPI;

// Запуск скрипта если файл выполняется напрямую
if (require.main === module) {
  main().catch(console.error);
}
