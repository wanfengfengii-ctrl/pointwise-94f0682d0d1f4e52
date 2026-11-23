# 质控卷中途离站

卷车出发前，归档员要确认 Q1 上本批前段已经实写并核实。车走后，归档员在 Q2 续写本批质控余行。夜班收到独立截取的振幅卷、旧质控卷和续用质控卷，再按同一成果号核账。卸载许可只授权移卷，核账资格以整批成果生效与三卷证据齐备为准。

## 办理接口

在 `issue.publish` 提供以下两个入口。`store` 和 `prepared` 沿用原来的 `FileReelStore` 和 `PreparedCatalog`。

```python
issue_unload_permit(store, prepared, request_id, prepared_id, amplitude_reel_id,
                    first_quality_reel_id, next_quality_reel_id, cut, checkpoint=None)
publish_after_unload(store, prepared, request_id, prepared_id, amplitude_reel_id,
                     first_quality_reel_id, next_quality_reel_id, cut, checkpoint=None)
```

三个卷依次为 A、Q1、Q2。初次开办须核对三张卷的角色、卷号和实物序列号，三张卷的卷号与序列号分别互异。请求号使用非空文本，在换卷模式内判重。`cut` 是前段行数，须为严格介于 0 和准备件行数之间的整数，布尔值无效。准备件的原序前 `cut` 行质控归 Q1，其余归 Q2。全部振幅归 A。原行引用和物理原址沿用 `README.md` 中的计数口径。

`issue_unload_permit` 开办并写齐首段所需的 Q1 质控记录。它须按本请求的准备件和实际原址核实 Q1，才可持久生效。若完整首段已经写成但未发许可，重开后核准原段及其原址。许可生效后锁定其原址、内容及实物身份。返回不可变的 `UnloadPermit`，含 `request_id`、`prepared_id`、`release_id` 和按原序排列的 `quality_addresses` 元组。成果号此时可用于查询，但许可阶段尚不能出账。许可生效后的同参补领可以在 Q1 已卸载时办理。

`publish_after_unload` 要求已有生效许可，仅凭仍可用的 A、Q2 和固定准备件即可续办。它须保留已核定的 Q1 段，核实其余实写记录，两段共同覆盖同一准备件后才能使整批成果生效。返回与许可同成果号的既有类型 `ReleaseReceipt`，双侧地址按原序一一对应。完整记录之间中断可重开续办，生效失答可领回首次回执，生效后的重投不重复追加。异参重投抛 `RequestConflict` 且不得改变原绑定、许可或成果。非法新参数抛 `ValueError`。未知准备件沿用 `KeyError`。许可生效前 Q1 不可用时，开办抛 `FileNotFoundError`。未获许可的续签抛 `ValueError`。

换卷模式仍按单发行进程和完整记录追加模型运行。`checkpoint(stage, detail, release_id)` 沿用原回调形状。`quality_written` 在质控原行实写后触发，`detail` 是实际 `RecordAddress`。`permit_effective` 在许可持久生效后、交付前触发，`detail` 是该许可。`release_effective` 在整批成果持久生效后、交付前触发。三个时点均提供同一成果号。夹具在回调中抛出 `InterruptedError`，由调用者重开后按原号办理。

## 夜班实收

在 `review.read` 提供 `read_split_release(release_id, amplitude_copy, first_quality_copy, next_quality_copy)`，返回现有的 `ReviewResult` 或 `ReviewUnavailable`。每份副本独立截取，参数顺序与办理时一致，`None` 表示该份未收到。夜班只凭三个副本及成果号核定，依据 A 副本中的最终生效事实，逐段实核写入归属、内容和原址。同值的异请求实写属于异件。只有全部覆盖并核实后，才按原序交付明细、原行引用、双侧原址和原分码组账。缺卷、短尾、证据错误、未知成果号及待生效批次返回 `ReviewUnavailable`，无明细或组账。普通双卷流程、历史件和所有原回归沿用原入口。

## 运输班次样例

`unload_example.py` 以测位 14、2、9 接纳 7、11、13 微伏，质控依次为合格、复检、合格，切点为 2。许可补领后，前两条质控地址保持在 Q1 的实际原址，末条在 Q2。复核后合格 2 行、和 20，复检 1 行、和 11。早截 A、缺失旧卷、旧卷短尾、同卷号异实物和同值异请求分别验证领取资格。

随题夹具的 `python3 -B unload_example.py fixture` 可在开发前用原双卷路径检查样例。交付时将 `.pointwise-runtime.json` 的 `verify` 接到 `python3 -B unload_example.py verify`，该入口先跑原完整回归，再核对换卷样例。`demo` 接到 `python3 -B unload_example.py demo`，演示实际搬离 Q1、重开续签及停源实收。运行清单沿用 `version: 1`、`kind: cli` 和空 `setup`，命令各用 argv 数组。任一业务核验失败须非零退出。
