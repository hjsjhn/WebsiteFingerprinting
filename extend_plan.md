# 网站指纹防御中的 FEC 优化与评估设计规范 (最终完整版)

## 第一部分：FEC 嵌入策略算法设计 (Embedding Strategies)

**目标：** 修改现有的防御算法输出逻辑。
**核心原则：**
1.  **Real 包**：产生后立即发送。
2.  **Dummy 包**：根据不同策略，决定是保持原样（对照组）还是替换为 FEC 包（实验组）。

### 1. 通用数据结构
* `HistoryBuffer`: 一个固定大小（如 $W=32$）的队列，存储最近发出的 Real 包 ID。
* `SendLog`: 记录每个发出的包的类型和元数据。

---

### 策略 A：基准对照组 (Strategy A: Baseline / Control Group)
* **适用场景：** 原始的网站指纹防御算法，没有任何 FEC 优化。
* **逻辑描述：**
    1.  **发送 Real 包时：** 正常发送，记录 ID。
    2.  **发送 Dummy 包时：**
        * **动作：** 保持原样，发送类型为 `DUMMY` 的包。
        * **内容：** 全 0 或随机填充，**不携带**任何 FEC 元数据。
        * **意义：** 它的存在仅仅是为了维持流量形状（Traffic Shape），对可靠性没有任何贡献。

---

### 策略 B：固定分桶策略 (Strategy B: Fixed Bucket)
* **适用场景：** 模拟最基础的块编码 (Block Code)。
* **逻辑描述：**
    1.  将数据流切分为固定大小的块（Block），设容量为 $K$（例如 10）。
    2.  维护变量 `current_block_id` 和 `packets_in_current_block`。
    3.  **发送 Real 包时：**
        * 计数器 +1。若计数器达到 $K$，关闭当前块，开启新块。
    4.  **发送 Dummy 包时 (即 FEC 机会)：**
        * 若当前块内有数据 (`counter > 0`)：生成一个保护 `current_block_id` 的 FEC 包。
        * 若当前块为空：无法生成有效 FEC，发送普通空 Dummy（标记为 Wasted）。

---

### 策略 C：类 LT 随机子集策略 (Strategy C: LT-like Random Subset)
* **适用场景：** 模拟无速率码/喷泉码，利用异或运算的灵活性。
* **逻辑描述：**
    1.  维护一个滑动窗口 `buffer`，存储最近 $W$ 个 Real 包。
    2.  **发送 Real 包时：** 入队，若超长则移除最老元素。
    3.  **发送 Dummy 包时 (即 FEC 机会)：**
        * **确定度数 (Degree, $d$)**：在 $[1, \text{len(buffer)}]$ 范围内随机选一个整数。
        * **选择包**：从 `buffer` 中随机选择 $d$ 个包的 ID。
        * **生成**：记录该 FEC 包保护了这 $d$ 个 ID（模拟逻辑中记录 ID 列表即可）。

---

### 策略 D：智能滑动窗口 RLNC (Strategy D: Smart Sliding Window) —— **推荐方案**
* **适用场景：** 解决新老包交替和 Dummy 浪费问题，利用线性方程组特性。
* **逻辑描述：**
    1.  维护 `head_id` (最新发送的 Real 包 ID)。
    2.  维护 `first_missing_id` (最早未被确认的 Real 包 ID，模拟中可设为 `max(0, head_id - W + 1)` )。
    3.  **发送 Real 包时：** 更新 `head_id`。
    4.  **发送 Dummy 包时 (即 FEC 机会)：**
        * **确定范围**：`start = max(head_id - W + 1, first_missing_id)`, `end = head_id`。
        * **生成**：该 FEC 包被视为一个覆盖 `[start, end]` 范围内所有 Real 包的线性方程。

---

## 第二部分：性能评估方式设计 (Evaluation Methodology)

**目标：** 在第一部分生成的“增强版流量”基础上，模拟网络传输和重传机制，计算性能指标。
**核心逻辑：** 混合 ARQ 模型（FEC 优先恢复 -> 失败则重传）。

### 1. 评估器架构 (Evaluator Class)

请编写一个独立的评估脚本，输入为第一部分生成的 Trace。

#### 步骤 1: 传输与丢包模拟 (Loss Simulation)
* 遍历 Trace 中的所有包。
* 根据预设的 `loss_rate` (如 1%, 3%, 5%) 随机判定每个包是否丢失。
* **Real 包丢失**：加入 `Missing_List`。
* **Dummy/FEC 包丢失**：直接丢弃。
* **FEC 包保留**：放入 `Received_FEC_Buffer` (仅针对策略 B/C/D)。

#### 步骤 2: FEC 恢复模拟 (Recovery Phase)
* **对于策略 A (Baseline)：**
    * **跳过此步骤**。Dummy 包无法恢复任何数据。
* **对于策略 B/C/D (FEC)：**
    * 根据各自算法（Bucket检查 / Peeling / Rank检查）尝试复活 `Missing_List` 中的包。

#### 步骤 3: 重传结算 (Retransmission Calculation)
* 经过上述步骤后，`Missing_List` 中**剩余**的包，被视为必须进行 **重传 (Retransmission)**。
* 记录 `Residual_Loss_Count = len(Missing_List)`。

---

### 2. 关键评估指标 (Metrics)

请计算并对比以下指标（重点对比 Baseline vs Strategy D）：

#### 指标 A: 节省后的总带宽 (Total Bandwidth Consumption)
* **Baseline Cost** = $\sum \text{Size(Real)} + \sum \text{Size(Dummy)} + (\text{原丢包数} \times \text{Size(Real)})$
* **FEC Cost** = $\sum \text{Size(Real)} + \sum \text{Size(FEC)} + (\text{剩余丢包数} \times \text{Size(Real)})$
* **预期结论**：虽然 FEC 和 Dummy 占用空间一样，但因为 FEC 减少了“重传部分（第三项）”，所以总带宽更低。

#### 指标 B: 模拟完成时间 / 延迟惩罚 (Simulated Latency)
* 假设每个重传带来固定的 `RTT_Penalty` (例如 100ms)。
* **Baseline Latency** = `Trace_Duration` + `原丢包数` * `RTT_Penalty`
* **FEC Latency** = `Trace_Duration` + `剩余丢包数` * `RTT_Penalty`

#### 指标 C: 有效丢包率 / 重传率 (Effective Packet Loss Rate)
* $\text{EPLR} = \frac{\text{剩余丢包数}}{\text{Real 包总数}}$
* **预期结论**：展示 FEC 方案将 5% 的物理丢包率降低到了极低水平（如 0.01%）。

### 3. 输出报表格式 (CSV)

请生成如下格式的 CSV 文件以便绘图：

| 策略名称 (Strategy) | 物理丢包率 (Loss Rate) | 原始重传数 (Raw Retrans.) | 剩余重传数 (Residual Retrans.) | 总流量消耗 (MB) | 延迟惩罚 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Baseline | 0.05 | 50 | 50 | 10.5 | 5000 |
| Bucket | 0.05 | 50 | 12 | 10.2 | 1200 |
| SmartSliding | 0.05 | 50 | 0 | 10.1 | 0 |
