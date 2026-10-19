# 任务入口

DSH 往这里写 `command.json`：

```json
{
  "id": "20261019-001",
  "status": "pending",
  "prompt": "完整任务提示词",
  "timeout": 3600
}
```

runner 执行后会把它移到 `inbox/done/`，结果写到 `outbox/<id>.json`。
