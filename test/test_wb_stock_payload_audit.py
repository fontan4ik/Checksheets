import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_wb_stock_audit_records_searchable_payload_and_result(tmp_path):
    script = r"""
const { createWbStockAudit } = require('./wb_stock_audit');
const audit = createWbStockAudit({
  scriptName: 'test-sync',
  sheetName: 'StreamSupps',
  sourceReadAt: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
  logDirectory: process.argv[1],
});
const payload = audit.recordPayload({
  warehouseId: 798761,
  warehouseName: 'ВольтМир',
  sourceColumn: 'AC:WB ВОЛЬТМИР ИТОГ',
  batchIndex: 70,
  totalBatches: 85,
  items: [{ offerId: 'MPR10-2-063-1', chrtId: 1921504612, amount: 300 }],
});
audit.recordBatchResult({
  warehouseId: 798761,
  batchIndex: 70,
  checksum: payload.checksum,
  status: 'success',
  code: 204,
  successCount: 1,
});
console.log(audit.filePath);
"""
    completed = subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    audit_path = Path(completed.stdout.strip())
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

    payload = next(record for record in records if record["event"] == "payload_prepared")
    result = next(record for record in records if record["event"] == "batch_result")

    assert payload["sourceColumn"] == "AC:WB ВОЛЬТМИР ИТОГ"
    assert payload["snapshotAgeSeconds"] >= 20 * 60
    assert payload["staleSnapshot"] is True
    assert payload["items"] == [
        {"offerId": "MPR10-2-063-1", "chrtId": 1921504612, "amount": 300}
    ]
    assert result["checksum"] == payload["checksum"]
    assert result["status"] == "success"


def test_all_local_wb_writers_enable_payload_audit():
    etm = (PROJECT_ROOT / "sync-etm-stocks.js").read_text(encoding="utf-8")
    feron = (PROJECT_ROOT / "sync-feron-stocks.js").read_text(encoding="utf-8")

    for source in (etm, feron):
        assert 'require("./wb_stock_audit")' in source
        assert "recordPayload({" in source
        assert "WB STALE SNAPSHOT" in source

