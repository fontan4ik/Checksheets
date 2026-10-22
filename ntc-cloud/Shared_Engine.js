/* Pure NTC ledger. All quantities in F/movements are physical pieces; order/K
 * quantities are packs. Callers must persist F and the journal atomically. */
function ntcInteger_(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(label + ' must be a nonnegative safe integer');
  return value;
}

function ntcCopy_(value) { return JSON.parse(JSON.stringify(value)); }
function ntcEqual_(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  var keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(function (key) {
    return Object.prototype.hasOwnProperty.call(b, key) && ntcEqual_(a[key], b[key]);
  });
}
function ntcArticles_(items, stock) {
  var result = {};
  items.forEach(function (item) {
    var offer = String(item.offer_id || '').trim(), model = String(item.model || '').trim();
    var size = ntcInteger_(item.H, 'H/' + offer);
    if (!offer || !model || !size || Object.prototype.hasOwnProperty.call(result, offer) ||
        !Object.prototype.hasOwnProperty.call(stock, model)) throw new Error('invalid article ' + offer);
    result[offer] = {model: model, H: size};
  });
  return result;
}
function ntcQuantities_(items, label) {
  var quantities = {};
  items.forEach(function (item) {
    var offer = String(item.offer_id || '').trim();
    if (!offer) throw new Error(label + ': missing offer_id');
    quantities[offer] = ntcInteger_((quantities[offer] || 0) + ntcInteger_(item.quantity, label + '/' + offer), label);
  });
  return quantities;
}
function ntcOutstanding_(state, offer) {
  var quantity = (state.manual_k || {})[offer] || 0;
  Object.keys(state.postings).forEach(function (number) {
    var posting = state.postings[number];
    if ((posting.status === 'cancelled' || posting.status === 'not_accepted') && !posting.ever_handed_over) return;
    var returned = 0;
    Object.keys(state.returns).forEach(function (id) {
      var entry = state.returns[id];
      if (entry.posting_number === number && entry.offer_id === offer) returned += entry.quantity;
    });
    quantity += Math.max(0, (posting.items[offer] || 0) - returned);
  });
  return quantity;
}
function ntcTrackSchema_(state, articles) {
  var previous = state.article_schema_by_offer || {};
  Object.keys(previous).forEach(function (offer) {
    if (!ntcEqual_(previous[offer], articles[offer]) && ntcOutstanding_(state, offer)) {
      throw new Error('article model/multiplicity changed with outstanding history: ' + offer);
    }
  });
  state.article_schema_by_offer = ntcCopy_(articles);
}
function ntcDeriveF_(state) {
  Object.keys(state.base_physical_by_model).forEach(function (model) {
    state.last_f_by_model[model] = Math.max(0, state.base_physical_by_model[model] - state.applied_physical_by_model[model]);
  });
}

