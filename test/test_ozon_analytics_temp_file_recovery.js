const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sourcePath = path.join(__dirname, "..", "Ozon заказы.js");
const source = fs.readFileSync(sourcePath, "utf8");

const properties = {};
const createdFiles = [];
const context = {
  console,
  JSON,
  Math,
  Date,
  String,
  Number,
  Object,
  Array,
  Logger: { log: () => {} },
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (name) => properties[name] || null,
      setProperty: (name, value) => { properties[name] = String(value); },
      deleteProperty: (name) => { delete properties[name]; }
    })
  },
  DriveApp: {
    getFileById: (fileId) => {
      if (fileId === "stale-file-id") throw new Error("No item with the given ID could be found");
      throw new Error(`unexpected file id: ${fileId}`);
    },
    createFile: (name, content, mimeType) => {
      const file = {
        id: "new-file-id",
        getId: () => file.id,
        name,
        content,
        mimeType
      };
      createdFiles.push(file);
      return file;
    }
  },
  MimeType: { PLAIN_TEXT: "text/plain" }
};

vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

properties.OZON_ANALYTICS_TEMP_FILE_ID = "stale-file-id";
properties.OZON_ANALYTICS_RUN_ID = "test-run";
context.appendOzonAnalyticsTempRows_([["test-run", 0, "123", 1, ""]]);

assert.strictEqual(properties.OZON_ANALYTICS_TEMP_FILE_ID, "new-file-id");
assert.strictEqual(createdFiles.length, 1);
assert.deepStrictEqual(JSON.parse(createdFiles[0].content).rows, [["test-run", 0, "123", 1, ""]]);

properties.OZON_ANALYTICS_TEMP_FILE_ID = "stale-file-id";
context.writeOzonAnalyticsTempPayload_({ rows: [["test-run", 0, "456", 2, ""]] });
assert.strictEqual(properties.OZON_ANALYTICS_TEMP_FILE_ID, "new-file-id");
assert.strictEqual(createdFiles.length, 2);
assert.deepStrictEqual(JSON.parse(createdFiles[1].content).rows, [["test-run", 0, "456", 2, ""]]);

console.log("PASS test_ozon_analytics_temp_file_recovery");
