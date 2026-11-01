# ChatGPT 网页版训练协议

这些文件是公开、无个人成绩的可复用模板。学生的学习入口是 ChatGPT 网页版；模板不要求学生安装软件、运行 Python、开启服务器或配置 API。

- COACH_PROTOCOL.md：新会话接管、读包、首答、阅卷与证据边界。
- DEEP_FEEDBACK.md：每题逐式深讲与本人原答对照。
- SPECIALTY_COACH.md：微修复、深专项、实际互动与形成性验收。
- BUDGET_AND_EXPOSURE.md：R2 主线、七族覆盖、预算、曝光与盲测。
- DAY_END_EXPORT.md：默认深入复盘、下载文件与跨日结转。
- RETURN_CONTRACT.md：日终 JSON 的精确字段与未知项处理。
- STUDENT_START.md：可直接发送的学员启动消息与日常口令。

math2_pack.protocol.coach_protocol() 会合并前六份文件，形成无需旧对话上下文的完整协议；student_start() 返回启动消息；render_run_prompt(release) 将当日 manifest 的中性元数据与完整协议、启动消息组合成独立 RUN_TODAY_IN_CHATGPT.md。

默认 COACH_BUNDLE_LIMITED 方便每天一次上传学生 ZIP 和教练 ZIP，并在聊天里一次出一道题。完整 ZIP 在同会话内可被查看，不能由提示词提供服务端保密、防提前查看或不可篡改保证。ACTIVE_ITEM_STRICT 只上传当前题及其最小当题教练资料；后续题须由构建端继续交付，不能同时上传完整教练包又称严格隔离。

历史 PILOT 的已见题、未知曝光、补页争议及模拟统计口径由私有历史状态保存。本目录不包含学生原答、真实成绩、照片或账户信息。不要把私有结转文件、答案照片或完整个人状态提交到公开仓库。

产品边界参考：官方 [ChatGPT 网页版说明](https://learn.chatgpt.com/docs/web) 与 [文件工作流说明](https://learn.chatgpt.com/docs/artifacts-viewer)。文件读取、附件生成等能力须以当前会话实际可用工具为准；协议不承诺所有账户都能解压 ZIP 或生成 ZIP。
