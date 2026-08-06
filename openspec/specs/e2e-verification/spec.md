# e2e-verification Specification

## Purpose

E2E 节点 Test Designer / Test Runner / Test Diagnoser：基于需求点清单生成覆盖矩阵与结构化 DSL 用例，选择器优先 data-testid/文本/role；执行引擎收集 console 与网络异常、支持等待条件与失败证据；失败三方诊断（预期失效/选择器耦合/真实回归）；用例写入 `e2e/cases/` 随代码仓版本化。

## Requirements

### Requirement: 测试用例覆盖矩阵

E2E 节点的 Test Designer SHALL 依据需求点清单(PRD 结构化产物)生成覆盖矩阵,建立"需求点 → 用例"映射;每个需求点至少有一个用例,覆盖不完整时矩阵状态为未通过。

#### Scenario: 覆盖矩阵门禁

- **WHEN** 某需求点 R-07 没有任何用例覆盖
- **THEN** 覆盖矩阵标记 R-07 未覆盖,并在对话框中以 coverage_matrix 消息呈现缺口

#### Scenario: 全需求点覆盖

- **WHEN** 全部需求点均有至少一个用例
- **THEN** 覆盖矩阵状态为通过,可进入用例确认环节

### Requirement: 用例结构化 DSL

Test Designer SHALL 输出结构化 DSL 用例(JSON),包含 id、requirement_id、scenario、steps(动作/目标/断言),不得以自然语言 Markdown 作为用例主体。

#### Scenario: DSL 用例生成

- **WHEN** Test Designer 为需求点 R-03 生成用例
- **THEN** 用例为结构化 JSON,steps 中每个动作含 action、target、断言类型

#### Scenario: 非法 DSL 拒绝执行

- **WHEN** 用例 JSON 无法通过 schema 校验
- **THEN** 执行引擎拒绝该用例并触发用例重生成

### Requirement: 选择器优先测试钩子

用例目标选择器 SHALL 按 data-testid → 文本 → role → CSS 的优先级生成;CSS 选择器仅作为兜底。

#### Scenario: 优先 testid

- **WHEN** 目标元素存在 data-testid 且可用文本定位
- **THEN** 用例选择器使用 data-testid 而非文本

### Requirement: 用例确认环节

用例生成与覆盖矩阵展示后,系统 SHALL 等待用户确认再执行;用户可补充或删除用例。

#### Scenario: 用户确认执行

- **WHEN** 用户确认用例清单
- **THEN** 执行引擎按顺序运行用例,逐条展示结果

### Requirement: 执行引擎增强

E2E 执行引擎 SHALL 在运行时收集 console 错误与网络请求异常,支持等待条件(如元素出现),并在失败时生成证据(DOM 快照、console 日志、渲染截图)。

#### Scenario: 失败证据收集

- **WHEN** 某用例断言失败
- **THEN** 结果包含 DOM 快照、运行期 console 日志与渲染截图

#### Scenario: 等待条件

- **WHEN** 用例步骤声明等待某元素出现
- **THEN** 执行引擎轮询至元素出现或超时,而非固定 sleep

### Requirement: 失败三方诊断

Test Diagnoser SHALL 对回归失败的用例进行三方分类:行为变更导致的预期失效(改用例)、选择器耦合导致的定位失败(修钩子/换选择器)、真实回归(回功能实现节点);分类依据变更 manifest 与证据。

#### Scenario: 预期失效

- **WHEN** 用例断言与 manifest 声明的行为变更一致
- **THEN** 该失败记为预期失效,改写成新行为对应的用例,不触发代码回退

#### Scenario: 真实回归

- **WHEN** 用例断言显示用户可见行为确实被破坏且 manifest 未声明行为变更
- **THEN** 判定真实回归,携带证据回功能实现节点修复

### Requirement: 复杂用例标注

执行引擎无法支持的用例 SHALL 标注 `requires_browser`,一期跳过并列入人工执行清单,不得静默失败。

#### Scenario: 复杂用例跳过

- **WHEN** 用例涉及多页面流转且标注 requires_browser
- **THEN** 执行引擎跳过该用例,在结果中标注"待人工/后端浏览器执行"

### Requirement: 用例入库版本化

生成的用例 SHALL 写入生成应用的 `e2e/cases/` 目录并随代码仓版本化,每条用例带状态字段(active/expected_broken/archived)。

#### Scenario: 用例写入仓库

- **WHEN** Test Designer 完成用例生成
- **THEN** 用例文件写入 `e2e/cases/`,manifest.json 记录用例清单与状态

#### Scenario: 重构用例处置

- **WHEN** 增量开发重构导致某用例预期失效
- **THEN** 该用例状态标记为 expected_broken 或按处置改写,保留在版本历史中
