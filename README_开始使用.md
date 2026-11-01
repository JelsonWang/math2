# 数学二120分：ChatGPT网页版文件训练

唯一日常训练入口是ChatGPT网页版聊天。Codex在后台维护题库、67节点、曝光与历史，生成文件；GitHub是版本仓库，不是练习界面。不需要启动网页软件、登录本地平台或常驻服务器。

## 你每天怎么使用

1. 从Codex领取当天学生ZIP、教练ZIP和RUN_TODAY_IN_CHATGPT.md。
2. 在ChatGPT网页版新聊天上传当天两个ZIP，粘贴运行提示词。ChatGPT必须先确认读到文件，再一次只发一道题。
3. 拍照或文字作答；封存首答后接受逐式讲解、首错定位和实际专项互动。困难时先修复一个主要断点，不把生成专项说明当作已经学会。
4. 结课默认得到深入复盘，下载DAILY_RETURN日期.json、复盘Markdown、作答JSONL、专项状态和返回ZIP。
5. 把返回文件交给Codex；它校验、原子导入并生成下一训练日包。你不需要每天修改代码。

上传的ZIP由用户持有，答案和未来题可能被查看。一题一发是教学规则，不提供技术上的教师权限隔离。默认整包模式记录可能曝光，不自动认证受信H0/M4。可选ACTIVE_ITEM_STRICT只给当前题与当前教练小包，后续题需由构建端逐题提供；不要同时上传完整教练包。

## Codex/维护端命令

需要Python3.11+。完整本地交付含私有题库；公开GitHub出于隐私不含真实题库、教师答案和个人学习记录。恢复本地交付中的verified_bank/private_catalog.json及其manifest即可，无需部署服务。

```powershell
python -m pip install -r requirements-file-workflow.lock
python -m math2_pack validate
python -m math2_pack init
python -m math2_pack build-daily --date 2026-11-01 --output releases
python -m math2_pack import-return --file C:\Private\DAILY_RETURN_20261101.json --next-date 2026-11-02 --output releases
python -m math2_pack build-specialty --topic Q03 --output releases\specialty-Q03
python -m math2_pack coverage-report --output C:\Private\coverage.json
python -m math2_pack export-history --output C:\Private\history.json
python -m math2_pack verify-release --folder releases\DAILY_20261101_v1
python -m pytest -q
```

Windows CPython3.11的依赖可在完整交付中离线安装：

```powershell
python -m pip install --no-index --find-links vendor/file_wheels -r requirements-file-workflow.lock
```

可用全局参数`--bank 私有题库路径`和`--records 私有历史目录`，写在子命令前。每条命令都有`--help`，验证失败返回非零。首次init不创建假作答；`--synthetic`只能初始化独立合成账本，不得用于真实records目录。

如果已有前一训练日发布却没有新结转，默认停止声称已更新自适应；确需生成未更新基线时显式加`--allow-unreturned`，输出会标记BASELINE_NO_NEW_RETURN。

## 持久化和真实性

事件保存在本地records/private/events.jsonl，带顺序和hash链，每次导入一笔原子文件提交。state.json是可重算缓存，不能以手改缓存制造掌握。首答不可覆盖，补页独立追加；JSON重复键、失效版本、外来题号、矛盾满分、伪造净时长和跨日复测跳级均拒绝。AI文字评分仅为形成性，验证通过表示文件可导入，不表示真实教师签核或已达到目标分数。

原始候选内容保留来源与冻结层级，未审Tier2不自动发布。当前新增材料为经版本绑定和模型重算的形成性候选，真实难度校准和长期陌生题供给仍不足；缺题会明确报告，不用改数字换皮或桥题凑满每日主线。七族计划与实际展示/作答分账。

## 公开仓库与本地私有文件

目标仓库是 https://github.com/JelsonWang/math2 ，首次检查为公开空仓库。公开分支只包含通用构建工具、Schema、运行提示词和合成测试。真实成绩、原照、原始附件、未曝光题、教师答案、私有bank、records和releases均由.gitignore排除，不上传公开仓库。需要全量GitHub私有持久化时，应先由用户决定仓库隐私；本次不擅自改变可见性。

旧Web代码已保留并标记NOT_IN_ACTIVE_WORKFLOW，改造前快照位于本地legacy_webapp。详见MIGRATION_NOTES.md。当前文件流程不依赖这些代码，旧HTTP测试结果不能替代新的离线流程验收。
