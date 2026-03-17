/**
 * Диагностика доступа к RS API
 * Помогает определить, заблокирован ли IP Google или проблема в формате запроса.
 */
function runRSDiagnostics() {
  const warehouseId = 96;
  const endpoints = [
    { name: "Список складов (базовый)", url: `${rsApiBaseUrl()}/stocks` },
    { name: "Список позиций (1 страница)", url: `${rsApiBaseUrl()}/position/${warehouseId}/instock?page=1&rows=50` },
    { name: "Массовые остатки (all)", url: `${rsApiBaseUrl()}/residue/all/${warehouseId}?page=1&rows=50` }
  ];
  
  Logger.log("=== ДИАГНОСТИКА RS API ===");
  Logger.log(`Логин: ${rsLogin()}`);
  
  endpoints.forEach(ep => {
    Logger.log(`\n🔍 Проверка: ${ep.name}...`);
    const options = {
      method: "get",
      headers: {
        ...rsHeaders(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://rs24.ru/"
      },
      muteHttpExceptions: true
    };
    
    try {
      const response = UrlFetchApp.fetch(ep.url, options);
      const code = response.getResponseCode();
      Logger.log(`Результат: ${code}`);
      
      if (code === 200) {
        const text = response.getContentText();
        Logger.log(`✅ Успех! Получено символов: ${text.length}`);
        if (text.length < 500) Logger.log(`Ответ: ${text}`);
      } else {
        Logger.log(`❌ Ошибка ${code}`);
        const content = response.getContentText();
        if (content.includes("VPN")) {
          Logger.log("⚠️ API сообщает о блокировке VPN/IP");
        }
        Logger.log(`Тело ответа: ${content.substring(0, 500)}`);
      }
    } catch (e) {
      Logger.log(`❌ Ошибка сети: ${e.message}`);
    }
  });
}