function ntcAdvance_(payload, previousState) {
  var current = {};
  Object.keys(payload.stock_by_model).forEach(function (model) {
    current[model] = ntcInteger_(payload.stock_by_model[model], 'F/' + model);
  });
  var articles = ntcArticles_(payload.articles, current);
  var state = previousState ? ntcCopy_(previousState) : {
    last_f_by_model: ntcCopy_(current), applied_physical_by_model: {},
    base_physical_by_model: ntcCopy_(current), postings: {}, returns: {}, manual_k: {}
  };
  if (!previousState) Object.keys(current).forEach(function (model) { state.applied_physical_by_model[model] = 0; });
  if (!state.base_physical_by_model) {
    state.base_physical_by_model = {};
    Object.keys(state.last_f_by_model).forEach(function (model) {
      state.base_physical_by_model[model] = state.last_f_by_model[model] + state.applied_physical_by_model[model];
    });
  }
  Object.keys(state.last_f_by_model).forEach(function (model) {
    if (current[model] !== state.last_f_by_model[model]) throw new Error('F changed outside this ledger; reconcile warehouse source before continuing');
  });
  Object.keys(current).forEach(function (model) {
    if (!Object.prototype.hasOwnProperty.call(state.last_f_by_model, model)) {
      if (state.applied_physical_by_model[model]) throw new Error('new model has prior debit: ' + model);
      state.last_f_by_model[model] = current[model];
      state.base_physical_by_model[model] = current[model];
      state.applied_physical_by_model[model] = 0;
    }
  });
  ntcTrackSchema_(state, articles);
  (payload.postings || []).forEach(function (posting) {
    var number = String(posting.posting_number || '').trim(), status = String(posting.status || '').trim();
    if (!number || !status) throw new Error('posting requires posting_number and status');
    var old = state.postings[number], handoff = posting.ever_handed_over;
    if (handoff != null && typeof handoff !== 'boolean') throw new Error('invalid handoff history for ' + number);
    var handed = !!(old && old.ever_handed_over) || ['driver_pickup', 'delivering', 'delivered', 'last_mile'].indexOf(status) >= 0 || handoff === true;
    if (['cancelled', 'not_accepted'].indexOf(status) >= 0 && handoff == null) handed = true;
    var items;
    if (Object.prototype.hasOwnProperty.call(posting, 'items')) items = ntcQuantities_(posting.items, number);
    else if (old) items = ntcCopy_(old.items);
    else throw new Error('posting ' + number + ' has no items');
    if (handed && old) Object.keys(old.items).forEach(function (offer) { items[offer] = Math.max(items[offer] || 0, old.items[offer]); });
    Object.keys(items).forEach(function (offer) { if (!articles[offer]) throw new Error('unknown article ' + offer + ' in ' + number); });
    state.postings[number] = {status: status, items: items, ever_handed_over: handed};
  });
  (payload.returns || []).forEach(function (entry) {
    var id = String(entry.id || '').trim();
    if (!id) throw new Error('return without id');
    if (String(entry.schema || '').toLowerCase() !== 'fbs' || (((entry.visual || {}).status || {}).sys_name !== 'ReceivedBySeller')) return;
    var number = String(entry.posting_number || '').trim(), product = entry.product || {}, offer = String(product.offer_id || '').trim();
    var accepted = {posting_number: number, offer_id: offer, quantity: ntcInteger_(product.quantity, 'return/' + id)};
    if (!number || !offer || !articles[offer]) throw new Error('invalid accepted return ' + id);
    if (state.returns[id] && !ntcEqual_(state.returns[id], accepted)) throw new Error('return ' + id + ' changed after acceptance');
    state.returns[id] = accepted;
  });
  var returned = {}, units = {};
  Object.keys(state.returns).forEach(function (id) {
    var entry = state.returns[id];
    if (!returned[entry.posting_number]) returned[entry.posting_number] = {};
    var row = returned[entry.posting_number];
    row[entry.offer_id] = (row[entry.offer_id] || 0) + entry.quantity;
  });
  Object.keys(state.postings).forEach(function (number) {
    var posting = state.postings[number];
    var cancelled = ['cancelled', 'not_accepted'].indexOf(posting.status) >= 0 && !posting.ever_handed_over;
    Object.keys(posting.items).forEach(function (offer) {
      var accepted = (returned[number] || {})[offer] || 0, ordered = posting.items[offer];
      if (accepted > ordered) throw new Error('returns exceed ordered quantity for ' + number + '/' + offer);
      if (!cancelled && ordered > accepted) units[offer] = (units[offer] || 0) + ordered - accepted;
    });
  });
  // Retain already accounted legacy writeoffs after their input column is removed.
  var manualInput = Object.prototype.hasOwnProperty.call(payload, 'manual_k') ? payload.manual_k : state.manual_k;
  state.manual_k = {};
  Object.keys(manualInput || {}).forEach(function (offer) {
    if (!articles[offer]) throw new Error('unknown manual article ' + offer);
    var quantity = ntcInteger_(manualInput[offer], 'K/' + offer);
    state.manual_k[offer] = quantity;
    if (quantity) units[offer] = (units[offer] || 0) + quantity;
  });
  var physical = {}, delta = {}, shortage = {};
  Object.keys(current).forEach(function (model) { physical[model] = 0; });
  Object.keys(units).forEach(function (offer) {
    if (!articles[offer]) throw new Error('unknown historical article ' + offer);
    var article = articles[offer];
    physical[article.model] = ntcInteger_(physical[article.model] + units[offer] * article.H, 'applied/' + article.model);
  });
  Object.keys(current).forEach(function (model) {
    delta[model] = physical[model] - state.applied_physical_by_model[model];
    shortage[model] = Math.max(0, physical[model] - state.base_physical_by_model[model]);
  });
  state.applied_physical_by_model = physical;
  ntcDeriveF_(state);
  return {F_by_model: ntcCopy_(state.last_f_by_model), delta_physical_by_model: delta,
    shortage_physical_by_model: shortage, applied_units_by_offer: units, state: state};
}

