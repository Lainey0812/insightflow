# README V2 — REQ-0161

将根README从历次开发追加记录改为入门说明：两个系统的定位、当前功能、技术栈与目录、安装、模型及Admin配置、三个终端启动、常用地址、测试/构建、数据与版本存储。

源码核对frontend/admin Vite端口及代理、package.json脚本、FastAPI模块和健康检查路由、Settings环境读取、配置模板。明确后端不会自动加载.env，macOS/Linux通过set -a/source加载；密钥不进入VITE变量，本机测试模式不对外暴露。明确黄金集管理与旧五例评分器尚未自动接通，以及新克隆没有本机数据库。

旧README完整保留为README-before.md，新版为README-after.md，不删除旧版需求、评测或失败记录。说明首次Git导入与旧本地档案的差异。

完成本地文档链接检查、所有bash代码块语法检查、npm脚本核对。只修改README与本轮档案，不重启服务、不运行模型或业务测试，不将文档检查宣称为完整回归。将本轮文档提交并同步到已授权GitHub仓库main。
