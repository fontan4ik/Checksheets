/**
 * ДИАГНОСТИКА ТОКЕНА API
 *
 * Проверяет что токен работает и может видеть карточки
 */

function testAPIToken() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ПРОВЕРКА ТОКЕНА API                                                  ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = wbHeaders();
  const baseUrl = "https://content-api.wildberries.ru";

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Проверяем сколько карточек видит токен вообще
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 1: Сколько карточек видит токен ===");

  const payload = {
    "settings": {
      "sort": { "ascending": true },
      "cursor": { "limit": 10 }
    },
    "filter": {
      "withPhoto": -1
    }
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: headers,
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(baseUrl + "/content/v2/get/cards/list", options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(`Response Code: ${responseCode}`);

    if (responseCode === 200) {
      const data = JSON.parse(responseText);

      if (data && data.cards && Array.isArray(data.cards)) {
        Logger.log(`✅ Токен работает! Видит карточек: ${data.cards.length}`);

        if (data.cards.length > 0) {
          Logger.log(`\n📦 Первые 5 карточек:`);
          data.cards.slice(0, 5).forEach((card, i) => {
            Logger.log(`   ${i + 1}. nmID: ${card.nmID}, vendorCode: ${card.vendorCode}, Название: ${card.title?.substring(0, 30) || "(нет)"}`);
          });
        }
      } else {
        Logger.log(`⚠️  Неверный формат ответа`);
      }
    } else if (responseCode === 401) {
      Logger.log(`❌ Ошибка 401: Токен недействителен или истёк!`);
      Logger.log(`\nРешение:`);
      Logger.log(`   1. Проверьте токен в settings.gs`);
      Logger.log(`   2. Получите новый токен в личном кабинете WB`);
      return;
    } else if (responseCode === 403) {
      Logger.log(`❌ Ошибка 403: Нет прав на Content API!`);
      Logger.log(`\nРешение:`);
      Logger.log(`   1. Проверьте права токена (нужна категория "Контент")`);
      Logger.log(`   2. Создайте новый токен с правами Content API`);
      return;
    } else {
      Logger.log(`❌ Ошибка: ${responseCode}`);
      Logger.log(`Response: ${responseText.substring(0, 500)}`);
    }
  } catch (e) {
    Logger.log(`❌ Исключение: ${e.message}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Проверяем Statistics API
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 2: Проверка Statistics API ===");

  try {
    const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";
    const options = {
      method: "get",
      headers: headers,
      muteHttpExceptions: true
    };

    const response = retryFetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      const stocks = JSON.parse(response.getContentText());
      Logger.log(`✅ Statistics API работает! Записей: ${stocks.length}`);

      // Ищем 48724-1 в stocks
      const found = stocks.find(item => item.supplierArticle === "48724-1");

      if (found) {
        Logger.log(`\n✅ Артикул 48724-1 найден в Statistics API!`);
        Logger.log(`   nmId: ${found.nmId}`);
        Logger.log(`   Склад: ${found.warehouseName || "(не указан)"}`);
        Logger.log(`   Остаток: ${found.quantity} шт`);
        Logger.log(`   Размер: ${found.techSize || "-"}`);
      } else {
        Logger.log(`\n⚠️  Артикул 48724-1 НЕ найден в Statistics API`);
        Logger.log(`   (нет остатков на складах WB)`);
      }
    } else if (responseCode === 401) {
      Logger.log(`❌ Statistics API: Токен недействителен`);
    } else {
      Logger.log(`⚠️  Statistics API код: ${responseCode}`);
    }
  } catch (e) {
    Logger.log(`❌ Statistics API ошибка: ${e.message}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 3: Проверяем warehouseId для ФЕРОН и ВольтМир
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 3: Проверка складов ===");

  try {
    const url = "https://marketplace-api.wildberries.ru/api/v3/warehouses";
    const options = {
      method: "get",
      headers: headers,
      muteHttpExceptions: true
    };

    const response = retryFetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      const warehouses = JSON.parse(response.getContentText());
      Logger.log(`✅ Marketplace API работает! Складов: ${warehouses.length}`);

      Logger.log(`\n📦 Все склады:`);
      warehouses.forEach((wh, i) => {
        const type = wh.isFbs ? 'FBS' : (wh.isDbs ? 'DBS' : '?');
        Logger.log(`   ${i + 1}. [${type}] "${wh.name}" (ID: ${wh.id})`);
      });

      // Проверяем нужные склады
      const feron = warehouses.find(wh => wh.name.includes("ФЕРОН") || wh.name.includes("МОСКВА"));
      const volt = warehouses.find(wh => wh.name.includes("Вольт"));

      Logger.log(`\n🎯 Целевые склады:`);
      if (feron) {
        Logger.log(`   ✅ "${feron.name}" (ID: ${feron.id})`);
      } else {
        Logger.log(`   ❌ ФЕРОН МОСКВА не найден`);
      }

      if (volt) {
        Logger.log(`   ✅ "${volt.name}" (ID: ${volt.id})`);
      } else {
        Logger.log(`   ❌ ВольтМир не найден`);
      }
    } else if (responseCode === 401) {
      Logger.log(`❌ Marketplace API: Токен недействителен`);
    } else {
      Logger.log(`⚠️  Marketplace API код: ${responseCode}`);
    }
  } catch (e) {
    Logger.log(`❌ Marketplace API ошибка: ${e.message}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ИТОГИ
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ИТОГИ ===");

  Logger.log(`Возможные причины почему карточка 48724-1 не находится:`);
  Logger.log(``);
  Logger.log(`1. API токен от ДРУГОГО аккаунта WB`);
  Logger.log(`   • Проверьте nmId первых 5 карточек из ЛК и из API`);
  Logger.log(`   • Если не совпадают - токен от другого аккаунта`);
  Logger.log(``);
  Logger.log(`2. Нет прав Content API у токена`);
  Logger.log(`   • Content API вернул 403 или пустой список`);
  Logger.log(`   • Нужно создать новый токен с правом "Контент"`);
  Logger.log(``);
  Logger.log(`3. Карточка в особом статусе`);
  Logger.log(`   • Архивные карточки`);
  Logger.log(`   • На модерации`);
  Logger.log(`   • Черновик`);

  Logger.log("\n════════════════════════════════════════════════════════════════════════");
}
