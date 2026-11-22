<!-- markdownlint-disable MD033 MD041 -->

<div align="center">

# MaaResonance Plus

基于 MaaFramework 的《雷索纳斯》自动化小助手（社区衍生增强发行版）。  
由 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 强力驱动！  
<a href="https://github.com/JizhiShiroppu/MaaResonance" target="_blank" style="font-weight: bold;">🔗 本发行版 GitHub 仓库</a><br>
🌟喜欢本项目欢迎给上游原仓库与本仓库点个星星🌟

</div>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Android%20Emulator-blueviolet">
  <img alt="license" src="https://img.shields.io/github/license/JizhiShiroppu/MaaResonance">
  <br>
  <img alt="commit" src="https://img.shields.io/github/commit-activity/m/JizhiShiroppu/MaaResonance">
  <img alt="stars" src="https://img.shields.io/github/stars/JizhiShiroppu/MaaResonance?style=social">
  <img alt="downloads" src="https://img.shields.io/github/downloads/JizhiShiroppu/MaaResonance/total?style=social">
</p>

<div align="center">

[简体中文](./README.md)

</div>

> [!Important]
>
> 本发行版是基于 [DaiMao204/MaaResonance](https://github.com/DaiMao204/MaaResonance) 的社区衍生增强版，遵循原项目 **AGPL-3.0-only** 开源协议。  
> 新增功能均按独立模块向原仓库提交 PR，上游合入后也会持续同步主线。  
> **使用本增强版遇到任何问题，请直接在本仓库 [Issues](https://github.com/JizhiShiroppu/MaaResonance/issues) 反馈，请勿去原仓库打扰原作者。**

## ⚠️免责声明与风险提示

> [!Note]
>
> 本软件为第三方工具，通过识别游戏画面模拟常规交互动作，简化《雷索纳斯》的游戏玩法。本项目遵循相关法律法规。本项目旨在简化用户的重复性操作，不会破坏游戏平衡或提供不公平优势，也绝不会修改任何游戏文件或数据。
>
> 本项目开源、免费，且仅供学习和交流使用。项目源码使用 GNU Affero General Public License v3.0 only 开源；再分发、修改或发布衍生版本时，请遵守 AGPL-3.0-only 及第三方组件各自许可证。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题，均与本项目及开发者无关。
>
> 本项目使用了一定程度的AI编程，可能会导致代码可读性差、开发维护困难等，如遇到问题可提交Issues。

> [!Caution]
>
> 根据《雷索纳斯》公平运营宣言：
>
> 严禁制作、使用、传播第三方软件、插件、外挂和恶意利用游戏BUG等破坏游戏公平性的行为：对破坏游戏公平性的行为，我们将依据后台监控和玩家举报。经核实后被认定为具有上述违规行为的用户，依据情节轻重对其采取惩戒措施，包括但不限于扣除违规收益、冻结游戏账号、永久封禁游戏账号等。
>
> **您应充分了解并自愿承担使用本工具可能带来的所有风险。**

## 使用须知

- 运行 `MaaResonance.exe` 后选择控制器。游戏画面使用 16:9，推荐 `1920x1080` 或 `1280x720`。
- **安卓模拟器**使用 ADB 连接，推荐 MuMu。可使用完整自动日常、主线/铁安局/作战中心/虚演刻录推进、启动游戏及双城跑商。
- **国服 PC 客户端**支持**前台**与两种可选**后台模式**（`PC 客户端（后台-移窗不抢鼠标）` / `PC 客户端（后台-移光标）`）。先打开游戏并登录，进入可操作的主界面再连接游戏窗口；后台模式下游戏窗口可被其他窗口遮挡，但**不可最小化**；若遇到兼容性问题可随时切回默认的「PC 客户端（前台）」。
- 首次在 PC 上跑商时可选「PC 手动跑商（一轮）」或「PC 自动跑商（试用）」预设，核对参数后开始。PC 一轮预设会核对当前 UID 并使用本地账号资料，缺失时采用默认配置；需要更新资料时可将「账号配置读取模式」改为「智能读取」。

## 功能列表

- **一键自动日常**（可自由勾选顺序与开关）与轻量日常整合：
  - 开始唤醒（热更确认、公告关闭、首登弹窗收口）
  - 日常前置收菜（邮箱领取、派遣委托、好友支援金币、启程签到、商城无垠补给周卡、营收排行榜点赞）
  - 自动商店采购（按 UID 记录 05:00 日/周/月刷新周期，支持黑月总部商店、赴命商店、商会里程点数兑换与 `*N` 限购 / `^` 置顶）
  - 共斗活动（众志攻坚自动挑存活最高难度及领奖）、活动/关卡刷澄明度、限时剧情日常（糖霜记忆）
  - 日常收尾领奖（导航手册每日活跃与宝箱、环游手册通行证奖励）
- **战斗与剧情推进**：
  - 主线自动推进（实验性）、剧情跳过、自动编队与自动战斗（快斩模式 / 权重出牌模式）
  - 铁安局全自动（远程逐城清 100% / 本地刷声望）
  - 区域作战中心自动推关（支持短站点低关卡优先与澄明度安全停机）
  - 虚演刻录自动推关（支持低敌方等级优先、未达成 S 级自动跳过与 0 门票收口）
- **双城跑商与全局守卫**：
  - 启动游戏、手动/自动双城跑商（支持可选的行车自动拾取）
  - 断线弹窗自动重连守卫（全局可选）

## 开发相关

- [开发文档](./docs/zh_cn/develop/how_to_develop.md)

更多文档请前往 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 主仓库查看。

## 开源许可证

本项目使用 GNU Affero General Public License v3.0 only 开源，详见 [LICENSE](./LICENSE)。
发布包中包含的第三方组件按其原许可证授权：

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework)：LGPL-3.0
- [MXU](https://github.com/MistEO/MXU)：AGPL-3.0

## Star 历史

<a href="https://www.star-history.com/#JizhiShiroppu/MaaResonance&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=JizhiShiroppu/MaaResonance&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=JizhiShiroppu/MaaResonance&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=JizhiShiroppu/MaaResonance&type=Date" />
 </picture>
</a>

## 鸣谢

### 上游原项目

- [DaiMao204/MaaResonance](https://github.com/DaiMao204/MaaResonance)  
  本衍生增强版的上游项目与原始基础。

### 核心框架

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework)  
  基于图像识别的自动化黑盒测试框架 | An automation black-box testing framework based on image recognition

### UI 支持

- [MXU](https://github.com/MistEO/MXU)  
  基于 MaaFramework PI V2 协议的通用 GUI 客户端，使用 Tauri + React + TypeScript 构建。

### 开发者

感谢所有为上游项目与本衍生版作出贡献的开发者:

[![Contributors](https://contrib.rocks/image?repo=DaiMao204/MaaResonance&max=1000)](https://github.com/DaiMao204/MaaResonance/graphs/contributors)

## 问题反馈与交流

- 本增强版问题反馈：[Issues](https://github.com/JizhiShiroppu/MaaResonance/issues)
- MaaFramework 开发交流 QQ 群：595990173
- 反馈问题时请附带 MXU 日志、任务配置与出错界面截图。
