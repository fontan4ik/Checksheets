/**
 * ОБНОВЛЕНИЕ АРТИКУЛОВ WILDBERRIES
 *
 * Заполняет колонку T (20): Артикул ВБ (nmId)
 *
 * Двухшаговый сценарий:
 * 1. Content API - получить ВСЕ карточки (nmID + vendorCode)
 * 2. Statistics API - получить остатки и дополнить barcode
 */

function updateWBArticles() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  // Читаем offer_id (Артикул) из колонки A
  const offerIds = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

  // Создаём мапу: vendorCode (offer_id) → {row, nmId, barcode}
  const offerToData = {};
  const validOffers = [];

  offerIds.forEach((offer, index) => {
    const trimmed = offer?.toString().trim();
    if (trimmed) {
      offerToData[trimmed] = {
        row: index + 2,
        nmId: "",
        barcode: ""
      };
      validOffers.push(trimmed);
    }
  });

  if (validOffers.length === 0) {
    Logger.log("Нет артикулов для обработки");
    return;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОБНОВЛЕНИЕ АРТИКУЛОВ WB (nmId)                                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log(`📦 Всего артикулов в таблице: ${validOffers.length}`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Content API - ВСЕ карточки (включая без остатков)
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 1: Content API (все карточки) ===");

  let processedFromContent = 0;
  let totalCardsLoaded = 0;

  try {
    const baseUrl = "https://content-api.wildberries.ru";
    let hasMore = true;
    let cursorData = null;
    let iteration = 0;

    while (hasMore) {
      iteration++;

      const payload = {
        "settings": {
          "sort": { "ascending": true },
          "cursor": {
            "limit": 100
          }
        },
        "filter": {
          "withPhoto": -1
        }
      };

      // Добавляем курсор для пагинации (не первая итерация)
      if (cursorData) {
        payload.settings.cursor = cursorData;
      }

      const options = {
        method: "post",
        contentType: "application/json",
        headers: wbHeaders(),
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      };

      const response = retryFetch(baseUrl + "/content/v2/get/cards/list", options);

      if (!response) {
        Logger.log("   ❌ Не удалось получить карточки (network error)");
        hasMore = false;
        break;
      }

      const responseCode = response.getResponseCode();
      const responseText = response.getContentText();

      if (responseCode === 200) {
        const data = JSON.parse(responseText);

        if (data && data.cards && Array.isArray(data.cards)) {
          const cardCount = data.cards.length;
          totalCardsLoaded += cardCount;

          if (iteration === 1 || totalCardsLoaded % 1000 === 0) {
            Logger.log(`   Загружено: ${cardCount} карточек (всего: ${totalCardsLoaded})`);
          }

          // Обрабатываем карточки: vendorCode → nmId
          data.cards.forEach(card => {
            const nmId = card.nmID || card.nmId;
            const vendorCode = card.vendorCode;

            if (nmId && vendorCode) {
              // Если этот артикул есть в нашей таблице
              if (offerToData[vendorCode]) {
                offerToData[vendorCode].nmId = nmId.toString();

                // Берём первый SKU из размеров для barcode
                if (card.sizes && card.sizes.length > 0) {
                  const firstSize = card.sizes[0];
                  if (firstSize.skus && firstSize.skus.length > 0) {
                    offerToData[vendorCode].barcode = firstSize.skus[0];
                  }
                }

                processedFromContent++;
              }
            }
          });

          // Пагинация: проверяем есть ли еще данные
          if (data.cursor && data.cards.length > 0) {
            cursorData = data.cursor;

            // Защита от бесконечного цикла
            if (totalCardsLoaded > 50000) {
              Logger.log("   ⚠️  Достигнут лимит 50000 карточек (защита)");
              hasMore = false;
            }
          } else {
            // Конец данных
            hasMore = false;
            Logger.log(`   ✅ Загружено ВСЕ карточек: ${totalCardsLoaded}`);
          }
        } else {
          Logger.log("   ⚠️  Неверный формат ответа Content API");
          hasMore = false;
        }
      } else {
        Logger.log(`   ❌ Content API код: ${responseCode}`);
        Logger.log(`   Response: ${responseText.substring(0, 300)}`);
        hasMore = false;
      }
    }

    Logger.log(`📝 Content API найдено артикулов: ${processedFromContent}`);

  } catch (e) {
    Logger.log(`❌ Content API ошибка: ${e.message}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Statistics API - остатки (дополняем barcode)
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 2: Statistics API (остатки) ===");

  let processedFromStocks = 0;

  try {
    const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";
    const options = {
      method: "get",
      headers: wbHeaders(),
      muteHttpExceptions: true
    };

    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить остатки (Statistics API)`);
      throw new Error("Failed to fetch stocks");
    }

    const stocks = JSON.parse(response.getContentText());

    if (stocks && Array.isArray(stocks)) {
      Logger.log(`   Stocks API записей: ${stocks.length}`);

      // Дополняем данные по barcode для товаров с остатками
      stocks.forEach(item => {
        const supplierArticle = item.supplierArticle;
        if (offerToData[supplierArticle]) {
          // Если ещё нет barcode из Content API
          if (!offerToData[supplierArticle].barcode && item.barcode) {
            offerToData[supplierArticle].barcode = item.barcode;
          }

          // Дополнительная проверка: если nmId не заполнен из Content API
          if (!offerToData[supplierArticle].nmId && item.nmId) {
            offerToData[supplierArticle].nmId = item.nmId.toString();
          }

          processedFromStocks++;
        }
      });

      Logger.log(`📝 Statistics API обработано: ${processedFromStocks}`);
    }

  } catch (e) {
    Logger.log(`⚠️  Statistics API ошибка: ${e.message}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ЗАПИСЬ В ТАБЛИЦУ
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ЗАПИСЬ В ТАБЛИЦУ ===");

  const totalProcessed = Object.values(offerToData).filter(d => d.nmId).length;

  // Записываем nmId в колонку T (20)
  const wbData = offerIds.map(offer => {
    const data = offerToData[offer?.toString()];
    return [data && data.nmId ? data.nmId : ""];
  });

  sheet.getRange(2, 20, wbData.length, 1).setValues(wbData);

  Logger.log(`\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!`);
  Logger.log(`📊 Статистика:`);
  Logger.log(`   • Всего артикулов: ${validOffers.length}`);
  Logger.log(`   • Найдено nmId: ${totalProcessed} (${Math.round(totalProcessed/validOffers.length*100)}%)`);
  Logger.log(`   • Из Content API: ${processedFromContent}`);
  Logger.log(`   • Из Statistics API: ${processedFromStocks}`);
  Logger.log(`   • Не найдено: ${validOffers.length - totalProcessed}`);
  Logger.log("══════════════════════════════════════════════════════════════════════════");
}

/**
 * Быстрая проверка Content API
 */
function testContentAPI() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ CONTENT API                                                      ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════════╝");

  const baseUrl = "https://content-api.wildberries.ru";

  const payload = {
    "settings": {
      "sort": { "ascending": true },
      "cursor": {
        "limit": 10
      }
    },
    "filter": {
      "withPhoto": -1
    }
  };

  const options = {
    method: "post",
    "contentType": "application/json",
    headers: wbHeaders(),
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    Logger.log(`POST ${baseUrl}/content/v2/get/cards/list`);
    const response = retryFetch(baseUrl + "/content/v2/get/cards/list", options);

    if (!response) {
      Logger.log("❌ Не удалось подключиться к Content API");
      return;
    }

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(`Status: ${responseCode}`);

    if (responseCode === 200) {
      const data = JSON.parse(responseText);

      if (data && data.cards && Array.isArray(data.cards)) {
        Logger.log(`✅ Получено карточек: ${data.cards.length}`);

        data.cards.slice(0, 5).forEach((card, i) => {
          Logger.log(`\n${i + 1}. ${card.vendorCode || '(нет vendorCode)'} -> nmID: ${card.nmID || card.nmId || '(нет)'}`);
          if (card.sizes && card.sizes.length > 0) {
            Logger.log(`   SKU: ${card.sizes[0].skus?.join(", ") || "(нет)"}`);
          }
        });

        if (data.cursor) {
          Logger.log(`\nВсего карточек: ${data.cursor.total || "(не указано)"}`);
          Logger.log(`Cursor: ${JSON.stringify(data.cursor)}`);
        }
      }
    } else {
      Logger.log(`❌ Неверный формат ответа`);
      Logger.log(responseText.substring(0, 1000));
    }
  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
  }

  Logger.log("══════════════════════════════════════════════════════════════════════════");
}

/**
 * Поиск 48724-1 в Content API
 */
function find48724ContentAPI() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ПОИСК 48724-1 В CONTENT API                                           ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const baseUrl = "https://content-api.wildberries.ru";
  let totalCards = 0;
  let hasMore = true;
  let cursorData = null;

  while (hasMore) {
    const payload = {
      "settings": {
        "sort": { "ascending": true },
        "cursor": {
          "limit": 100
        }
      },
      "filter": {
        "withPhoto": -1
      }
    };

    if (cursorData) {
      payload.settings.cursor = cursorData;
    }

    const options = {
      method: "post",
      "contentType": "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = retryFetch(baseUrl + "/content/v2/get/cards/list", options);

    if (!response) {
      Logger.log(`❌ Не удалось получить карточки (поиск 48724-1)`);
      hasMore = false;
      break;
    }

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode === 200) {
      const data = JSON.parse(responseText);

      if (data && data.cards && Array.isArray(data.cards)) {
        totalCards += data.cards.length;

        // Ищем 48724-1
        const found = data.cards.filter(card => {
          const vc = card.vendorCode || "";
          return vc === "48724-1" || vc.includes("48724");
        });

        if (found.length > 0) {
          Logger.log(`\n✅ НАЙДЕН в карточке ${totalCards}!`);

          found.forEach(card => {
            Logger.log(`\nАртикул: ${card.vendorCode}`);
            Logger.log(`nmID: ${card.nmID || card.nmId}`);
            Logger.log(`Название: ${card.title || '(нет)'}`);
            Logger.log(`Бренд: ${card.brand || '(нет)'}`);

            if (card.sizes && card.sizes.length > 0) {
              Logger.log(`Размеры: ${card.sizes.length}`);
              card.sizes.slice(0, 3).forEach((size, i) => {
                Logger.log(`  ${i + 1}. ${size.techSize || '(нет)'} - SKU: ${size.skus?.join(", ") || '(нет)'}`);
              });
            }

            // Нашли точное совпадение
            if (card.vendorCode === "48724-1") {
              Logger.log(`\n🎯 ТОЧНОЕ СОВПАДЕНИЕ!`);
              Logger.log(`nmId для 48724-1: ${card.nmID || card.nmId}`);
            }
          });
        }

        if (data.cursor && data.cards.length > 0) {
          cursorData = data.cursor;
        } else {
          hasMore = false;
        }
      } else {
        hasMore = false;
      }

      // Защита от чтения слишком большого объема
      if (totalCards > 5000) {
        Logger.log(`\nПрочитано ${totalCards} карточек, остановка поиска`);
        hasMore = false;
      }
    } else {
      Logger.log(`❌ Error: ${responseCode}`);
      hasMore = false;
    }
  }

  Logger.log(`\nВсего обработано карточек: ${totalCards}`);
  Logger.log("════════════════════════════════════════════════════════════════════════");
}
