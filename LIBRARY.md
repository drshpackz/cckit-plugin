# Библиотека компонентов

**Генерируется** из манифестов (`python3 bin/cckit_library.py index`) — руками не править.
Приём живёт тремя опорами: файл компонента, строка в карточке роли, проверка (`proof`
в манифесте). Заказ: `python3 bin/cckit_library.py order --needs …`.

| id | вид | даёт | статус | версия | что это |
|---|---|---|---|---|---|
| seed-record | format | writes-findings | wired-later | c277b30 | запись-зерно — одна находка, самодостаточная: вопрос, коммит, уверенность, источник, вердикт первым |
| lint-learned | hook | keeps-learned | works | не в git | запись в LEARNED.md без статуса не проходит |
| read-ledger | hook | reads-ledger | works | не в git | SessionStart — ведомость проекта в контекст; актуальное не переисследуется |
| report-done | hook | reports-to-main | works | не в git | Stop — строка в <дом>/reports.jsonl в конце каждого хода; основной агент узнаёт о конце без опроса |
| fan-out | practice | splits-work | works | c277b30 | независимые части работы — субагентам, сразу; модель сама не делит, пока ей не сказано |
| write-early | practice | long-tasks | works | c277b30 | результат — в файл с первых минут, по частям; план в голове пропадает при сжатии |
| window-1m | setting | long-tasks | works | c277b30 | окно 1M и порог сжатия у края окна — длинная задача не сжимается посередине |
| speed-patterns | skill | speed-diagnosis | works | c277b30 | измеренные рычаги скорости агентов и сэмплер |

## Роли — что каждая может, до установки

Права вычислены константами установщика: описание не может разойтись с тем, что роль получит.
Читают все роли весь проект и свой дом. Опасные группы — только по явной выдаче при установке.

| роль | для чего | пишет | разрешено | запрещено | хуки | модель |
|---|---|---|---|---|---|---|
| cckit-smith | Улучшает сам CCKit: ищет разрывы между обещанным и существующим, пишет находки со статусом и предлагает правки с доказательством. | docs/findings/**, docs/superpowers/specs/** | Edit, Glob, Grep, NotebookEdit, Read, Skill, TodoWrite, ToolSearch, Write | Agent, Artifact, ArtifactComments, ArtifactData, Bash, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, ListAgents, Monitor, PushNotification, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Task, TaskStop, WebFetch, WebSearch, Workflow | report-done, lint-learned, read-ledger | claude-fable-5-1[1m] |
| design-hand | Рука на холсте: меняет артборды BOOMZI по словам владельца и публикует их. | docs/design/** | Edit, Glob, Grep, NotebookEdit, Read, Skill, TodoWrite, ToolSearch, Write | Agent, Artifact, ArtifactComments, ArtifactData, Bash, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, ListAgents, Monitor, PushNotification, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Task, TaskStop, WebFetch, WebSearch, Workflow | report-done, lint-learned | claude-opus-5[1m] |
| design-scout | Кладёт дизайн на внутренности кодовой базы и пишет справку со ссылками file:line. | docs/vscode-internals/** | Edit, Glob, Grep, NotebookEdit, Read, Skill, TodoWrite, ToolSearch, Write | Agent, Artifact, ArtifactComments, ArtifactData, Bash, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, ListAgents, Monitor, PushNotification, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Task, TaskStop, WebFetch, WebSearch, Workflow | report-done, lint-learned, read-ledger | claude-opus-5-5[1m] |
| under-the-hood | Строит в коде то, что решено на холсте: темы, вклады, контрибуции — со ссылками path:line. | extensions/theme-boomzi/**, docs/vscode-internals/** | Edit, Glob, Grep, NotebookEdit, Read, Skill, TodoWrite, ToolSearch, Write | Agent, Artifact, ArtifactComments, ArtifactData, Bash, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, ListAgents, Monitor, PushNotification, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Task, TaskStop, WebFetch, WebSearch, Workflow | report-done, lint-learned, read-ledger | claude-opus-5-5[1m] |
