# 装载票与匿名量规实读

双工位的具名工作流见 README.md。匿名窗是一个可选的开班模式。每班最多启用一侧且该侧只有一个窗，两份独立录制均以该班次和工位为作用域。对侧继续接纳具名测次并按本地截点封账。仍用 line.workday.connect 和 initialize，初始化可在旧库和重开后调用。

## 开班和收件

- line.intake.shifts.open(db, shift_id, left_version, right_version, *, anonymous_station=None) 新增可选工位，返回原有开班对象。启用与版本冻结一起提交。无参数沿用原模式，指定非本班工位报 OpeningRejected。
- 下面三个入口位于 line.capture.admission。只能对已启用的班次和工位调用。输入非法、错台、位置冲突或封尾冲突报 IngestRejected。

| 入口 | 输入与收件 |
| --- | --- |
| ingest_ticket(db, shift_id, station, source_seq, source_line, specimen_id, first_shot, last_shot) | 接纳装载票并返回 source_seq。试片必须登记在该台，且每片至多一票。first_shot 到 last_shot 是含两端的可配拍号。 |
| ingest_anonymous(db, shift_id, station, source_seq, source_line, shot, reading_id, raw_code) | 接纳匿名实读并返回 source_seq。按开班冻结口径校验原码，无需试片号。 |
| declare_end(db, shift_id, station, stream, last_seq) | stream 为 ticket 或 reading。冻结该流最后源序 last_seq 并返回它，0 表示空流。 |

每流的源序和原物理行是正整数，两者独立且分别在本流内唯一。源序为 1 到封尾位置，物理行号可跳过。读号按原标识符规则校验，在匿名实读流内唯一，并与对侧具名测次号独立。拍号及整数位置须可用 SQLite 的有符号 64 位整数表示，不接受布尔值。原码沿用 V1 精确数值规则，复投时 7 和 7/1 等价。两流源序、行号或拍号可以交叠。

收件及结束声明可以任意交错。相同收件或结束声明在签发前后重投都返回原结果。相同源序异内容、复用本流物理行或实读号、同一试片另投第二张票、变更已声明的封尾、声明低于已收最大源序、发送超过已声明封尾的原件均拒绝，原件和覆盖事实保持。匿名侧沿用的 ingest 和 ingest_recording 报 IngestRejected，旧 seal 报 SealRejected。

## 工位封账和班账领取

调用 line.closing.cut.seal_anonymous(db, shift_id, station)，返回二元组 (state, seal_id)。未启用的班台和数据库写入或提交失败报 SealRejected。状态如下。

| 返回 | 核定结果 |
| --- | --- |
| ("pending", None) | 任一路未声明封尾或缺少 1 到 last_seq 的任一位置。 |
| ("no_match", None) | 两路已齐，但无法配对全部票和全部实读。 |
| ("ambiguous", None) | 至少有两种完整配对，即使交换的读数原码相同。 |
| ("sealed", seal_id) | 唯一配对已固定，成功后重投返回同号。 |

仅在两流都已声明结束且分别收齐 1 到 N 的每个位置，才可裁定归属。两路票数和读数不等时没有完整配对。两路均为空时空配对唯一。按物理记录判定完整配对是否唯一，即使原码相同也区分各条实读。待齐、无解或歧义均不生成封账。封账提交失败不留下可见封账，同窗可沿原件续办，成功后重投领取原封账号。

唯一配对后原码按开班口径精确换算，沿用原清册质控与原有状态。没有票的试片仍在清册中，次数为 0，最大值为空，状态为 missing。继续使用 line.report.publish.publish 接收两个父账号，并由 line.report.readback.read 按班账号读取。按固定班账号返回原质控结果及实际采用的逐条装载票与量规原据，包含各自源序和原物理行。

逐条读证据沿用 reading_id、sequence、source_line、raw_code、thickness_um、profile_version。匿名读的 reading_id 是实读号，sequence 是实读源序。新增 anonymous 属性用于查看来源，原具名读为 None，匿名读的该属性提供 shot 和 ticket。ticket 提供 source_seq、source_line、specimen_id、first_shot、last_shot。班账原有父账号、清册顺序、定标和判定保持，未知班账号沿用 ReportNotFound。匿名源内读号可与对侧旧测次号相同，两份原据须能独立领取。

## 样例和运行

samples/station_events.json 记录三份独立窗口的逐条投递。检查点 expect 表示调用封账并核对状态。样例换算倍率为 1，偏置为 0，原码区间为 [0,20]，限值为 10 μm。迟到场景的首条 r1 可配两片，补到拍 2 的 r2 后只可配 L-A，L-B 归 r1，R-A 仍领对侧同号 r1。report 的每行列出试片、状态、最大厚度和读数列表。读数列表里的每项依次是读号、源序、行号、原码、厚度及匿名出处，匿名出处依次是拍号和装载票字段，票字段顺序同上。

从工程根目录运行 python3 -B check_anonymous.py fixture 可查看样例事件。交付功能后，python3 -B check_anonymous.py replay 逐条投递并核对结果。样例用 SQLite 授权回调在封账的 COMMIT 生效前制造失败，通过另一连接检查可见父账，释放连接并停用样例源后验证原件续办和班账领件。可用等价的失败验证接入不同存储组织。

使用现有 .pointwise-runtime.json 接上联合核验与演示，保留 README.md 两条 V1 命令各自的业务覆盖和失败退出码。该清单沿用原有字段，verify 和 demo 各指向一个 argv，setup 是准备命令的 argv 列表。
