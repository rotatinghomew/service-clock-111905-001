# 联办履约与催办

本项目用于整理社区服务运营数据。`fixtures/` 保存本地合成源记录，各表字段和业务时序约定见 `DATA.md`。没有线上服务或真实个人信息。

使用 Python 3.11 验证资料结构：

```sh
python3 -m unittest discover -s tests -v
```

## 履约账与催办（serviceclock）

`serviceclock/` 用源记录记当天的履约账：责任项按适用班表计时（停钟以有效
等待原因为限，重叠不重复扣；回执只有发生界限时保留各种可能先后关系，
不按最有利解释算达标）；居民承诺按同意的实际窗口履约，候约、通知已发、
已接受是不同事实；调整单只暂占到确认截止，旧约在居民确认前仍然有效，
逾期才知道的接受不能复活已释放的暂占。

```sh
python3 -m serviceclock --now 10:40 status [--case C1|--grid 北区|--window W2]
python3 -m serviceclock --now 09:55 impact --duty D12   # 退单影响
python3 -m serviceclock --now 10:40 options --case C5   # 催办方案比较
python3 -m serviceclock --now 10:46 handover --case C2  # 发出最优方案并交接
```

催办方案不按剩余分钟排队：同一人员和同一间核验室不重复承诺，联合上门
要求材料预审已结束且整组同时段可用，受保护的既有预约不能被挪给新单；
所有收发都写本地业务回执，值班交接可从一条催办记录查到它处置过的风险、
当前仍有效的预约及未能处理的原因。
