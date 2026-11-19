# 源记录说明

均为合成运营记录。文件为 UTF-8 CSV，首行为字段名；空值没有声明事实，不等于零。时段左闭右开。

同一服务日，时间精度为分钟。两个窗口的责任项计时适用各自营业时段；时长和实际预约另记。记录按 received 的到件时点可分批读入；同一时刻全批可用。没有 supersedes 表示追加而非覆盖。

- `terms.csv`：居民受理单。`due_minutes` 是责任项上限，每项各计；`duration` 是联合约的占用分钟。

- `duties.csv`：责任项的初始归属、窗口、技能和上门前置关系；空 prerequisite 表示无前置。prep 是准备环节，visit 是实地岗位。

- `shifts.csv`：人员班表与共同房间的可用段。房间无所属窗口；多个技能以分号分隔。修订以 received 起对值班台可知，业务有效区间仍用 start/end。

- `appointments.csv`：原通知与值班员收到的待比较调整单。各资源同段容量均为一。proposal 有接受截止，不能把既有约当成已解除；示例中的历史发送回执只是收到的事实。

- `receipts.csv`：时点不明可给发生界限；pause_open/pause_close 的 detail 是等待理由，transfer 为新接手人，void 为撤销。预约回执 target 指通知，其他指责任项。
