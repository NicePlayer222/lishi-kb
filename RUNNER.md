# LightVela Runner（A 方案）

这个 runner 让 DSH 通过 GitHub 给 LightVela 的 Hermes 发任务，不需要 SSH、不需要公网端口。

## 工作原理

1. DSH 在仓库写 `inbox/command.json`（`status: pending`）；
2. LightVela 云机上的 `scripts/runner.sh` 每 30 秒 `git pull` 一次；
3. 发现 pending 命令后，调用 `hermes --yolo -z "<prompt>"` 执行；
4. 结果写到 `outbox/<id>.json`，命令移到 `inbox/done/`，自动 commit + push；
5. DSH 读 `outbox/<id>.json` 就知道结果。

## 在 LightVela 上启动（只需一次）

在 LightVela 的终端里执行：

```bash
cd ~
git clone https://github.com/NicePlayer222/lishi-kb lishi-runner
cd lishi-runner
nohup bash scripts/runner.sh > ~/lishi-runner.log 2>&1 &
```

如果目录已存在，改成：

```bash
cd ~/lishi-runner
git pull --rebase
nohup bash scripts/runner.sh > ~/lishi-runner.log 2>&1 &
```

查看日志：

```bash
tail -f ~/lishi-runner.log
```

## 给 LightVela Agent 的一句话

如果不想手打上面的命令，直接把下面这句发给它：

> 请把 https://github.com/NicePlayer222/lishi-kb 克隆到 ~/lishi-runner，然后读 RUNNER.md，按里面的步骤启动 runner，并把启动日志最后 20 行发我。

## 注意

- runner 会以 `--yolo` 运行 Hermes，任务提示词只从私有仓库读取，不要往 `inbox/` 放不可信内容；
- 一次只执行一条命令；执行期间 `inbox/command.json` 是 `running`；
- 如果 `hermes` 不在 PATH，runner 会直接退出，先在终端确认 `hermes --version`；
- 任务超时默认 3600 秒，可在命令里用 `timeout` 字段改。
