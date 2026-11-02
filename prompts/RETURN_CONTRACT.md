# 日终主结转字段契约

以教练包内版本为准：version="1.0"，文件遵循 daily_return Schema。下面说明填写语义，不替代原 Schema；不要在严格 JSON 中增加本说明自创字段。源模板缺失时明确输出无法按本版完整校验，而不是自行猜一个“已通过”的 Schema。

主对象必须保留以下字段：

- version、record_kind、release_id、date、source_state_hash。
- presented_items、attempts、repair_events、retest_events。
- time_summary、review、declarations。

字段及必填性以包内 JSON Schema 的实际 required 为准。数据记录的字段如下：

presented_items：每个 item_id + item_version 只保留一条最终保守状态。只有随整包上传但未在屏幕实际出题者，exposure=UNKNOWN_POSSIBLY_EXPOSED 且 presented_at=null；实际展示的当前题用 CONFIRMED_SEEN。不得为了填时间抄当前日期零点。每个 attempt 都应引用同版本的 CONFIRMED_SEEN 记录。

attempts：每次真实首答一个 attempt_id，含 item_id、item_version、first_answer、hint_level、exposure_declaration、grade、feedback_at、net_seconds、completion、abandon_reason、supplements。只有存在可用计时证据且 net_seconds 非 null 时，附 time_evidence。不得用“没收到学生答案”制造一条空白真实 attempt。

first_answer：raw 是原文/照片证据说明；assets 只引用已真实导出的附件对象，每个对象含 path 与 sha256；received_at 没有确切来源为 null。未导出照片用 assets=[]，raw 注明 SOURCE_NOT_ATTACHED；不编造图片文件。

hint_level：0—5，按实际收到的最高提示记录。exposure_declaration 仅用 UNSEEN_SELF_DECLARED / CONFIRMED_SEEN / UNKNOWN_POSSIBLY_EXPOSED；未知不默认为未见。

grade：status 只用 FORMATIVE_AI_PROVISIONAL / PENDING_HUMAN_REVIEW；score 无法可靠评分则 null；max_points 来自当前题版本；confidence 为 LOW / MEDIUM / HIGH / UNKNOWN。first_divergence 为 null 或 {location, student, correction, cause}；step_scores 为真实评分点数组，每项 {step_id, earned, maximum, reason}，earned 未确定用 null。可选 error_codes 仅含 R1—R8 不重复代码；可选 dimensions 仅含 R/T/M/C/F 的文字证据或 null。不要把识别工具不支持直接写成数学首错。

completion：COMPLETE / PARTIAL / ABANDONED，按真实完整性而不是正确率填写。不会或省略用 abandon_reason 保留本人原因。supplements 中每次追加保留 supplement_id、raw、assets、received_at 与 relation_to_feedback=BEFORE_FEEDBACK / AFTER_FEEDBACK / UNKNOWN；首答原文和证据等级不能被补页替换。

repair_events：每次真实状态变化一条 {event_id, repair_id, origin_attempt_id, status, actual_answer, item_id, at}。已知当前专项题版本时附 Schema 允许的 item_version；不能自行编造哈希。status 只用 PLANNED / STARTED / IN_PROGRESS / ATTEMPTED / FORMATIVE_PASSED / DELAYED_PENDING；无本人实际回答时 actual_answer=null，机器事件只记PLANNED，已展示但未作答的细节写复盘；未核验外部时间 at=null。

retest_events：每次真实事件 {event_id, cohort_id, stage, attempt_id, outcome, at}，stage 为 D0 / D3 / D7 / D14，outcome 为 FORMATIVE_PASS / FAIL / PENDING。无真实阶段记录保持空数组；不预造迟测通过。

time_summary：activity_window_seconds、verified_net_seconds、feedback_seconds、specialty_seconds、review_seconds；未知为 null，其中 verified_net_seconds 固定 null。活动窗口、计时日志和学员自报不冒充核验净思考。

review：summary、unresolved 数组、next_actions 数组；正文写日终 Markdown。declarations 固定 {teacher_signatures:false, official_exam_score:null, certified_h0:false, certified_m4:false}。

date 取有证据的实际训练日；与发布日不一致时，release_date逐字保留原发布日，release_id及source_state_hash不变，提交离线日期校验，禁止重写原release。跨日、暂停或时刻未知时保留真实证据差异，不能假定天天连续；迟测不能把同日作答改写事件日期拼成跨日。source_state_hash 只复制输入值，不能宣称聊天里变成了新的已导入源状态。完全空白模板只是待填写表，不是学习证据；离线导入会拒绝 EMPTY_RETURN_NOT_LEARNING_EVIDENCE。

COMPLETE_SESSION 必须附 reported_answered_item_ids，准确声明实际作答清单并全部导出。提前结束时，未开始的计划题保留未开始，不为凑全计划虚构作答。只有二级报告时使用独立REPORTED_SESSION，不填造first_answer。
