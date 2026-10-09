const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const workspace = '/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets';
const projectRequire = createRequire(path.join(workspace, 'package.json'));
projectRequire('dotenv').config({ path: process.env.OZON_REVIEWS_SECRETS_FILE || '/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env', quiet: true });
projectRequire('dotenv').config({ path: path.join(workspace, '.env'), quiet: true });

const productIds = [6541499612, 6542009054, 6542009074, 6542009068, 6542009049];
const output = {
  observedAt: new Date().toISOString(),
  readOnly: true,
  productIds,
  calls: [],
};

function safeAttribute(attribute) {
  return {
    id: attribute.id || attribute.attribute_id,
    name: attribute.name,
    values: (attribute.values || []).map((value) => ({
      dictionaryValueId: value.dictionary_value_id,
      value: value.value,
    })),
  };
}

async function call(endpoint, payload) {
  const response = await fetch(`https://api-seller.ozon.ru${endpoint}`, {
    method: 'POST',
    headers: {
      'Client-Id': process.env.OZON_CLIENT_ID,
      'Api-Key': process.env.OZON_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(20000),
  });
  const body = await response.json();
  output.calls.push({ endpoint, status: response.status });
  return { status: response.status, body };
}

(async () => {
  try {
    const attributes = await call('/v4/product/info/attributes', {
      filter: { product_id: productIds.map(String), visibility: 'ALL' },
      limit: 100,
      sort_dir: 'ASC',
    });
    output.attributesStatus = attributes.status;
    output.products = (attributes.body.result || attributes.body.items || []).map((product) => ({
      productId: product.id || product.product_id,
      offerId: product.offer_id,
      name: product.name,
      description: product.description,
      categoryId: product.description_category_id,
      typeId: product.type_id,
      price: product.price,
      oldPrice: product.old_price,
      depth: product.depth,
      width: product.width,
      height: product.height,
      dimensionUnit: product.dimension_unit,
      weight: product.weight,
      weightUnit: product.weight_unit,
      images: product.images,
      primaryImage: product.primary_image,
      attributes: (product.attributes || []).map(safeAttribute),
    }));

    const pictures = await call('/v2/product/pictures/info', { product_id: productIds });
    output.picturesStatus = pictures.status;
    output.pictures = pictures.body;

    output.schema = [];
    output.dictionaries = [];
    const schema = await call('/v1/description-category/attribute', {
      description_category_id: 17028654,
      type_id: 99040,
      language: 'RU',
    });
    output.schemaStatus = schema.status;
    output.schema = (schema.body.result || []).map((attribute) => Object.fromEntries(
      ['id', 'name', 'description', 'type', 'is_required', 'is_collection', 'dictionary_id', 'complex_id', 'max_value_count']
        .filter((key) => attribute[key] !== undefined)
        .map((key) => [key, attribute[key]]),
    ));

    for (const attributeId of [10818, 10819]) {
      const dictionary = await call('/v1/description-category/attribute/values', {
        attribute_id: attributeId,
        description_category_id: 17028654,
        type_id: 99040,
        language: 'RU',
        last_value_id: 0,
        limit: 100,
      });
      output.dictionaries.push({
        attributeId,
        status: dictionary.status,
        values: (dictionary.body.result || []).map((value) => ({ id: value.id, value: value.value })),
        hasNext: dictionary.body.has_next,
      });
    }
  } catch (error) {
    output.errorType = error?.name || 'Error';
    output.errorMessage = String(error?.message || 'unknown').slice(0, 240);
  }

  const destination = path.join(__dirname, 'iek-card-correction-20261009-live-readback.json');
  fs.writeFileSync(destination, `${JSON.stringify(output, null, 2)}\n`);
  console.log(JSON.stringify({
    observedAt: output.observedAt,
    readOnly: output.readOnly,
    attributesStatus: output.attributesStatus,
    productCount: output.products?.length,
    picturesStatus: output.picturesStatus,
    schemaStatus: output.schemaStatus,
    dictionaryStatuses: output.dictionaries?.map(({ attributeId, status, values }) => ({ attributeId, status, count: values.length })),
    errorType: output.errorType,
  }));
})();
