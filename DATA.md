# 资料约定

原始资料均为本地合成。CSV 使用 UTF-8，首行是字段名。

所有时间为同一当地时区，日历以 `calendar` 中的半开区间为准。`commitments` 的 `start` 取 received、accepted 或 ready；ready 表示已接单且前置工作已达到确认标准。`clock` 为 elapsed 或 open；限时及提醒提前量均为分钟。`replace` 是经批准结束原范围另立范围，`transfer` 只移交责任；两者都不抹去历史责任。`finish` 是承办人完成记录，`confirm` 是确认必要工作或整个事项已解决，`dispute` 标识原问题未解，`new_case` 引用另外的事项。没有权限取证的工作项不因为收到催办而转为可办理。
`events.recorded` 是到达时间，`occurred` 是业务发生时间；`supersedes` 非空时新记录替代对应旧事实，不替代发送回执。`pause` 和 `resume` 的 `detail` 是材料原因，需与承诺允许的原因一致。`notices` 保存实际发出或计划中的催办，`action` 与工作项的动作词同域。发送历史的 `as_of` 是当时能看到的输入截止时间，`due` 是催办回执持续追踪的期限。空工作项表示整个事项。
