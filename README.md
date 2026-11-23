# 轨检资料中心双卷归档 V1

白班把按测位记录的振幅和质控码接纳为固定录制，计量员统一单位，归档员将两列分别存入只追加卷。夜班持两份独立截取的卷副本按成果号领取逐行明细及质控组账，复检人员据双侧原址定位原记录。

## 运行

需要 Python 3.11，依赖均在标准库中。从项目根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

第一条运行完整业务回归，入口由运行平台提供。演示在独立临时工作区挂载随附旧卷，接纳 `examples/day.json` 的来件，实际换算、发行、截卷和离线核账。演示输出的 `POINTWISE_SCENARIO` 行含实测明细和组账。

## 白班到夜班

1. 设备按实测顺序提交具名来件，包含设备号、检测区段和原行。
2. 资料员整批检查字段及测位唯一性，随后冻结来件及原序。
3. 计量员按录制号和口径取得固定准备件。准备件保存每条原行的引用。
4. 归档员提交具名请求、准备号和有序目标卷对，持久接纳这组参数。
5. 振幅和质控逐条追加到各自卷。中断后重开可识别待办请求，已写记录保留。
6. 双侧完整且归档已生效后返回成果号和双侧原址。丢失回包时可凭原请求补领。
7. 夜班分别选取两卷的完整记录前缀，副本保留原身份和原址。
8. 夜班指定成果号核验实际收到的两份卷副本，领取原序明细或收到不可用结果。
9. 已核实明细同时形成分码组账，供复检人员核对行数、有效振幅和及原址。

## Python 接口

| 接口 | 调用与返回 | 失败行为 |
| --- | --- | --- |
| I1 | `recording.intake.accept_recording(catalog, submission, source, rows)` 返回 `FrozenRecording`，含 `recording_id` 与 `row_refs` | 非法字段、空批或重复测位抛出 `ValueError`，无冻结件 |
| I2 | `prepare.batch.prepare_batch(recordings, prepared, recording_id, profile_name='v1')` 返回 `PreparedBatch` | 缺录制抛出 `KeyError`，未知口径、单位或码抛出 `ValueError`，无准备件 |
| I3 | `issue.publish.publish(store, prepared, request_id, prepared_id, amplitude_reel_id, quality_reel_id, checkpoint=None)` 返回 `ReleaseReceipt`，含成果号和两列逐行地址 | 同号异参抛出 `issue.requests.RequestConflict`。缺准备件抛出 `KeyError`，错卷角色抛出 `ValueError`，找不到卷抛出 `FileNotFoundError` |
| I4 | `reels.append.append_record(store, reel_id, logical, expected_ordinal=None)` 返回 `RecordAddress` | 找不到卷抛出 `FileNotFoundError`，非法记录、卷身份或非尾部序号抛出 `ValueError` |
| I5 | `reels.copy.copy_prefix(store, reel_id, count=None)` 返回不可变 `ReelCopy` | 找不到卷抛出 `FileNotFoundError`，非法身份或截点抛出 `ValueError` |
| I6 | `review.read.read_release(release_id, amplitude_copy, quality_copy)` 返回 `ReviewResult` 或 `ReviewUnavailable` | 证据不足时 `available` 为假，结果无明细或组账字段 |

`DeviceSource(device_id, section)` 的两个字段与来件名均为非空文本。原行使用 `position`、`amplitude`、`unit`、`status` 四个字段。测位是正整数，振幅用十进制字符串、Python 整数、有限 `Decimal` 或显式 `None` 表示。样例将小数写成字符串。`uV` 和 `mV` 分别按因子 1 和 1000 换算为整数微伏，恰半向远离零舍入。状态 OK、RECHECK、BAD 对应合格、复检、无效。未知单位与状态由准备入口拒绝。组账按码排序，缺测计行，求和只累加有效整数。零值保留为有效读数。

`RecordingCatalog(path)` 和 `PreparedCatalog(path)` 分别固定录制和准备件。原行引用是录制号与从 0 开始的行序。地址是卷号与从 1 开始的物理记录序号。新发行每侧每行占一条记录。旧卷的历史行束在同侧共享原记录地址，原行引用区分束内各行。

`FileReelStore(path).initialize_reel(ReelHeader(reel_id, role, serial))` 创建或核对介质。角色为 `amplitude` 或 `quality`，卷号与实物序列号由工作区配置。重复初始化沿用原记录和地址，身份不符时报错。`fixtures/legacy-reels` 可原样复制为卷工作区，卷头与历史记录可直接扫描。修改来件后再次接纳会按新内容生成身份，旧冻结件与旧成果保持原内容。副本截点为从卷首起的完整记录数，`None` 表示整个当前前缀。

可选 `checkpoint(stage, detail, release_id)` 在持久追加之后以及交付成功回执之前调用。追加阶段为 `request_bound`、`amplitude_written`、`quality_written`、`release_effective`，`detail` 为刚追加的原址。`before_reply` 的 `detail` 为将要交付的回执。候选产生前 `release_id` 可以为 `None`。回调抛出 `InterruptedError` 模拟追加之间或回包前中断。新的工作区对象从持久文件恢复。

介质模型以完整记录为追加单位。初始化与追加据目录中的完整记录恢复，已挂载文件保持原址。V1 按单发行进程运行，工作范围为固定卷对和独立前缀复核。

## 业务回归

`tests/test_recording.py` 覆盖拒收和冻结。`tests/test_prepare.py` 核对混合单位、恰半舍入、缺测、原序及重开复取。`tests/test_issuance.py` 覆盖持久接纳、追加中断、齐行待生效、丢回包、异参拒绝和旧介质重开。`tests/test_review.py` 覆盖错卷、错开前缀、旧候选、断源原址和分码核账。`tests/test_end_to_end.py` 通过同一个演示流程核对整班交接。
