const ARTICLE_RE = /^[A-Za-zА-Яа-яЁё0-9]+(?:[-_][A-Za-zА-Яа-яЁё0-9]+)*$/;

const safeMultiplicity = (value) => Number.isSafeInteger(value) && value >= 1;

export function resolveOfferId(sourceArticle, multiplicity) {
  const article = String(sourceArticle ?? "").trim();
  if (!ARTICLE_RE.test(article)) throw new Error("Некорректный исходный артикул IEK.");
  if (!safeMultiplicity(multiplicity)) {
    throw new Error("IEK не вернул достоверную кратность упаковки.");
  }
  return `${article}-${multiplicity}`;
}

function recordBySource(records, sourceArticle) {
  if (records instanceof Map) return records.get(sourceArticle) || null;
  if (Array.isArray(records)) return records.find((record) => record?.article === sourceArticle) || null;
  return records?.[sourceArticle] || null;
}

function recordValues(records) {
  if (records instanceof Map) return [...records.values()];
  if (Array.isArray(records)) return records;
  return Object.values(records || {});
}

function verifiedIdentity(sourceArticle, record) {
  const supplier = record?.supplier || {};
  if (supplier.article !== sourceArticle || !safeMultiplicity(supplier.multiplicity)) {
    throw new Error(`Нет проверенной кратности IEK для ${sourceArticle}; сначала нужен refresh поставщика.`);
  }
  return {
    article: sourceArticle,
    listingArticle: resolveOfferId(sourceArticle, supplier.multiplicity),
    multiplicity: supplier.multiplicity,
    record,
  };
}

export function resolveImportIdentities(values, records) {
  if (!Array.isArray(values)) throw new Error("Submit article values as an array.");
  const byInput = new Map();
  const bySource = new Map();
  const verificationErrors = new Map();
  for (const record of recordValues(records)) {
    const sourceArticle = record?.article;
    if (typeof sourceArticle !== "string") continue;
    try {
      const identity = verifiedIdentity(sourceArticle, recordBySource(records, sourceArticle));
      bySource.set(sourceArticle, identity);
      byInput.set(sourceArticle, identity);
      byInput.set(identity.listingArticle, identity);
    } catch (error) {
      verificationErrors.set(sourceArticle, String(error?.message || "Нет проверенной кратности IEK."));
      if (record) bySource.set(sourceArticle, null);
      byInput.set(sourceArticle, null);
    }
  }

  const articles = [];
  const identities = [];
  const duplicates = [];
  const errors = [];
  const seen = new Set();
  values.forEach((value, index) => {
    const input = String(value ?? "").trim();
    if (!input) return;
    if (!ARTICLE_RE.test(input)) {
      errors.push({ lines: [index + 1], value: input, message: "Артикул должен содержать только буквы, цифры, дефисы и подчёркивания." });
      return;
    }
    const identity = byInput.get(input);
    if (!identity) {
      const source = [...bySource.keys()].sort((left, right) => right.length - left.length)
        .find((article) => input === article || input.startsWith(`${article}-`));
      const expected = bySource.get(source)?.listingArticle;
      const message = source
        ? verificationErrors.get(source) || `Артикул ${input} не совпадает с проверенным offer_id ${expected}.`
        : "Артикул не найден в каталоге IEK.";
      errors.push({ lines: [index + 1], value: input, message });
      return;
    }
    if (seen.has(identity.article)) {
      duplicates.push(input);
      return;
    }
    seen.add(identity.article);
    articles.push(identity.article);
    identities.push(identity);
  });
  if (!articles.length && !errors.length) throw new Error("No supplier article values were found after identity resolution.");
  return { articles, identities, duplicates, errors };
}
