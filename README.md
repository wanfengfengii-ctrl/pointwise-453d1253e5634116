# 双工位涂层检验线

涂装厂白班导入左右量规的录制并按两台独立的实收序位封账。夜班凭班账号领取固定结果，在量规录制停用后仍能核对厚度、口径、原码和原物理行。每片在本班由登记工位采集。

## 一天的业务流程

1. 操作员登记班次及左右工位，按上游清册顺序录入试片。工作日样例的顺序是 R-A、L-A、R-B、L-B。
2. 计量员为各台发布量规版本。每版含正倍率、偏置、闭原码区间和厚度限值。
3. 班长明确选用左右各一版开班。后续发布的版本可供其他班选用。
4. 操作员从两台录制读取试片号、测次号和原码，保留原物理行号。
5. 采集服务核对工位、范围及身份。合法首投在本台获得下一个序位。按冻结口径计算原码 × 倍率 + 偏置，单位为 μm。合法复投领原收件。
6. 班长按指定本地序位固定该台的实测前缀。每片保留实收次数、最大值及测次原据。无实测时记录缺测和空最大值。零原码是实测，等限判未超限。
7. 班长选择同班的左右封账号。签发按全班清册顺序保存父账与逐片引用，提交成功才返回班账号。
8. 夜班停用录制源后重开数据库按号领取。补采及另封新账后，旧号继续返回原证据和判定。

## 运行

使用 Python 3.11 及其标准库。平台物化时提供 `check_project.py`，从项目根目录运行完整回归与工作日演示。

```text
python3 -B check_project.py
python3 -B -m line.workday
python3 -B check_anonymous.py replay
```

匿名窗样例的逐条投递见 `ANONYMOUS.md`。`.pointwise-runtime.json` 的 `verify` 指向 `check_all.py`，它依次跑完整回归、匿名样例回放和工作日演示并传播失败退出码；`demo` 仍指向 `line.workday`。

演示在临时目录中导入 `samples/left.csv` 与 `samples/right.csv`。左台原码 0 和 10 分别得 1 与 16 μm，右台原码 4 得 7 μm。停源后追加左台原码 12，新账显示 19 μm 并判超限，旧账仍显示 16 μm。第二个场景演示匿名窗的迟到补齐、提交失败续办与停源领取。业务断言失败会使对应进程返回非零状态。

## Python 接口

以 `line.workday.connect(path)` 打开数据库连接，并调用 `line.workday.initialize(db)` 建立业务表。初始化可重复，保留现有清册、追加口径、测次及封账和班账。调用方关闭连接。工作流的写接口拥有本次事务，要求连接当前没有外层事务。仓储的内部写入由工作流的同一事务覆盖。

| 模块 | 接口与结果 | 业务拒绝 |
| --- | --- | --- |
| `line.intake.shifts` | `register(db, shift_id, left, right, entries)` 返回登记号。`entries` 是按清册排列的 `(specimen_id, station)`。`open(db, shift_id, left_version, right_version, *, anonymous_station=None)` 返回含冻结版本的 `OpenedShift`；指定工位即启用该侧匿名窗。 | 清册非法或重复登记报 `RegistrationRejected`。未知班、已开班、缺版本、错绑或匿名工位不在本班报 `OpeningRejected`。 |
| `line.calibration.revisions` | `calibrate(db, station, gain, offset_um, raw_min, raw_max, limit_um)` 返回新版本整数号。 | 非法工位、数值、倍率或区间报 `ProfileRejected`。 |
| `line.capture.admission` | `ingest(db, shift_id, station, specimen_id, reading_id, raw_code, source_line)` 返回含测次号、序位、精确厚度的 `Receipt`。`ingest_recording(db, shift_id, station, source)` 返回逐条收件。匿名窗另有 `ingest_ticket`、`ingest_anonymous`、`declare_end`，见 `ANONYMOUS.md`。 | 未开班、未知片、错台、越界或同号异参报 `IngestRejected`。录制格式错误报 `RecordingFormatError`。批次录制逐条提交，较早的合法收件可保留。匿名侧调用具名 `ingest` 或 `ingest_recording` 亦报 `IngestRejected`。 |
| `line.closing.cut` | `seal(db, shift_id, station, cutoff)` 返回含固定封账号和质量明细的 `StationSeal`。截点 0 表示空前缀。匿名窗用 `seal_anonymous(db, shift_id, station)`，返回 `(state, seal_id)`。 | 未开班、错台、负序或超出本台日志头报 `SealRejected`。匿名侧调用旧 `seal`、未启用窗或提交失败同样报 `SealRejected`。 |
| `line.report.publish` | `publish(db, first_seal_id, second_seal_id)` 接收同班左右两份封账号，参数顺序不限，返回整数班账号。 | 父账不存在、跨班、同侧、写入或提交失败报 `PublishRejected`，无新账可领。 |
| `line.report.readback` | `read(db, report_id)` 返回 `ReportView`，含两父账号及原清册顺序的明细。 | 未知班账号报 `ReportNotFound`，它是 `LookupError` 的子类。 |

标识符为首尾无空白且不含换行或空字符的非空字符串。同班测次身份覆盖工位、试片、精确原码值和行号，`10` 与 `10/1` 表示相同原码。录制采用文本 CSV，表头是 `specimen_id,reading_id,raw_code`，空物理行可跳过，原行号从 1 开始并包含表头。精确数值接受整数、`Fraction`、有限 `Decimal` 或分数/小数字符串。布尔值、浮点数、非有限值和空值拒收。读回的数值使用 `Fraction`。逐片清册位置从 0 开始，质量状态为 `missing`、`within_limit` 或 `over_limit`。