function ntcApplyMovements_(previousState, articleRows, movements) {
  var state = ntcCopy_(previousState);
  var articles = ntcArticles_(articleRows, state.last_f_by_model);
  ntcTrackSchema_(state, articles);
  if (!state.base_physical_by_model) {
    state.base_physical_by_model = {};
    Object.keys(state.last_f_by_model).forEach(function (model) {
      state.base_physical_by_model[model] = state.last_f_by_model[model] + state.applied_physical_by_model[model];
    });
  }
  state.movements = state.movements || {};
  state.manual_movement_physical_by_model = state.manual_movement_physical_by_model || {};
  movements.forEach(function (movement) {
    var id = String(movement.id || '').trim(), model = String(movement.model || '').trim();
    var quantity = ntcInteger_(movement.quantity, 'movement/' + id);
    if (!id || !quantity || !Object.prototype.hasOwnProperty.call(state.last_f_by_model, model) ||
        ['supply', 'writeoff'].indexOf(movement.type) < 0) throw new Error('invalid movement ' + id);
    var entry = {id: id, model: model, quantity: quantity, type: movement.type,
      timestamp: String(movement.timestamp || ''), comment: String(movement.comment || '')};
    if (state.movements[id]) {
      var saved = ntcCopy_(state.movements[id]); delete saved.applied_quantity;
      if (!ntcEqual_(saved, entry)) throw new Error('movement id changed: ' + id);
      return;
    }
    // An excessive writeoff consumes available pieces only; never create debt.
    entry.applied_quantity = entry.type === 'supply' ? quantity : Math.min(quantity, state.last_f_by_model[model]);
    var signed = entry.type === 'supply' ? entry.applied_quantity : -entry.applied_quantity;
    state.base_physical_by_model[model] = ntcInteger_(state.base_physical_by_model[model] + signed, 'base/' + model);
    state.manual_movement_physical_by_model[model] = (state.manual_movement_physical_by_model[model] || 0) + signed;
    state.movements[id] = entry;
    ntcDeriveF_(state);
  });
  return state;
}

function ntcAllocate_(stock, articleRows) {
  var articles = ntcArticles_(articleRows, stock), groups = {}, result = {};
  Object.keys(stock).forEach(function (model) { ntcInteger_(stock[model], 'F/' + model); });
  Object.keys(articles).forEach(function (offer) {
    var model = articles[offer].model;
    (groups[model] || (groups[model] = [])).push(offer);
  });
  Object.keys(groups).forEach(function (model) {
    var offers = groups[model].sort(function (a, b) { return articles[a].H - articles[b].H; });
    var prefixes = [], total = 0;
    offers.forEach(function (offer, index) {
      if (index && articles[offers[index - 1]].H === articles[offer].H) throw new Error('one model contains repeated multiplicity H');
      total = ntcInteger_(total + articles[offer].H, 'multiplicity sum'); prefixes.push(total);
    });
    var remainder = stock[model], cumulative = 0;
    for (var i = offers.length - 1; i >= 0; i--) {
      cumulative += Math.floor(remainder / prefixes[i]);
      remainder %= prefixes[i]; result[offers[i]] = cumulative;
    }
  });
  return result;
}

if (typeof module !== 'undefined') module.exports = {ntcAdvance_: ntcAdvance_, ntcApplyMovements_: ntcApplyMovements_, ntcAllocate_: ntcAllocate_};
